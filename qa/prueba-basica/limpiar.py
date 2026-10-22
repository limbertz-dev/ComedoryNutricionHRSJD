"""Limpieza acotada a corrida.json. Simulacro por defecto; --aplicar confirma."""
import argparse
from collections.abc import Mapping
import copy
from datetime import date, datetime

from sqlalchemy import text

import comun as c


def objetivos(conn, datos, actuales=None):
    if c.es_corrida_multi(datos):
        c.validar_casos_diario(datos)
        lid_1 = datos['casos']['qa01'].get('lectura_id')
        lid_2 = datos['casos']['qa02'].get('lectura_id')
        params = {
            'lectura_qa01': lid_1,
            'lectura_qa02': lid_2,
            'inicio': datetime.fromisoformat(datos['inicio']),
            'max_intento': datos['max_intento_inicial'],
            'max_sesion': datos['max_sesion_inicial'],
        }
        filtros = [
            ('intervenciones_lectura', '((:lectura_qa01 IS NOT NULL AND lectura_id=:lectura_qa01) OR (:lectura_qa02 IS NOT NULL AND lectura_id=:lectura_qa02))'),
            ('asistencias', '((:lectura_qa01 IS NOT NULL AND lectura_id=:lectura_qa01) OR (:lectura_qa02 IS NOT NULL AND lectura_id=:lectura_qa02))'),
            ('lecturas_biometricas', '((:lectura_qa01 IS NOT NULL AND id=:lectura_qa01) OR (:lectura_qa02 IS NOT NULL AND id=:lectura_qa02))'),
        ]
    else:
        params = {'lectura': datos['lectura_id'], 'inicio': datetime.fromisoformat(datos['inicio']),
                  'max_intento': datos['max_intento_inicial'], 'max_sesion': datos['max_sesion_inicial']}
        filtros = [('intervenciones_lectura', ':lectura IS NOT NULL AND lectura_id=:lectura'),
                   ('asistencias', ':lectura IS NOT NULL AND lectura_id=:lectura'),
                   ('lecturas_biometricas', ':lectura IS NOT NULL AND id=:lectura')]
    if datos.get('casos_por_comida'):
        ids = sorted(c.ids_casos_corrida(datos) - {datos['casos'][k].get('lectura_id') for k in ('qa01', 'qa02')})
        for indice, lid in enumerate(ids):
            params[f'historica_{indice}'] = lid
        if ids:
            lista = ','.join(f':historica_{i}' for i in range(len(ids)))
            filtros = [(tabla, f'({filtro}) OR {"id" if tabla == "lecturas_biometricas" else "lectura_id"} IN ({lista})')
                       for tabla, filtro in filtros]
    if datos.get('lecturas_enroladas'):
        import lector_enrolado
        ids = sorted(lector_enrolado.validar(conn, datos))
        if ids:
            claves = []
            for indice, lid in enumerate(ids):
                clave = f'enrolada_{indice}'
                params[clave] = lid
                claves.append(f':{clave}')
            lista = ','.join(claves)
            filtros = [(tabla, f'({filtro}) OR {"id" if tabla == "lecturas_biometricas" else "lectura_id"} IN ({lista})')
                       for tabla, filtro in filtros]
    if datos.get('lecturas_concurrentes'):
        import concurrencia
        ids = sorted(concurrencia.validar(conn, datos))
        if ids:
            params.update({f'concurrente_{i}': lid for i,lid in enumerate(ids)})
            lista = ','.join(f':concurrente_{i}' for i in range(len(ids)))
            filtros = [(tabla, f'({filtro}) OR {"id" if tabla == "lecturas_biometricas" else "lectura_id"} IN ({lista})') for tabla,filtro in filtros]
    if c.existe_tabla(conn, 'sesiones'):
        contrato = c.contrato_sesiones(conn)
        if contrato != datos['contrato_sesiones'] or params['max_sesion'] is None:
            raise c.Abortado("El contrato de sesiones cambió desde el inicio")
        cuenta, fecha = contrato['cuenta'], contrato['fecha']
        if cuenta == 'username':
            valores = list(c.CUENTAS)
        else:
            ids = list((actuales or datos['cuentas']).values())
            valores = ids + [ids[0]] * (4 - len(ids))
        params.update(cuenta1=valores[0], cuenta2=valores[1], cuenta3=valores[2], cuenta4=valores[3])
        filtros.append(('sesiones', f"`{cuenta}` IN (:cuenta1,:cuenta2,:cuenta3,:cuenta4) AND `{fecha}`>=:inicio AND id>:max_sesion"))
    if c.existe_tabla(conn, 'intentos_login'):
        if params['max_intento'] is None:
            raise c.Abortado("intentos_login apareció después del inicio")
        filtros.append((
            'intentos_login',
            "username IN ('cocinera1','cocinera2','cocinera3','jefa') AND fecha_hora>=:inicio AND id>:max_intento",
        ))
    return filtros, params


def contar(conn, filtros, params):
    return {tabla: {
        'de_corrida': c.normalizar_contador(
            conn.execute(text(f"SELECT COUNT(*) FROM `{tabla}` WHERE {filtro}"), params).scalar_one(),
            permitir_none=False,
        ),
        'total_tabla': c.normalizar_contador(
            conn.execute(text(f"SELECT COUNT(*) FROM `{tabla}`")).scalar_one(),
            permitir_none=False,
        ),
    } for tabla, filtro in filtros}


def _normalizar_intervencion(fila):
    if isinstance(fila, Mapping):
        return dict(fila)
    if hasattr(fila, '_mapping'):
        return dict(fila._mapping)
    if isinstance(fila, (list, tuple)):
        if len(fila) == 7:
            return {
                'id': fila[0],
                'lectura_id': fila[1],
                'cuenta_id': fila[2],
                'usuario_id': fila[3],
                'resultado': fila[4],
                'motivo_rechazo': fila[5],
                'asistencia_id': fila[6],
            }
        if len(fila) == 5:
            return {
                'id': 1,
                'lectura_id': fila[0],
                'cuenta_id': fila[1],
                'usuario_id': fila[2],
                'resultado': fila[3],
                'motivo_rechazo': fila[4],
                'asistencia_id': None,
            }
    if hasattr(fila, 'lectura_id') and hasattr(fila, 'cuenta_id'):
        return {
            'id': getattr(fila, 'id', None),
            'lectura_id': fila.lectura_id,
            'cuenta_id': fila.cuenta_id,
            'usuario_id': fila.usuario_id,
            'resultado': getattr(fila, 'resultado', None),
            'motivo_rechazo': getattr(fila, 'motivo_rechazo', None),
            'asistencia_id': getattr(fila, 'asistencia_id', None),
        }
    raise ValueError(f"Formato no reconocido para fila de intervención: {fila}")


def _normalizar_asistencia(fila):
    if isinstance(fila, Mapping):
        return dict(fila)
    if hasattr(fila, '_mapping'):
        return dict(fila._mapping)
    if isinstance(fila, (list, tuple)) and len(fila) == 7:
        return {
            'id': fila[0],
            'lectura_id': fila[1],
            'usuario_id': fila[2],
            'comida_id': fila[3],
            'turno_asignado_id': fila[4],
            'metodo': fila[5],
            'registrado_por_cuenta': fila[6],
        }
    if hasattr(fila, 'lectura_id') and hasattr(fila, 'usuario_id'):
        return {
            'id': getattr(fila, 'id', None),
            'lectura_id': fila.lectura_id,
            'usuario_id': fila.usuario_id,
            'comida_id': getattr(fila, 'comida_id', None),
            'turno_asignado_id': getattr(fila, 'turno_asignado_id', None),
            'metodo': getattr(fila, 'metodo', None),
            'registrado_por_cuenta': getattr(fila, 'registrado_por_cuenta', None),
        }
    raise ValueError(f"Formato no reconocido para fila de asistencia: {fila}")


def contrastar_casos_interrumpidos(conn, datos, aplicar=False, guardar_diario=False, actuales=None, otras_lecturas=()):
    """Contrasta IDs anotados antes del commit con las filas realmente persistidas en MySQL.

    Recupera de forma segura cualquier corrida o caso en `lectura_pendiente`:
    - Si la transacción abortó/hizo rollback antes del commit: constata que no hay fila
      persistida y reconcilia el caso a `pendiente` (o v1 a `iniciada`/`refechada`) con `lectura_id=None`.
    - Si la transacción se confirmó en MySQL pero se interrumpió antes de actualizar el diario:
      constata la fila persistida, valida que cumple la titularidad exacta del caso y reconcilia
      el diario sin reenviar la marcación ni borrar datos ajenos.
    """
    if datos.get('casos_por_comida'):
        c.validar_casos_diario(datos)
        ids = c.ids_casos_corrida(datos)
        cambios = False
        for vista in c.vistas_servicios(datos):
            propios = c.ids_casos_corrida(vista)
            cambios |= contrastar_casos_interrumpidos(conn, vista, aplicar, False, actuales, ids - propios)
        if cambios and guardar_diario:
            c.guardar_corrida(datos)
        return cambios
    cambios = False
    if actuales is None:
        actuales = dict(datos.get('cuentas') or {})

    if c.es_corrida_multi(datos):
        c.validar_casos_diario(datos)
        casos = datos['casos']
        for codigo, info in casos.items():
            if info.get('estado') != 'lectura_pendiente' and (info.get('estado') == 'pendiente') == (info.get('lectura_id') is None):
                continue
            spec = c.COMENSALES_QA[codigo]
            uid_esperado = spec['usuario_id'] if spec['rol_escenario'] == 'registro_normal' else None
            lid = info.get('lectura_id')
            momento_esperado = info.get('momento_lectura')

            otros_lids = {
                c_info['lectura_id']
                for c_cod, c_info in casos.items()
                if c_cod != codigo and c_info.get('lectura_id') is not None
            }
            otros_lids.update(otras_lecturas)

            lectura = None
            if lid is not None:
                res_directa = conn.execute(text(
                    "SELECT id, usuario_id, dispositivo, fecha_hora, resultado, motivo "
                    "FROM lecturas_biometricas WHERE id=:lid"
                    + (' FOR UPDATE' if aplicar else '')
                ), {'lid': lid}).mappings()
                lectura_directa = res_directa.one_or_none() if hasattr(res_directa, 'one_or_none') else None

                if lectura_directa is None:
                    res_disp = conn.execute(text(
                        "SELECT id, usuario_id, dispositivo, fecha_hora, resultado, motivo "
                        "FROM lecturas_biometricas WHERE dispositivo=:d"
                        + (' FOR UPDATE' if aplicar else '')
                    ), {'d': c.DISPOSITIVO}).mappings()
                    raw_disp = res_disp.all() if hasattr(res_disp, 'all') else []
                    filas_disp = list(raw_disp) if isinstance(raw_disp, (list, tuple)) else []
                    candidatas_disp = [f for f in filas_disp if f['id'] not in otros_lids]
                    if not candidatas_disp:
                        info['estado'] = 'pendiente'
                        info['lectura_id'] = None
                        info['asistencia_id'] = None
                        cambios = True
                        continue
                    raise c.Abortado(
                        f"Lectura {lid} de {codigo} no existe pero hay lecturas en {c.DISPOSITIVO}: ambigüedad"
                    )
                lectura = lectura_directa
            else:
                res_disp = conn.execute(text(
                    "SELECT id, usuario_id, dispositivo, fecha_hora, resultado, motivo "
                    "FROM lecturas_biometricas WHERE dispositivo=:d"
                    + (' FOR UPDATE' if aplicar else '')
                ), {'d': c.DISPOSITIVO}).mappings()
                raw_disp = res_disp.all() if hasattr(res_disp, 'all') else []
                filas_disp = list(raw_disp) if isinstance(raw_disp, (list, tuple)) else []
                candidatas_disp = [f for f in filas_disp if f['id'] not in otros_lids]

                if not candidatas_disp:
                    info['estado'] = 'pendiente'
                    info['lectura_id'] = None
                    info['asistencia_id'] = None
                    cambios = True
                    continue
                if len(candidatas_disp) > 1:
                    raise c.Abortado(
                        f"Reconciliación ambigua para {codigo}: múltiples lecturas candidatas en {c.DISPOSITIVO}"
                    )
                lectura = candidatas_disp[0]
                lid = lectura['id']
                info['lectura_id'] = lid

            if lectura['dispositivo'] != c.DISPOSITIVO:
                raise c.Abortado(f"Lectura {lid} de {codigo} pertenece a otro dispositivo: no se borra")

            if not momento_esperado:
                raise c.Abortado(f"Faltan indicios en el diario para {codigo}: momento_lectura ausente")
            fh_str = datetime.fromisoformat(str(lectura['fecha_hora'])).isoformat()
            fh_norm = fh_str.replace(' ', 'T')
            if fh_norm != momento_esperado:
                raise c.Abortado(
                    f"Lectura {lid} de {codigo} con hora distinta a la registrada en la corrida: {fh_norm} != {momento_esperado}"
                )

            if spec['rol_escenario'] == 'registro_normal':
                if (
                    lectura['usuario_id'] != spec['usuario_id']
                    or lectura['resultado'] != 'aceptada'
                    or lectura['motivo'] is not None
                ):
                    raise c.Abortado(f"Lectura {lid} de {codigo} alterada o ajena: no se borra")

                res_asists = conn.execute(text(
                    "SELECT id, lectura_id, usuario_id, comida_id, turno_asignado_id, metodo, registrado_por_cuenta "
                    "FROM asistencias WHERE lectura_id=:lid"
                ), {'lid': lid}).mappings().all()
                asists = [_normalizar_asistencia(f) for f in res_asists]

                n_intervs = conn.execute(text(
                    "SELECT COUNT(*) FROM intervenciones_lectura WHERE lectura_id=:lid"
                ), {'lid': lid}).scalar_one()

                if n_intervs != 0:
                    raise c.Abortado(f"Intervenciones indebidas encontradas para {codigo}")

                if len(asists) > 1:
                    raise c.Abortado(f"Múltiples asistencias para lectura {lid} de {codigo}")
                if len(asists) == 1:
                    asist = asists[0]
                    aid_esp = info.get('asistencia_id')
                    if (
                        asist['id'] is None
                        or asist['usuario_id'] != spec['usuario_id']
                        or asist['comida_id'] != c.comida_corrida(datos)
                        or asist['turno_asignado_id'] != spec['asignacion_id']
                        or asist['metodo'] != 'biometrico'
                        or asist['registrado_por_cuenta'] is not None
                        or (aid_esp is not None and asist['id'] != aid_esp)
                    ):
                        raise c.Abortado(f"Asistencia de {codigo} alterada o ajena: relaciones incompatibles")
                    info['asistencia_id'] = asist['id']
                    info['estado'] = 'completado'
                    cambios = True
                else:
                    info['asistencia_id'] = None
                    info['estado'] = 'lectura_creada'
                    cambios = True
            else:
                if (
                    lectura['usuario_id'] is not None
                    or lectura['resultado'] != 'rechazada'
                    or lectura['motivo'] != 'no_identificado'
                ):
                    raise c.Abortado(f"Lectura {lid} de {codigo} alterada o ajena: no se borra")

                res_asists = conn.execute(text(
                    "SELECT id, lectura_id, usuario_id, comida_id, turno_asignado_id, metodo, registrado_por_cuenta "
                    "FROM asistencias WHERE lectura_id=:lid"
                ), {'lid': lid}).mappings().all()
                asists = [_normalizar_asistencia(f) for f in res_asists]

                res_int = conn.execute(text(
                    "SELECT id, lectura_id, cuenta_id, usuario_id, resultado, motivo_rechazo, asistencia_id "
                    "FROM intervenciones_lectura WHERE lectura_id=:lid"
                ), {'lid': lid}).mappings().all()
                intervs = [_normalizar_intervencion(f) for f in res_int]

                if len(asists) == 0 and len(intervs) == 0:
                    info['asistencia_id'] = None
                    info['estado'] = 'lectura_creada'
                    cambios = True
                elif len(asists) == 1 and len(intervs) == 1:
                    asist = asists[0]
                    interv = intervs[0]
                    cocinera2_id = (actuales or {}).get('cocinera2')
                    if cocinera2_id is None:
                        raise c.Abortado("Falta cocinera2 en las cuentas")
                    aid_esp = info.get('asistencia_id')

                    if (
                        asist['id'] is None
                        or asist['usuario_id'] != spec['usuario_id']
                        or asist['comida_id'] != c.comida_corrida(datos)
                        or asist['turno_asignado_id'] != spec['asignacion_id']
                        or asist['metodo'] != 'manual'
                        or asist['registrado_por_cuenta'] != cocinera2_id
                        or (aid_esp is not None and asist['id'] != aid_esp)
                    ):
                        raise c.Abortado(f"Asistencia de {codigo} alterada o ajena: relaciones incompatibles")

                    if (
                        interv['id'] is None
                        or interv['lectura_id'] != lid
                        or interv['usuario_id'] != spec['usuario_id']
                        or interv['cuenta_id'] != cocinera2_id
                        or interv['resultado'] != 'registrada'
                        or interv['motivo_rechazo'] is not None
                        or interv['asistencia_id'] is None
                        or interv['asistencia_id'] != asist['id']
                    ):
                        raise c.Abortado(f"Intervención de {codigo} ajena o alterada: relaciones incompatibles")

                    info['asistencia_id'] = asist['id']
                    info['estado'] = 'completado'
                    cambios = True
                else:
                    if len(asists) > 0 and len(intervs) == 0:
                        raise c.Abortado(f"Inconsistencia en {codigo}: asistencia manual presente sin intervención registrada")
                    if len(asists) == 0 and len(intervs) > 0:
                        raise c.Abortado(f"Inconsistencia en {codigo}: intervención registrada presente sin asistencia")
                    raise c.Abortado(f"Inconsistencia en {codigo}: {len(asists)} asistencias y {len(intervs)} intervenciones")
    else:
        if datos.get('estado') == 'lectura_pendiente':
            lid = datos.get('lectura_id')
            momento_esperado = datos.get('momento_lectura')

            lectura = None
            if lid is not None:
                res_directa = conn.execute(text(
                    "SELECT id, usuario_id, dispositivo, fecha_hora, resultado, motivo "
                    "FROM lecturas_biometricas WHERE id=:lid"
                    + (' FOR UPDATE' if aplicar else '')
                ), {'lid': lid}).mappings()
                lectura_directa = res_directa.one_or_none() if hasattr(res_directa, 'one_or_none') else None

                if lectura_directa is None:
                    res_disp = conn.execute(text(
                        "SELECT id, usuario_id, dispositivo, fecha_hora, resultado, motivo "
                        "FROM lecturas_biometricas WHERE dispositivo=:d"
                        + (' FOR UPDATE' if aplicar else '')
                    ), {'d': c.DISPOSITIVO}).mappings()
                    raw_disp = res_disp.all() if hasattr(res_disp, 'all') else []
                    filas_disp = list(raw_disp) if isinstance(raw_disp, (list, tuple)) else []
                    if not filas_disp:
                        datos['estado'] = 'refechada' if datos.get('fecha_destino') else 'iniciada'
                        datos['lectura_id'] = None
                        cambios = True
                    else:
                        raise c.Abortado("Reconciliación ambigua: lecturas no identificadas en dispositivo")
                else:
                    lectura = lectura_directa
            else:
                res_disp = conn.execute(text(
                    "SELECT id, usuario_id, dispositivo, fecha_hora, resultado, motivo "
                    "FROM lecturas_biometricas WHERE dispositivo=:d"
                    + (' FOR UPDATE' if aplicar else '')
                ), {'d': c.DISPOSITIVO}).mappings()
                raw_disp = res_disp.all() if hasattr(res_disp, 'all') else []
                filas_disp = list(raw_disp) if isinstance(raw_disp, (list, tuple)) else []
                if not filas_disp:
                    datos['estado'] = 'refechada' if datos.get('fecha_destino') else 'iniciada'
                    cambios = True
                elif len(filas_disp) > 1:
                    raise c.Abortado("Reconciliación ambigua: múltiples lecturas en el dispositivo")
                else:
                    lectura = filas_disp[0]
                    lid = lectura['id']
                    datos['lectura_id'] = lid

            if lectura is not None:
                if (
                    lectura['dispositivo'] != c.DISPOSITIVO
                    or lectura['usuario_id'] is not None
                    or lectura['resultado'] != 'rechazada'
                    or lectura['motivo'] != 'no_identificado'
                ):
                    raise c.Abortado("Lectura ajena o alterada: no se borra")
                if not momento_esperado:
                    raise c.Abortado("Faltan indicios en el diario: momento_lectura ausente")
                fh_str = datetime.fromisoformat(str(lectura['fecha_hora'])).isoformat()
                fh_norm = fh_str.replace(' ', 'T')
                if fh_norm != momento_esperado:
                    raise c.Abortado("Lectura con hora distinta a la registrada en la corrida")
                datos['estado'] = 'lectura_creada'
                cambios = True

    if cambios and guardar_diario:
        c.guardar_corrida(datos)
    return cambios


def _comprobar_propiedad_multi(conn, datos, actuales, aplicar):
    c.validar_casos_diario(datos)
    if datos.get('casos_por_comida'):
        ids = c.ids_casos_corrida(datos)
        if ids & {f.get('lectura_id') for f in datos.get('lecturas_enroladas', [])}:
            raise c.Abortado('Una lectura pertenece a dos circuitos del diario')
        for vista in c.vistas_servicios(datos):
            propios = c.ids_casos_corrida(vista)
            _comprobar_propiedad_servicio(conn, vista, actuales, aplicar, ids - propios)
    else:
        _comprobar_propiedad_servicio(conn, datos, actuales, aplicar)


def _comprobar_propiedad_servicio(conn, datos, actuales, aplicar, otras_lecturas=()):
    extras = set()
    if datos.get('lecturas_enroladas'):
        import lector_enrolado
        extras = lector_enrolado.validar(conn, datos)
    if datos.get('lecturas_concurrentes'):
        import concurrencia
        extras |= concurrencia.validar(conn, datos)
    c.validar_casos_diario(datos)
    contrastar_casos_interrumpidos(conn, datos, aplicar=aplicar, guardar_diario=False, actuales=actuales, otras_lecturas=otras_lecturas)
    casos = datos['casos']
    for info in casos.values():
        if info['estado'] == 'lectura_pendiente' or (info['estado'] == 'pendiente') != (info.get('lectura_id') is None):
            raise c.Abortado("Caso con lectura pendiente o inconclusa: revisar diario antes de limpiar")

    caso_qa01 = casos['qa01']
    caso_qa02 = casos['qa02']
    lid_1 = caso_qa01.get('lectura_id')
    lid_2 = caso_qa02.get('lectura_id')
    u1 = c.COMENSALES_QA['qa01']['usuario_id']
    u2 = c.COMENSALES_QA['qa02']['usuario_id']
    u3 = c.COMENSALES_QA['qa03']['usuario_id']
    a1 = c.COMENSALES_QA['qa01']['asignacion_id']
    a2 = c.COMENSALES_QA['qa02']['asignacion_id']
    a3 = c.COMENSALES_QA['qa03']['asignacion_id']
    ids_esperados = {lid for lid in (lid_1, lid_2) if lid is not None}

    lecturas = conn.execute(text(
        "SELECT id, usuario_id, dispositivo, fecha_hora, resultado, motivo FROM lecturas_biometricas "
        "WHERE id=:lid1 OR id=:lid2 OR dispositivo=:d OR usuario_id IN (:u1,:u2,:u3)"
        + (' FOR UPDATE' if aplicar else '')
    ), {'lid1': lid_1, 'lid2': lid_2, 'd': c.DISPOSITIVO, 'u1': u1, 'u2': u2, 'u3': u3}).mappings().all()

    lecturas = [f for f in lecturas if f['id'] not in extras and f['id'] not in otras_lecturas]
    if {fila['id'] for fila in lecturas} != ids_esperados or len(lecturas) != len(ids_esperados):
        raise c.Abortado("Lectura ajena o alterada: no se borra")

    for lectura in lecturas:
        fh = lectura['fecha_hora']
        fh_str = datetime.fromisoformat(str(fh)).isoformat()
        if lectura['id'] == lid_1:
            if (
                lectura['dispositivo'] != c.DISPOSITIVO
                or lectura['usuario_id'] != u1
                or lectura['resultado'] != 'aceptada'
                or lectura['motivo'] is not None
                or fh_str != caso_qa01.get('momento_lectura')
            ):
                raise c.Abortado("Lectura de qa01 ajena o alterada: no se borra")
        elif lectura['id'] == lid_2:
            if (
                lectura['dispositivo'] != c.DISPOSITIVO
                or lectura['usuario_id'] is not None
                or lectura['resultado'] != 'rechazada'
                or lectura['motivo'] != 'no_identificado'
                or fh_str != caso_qa02.get('momento_lectura')
            ):
                raise c.Abortado("Lectura de qa02 ajena o alterada: no se borra")
        else:
            raise c.Abortado("Lectura ajena o alterada: no se borra")

    propias = set(actuales.values())
    cocinera2_id = actuales.get('cocinera2')
    if cocinera2_id is None:
        raise c.Abortado("Falta cocinera2 en usuarios_sistema")

    res_intentos = conn.execute(text(
        "SELECT id, lectura_id, cuenta_id, usuario_id, resultado, motivo_rechazo, asistencia_id "
        "FROM intervenciones_lectura "
        "WHERE lectura_id=:lid1 OR lectura_id=:lid2 OR usuario_id IN (:u1,:u2,:u3)"
    ), {'lid1': lid_1, 'lid2': lid_2, 'u1': u1, 'u2': u2, 'u3': u3}).mappings().all()
    intentos = [_normalizar_intervencion(f) for f in res_intentos]
    intentos = [f for f in intentos if f['lectura_id'] not in extras and f['lectura_id'] not in otras_lecturas]

    res_asists = conn.execute(text(
        "SELECT id, lectura_id, usuario_id, comida_id, turno_asignado_id, metodo, registrado_por_cuenta "
        "FROM asistencias WHERE lectura_id=:lid1 OR lectura_id=:lid2 OR usuario_id IN (:u1,:u2,:u3)"
    ), {'lid1': lid_1, 'lid2': lid_2, 'u1': u1, 'u2': u2, 'u3': u3}).mappings().all()
    asistencias = [_normalizar_asistencia(f) for f in res_asists]
    asistencias = [f for f in asistencias if f['lectura_id'] not in extras and f['lectura_id'] not in otras_lecturas]

    if any(a['usuario_id'] == u3 or a['turno_asignado_id'] == a3 for a in asistencias):
        raise c.Abortado("Asistencia ajena o indebida en comensal de reserva qa03")
    if any(i['usuario_id'] == u3 for i in intentos):
        raise c.Abortado("Intervención ajena o indebida en comensal de reserva qa03")

    asist_qa01 = [a for a in asistencias if a['usuario_id'] == u1 or (lid_1 is not None and a['lectura_id'] == lid_1)]
    int_qa01 = [i for i in intentos if i['usuario_id'] == u1 or (lid_1 is not None and i['lectura_id'] == lid_1)]

    if len(int_qa01) > 0:
        raise c.Abortado("Intervenciones fuera del caso básico: qa01 no debe tener intervenciones de cocina")

    if lid_1 is None:
        if len(asist_qa01) > 0:
            raise c.Abortado("Asistencia de qa01 sin lectura registrada")
    else:
        if len(asist_qa01) != 1:
            raise c.Abortado(f"El caso qa01 debe tener exactamente una asistencia propia, encontrados {len(asist_qa01)}")
        asist1 = asist_qa01[0]
        aid_esperado_1 = caso_qa01.get('asistencia_id')
        if (
            asist1['id'] is None
            or asist1['lectura_id'] != lid_1
            or asist1['usuario_id'] != u1
            or asist1['comida_id'] != c.comida_corrida(datos)
            or asist1['turno_asignado_id'] != a1
            or asist1['metodo'] != 'biometrico'
            or asist1['registrado_por_cuenta'] is not None
            or (aid_esperado_1 is not None and asist1['id'] != aid_esperado_1)
        ):
            raise c.Abortado("Asistencia de qa01 ajena o alterada: relaciones incompatibles")

    asist_qa02 = [a for a in asistencias if a['usuario_id'] == u2 or (lid_2 is not None and a['lectura_id'] == lid_2)]
    int_qa02 = [i for i in intentos if i['usuario_id'] == u2 or (lid_2 is not None and i['lectura_id'] == lid_2)]

    resto_asist = [a for a in asistencias if a not in asist_qa01 and a not in asist_qa02]
    if resto_asist:
        raise c.Abortado("Asistencia ajena a la corrida")
    resto_int = [i for i in intentos if i not in int_qa02]
    if resto_int:
        raise c.Abortado("Intervenciones fuera del caso básico: intervención ajena a la corrida")

    if lid_2 is None:
        if len(asist_qa02) > 0 or len(int_qa02) > 0:
            raise c.Abortado("Asistencia o intervención de qa02 sin lectura registrada")
    else:
        if len(asist_qa02) == 0 and len(int_qa02) == 0:
            if caso_qa02.get('asistencia_id') is not None:
                raise c.Abortado("asistencia_id anotado en diario pero ausente en base de datos")
            if caso_qa02.get('estado') == 'completado':
                raise c.Abortado("qa02 marcado completado en diario pero sin asistencia ni intervención")
        elif len(asist_qa02) == 1 and len(int_qa02) == 1:
            asist2 = asist_qa02[0]
            int2 = int_qa02[0]
            aid_esperado_2 = caso_qa02.get('asistencia_id')

            if (
                asist2['id'] is None
                or asist2['lectura_id'] != lid_2
                or asist2['usuario_id'] != u2
                or asist2['comida_id'] != c.comida_corrida(datos)
                or asist2['turno_asignado_id'] != a2
                or asist2['metodo'] != 'manual'
                or asist2['registrado_por_cuenta'] != cocinera2_id
                or (aid_esperado_2 is not None and asist2['id'] != aid_esperado_2)
            ):
                raise c.Abortado("Asistencia de qa02 ajena o alterada: relaciones incompatibles")

            if (
                int2['id'] is None
                or int2['lectura_id'] != lid_2
                or int2['usuario_id'] != u2
                or int2['cuenta_id'] != cocinera2_id
                or int2['resultado'] != 'registrada'
                or int2['motivo_rechazo'] is not None
                or int2['asistencia_id'] is None
                or int2['asistencia_id'] != asist2['id']
            ):
                raise c.Abortado("Intervenciones fuera del caso básico: intervención de qa02 ajena o alterada")
        else:
            if len(asist_qa02) > 0 and len(int_qa02) == 0:
                raise c.Abortado("QA02 con asistencia manual propia pero ninguna intervención registrada")
            if len(asist_qa02) == 0 and len(int_qa02) > 0:
                raise c.Abortado("QA02 con intervención registrada pero ninguna asistencia")
            raise c.Abortado(f"Inconsistencia en QA02: {len(asist_qa02)} asistencias y {len(int_qa02)} intervenciones")


def comprobar_propiedad(conn, datos, aplicar):
    fila = c.filas_asignaciones_corrida(conn, datos, bloquear=aplicar)
    if fila['fecha'].isoformat() not in {datos['fecha_original'], datos['fecha_destino']}:
        raise c.Abortado("Fecha modificada fuera de la corrida: no se restaura")
    cuentas = conn.execute(text(
        "SELECT id, username, rol, usuario_turnos_id FROM usuarios_sistema "
        "WHERE username IN ('cocinera1','cocinera2','cocinera3','jefa')"
    )).mappings().all()
    actuales = c.validar_cuentas_limpieza(cuentas, datos.get('cuentas'))
    if not set(datos.get('verificacion_cuentas') or ()) <= set(actuales):
        raise c.Abortado("Las cuentas cambiaron de identidad")

    if c.es_corrida_multi(datos):
        _comprobar_propiedad_multi(conn, datos, actuales, aplicar)
        return fila['fecha'], actuales

    contrastar_casos_interrumpidos(conn, datos, aplicar=aplicar, guardar_diario=False, actuales=actuales)
    lecturas = conn.execute(text(
        "SELECT id, usuario_id, dispositivo, fecha_hora, resultado, motivo FROM lecturas_biometricas "
        "WHERE id=:id OR dispositivo=:d" + (' FOR UPDATE' if aplicar else '')
    ), {'id': datos['lectura_id'], 'd': c.DISPOSITIVO}).mappings().all()
    for lectura in lecturas:
        if (lectura['id'] != datos['lectura_id'] or lectura['dispositivo'] != c.DISPOSITIVO
                or lectura['usuario_id'] is not None or lectura['motivo'] != 'no_identificado'
                or lectura['resultado'] != 'rechazada'
                or lectura['fecha_hora'].isoformat() != datos.get('momento_lectura')):
            raise c.Abortado("Lectura ajena o alterada: no se borra")
    propias = set(actuales.values())
    intentos = conn.execute(text(
        "SELECT cuenta_id, usuario_id FROM intervenciones_lectura WHERE lectura_id=:id"
    ), {'id': datos['lectura_id']}).all()
    if any(cuenta not in propias or uid != c.USUARIO for cuenta, uid in intentos):
        raise c.Abortado("Intervenciones fuera del caso básico: revisar antes de limpiar")
    asistencias = conn.execute(text(
        "SELECT usuario_id, comida_id, turno_asignado_id, registrado_por_cuenta FROM asistencias WHERE lectura_id=:id"
    ), {'id': datos['lectura_id']}).all()
    if any(uid != c.USUARIO or comida != c.comida_corrida(datos) or asignacion != c.ASIGNACION or cuenta not in propias
           for uid, comida, asignacion, cuenta in asistencias):
        raise c.Abortado("Asistencia ajena a la corrida")
    return fila['fecha'], actuales


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--aplicar', action='store_true')
    parser.add_argument(
        '--reconciliar',
        action='store_true',
        help="Contrasta IDs guardados antes del commit con filas reales sin borrar datos",
    )
    args = parser.parse_args()
    permitidas = c.permisos((c.DEMO, 'turnos_asignados', 'UPDATE'), *(
        (c.SIM, tabla, 'DELETE') for tabla in (
            'intervenciones_lectura', 'asistencias', 'lecturas_biometricas', 'sesiones', 'intentos_login')
    )) if args.aplicar else ()
    with c.bloqueo_corrida(), c.entorno_seguro(permitidas) as (motor, huella, servidor):
        if (c.CARPETA / 'api.activa').exists():
            raise c.Abortado("Detener la API QA antes de limpiar")
        datos = c.leer_corrida(servidor)
        c.comprobar_base(datos, huella)
        with motor.begin() as conn:
            if args.reconciliar:
                datos_reconciliados = copy.deepcopy(datos)
                cambios = contrastar_casos_interrumpidos(
                    conn, datos_reconciliados, aplicar=False, guardar_diario=False
                )
                comprobar_propiedad(conn, datos_reconciliados, False)
                if cambios:
                    c.guardar_corrida(datos_reconciliados)
                    print("Diario corrida.json contrastado y reconciliado con las filas persistidas en base de datos.")
                else:
                    print("No se requirieron cambios: ningún caso interrumpido en lectura_pendiente.")
                return
            actual, actuales = comprobar_propiedad(conn, datos, args.aplicar)
            filtros, params = objetivos(conn, datos, actuales)
            antes = contar(conn, filtros, params)
            print(f"Conteos antes (selección y total): {antes}")
            if c.es_corrida_multi(datos):
                ids_asig = [spec['asignacion_id'] for spec in c.COMENSALES_QA.values()]
                print(f"Asignaciones QA {ids_asig}: {actual} -> {datos['fecha_original']}")
            else:
                print(f"Asignación {c.ASIGNACION}: {actual} -> {datos['fecha_original']}")
            if args.aplicar:
                datos['estado'] = 'limpieza_pendiente'
                c.guardar_corrida(datos)
                for tabla, filtro in filtros:
                    resultado = conn.execute(text(f"DELETE FROM `{tabla}` WHERE {filtro}"), params)
                    if resultado.rowcount != antes[tabla]['de_corrida']:
                        raise c.Abortado("Conteo cambió durante limpieza; rollback completo")
                original = date.fromisoformat(datos['fecha_original'])
                if actual != original:
                    c.cambiar_fecha_corrida(conn, datos, actual, original)
                c.restaurar_turno_laboratorio(conn, datos)
            despues = contar(conn, filtros, params)
            print(f"Conteos después {'reales' if args.aplicar else '(simulacro, sin cambios)'}: {despues}")
            if args.aplicar and any(v['de_corrida'] for v in despues.values()):
                raise c.Abortado("Quedaron filas de la corrida; rollback completo")
            for tabla in antes:
                esperado = antes[tabla]['total_tabla'] - (antes[tabla]['de_corrida'] if args.aplicar else 0)
                if despues[tabla]['total_tabla'] != esperado:
                    raise c.Abortado("Cambió una fila ajena o hubo concurrencia; rollback completo")
        if args.aplicar:
            datos.update(estado='limpia', limpieza={'antes': antes, 'despues': despues},
                         fin=datetime.now().isoformat())
            c.guardar_corrida(datos)
            print("Limpieza confirmada. Cuentas existentes y sus claves se conservan.")
        else:
            print("Simulacro: no se emitieron DELETE/UPDATE ni se modificó corrida.json")


if __name__ == '__main__':
    c.ejecutar(main)
