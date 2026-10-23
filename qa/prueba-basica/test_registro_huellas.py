"""Listado de vinculos reales del archivo QA con SQL y permisos reales offline."""
from types import SimpleNamespace
from uuid import uuid4
import json

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

import comun as c
import enrolamiento as e
from test_perfiles_lectura import circuito


def test_listado_relaciona_comensal_y_operador_original_sin_modificar_registro(circuito):
    motor, _ = circuito
    with c.app_sin_dotenv():
        from app.modelos.usuarios import UsuarioSistema
        with Session(motor) as sesion:
            sesion.add(UsuarioSistema(id=7, username='cocinera1', nombre='Operadora Uno', rol='cocinera',
                                      password_hash='fixture-no-autenticable', debe_cambiar=False, activo=True))
            sesion.commit()
        original = e.registrar(900101, 2, str(uuid4()))
        e.registrar(900102, 7, str(uuid4()))
        e.registrar(900101, 7, str(uuid4()))
        ruta = c.CARPETA / 'huellas_simuladas.json'
        antes = ruta.read_bytes()
        sql = []
        def recordar(_conn, _cursor, sentencia, *_):
            sql.append(sentencia)
        event.listen(motor, 'before_cursor_execute', recordar)
        try:
            pagina = e.listar_registros(motor, limite=1)
            otra = e.listar_registros(motor, limite=1, desplazamiento=1)
        finally:
            event.remove(motor, 'before_cursor_execute', recordar)
        assert pagina['total'] == 2 and len(pagina['datos']) == 1
        assert pagina['datos'][0]['comensal']['usuario_id'] == 900102
        assert pagina['datos'][0]['cuenta']['usuario'] == 'cocinera1'
        fila = otra['datos'][0]
        assert fila['comensal']['nombre'] == c.COMENSALES_QA['qa01']['nombre']
        assert fila['comensal']['legajo'] == 'LEG-QA01'
        assert fila['cuenta']['usuario'] == 'cocinera2'
        assert fila['registrada_en'] == original['registrada_en']
        assert all('password_hash' not in sentencia for sentencia in sql)
        assert 'SIM-HUELLA-' not in json.dumps(pagina)
        assert ruta.read_bytes() == antes
        assert e.listar_registros(motor, busqueda='leg-qa02')['datos'][0]['comensal']['usuario_id'] == 900102
        assert e.listar_registros(motor, busqueda='MÉDICOS')['total'] == 1
        assert e.listar_registros(motor, busqueda='Operadora Uno')['total'] == 1
        assert e.listar_registros(motor, busqueda='900101')['total'] == 1
        assert e.listar_registros(motor, busqueda='inexistente')['datos'] == []


def test_vinculo_sin_ficha_o_cuenta_no_desaparece(circuito):
    motor, _ = circuito
    e.registrar(900199, 555, str(uuid4()))
    with c.app_sin_dotenv():
        fila = e.listar_registros(motor)['datos'][0]
    assert fila['comensal']['usuario_id'] == 900199 and not fila['comensal']['disponible']
    assert fila['cuenta']['id'] == 555 and not fila['cuenta']['disponible']


def test_listado_rechaza_fecha_sin_zona_sin_alterar_archivo(circuito):
    motor, _ = circuito
    e.registrar(900101, 2, str(uuid4()))
    ruta = c.CARPETA / 'huellas_simuladas.json'
    datos = json.loads(ruta.read_text())
    datos['registros']['900101']['registrada_en'] = '2026-10-20T12:00:00'
    ruta.write_text(json.dumps(datos))
    antes = ruta.read_bytes()
    with c.app_sin_dotenv(), pytest.raises(c.Abortado, match='fecha'):
        e.listar_registros(motor)
    assert ruta.read_bytes() == antes


def test_registros_solo_jefa_lectura_sin_comida_y_con_paginacion_validada(circuito, monkeypatch):
    motor, _ = circuito
    with c.app_sin_dotenv():
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.core.autorizacion import usuario_actual
        from app.core.config import config
        monkeypatch.setattr(config, 'db_name', c.SIM)
        monkeypatch.setattr(config, 'db_name_turnos', c.DEMO)
        app = FastAPI()
        app.state.entorno = 'desarrollo'
        actual = SimpleNamespace(id=2, rol='jefa')
        app.dependency_overrides[usuario_actual] = lambda: actual
        e.registrar(900101, 2, str(uuid4()))
        antes = (c.CARPETA / 'huellas_simuladas.json').read_bytes()
        e.instalar(app, motor, 'srv', {})
        with TestClient(app) as cliente:
            res = cliente.get('/_qa/enrolamiento/registros?limite=1')
            assert res.status_code == 200, res.text
            assert res.json()['datos'][0]['comensal']['usuario_id'] == 900101
            for consulta in ('limite=101', 'desplazamiento=-1', 'busqueda=' + 'x' * 101):
                assert cliente.get('/_qa/enrolamiento/registros?' + consulta).status_code == 422
            for rol in ('cocinera', 'sistemas'):
                actual.rol = rol
                assert cliente.get('/_qa/enrolamiento/registros').status_code == 403
            actual.rol = 'jefa'
            assert cliente.post('/_qa/enrolamiento/capturas', json={'usuario_id': 900102},
                                headers={'Idempotency-Key': str(uuid4())}).status_code == 403
            assert cliente.post('/_qa/enrolamiento/registros', json={}).status_code == 405
            app.dependency_overrides.clear()
            assert cliente.get('/_qa/enrolamiento/registros').status_code == 401
        assert (c.CARPETA / 'huellas_simuladas.json').read_bytes() == antes


def test_filtro_por_dia_usa_la_hora_de_bolivia(circuito):
    from datetime import date
    motor, _ = circuito
    with c.app_sin_dotenv():
        e.registrar(900101, 2, str(uuid4()))
        e.registrar(900102, 2, str(uuid4()))
        ruta = c.CARPETA / 'huellas_simuladas.json'
        datos = json.loads(ruta.read_text(encoding='utf-8'))
        # 02:30 UTC del 23 = 22:30 del 22 en Bolivia; 03:30 UTC del 22 = 23:30 del 21.
        datos['registros']['900101']['registrada_en'] = '2026-10-23T02:30:00+00:00'
        datos['registros']['900102']['registrada_en'] = '2026-10-22T03:30:00+00:00'
        ruta.write_text(json.dumps(datos), encoding='utf-8')
        assert [f['comensal']['usuario_id'] for f in
                e.listar_registros(motor, fecha=date(2026, 10, 22))['datos']] == [900101]
        assert [f['comensal']['usuario_id'] for f in
                e.listar_registros(motor, fecha=date(2026, 10, 21))['datos']] == [900102]
        assert e.listar_registros(motor, fecha=date(2026, 10, 23))['total'] == 0
        assert e.listar_registros(motor)['total'] == 2
