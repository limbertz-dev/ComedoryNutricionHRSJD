"""Lectura reconocida de referencias enroladas, con diario y propiedad exacta."""
from datetime import datetime
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.orm import Session

import comun as c
import enrolamiento

DISPOSITIVO = 'lector-enrolamiento-qa'


def _uuid(valor):
    try:
        return str(UUID(valor)) == valor and UUID(valor).version == 4
    except (ValueError, TypeError, AttributeError):
        return False


def validar(conn, datos):
    """Solo SELECT; devuelve IDs propios para conciliar y limpiar sin adivinar."""
    ids, solicitudes = set(), set()
    registros = datos.get('lecturas_enroladas', [])
    if not isinstance(registros, list):
        raise c.Abortado('Diario de lecturas enroladas incompatible.')
    for info in registros:
        if (not isinstance(info, dict) or not _uuid(info.get('solicitud_id'))
                or type(info.get('cuenta_id')) is not int or info['cuenta_id'] not in datos['cuentas'].values()
                or type(info.get('usuario_id')) is not int or info['usuario_id'] <= 0
                or (info['cuenta_id'], info['solicitud_id']) in solicitudes):
            raise c.Abortado('Diario de lecturas enroladas incompatible.')
        solicitudes.add((info['cuenta_id'], info['solicitud_id']))
        lid = info.get('lectura_id')
        if lid is None:
            if info.get('asistencia_id') is not None:
                raise c.Abortado('Asistencia enrolada sin lectura en el diario.')
            continue
        if type(lid) is not int or lid <= 0 or lid in ids:
            raise c.Abortado('ID de lectura enrolada invalido o duplicado.')
        ids.add(lid)
        lectura = conn.execute(text('SELECT id,usuario_id,dispositivo,fecha_hora,resultado,motivo FROM lecturas_biometricas WHERE id=:id'), {'id': lid}).mappings().one_or_none()
        if lectura is None:
            # IDs recordados por after_flush antes de un rollback son recuperables.
            if info.get('asistencia_id') is not None and conn.execute(text('SELECT id FROM asistencias WHERE id=:id'), {'id': info['asistencia_id']}).first():
                raise c.Abortado('Asistencia persistida sin su lectura enrolada; se conserva.')
            continue
        try:
            momento = datetime.fromisoformat(str(lectura['fecha_hora']))
            esperado = datetime.fromisoformat(info['momento_lectura'])
        except (ValueError, TypeError, KeyError):
            raise c.Abortado('Momento de lectura enrolada incompatible.') from None
        if (lectura['usuario_id'] != info['usuario_id'] or lectura['dispositivo'] != DISPOSITIVO
                or momento != esperado
                or lectura['resultado'] not in {'aceptada', 'rechazada'}
                or (lectura['resultado'] == 'aceptada' and lectura['motivo'] is not None)
                or (lectura['resultado'] == 'rechazada' and lectura['motivo'] not in {'duplicado', 'sin_derecho', 'fuera_horario'})):
            raise c.Abortado('Lectura enrolada ajena o alterada; se conserva.')
        asistencias = conn.execute(text('SELECT id,lectura_id,usuario_id,comida_id,fecha_comida,servicio_id,turno_asignado_id,metodo,registrado_por_cuenta FROM asistencias WHERE lectura_id=:id OR (:aid IS NOT NULL AND id=:aid)'), {'id': lid, 'aid': info.get('asistencia_id')}).mappings().all()
        intervenciones = conn.execute(text('SELECT id FROM intervenciones_lectura WHERE lectura_id=:id'), {'id': lid}).all()
        if intervenciones:
            raise c.Abortado('Una lectura reconocida no debe tener intervenciones de cocina.')
        if lectura['resultado'] == 'rechazada' and (asistencias or info.get('asistencia_id') is not None):
            raise c.Abortado('Lectura enrolada rechazada con una asistencia incompatible.')
        if lectura['resultado'] == 'aceptada':
            if len(asistencias) != 1:
                raise c.Abortado('Lectura enrolada aceptada sin su asistencia unica.')
            asistencia = asistencias[0]
            if (asistencia['id'] != info.get('asistencia_id') or asistencia['lectura_id'] != lid
                    or asistencia['usuario_id'] != info['usuario_id'] or asistencia['comida_id'] != info.get('comida_id')
                    or str(asistencia['fecha_comida']) != info.get('fecha_comida')
                    or asistencia['servicio_id'] != info.get('servicio_id')
                    or asistencia['turno_asignado_id'] is None or asistencia['turno_asignado_id'] != info.get('turno_asignado_id')
                    or asistencia['metodo'] != 'biometrico'
                    or asistencia['registrado_por_cuenta'] is not None):
                raise c.Abortado('Asistencia enrolada con relaciones incompatibles.')
    ajenas = conn.execute(text('SELECT id FROM lecturas_biometricas WHERE dispositivo=:d'), {'d': DISPOSITIVO}).all()
    if any(f[0] not in ids for f in ajenas):
        raise c.Abortado('Hay lecturas del adaptador sin propiedad en el diario; no se borran.')
    return ids


def _recuperar(conn, datos, info):
    validar(conn, datos)
    if info.get('lectura_id') is None:
        return None
    lectura = conn.execute(text('SELECT resultado,motivo FROM lecturas_biometricas WHERE id=:id'), {'id': info['lectura_id']}).mappings().one_or_none()
    if lectura is None:
        return None
    if info.get('respuesta'):
        respuesta = info['respuesta']
        if (respuesta.get('usuario_id') != info['usuario_id'] or respuesta.get('lectura_id') != info['lectura_id']
                or respuesta.get('asistencia_id') != info.get('asistencia_id')
                or respuesta.get('valido') != (lectura['resultado'] == 'aceptada') or respuesta.get('motivo') != lectura['motivo']):
            raise c.Abortado('La respuesta del diario no coincide con la lectura persistida.')
        return respuesta
    valido = lectura['resultado'] == 'aceptada'
    return {'valido': valido, 'motivo': lectura['motivo'], 'usuario_id': info['usuario_id'],
            'nombre': info.get('nombre'), 'comida': info.get('comida'),
            'lectura_id': info['lectura_id'], 'asistencia_id': info.get('asistencia_id'),
            'titulo': 'Ración registrada' if valido else 'Lectura reconocida: entrega rechazada',
            'detalle': 'Registro recuperado del diario y contrastado con la base.', 'modo': 'simulado'}


def procesar(motor, servidor, huella, cuenta_id, referencia, solicitud_id):
    if not _uuid(solicitud_id):
        raise c.Abortado('Falta una solicitud de lectura valida.')
    uid = enrolamiento.resolver(referencia)
    if uid is None:
        raise c.Abortado('Esta huella de prueba no esta registrada. Registra su vinculo antes de leerla.')
    with c.bloqueo_corrida():
        datos = c.leer_corrida(servidor)
        c.comprobar_base(datos, huella)
        if cuenta_id not in datos['cuentas'].values():
            raise c.Abortado('La cuenta no pertenece al escenario QA.')
        intentos = datos.setdefault('lecturas_enroladas', [])
        info = next((f for f in intentos if f['cuenta_id'] == cuenta_id and f['solicitud_id'] == solicitud_id), None)
        if info is not None and info['usuario_id'] != uid:
            raise c.Abortado('No se puede reutilizar esta lectura para otra persona.')
        with motor.connect() as conn:
            validar(conn, datos)
            if info is not None:
                previo = _recuperar(conn, datos, info)
                if previo is not None:
                    return previo
        with c.app_sin_dotenv(), c.reloj_laboratorio(datos) as reloj, Session(motor) as sesion:
            from app.logica.marcacion import registrar_marcacion, resolver_comida_en_curso
            from app.modelos.comedor import LecturaBiometrica, Asistencia
            from app.modelos.heredados import Comensal
            persona = sesion.get(Comensal, uid)
            if persona is None:
                raise c.Abortado('La persona vinculada ya no esta en el padron.')
            momento = reloj.ahora()
            comida = resolver_comida_en_curso(sesion, momento)
            if info is None:
                info = {'cuenta_id': cuenta_id, 'solicitud_id': solicitud_id, 'usuario_id': uid}
                intentos.append(info)
            info.update(momento_lectura=momento.isoformat(), lectura_id=None, asistencia_id=None,
                        comida_id=comida.comida_id if comida else None, comida=comida.comida if comida else None,
                        fecha_comida=comida.fecha_comida.isoformat() if comida else None,
                        nombre=persona.nombre_completo, respuesta=None)
            c.guardar_corrida(datos)

            def recordar(s, _):
                for obj in s.new:
                    if isinstance(obj, LecturaBiometrica):
                        info['lectura_id'] = obj.id
                    elif isinstance(obj, Asistencia):
                        info['asistencia_id'] = obj.id
                        info['turno_asignado_id'] = obj.turno_asignado_id
                        info['servicio_id'] = obj.servicio_id
                c.guardar_corrida(datos)

            event.listen(sesion, 'after_flush', recordar)
            resultado = registrar_marcacion(sesion, usuario_id=uid, momento=momento, dispositivo=DISPOSITIVO)
            from app.esquemas.marcacion import RespuestaMarcacion
            respuesta = {**RespuestaMarcacion(**vars(resultado)).model_dump(mode='json'), 'modo': 'simulado'}
            info.update(lectura_id=resultado.lectura_id, asistencia_id=resultado.asistencia_id, respuesta=respuesta)
            c.guardar_corrida(datos)
            return respuesta
