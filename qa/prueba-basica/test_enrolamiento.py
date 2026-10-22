"""Enrolamiento sintetico: persistencia real y rutas reales, sin MySQL ni dotenv."""
from types import SimpleNamespace
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import MetaData, create_engine
from sqlalchemy.pool import StaticPool

import comun as c
import enrolamiento as e


@pytest.fixture
def carpeta(tmp_path, monkeypatch):
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    return tmp_path


def test_registro_persiste_y_resuelve_sin_crear_comida(carpeta):
    clave = str(uuid4())
    fila = e.registrar(900101, 2, clave)
    assert fila['modo'] == 'simulado' and not fila['ya_registrada']
    assert e.resolver(fila['referencia']) == 900101
    assert e.registro_de(900101)['cuenta_id'] == 2
    assert [p.name for p in carpeta.iterdir()] == ['huellas_simuladas.json']
    assert e.resolver('huella-desconocida') is None


def test_reenvio_y_nuevo_operador_no_cambian_vinculo_ni_autoria(carpeta):
    clave = str(uuid4())
    primera = e.registrar(900101, 2, clave)
    repetida = e.registrar(900101, 2, clave)
    otra_cuenta = e.registrar(900101, 3, str(uuid4()))
    assert primera['referencia'] == repetida['referencia'] == otra_cuenta['referencia']
    assert repetida['ya_registrada'] and otra_cuenta['cuenta_id'] == 2
    assert len(e.leer_registro()['registros']) == 1
    antes = (carpeta / 'huellas_simuladas.json').read_bytes()
    with pytest.raises(c.Abortado, match='otra persona'):
        e.registrar(900102, 2, clave)
    assert (carpeta / 'huellas_simuladas.json').read_bytes() == antes


def test_error_al_publicar_no_altera_registro_anterior(carpeta, monkeypatch):
    e.registrar(900101, 2, str(uuid4()))
    ruta = carpeta / 'huellas_simuladas.json'
    antes = ruta.read_bytes()
    monkeypatch.setattr(e.os, 'replace', lambda *_: (_ for _ in ()).throw(OSError('fallo controlado')))
    with pytest.raises(OSError):
        e.registrar(900102, 2, str(uuid4()))
    assert ruta.read_bytes() == antes
    assert not (carpeta / 'huellas_simuladas.lock').exists()
    assert not (carpeta / 'huellas_simuladas.json.tmp').exists()


def test_colision_de_referencia_no_se_asocia_a_otra_persona(carpeta, monkeypatch):
    from uuid import UUID
    primera = e.registrar(900101, 2, str(uuid4()))
    monkeypatch.setattr(e, 'uuid4', lambda: UUID(primera['referencia'][11:]))
    with pytest.raises(c.Abortado, match='otra persona'):
        e.registrar(900102, 2, str(uuid4()))
    assert e.registro_de(900102) is None
    assert e.resolver(primera['referencia']) == 900101


def test_registro_invalido_y_bloqueo_no_sobrescriben_datos(carpeta):
    ruta = carpeta / 'huellas_simuladas.json'
    ruta.write_text('{incompleto', encoding='utf-8')
    with pytest.raises(c.Abortado, match='conserva'):
        e.registrar(900101, 2, str(uuid4()))
    assert ruta.read_text() == '{incompleto'
    ruta.unlink()
    (carpeta / 'huellas_simuladas.lock').touch()
    with pytest.raises(c.Abortado, match='en curso'):
        e.registrar(900101, 2, str(uuid4()))
    assert not ruta.exists()


@pytest.mark.parametrize('uid,cuenta,clave', [(True, 2, str(uuid4())), (1, 0, str(uuid4())),
                                            (1, 2, 'no-es-uuid'), (0, 2, str(uuid4()))])
def test_datos_invalidos_no_generan_archivos(carpeta, uid, cuenta, clave):
    with pytest.raises(c.Abortado):
        e.registrar(uid, cuenta, clave)
    assert list(carpeta.iterdir()) == []


def test_rutas_autorizacion_padron_completo_y_captura_sin_asistencia(carpeta, monkeypatch):
    with c.app_sin_dotenv():
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.core.autorizacion import usuario_actual
        from app.core.config import config
        from app.modelos.heredados import Comensal, Servicio, UsuarioServicio

        monkeypatch.setattr(config, 'db_name', c.SIM)
        monkeypatch.setattr(config, 'db_name_turnos', c.DEMO)
        motor = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
        metadata = MetaData()
        tabla = Comensal.__table__.to_metadata(metadata)
        for col in tabla.columns:
            col.type = col.type.as_generic()
        for modelo in (Servicio, UsuarioServicio):
            extra = modelo.__table__.to_metadata(metadata)
            for col in extra.columns:
                col.type = col.type.as_generic()
        metadata.create_all(motor)
        with motor.begin() as conn:
            conn.execute(tabla.insert(), [
                {'usuario_id': 900101, 'nombre_completo': 'QA NORMAL', 'numero_item': 'LEG-QA01',
                 'categoria': 'Medicos', 'tiene_ficha': True},
                {'usuario_id': 900104, 'nombre_completo': 'QA ENFERMERIA', 'numero_item': 'LEG-QA04',
                 'categoria': 'Enfermeria', 'tiene_ficha': True},
                {'usuario_id': 900105, 'nombre_completo': 'QA ADMIN', 'numero_item': 'LEG-QA05',
                 'categoria': 'Administrativo', 'tiene_ficha': True},
                {'usuario_id': 900106, 'nombre_completo': 'QA INTERNA', 'numero_item': 'LEG-QA06',
                 'categoria': 'Interno-Enfermeria', 'tiene_ficha': True},
            ])
            conn.execute(Servicio.__table__.insert(), {'id': 1, 'nombre': 'MEDICINA INTERNA', 'cantidad_pacientes': 0})
            conn.execute(UsuarioServicio.__table__.insert(), [
                {'id': uid, 'usuario_id': uid, 'servicio_id': 1, 'estado': True, 'fecha_ingreso': date(2026, 10, 15)}
                for uid in (900101, 900104, 900105, 900106)])
        app = FastAPI()
        app.state.entorno = 'desarrollo'
        actual = SimpleNamespace(id=2, rol='cocinera')
        app.dependency_overrides[usuario_actual] = lambda: actual
        monkeypatch.setattr(c, 'leer_corrida', lambda *_: {'casos': {}, 'comensales': {}, 'parte_a': {'completa': True}})
        monkeypatch.setattr(c, 'comprobar_base', lambda *_: None)
        e.instalar(app, motor, 'srv', {})
        with TestClient(app) as cliente:
            personas = cliente.get('/_qa/enrolamiento/personas')
            assert personas.status_code == 200
            assert {p['id'] for p in personas.json()} == {900101}
            assert personas.json()[0]['servicio'] == 'MEDICINA INTERNA'
            for uid in (900104, 900105, 900106):
                assert cliente.post('/_qa/enrolamiento/capturas', json={'usuario_id': uid},
                                    headers={'Idempotency-Key': str(uuid4())}).status_code == 403
            assert all(not p['huella_registrada'] for p in personas.json())
            clave = str(uuid4())
            respuesta = cliente.post('/_qa/enrolamiento/capturas', json={'usuario_id': 900101},
                                     headers={'Idempotency-Key': clave})
            assert respuesta.status_code == 200, respuesta.text
            assert e.resolver(respuesta.json()['referencia']) == 900101
            assert cliente.post('/_qa/enrolamiento/capturas', json={'usuario_id': 900101},
                                headers={'Idempotency-Key': clave}).json()['ya_registrada']
            assert any(p['huella_registrada'] for p in cliente.get('/_qa/enrolamiento/personas').json())
            assert cliente.post('/_qa/enrolamiento/capturas', json={'usuario_id': 123456},
                                headers={'Idempotency-Key': str(uuid4())}).status_code == 404
            assert cliente.post('/_qa/enrolamiento/capturas', json={'usuario_id': 900101, 'plantilla': 'falsa'},
                                headers={'Idempotency-Key': str(uuid4())}).status_code == 422
            actual.rol = 'jefa'
            assert cliente.get('/_qa/enrolamiento/personas').status_code == 403
            assert cliente.post('/_qa/enrolamiento/capturas', json={'usuario_id': 900101},
                                headers={'Idempotency-Key': str(uuid4())}).status_code == 403
            app.dependency_overrides.clear()
            assert cliente.get('/_qa/enrolamiento/personas').status_code == 401
        assert set(metadata.tables) == {'v_comensales', 'v_servicios', 'v_usuario_servicios'}
        motor.dispose()


def test_no_instala_rutas_en_una_base_ajena(carpeta, monkeypatch):
    with c.app_sin_dotenv():
        from fastapi import FastAPI
        from app.core.config import config
        monkeypatch.setattr(config, 'db_name', 'base_ajena')
        app = FastAPI()
        app.state.entorno = 'desarrollo'
        with pytest.raises(c.Abortado, match='solo se habilita'):
            e.instalar(app, None, 'srv', {})
        assert not any(getattr(r, 'path', '').startswith('/_qa/') for r in app.routes)


def test_laboratorio_exige_vinculo_y_envia_referencia_al_lector(carpeta):
    from unittest.mock import Mock
    import laboratorio
    control = laboratorio.Laboratorio(Mock(), 'srv', {})
    with pytest.raises(c.Abortado, match='Falta la huella de QA 01 NORMAL'):
        control.simular({'caso': 'qa01'})
    fila = e.registrar(c.COMENSALES_QA['qa01']['usuario_id'], 2, str(uuid4()))
    control.diario = Mock(return_value={'turno_laboratorio': True, 'casos': {'qa01': {'lectura_id': None}}})
    control.estado = Mock(return_value={'servicio_elegido_vigente': True})
    control.ejecutar_script = Mock()
    control.simular({'caso': 'qa01'})
    control.ejecutar_script.assert_called_once_with('huella.py', '--caso', 'qa01', '--referencia', fila['referencia'])


def test_cli_rechaza_referencia_de_otra_persona_antes_de_conectar(carpeta):
    import huella
    fila = e.registrar(c.COMENSALES_QA['qa02']['usuario_id'], 2, str(uuid4()))
    with pytest.raises(c.Abortado, match='no esta registrada'):
        huella.main(['--caso', 'qa01', '--referencia', fila['referencia']])
