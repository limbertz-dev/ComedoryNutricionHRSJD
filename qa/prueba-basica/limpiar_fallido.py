"""Cierra un ensayo fallido sin exigir que el operador haya elegido la persona esperada.

La propiedad se prueba por lectura QA, fecha exacta y relaciones. Guarda la evidencia
antes de borrar; nunca alcanza marcaciones que no pertenezcan al diario.
"""
import argparse
from datetime import date, datetime

from sqlalchemy import text

import comun as c
import limpiar


def validar_filas(datos, lecturas, asistencias, intervenciones, cuentas):
    c.validar_casos_diario(datos)
    if datos.get('casos_por_comida'):
        if {f['id'] for f in lecturas} != c.ids_casos_corrida(datos):
            raise c.Abortado('Hay lecturas ajenas o faltantes entre comidas; no se borra.')
        ids_propios = c.ids_casos_corrida(datos)
        if any(f['lectura_id'] not in ids_propios for f in [*asistencias, *intervenciones]):
            raise c.Abortado('Hay relaciones ajenas entre comidas; no se borra.')
        for vista in c.vistas_servicios(datos):
            ids = c.ids_casos_corrida(vista)
            validar_filas(vista, [f for f in lecturas if f['id'] in ids],
                          [f for f in asistencias if f['lectura_id'] in ids],
                          [f for f in intervenciones if f['lectura_id'] in ids], cuentas)
        return
    por_lid = {info['lectura_id']: (codigo, info) for codigo, info in datos['casos'].items()
               if info.get('lectura_id') is not None}
    if len(lecturas) != len(por_lid) or {f['id'] for f in lecturas} != set(por_lid):
        raise c.Abortado('Hay lecturas ajenas o faltantes; no se cierra el ensayo fallido.')
    for lectura in lecturas:
        codigo, info = por_lid[lectura['id']]
        if (lectura['dispositivo'] != c.DISPOSITIVO
                or lectura['fecha_hora'].isoformat() != info['momento_lectura']
                or lectura['usuario_id'] != info['usuario_id']
                or lectura['resultado'] != ('aceptada' if codigo == 'qa01' else 'rechazada')
                or lectura['motivo'] != (None if codigo == 'qa01' else 'no_identificado')):
            raise c.Abortado('Lectura alterada o ajena al ensayo; no se borra.')
    ids_cocineras = {cuentas[nombre] for nombre in ('cocinera1', 'cocinera2', 'cocinera3') if nombre in cuentas}
    sinteticos = set(c.USUARIOS_HISTORICOS) | {s['usuario_id'] for s in c.COMENSALES_QA.values()}
    asist_por_id = {a['id']: a for a in asistencias}
    if len(asist_por_id) != len(asistencias):
        raise c.Abortado('Asistencias duplicadas o ambiguas.')
    por_lectura = {}
    registradas = {}
    for intervencion in intervenciones:
        lid = intervencion['lectura_id']
        if (lid not in por_lid or por_lid[lid][0] != 'qa02'
                or intervencion['cuenta_id'] not in ids_cocineras
                or intervencion['usuario_id'] not in sinteticos
                or intervencion['resultado'] not in ('registrada', 'rechazada')):
            raise c.Abortado('Intervención ajena al ensayo o a sus cuentas sintéticas.')
        aid = intervencion['asistencia_id']
        if intervencion['resultado'] == 'registrada':
            if aid is None or aid not in asist_por_id or aid in registradas or intervencion['motivo_rechazo'] is not None:
                raise c.Abortado('Intervención registrada sin correspondencia única de asistencia.')
            registradas[aid] = intervencion
        elif aid is not None or intervencion['motivo_rechazo'] is None:
            raise c.Abortado('Rechazo de intervención inconsistente.')
    for asistencia in asistencias:
        lid = asistencia['lectura_id']
        if lid not in por_lid or lid in por_lectura:
            raise c.Abortado('Asistencia ajena o múltiple para una lectura del ensayo.')
        por_lectura[lid] = asistencia['id']
        codigo, info = por_lid[lid]
        if (asistencia['comida_id'] != c.comida_corrida(datos)
                or asistencia['fecha_comida'].isoformat() != (datos.get('fecha_destino') or datos['fecha_original'])):
            raise c.Abortado('La asistencia no corresponde al servicio del ensayo.')
        if codigo == 'qa01':
            if (asistencia['usuario_id'] != info['usuario_id'] or asistencia['metodo'] != 'biometrico'
                    or asistencia['registrado_por_cuenta'] is not None
                    or asistencia['turno_asignado_id'] != info['asignacion_id']):
                raise c.Abortado('La asistencia normal no pertenece a QA 01.')
        else:
            intervencion = registradas.get(asistencia['id'])
            if (not intervencion or asistencia['usuario_id'] not in sinteticos
                    or asistencia['metodo'] != 'manual'
                    or asistencia['registrado_por_cuenta'] not in ids_cocineras
                    or intervencion['usuario_id'] != asistencia['usuario_id']
                    or intervencion['cuenta_id'] != asistencia['registrado_por_cuenta']
                    or intervencion['lectura_id'] != lid):
                raise c.Abortado('La asistencia manual no corresponde a su intervención QA.')


def evidencia(filas):
    return [{k: v.isoformat() if isinstance(v, (date, datetime)) else v for k, v in fila.items()}
            for fila in filas]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--aplicar', action='store_true')
    args = parser.parse_args()
    permitidas = c.permisos((c.DEMO, 'turnos_asignados', 'UPDATE'), *(
        (c.SIM, tabla, 'DELETE') for tabla in (
            'intervenciones_lectura', 'asistencias', 'lecturas_biometricas', 'sesiones', 'intentos_login')
    )) if args.aplicar else ()
    with c.bloqueo_corrida(), c.entorno_seguro(permitidas) as (motor, huella, servidor):
        if (c.CARPETA / 'api.activa').exists():
            raise c.Abortado('Detener la API antes de archivar el ensayo fallido.')
        datos = c.leer_corrida(servidor)
        c.comprobar_base(datos, huella)
        if not c.es_corrida_multi(datos):
            raise c.Abortado('Este cierre solo corresponde al escenario de tres comensales QA.')
        with motor.begin() as conn:
            asignaciones = c.filas_asignaciones_corrida(conn, datos, bloquear=args.aplicar)
            cuentas = conn.execute(text(
                "SELECT id,username,rol,usuario_turnos_id FROM usuarios_sistema "
                "WHERE username IN ('cocinera1','cocinera2','cocinera3','jefa')"
            )).mappings().all()
            actuales = c.validar_cuentas_limpieza(cuentas, datos['cuentas'])
            filtros, params = limpiar.objetivos(conn, datos, actuales)
            # Estas condiciones incluyen también datos ajenos sobre los tres usuarios, para abortar.
            params.update(u1=900101, u2=900102, u3=900103, dispositivo=c.DISPOSITIVO)
            por_tabla = dict(filtros)
            bloqueo = ' FOR UPDATE' if args.aplicar else ''
            lecturas = conn.execute(text(
                'SELECT id,usuario_id,dispositivo,fecha_hora,resultado,motivo FROM lecturas_biometricas WHERE '
                + por_tabla['lecturas_biometricas'] + ' OR dispositivo=:dispositivo OR usuario_id IN (:u1,:u2,:u3)' + bloqueo
            ), params).mappings().all()
            asistencias = conn.execute(text(
                'SELECT id,lectura_id,usuario_id,comida_id,fecha_comida,turno_asignado_id,metodo,registrado_por_cuenta '
                'FROM asistencias WHERE ' + por_tabla['asistencias'] + ' OR usuario_id IN (:u1,:u2,:u3)' + bloqueo
            ), params).mappings().all()
            intervenciones = conn.execute(text(
                'SELECT id,lectura_id,usuario_id,cuenta_id,asistencia_id,resultado,motivo_rechazo '
                'FROM intervenciones_lectura WHERE ' + por_tabla['intervenciones_lectura']
                + ' OR usuario_id IN (:u1,:u2,:u3)' + bloqueo
            ), params).mappings().all()
            import lector_enrolado
            extras = lector_enrolado.validar(conn, datos) if datos.get('lecturas_enroladas') else set()
            validar_filas(datos, [f for f in lecturas if f['id'] not in extras],
                          [f for f in asistencias if f['lectura_id'] not in extras], intervenciones, actuales)
            antes = limpiar.contar(conn, filtros, params)
            if args.aplicar:
                datos['evidencia_ensayo_fallido'] = {
                    'lecturas': evidencia(lecturas), 'asistencias': evidencia(asistencias),
                    'intervenciones': evidencia(intervenciones),
                    'resultado': 'archivado_sin_convertir_a_aprobado',
                }
                datos['estado'] = 'limpieza_pendiente'
                c.guardar_corrida(datos)
                for tabla, filtro in filtros:
                    borrado = conn.execute(text(f'DELETE FROM `{tabla}` WHERE {filtro}'), params)
                    if borrado.rowcount != antes[tabla]['de_corrida']:
                        raise c.Abortado('Las filas cambiaron durante el cierre; rollback.')
                original = date.fromisoformat(datos['fecha_original'])
                if asignaciones['fecha'] != original:
                    c.cambiar_fecha_corrida(conn, datos, asignaciones['fecha'], original)
                c.restaurar_turno_laboratorio(conn, datos)
                despues = limpiar.contar(conn, filtros, params)
                if any(v['de_corrida'] for v in despues.values()):
                    raise c.Abortado('Quedaron datos del ensayo; rollback.')
                if any(despues[t]['total_tabla'] != antes[t]['total_tabla'] - antes[t]['de_corrida'] for t in antes):
                    raise c.Abortado('Cambió un dato ajeno; rollback.')
        if args.aplicar:
            datos.update(estado='limpia', fin=datetime.now().isoformat(), limpieza={'antes': antes, 'despues': despues})
            c.guardar_corrida(datos)
        print('Cierre de ensayo fallido validado.' if args.aplicar else 'Simulacro: titularidad comprobada sin modificar datos ni diario.')


if __name__ == '__main__':
    c.ejecutar(main)
