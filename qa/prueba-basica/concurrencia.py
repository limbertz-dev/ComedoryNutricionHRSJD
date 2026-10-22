"""Adaptador QA de transacciones simultaneas, con diario breve y limpieza exacta.

Solo se instala por ejecutar_app.py --laboratorio. El bloqueo del diario nunca
abarca una transaccion SQL. Las barreras son instrumentacion de prueba; no
cambian las reglas ni el resultado de registrar_marcacion/identificar_lectura.
"""
from contextvars import ContextVar
from datetime import datetime
import threading
import time
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.orm import Session
import comun as c
import enrolamiento

DISPOSITIVO = 'lector-concurrencia-qa'
_diario = threading.RLock()
_solicitudes = {}
_grupos = {}
_grupo_actual = ContextVar('grupo_qa', default=None)


def uuid_valido(valor):
    try:
        return str(UUID(valor)) == valor and UUID(valor).version == 4
    except (ValueError, TypeError, AttributeError):
        return False


def actualizar(servidor, huella, solicitud, campos):
    with _diario, c.bloqueo_corrida():
        datos = c.leer_corrida(servidor)
        c.comprobar_base(datos, huella)
        filas = datos.setdefault('lecturas_concurrentes', [])
        fila = next((f for f in filas if f['solicitud'] == solicitud), None)
        if fila is None:
            fila = {'solicitud': solicitud, 'emitidos': []}
            filas.append(fila)
        if 'emitidos' in campos:
            campos = {**campos, 'emitidos': list(dict.fromkeys([*fila['emitidos'], *campos['emitidos']]))}
        fila.update(campos)
        c.guardar_corrida(datos)


def validar(conn, datos):
    """Valida todas las relaciones antes de seleccionar IDs para borrar."""
    propios = set()
    cuentas = {datos['cuentas'][n] for n in ('cocinera1', 'cocinera2', 'cocinera3') if n in datos['cuentas']}
    perfiles = {p['usuario_id']: p for p in c.COMENSALES_QA.values()}
    solicitudes = set()
    for info in datos.get('lecturas_concurrentes', []):
        if (info['solicitud'] in solicitudes or not uuid_valido(info['solicitud'].split(':')[-1])
                or info['cuenta_id'] not in cuentas or info['usuario_id'] not in {None, *perfiles}
                or info['solicitud'].split(':')[0] != str(info['cuenta_id'])
                or info['titular'] not in perfiles):
            raise c.Abortado('Solicitud concurrente ajena o duplicada.')
        solicitudes.add(info['solicitud'])
        persistidas = []
        for lid in info['emitidos']:
            if type(lid) is not int or lid <= 0 or lid in propios:
                raise c.Abortado('ID concurrente ambiguo.')
            propios.add(lid)
            fila = conn.execute(text('SELECT id,usuario_id,dispositivo,fecha_hora,resultado,motivo FROM lecturas_biometricas WHERE id=:id'), {'id': lid}).mappings().one_or_none()
            if fila is None:
                continue  # after_flush registra tambien el ID revertido por el indice unico.
            persistidas.append(lid)
            if (fila['usuario_id'] != info['usuario_id'] or fila['dispositivo'] != DISPOSITIVO
                    or datetime.fromisoformat(str(fila['fecha_hora'])) != datetime.fromisoformat(info['momento'])):
                raise c.Abortado('Lectura concurrente alterada; no se borra.')
            asistencias = conn.execute(text('SELECT * FROM asistencias WHERE lectura_id=:id'), {'id': lid}).mappings().all()
            intervenciones = conn.execute(text('SELECT * FROM intervenciones_lectura WHERE lectura_id=:id'), {'id': lid}).mappings().all()
            if fila['resultado'] == 'aceptada':
                if fila['motivo'] is not None or len(asistencias) != 1 or intervenciones or info['usuario_id'] is None:
                    raise c.Abortado('Entrega concurrente sin correspondencia unica.')
            elif fila['resultado'] == 'rechazada':
                if info['usuario_id'] is not None:
                    if asistencias or intervenciones or fila['motivo'] not in {'duplicado','sin_derecho','fuera_horario'}:
                        raise c.Abortado('Rechazo concurrente con entrega indebida.')
                elif fila['motivo'] != 'no_identificado' or len(asistencias) > 1:
                    raise c.Abortado('Lectura desconocida concurrente incompatible.')
            else:
                raise c.Abortado('Resultado concurrente desconocido.')
            registradas = [i for i in intervenciones if i['resultado'] == 'registrada']
            if info['usuario_id'] is None and len(registradas) != len(asistencias):
                raise c.Abortado('Asistencia manual sin intervencion correspondiente.')
            for a in asistencias:
                uid = a['usuario_id']
                manual = info['usuario_id'] is None
                if (uid not in perfiles or (not manual and uid != info['usuario_id'])
                        or a['comida_id'] != info['comida_id'] or str(a['fecha_comida']) != info['fecha_comida']
                        or a['turno_asignado_id'] != perfiles[uid]['asignacion_id']
                        or a['servicio_id'] != c.PERFILES_QA[uid]['servicio_id']
                        or a['metodo'] != ('manual' if manual else 'biometrico')
                        or (a['registrado_por_cuenta'] not in cuentas if manual else a['registrado_por_cuenta'] is not None)):
                    raise c.Abortado('Relacion concurrente ajena al escenario.')
                if manual and not any(i['asistencia_id'] == a['id'] and i['usuario_id'] == uid
                                     and i['cuenta_id'] == a['registrado_por_cuenta'] for i in registradas):
                    raise c.Abortado('Intervencion concurrente cruzada.')
            for i in intervenciones:
                if i['cuenta_id'] not in cuentas or i['usuario_id'] not in perfiles:
                    raise c.Abortado('Intervencion concurrente de una identidad ajena.')
                if i['resultado'] == 'registrada':
                    if i['motivo_rechazo'] is not None or not any(a['id'] == i['asistencia_id'] for a in asistencias):
                        raise c.Abortado('Intervencion concurrente sin asistencia propia.')
                elif i['resultado'] != 'rechazada' or i['asistencia_id'] is not None or i['motivo_rechazo'] is None:
                    raise c.Abortado('Resultado de intervencion concurrente incompatible.')
        if len(persistidas) > 1:
            raise c.Abortado('Una solicitud concurrente produjo varias lecturas persistidas.')
        if info.get('respuesta') and persistidas != [info['respuesta']['lectura_id']]:
            raise c.Abortado('La respuesta concurrente no corresponde a su fila.')
    ajenas = conn.execute(text('SELECT id FROM lecturas_biometricas WHERE dispositivo=:d'), {'d': DISPOSITIVO}).scalars().all()
    if set(ajenas) - propios:
        raise c.Abortado('Lecturas concurrentes fuera del diario; se conservan.')
    otros = c.ids_casos_corrida(datos) | {f.get('lectura_id') for f in datos.get('lecturas_enroladas', [])}
    if propios & otros:
        raise c.Abortado('Lectura compartida entre diarios.')
    return propios


def procesar(motor, servidor, huella, cuenta_id, referencia, desconocida, clave):
    from app.core import reloj
    from app.logica.marcacion import registrar_marcacion, resolver_comida_en_curso
    from app.modelos.comedor import LecturaBiometrica
    from app.esquemas.marcacion import RespuestaMarcacion
    if not uuid_valido(clave):
        raise c.Abortado('Se requiere UUID v4 de la solicitud.')
    titular = enrolamiento.resolver(referencia)
    if titular not in c.PERFILES_QA:
        raise c.Abortado('Solo se ensayan huellas de los tres comensales QA.')
    uid = None if desconocida else titular
    solicitud = f'{cuenta_id}:{clave}'
    with _diario:
        candado = _solicitudes.setdefault(solicitud, threading.Lock())
    with candado:
        datos = c.leer_corrida(servidor)
        c.comprobar_base(datos, huella)
        if cuenta_id not in {datos['cuentas'][n] for n in ('cocinera1','cocinera2','cocinera3') if n in datos['cuentas']}:
            raise c.Abortado('Cuenta ajena al escenario.')
        previo = next((f for f in datos.get('lecturas_concurrentes', []) if f['solicitud'] == solicitud), None)
        if previo:
            if previo['usuario_id'] != uid or previo['titular'] != titular:
                raise c.Abortado('Solicitud reutilizada con otra identidad.')
            if previo.get('respuesta'):
                return previo['respuesta']
            raise c.Abortado('Solicitud interrumpida: conservar evidencia y revisar antes de repetir.')
        momento = reloj.ahora()
        with Session(motor) as sesion:
            comida = resolver_comida_en_curso(sesion, momento)
            actualizar(servidor, huella, solicitud, {'cuenta_id': cuenta_id, 'usuario_id': uid, 'titular': titular,
                'momento': momento.isoformat(), 'comida_id': comida.comida_id if comida else None,
                'fecha_comida': comida.fecha_comida.isoformat() if comida else None, 'estado': 'en_curso'})

            def recordar(s, _):
                ids = [obj.id for obj in s.new if isinstance(obj, LecturaBiometrica)]
                if ids:
                    actualizar(servidor, huella, solicitud, {'emitidos': ids})

            event.listen(sesion, 'after_flush', recordar)
            resultado = registrar_marcacion(sesion, usuario_id=uid, momento=momento, dispositivo=DISPOSITIVO)
            respuesta = RespuestaMarcacion(**vars(resultado)).model_dump(mode='json')
            actualizar(servidor, huella, solicitud, {'respuesta': respuesta, 'estado': 'completada'})
            return respuesta


def instalar(app, motor, servidor, huella):
    from typing import Annotated
    from fastapi import APIRouter, Depends, Header, HTTPException
    from pydantic import BaseModel, Field, ConfigDict
    from app.core.autorizacion import UsuarioActual, requiere_rol
    from app.modelos.comedor import LecturaBiometrica, Asistencia
    from app.core.config import config

    if (config.db_name != c.SIM or config.db_name_turnos != c.DEMO
            or app.state.entorno != 'desarrollo'):
        raise c.Abortado('La concurrencia simulada solo se habilita en las bases QA de desarrollo.')

    router = APIRouter(prefix='/_qa/concurrencia', dependencies=[Depends(requiere_rol('cocinera'))])

    class Lectura(BaseModel):
        model_config = ConfigDict(extra='forbid')
        referencia: str
        desconocida: bool = False

    class Grupo(BaseModel):
        participantes: int = Field(ge=1, le=6)
        id: str

    @app.middleware('http')
    async def contexto_grupo(request, call_next):
        contexto = _grupo_actual.set(request.headers.get('X-QA-Grupo'))
        try:
            return await call_next(request)
        finally:
            _grupo_actual.reset(contexto)

    def coincidir(sesion, *_):
        grupo_id = _grupo_actual.get()
        grupo = _grupos.get(grupo_id)
        if not grupo or sesion.info.get('qa_barrera'):
            return
        if not any(isinstance(obj, (LecturaBiometrica, Asistencia)) for obj in sesion.new):
            return
        sesion.info['qa_barrera'] = True
        with _diario:
            grupo['llegadas'].append(time.perf_counter_ns())
        try:
            grupo['barrera'].wait(timeout=12)
        except threading.BrokenBarrierError:
            raise c.Abortado('No coincidieron las transacciones de la prueba; no se aprueba.') from None

    event.listen(Session, 'before_flush', coincidir)

    @router.post('/grupos')
    def grupo(cuerpo: Grupo):
        if not uuid_valido(cuerpo.id) or cuerpo.id in _grupos:
            raise HTTPException(409, 'Grupo invalido o ya usado.')
        _grupos[cuerpo.id] = {'barrera': threading.Barrier(cuerpo.participantes), 'llegadas': []}
        return {'id': cuerpo.id}

    @router.post('/lecturas')
    def leer(cuerpo: Lectura, usuario: UsuarioActual, clave: Annotated[str, Header(alias='Idempotency-Key')]):
        try:
            return procesar(motor, servidor, huella, usuario.id, cuerpo.referencia, cuerpo.desconocida, clave)
        except c.Abortado as error:
            raise HTTPException(409, str(error)) from None

    @router.get('/estado')
    def estado():
        with _diario:
            datos = c.leer_corrida(servidor)
            c.comprobar_base(datos, huella)
            with motor.connect() as conn:
                ids = validar(conn, datos)
                lecturas = [dict(f) for f in conn.execute(text('SELECT id,usuario_id,resultado,motivo FROM lecturas_biometricas WHERE dispositivo=:d'), {'d':DISPOSITIVO}).mappings()]
                asistencias = [dict(f) for f in conn.execute(text('SELECT id,usuario_id,lectura_id,comida_id,metodo,registrado_por_cuenta FROM asistencias')).mappings() if f['lectura_id'] in ids]
                intervenciones = [dict(f) for f in conn.execute(text('SELECT id,lectura_id,usuario_id,cuenta_id,resultado,motivo_rechazo,asistencia_id FROM intervenciones_lectura')).mappings() if f['lectura_id'] in ids]
        return {'lecturas':lecturas,'asistencias':asistencias,'intervenciones':intervenciones,
                'grupos':{k: {'llegadas':len(v['llegadas']), 'lapso_ms':(max(v['llegadas'])-min(v['llegadas']))/1e6 if v['llegadas'] else None} for k,v in _grupos.items()}}

    app.include_router(router)
