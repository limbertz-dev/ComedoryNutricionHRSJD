"""Adaptador de enrolamiento SIMULADO, exclusivo del laboratorio QA.

Persiste referencias sinteticas; no captura dedos, imagenes ni plantillas.
No escribe al padron, a asistencias ni a la base de turnos.
"""
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import json
import os
import unicodedata
from uuid import UUID, uuid4

import comun as c


def _vacio():
    return {'version': 1, 'modo': 'simulado', 'escenario': c.MARCADOR,
            'registros': {}, 'solicitudes': {}}


def leer_registro():
    ruta = c.CARPETA / 'huellas_simuladas.json'
    try:
        datos = json.loads(ruta.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return _vacio()
    except (ValueError, OSError):
        raise c.Abortado('No se pudo leer el registro de huellas de prueba; se conserva el archivo.') from None
    if (not isinstance(datos, dict) or datos.get('version') != 1
            or datos.get('modo') != 'simulado' or datos.get('escenario') != c.MARCADOR
            or not isinstance(datos.get('registros'), dict)
            or not isinstance(datos.get('solicitudes'), dict)):
        raise c.Abortado('El registro de huellas de prueba no tiene el formato esperado.')
    referencias = set()
    for uid, fila in datos['registros'].items():
        if (not isinstance(fila, dict) or type(fila.get('usuario_id')) is not int
                or fila['usuario_id'] <= 0 or uid != str(fila['usuario_id'])
                or type(fila.get('cuenta_id')) is not int or fila['cuenta_id'] <= 0
                or not isinstance(fila.get('registrada_en'), str)
                or not _referencia_valida(fila.get('referencia'))
                or fila['referencia'] in referencias):
            raise c.Abortado('El registro de huellas de prueba contiene vinculos inconsistentes.')
        referencias.add(fila['referencia'])
    for clave, uid in datos['solicitudes'].items():
        partes = clave.split(':', 1)
        if (len(partes) != 2 or not partes[0].isdigit() or int(partes[0]) <= 0
                or not _uuid4_valido(partes[1]) or type(uid) is not int
                or str(uid) not in datos['registros']):
            raise c.Abortado('El registro de solicitudes de prueba es inconsistente.')
    return datos


def _uuid4_valido(valor):
    try:
        return isinstance(valor, str) and str(UUID(valor)) == valor and UUID(valor).version == 4
    except ValueError:
        return False


def _referencia_valida(valor):
    return isinstance(valor, str) and valor.startswith('SIM-HUELLA-') and _uuid4_valido(valor[11:])


@contextmanager
def _bloqueo():
    ruta = c.CARPETA / 'huellas_simuladas.lock'
    try:
        fd = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise c.Abortado('Hay un registro de huella en curso. Vuelve a verificar el registro.') from None
    try:
        os.close(fd)
        yield
    finally:
        ruta.unlink()


def registrar(usuario_id, cuenta_id, clave):
    if (type(usuario_id) is not int or usuario_id <= 0 or type(cuenta_id) is not int
            or cuenta_id <= 0 or not _uuid4_valido(clave)):
        raise c.Abortado('Revisa la persona y la solicitud de registro de huella.')
    with _bloqueo():
        datos = leer_registro()
        solicitud = f'{cuenta_id}:{clave}'
        previo = datos['solicitudes'].get(solicitud)
        if previo is not None and previo != usuario_id:
            raise c.Abortado('Esta solicitud pertenece a otra persona; no se cambio el vinculo.')
        existente = datos['registros'].get(str(usuario_id))
        fila = existente or {
            'usuario_id': usuario_id, 'referencia': f'SIM-HUELLA-{uuid4()}',
            'cuenta_id': cuenta_id, 'registrada_en': datetime.now(timezone.utc).isoformat(),
        }
        if any(r['referencia'] == fila['referencia'] and r['usuario_id'] != usuario_id
               for r in datos['registros'].values()):
            raise c.Abortado('La referencia ya esta vinculada a otra persona. Repite la captura.')
        datos['registros'][str(usuario_id)] = fila
        datos['solicitudes'][solicitud] = usuario_id
        contenido = json.dumps(datos, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
        c._sin_secretos(datos)
        temporal = c.CARPETA / 'huellas_simuladas.json.tmp'
        try:
            with temporal.open('w', encoding='utf-8') as archivo:
                archivo.write(contenido)
                archivo.flush()
                os.fsync(archivo.fileno())
            os.replace(temporal, c.CARPETA / 'huellas_simuladas.json')
        finally:
            temporal.unlink(missing_ok=True)
        return {**fila, 'modo': 'simulado', 'ya_registrada': existente is not None}


def registro_de(usuario_id):
    return leer_registro()['registros'].get(str(usuario_id))


def resolver(referencia):
    if not _referencia_valida(referencia):
        return None
    return next((r['usuario_id'] for r in leer_registro()['registros'].values()
                 if r['referencia'] == referencia), None)


def listar_registros(motor, busqueda='', limite=50, desplazamiento=0, fecha=None):
    """Consulta el vinculo original; no expone referencias ni datos biometricos.

    `fecha` (date) deja solo las altas de ese dia en hora de Bolivia (UTC-4)."""
    from sqlalchemy import select, func
    from sqlalchemy.orm import Session
    from app.modelos.heredados import Comensal, Servicio, UsuarioServicio
    from app.modelos.usuarios import UsuarioSistema

    registros = list(leer_registro()['registros'].values())
    momentos = {}
    for fila in registros:
        try:
            momento = datetime.fromisoformat(fila['registrada_en'])
            if momento.utcoffset() is None:
                raise ValueError
        except ValueError:
            raise c.Abortado('Una fecha del registro de huellas no es valida; se conserva la evidencia.') from None
        momentos[fila['usuario_id']] = momento
    if fecha is not None:
        bolivia = timezone(timedelta(hours=-4))
        registros = [f for f in registros if momentos[f['usuario_id']].astimezone(bolivia).date() == fecha]
    registros.sort(key=lambda f: (momentos[f['usuario_id']], f['usuario_id']), reverse=True)
    personas, cuentas = {}, {}
    if registros:
        with Session(motor) as sesion:
            sala = select(UsuarioServicio.usuario_id, func.max(UsuarioServicio.id).label('id')).where(
                UsuarioServicio.estado == 1).group_by(UsuarioServicio.usuario_id).subquery()
            fichas = sesion.execute(select(
                Comensal.usuario_id, Comensal.nombre_completo, Comensal.numero_item,
                Comensal.categoria, Servicio.nombre.label('servicio'), Comensal.tiene_ficha,
            ).outerjoin(sala, sala.c.usuario_id == Comensal.usuario_id).outerjoin(
                UsuarioServicio, UsuarioServicio.id == sala.c.id).outerjoin(
                Servicio, Servicio.id == UsuarioServicio.servicio_id).where(
                Comensal.usuario_id.in_([f['usuario_id'] for f in registros]))).mappings()
            personas = {f['usuario_id']: f for f in fichas}
            # Seleccion explicita: nunca cargar hash de clave ni tokens en este listado.
            operadores = sesion.execute(select(UsuarioSistema.id, UsuarioSistema.username,
                                               UsuarioSistema.nombre).where(
                UsuarioSistema.id.in_({f['cuenta_id'] for f in registros}))).mappings()
            cuentas = {f['id']: f for f in operadores}

    def normalizar(valor):
        return ''.join(letra for letra in unicodedata.normalize('NFKD', valor.casefold())
                       if not unicodedata.combining(letra))

    termino = normalizar(busqueda.strip())
    filas = []
    for registro in registros:
        uid, cid = registro['usuario_id'], registro['cuenta_id']
        ficha, cuenta = personas.get(uid), cuentas.get(cid)
        fila = {
            'registrada_en': registro['registrada_en'],
            'comensal': {'usuario_id': uid, 'nombre': ficha['nombre_completo'] if ficha else None,
                         'legajo': ficha['numero_item'] if ficha else None,
                         'categoria': ficha['categoria'] if ficha else None,
                         'servicio': ficha['servicio'] if ficha else None,
                         'disponible': bool(ficha and ficha['tiene_ficha'])},
            'cuenta': {'id': cid, 'usuario': cuenta['username'] if cuenta else None,
                       'nombre': cuenta['nombre'] if cuenta else None, 'disponible': cuenta is not None},
        }
        texto = ' '.join(str(v) for bloque in (fila['comensal'], fila['cuenta']) for v in bloque.values() if v is not None)
        if not termino or termino in normalizar(texto):
            filas.append(fila)
    return {'datos': filas[desplazamiento:desplazamiento + limite], 'total': len(filas),
            'limite': limite, 'desplazamiento': desplazamiento, 'modo': 'simulado'}


def instalar(app, motor, servidor, huella):
    """Solo lo llama ejecutar_app.py api --laboratorio, nunca app.main normal."""
    from typing import Annotated
    from fastapi import APIRouter, Depends, Header, HTTPException, Query
    from pydantic import BaseModel, ConfigDict, Field
    from sqlalchemy import select, func
    from sqlalchemy.orm import Session
    from app.core.autorizacion import UsuarioActual, requiere_rol
    from app.core.config import config
    from app.modelos.heredados import Comensal, Servicio, UsuarioServicio
    from app.consultas.perfiles import categoria_permitida, categoria_permitida_sql

    if (config.db_name != c.SIM or config.db_name_turnos != c.DEMO
            or app.state.entorno != 'desarrollo'):
        raise c.Abortado('El alta simulada solo se habilita en las bases QA de desarrollo.')

    router = APIRouter(prefix='/_qa/enrolamiento', tags=['laboratorio QA'],
                       dependencies=[Depends(requiere_rol('cocinera', 'sistemas'))])
    consultas = APIRouter(prefix='/_qa/enrolamiento', tags=['laboratorio QA'],
                         dependencies=[Depends(requiere_rol('jefa'))])

    class Captura(BaseModel):
        model_config = ConfigDict(extra='forbid')
        usuario_id: Annotated[int, Field(strict=True, gt=0)]

    class Lectura(BaseModel):
        model_config = ConfigDict(extra='forbid')
        referencia: str

    def comprobar_corrida():
        datos = c.leer_corrida(servidor)
        c.comprobar_base(datos, huella)
        if not c.es_corrida_multi(datos) or not datos.get('parte_a', {}).get('completa'):
            raise c.Abortado('Completa la preparacion de las cuentas QA antes de registrar huellas.')

    @consultas.get('/registros')
    def registros(busqueda: Annotated[str, Query(max_length=100)] = '',
                  limite: Annotated[int, Query(ge=1, le=100)] = 50,
                  desplazamiento: Annotated[int, Query(ge=0)] = 0,
                  fecha: Annotated[date | None, Query(description='Solo las altas de ese día (Bolivia)')] = None):
        try:
            comprobar_corrida()
            return listar_registros(motor, busqueda, limite, desplazamiento, fecha)
        except c.Abortado as error:
            raise HTTPException(409, detail=str(error)) from None

    @router.get('/personas')
    def personas(usuario: UsuarioActual):
        try:
            comprobar_corrida()
            with Session(motor) as sesion:
                sala = select(UsuarioServicio.usuario_id, func.max(UsuarioServicio.id).label('id')).where(
                    UsuarioServicio.estado == 1).group_by(UsuarioServicio.usuario_id).subquery()
                filas = sesion.execute(select(
                    Comensal.usuario_id, Comensal.nombre_completo, Comensal.numero_item,
                    Comensal.categoria, Servicio.nombre.label('servicio'),
                ).outerjoin(sala, sala.c.usuario_id == Comensal.usuario_id).outerjoin(
                    UsuarioServicio, UsuarioServicio.id == sala.c.id).outerjoin(
                    Servicio, Servicio.id == UsuarioServicio.servicio_id).where(
                    Comensal.tiene_ficha == 1, categoria_permitida_sql(Comensal.categoria),
                ).order_by(Comensal.nombre_completo, Comensal.usuario_id)).mappings().all()
            registros = leer_registro()['registros']
            return [{'id': f['usuario_id'], 'nombre': f['nombre_completo'] or f"Comensal {f['usuario_id']}",
                     'legajo': f['numero_item'] or 'Sin legajo', 'categoria': f['categoria'],
                     'servicio': f['servicio'] or 'Sin servicio',
                     'huella_registrada': str(f['usuario_id']) in registros} for f in filas]
        except c.Abortado as error:
            raise HTTPException(409, detail=str(error)) from None

    @router.post('/capturas')
    def capturar(solicitud: Captura, usuario: UsuarioActual,
                 clave: Annotated[str, Header(alias='Idempotency-Key')]):
        try:
            comprobar_corrida()
            with Session(motor) as sesion:
                ficha = sesion.get(Comensal, solicitud.usuario_id)
                if ficha is None or not ficha.tiene_ficha:
                    raise HTTPException(404, detail='La persona no esta disponible en el padron QA.')
                if not categoria_permitida(ficha.categoria):
                    from app.core.autorizacion import ErrorAuth
                    raise ErrorAuth(403, 'perfil_no_autorizado', 'Esta categoria no esta habilitada para el comedor.')
                return registrar(solicitud.usuario_id, usuario.id, clave)
        except c.Abortado as error:
            raise HTTPException(409, detail=str(error)) from None

    @router.post('/lecturas')
    def leer(solicitud: Lectura, usuario: UsuarioActual,
             clave: Annotated[str, Header(alias='Idempotency-Key')]):
        import lector_enrolado
        try:
            comprobar_corrida()
            return lector_enrolado.procesar(motor, servidor, huella, usuario.id, solicitud.referencia, clave)
        except c.Abortado as error:
            raise HTTPException(409, detail=str(error)) from None

    app.include_router(router)
    app.include_router(consultas)
