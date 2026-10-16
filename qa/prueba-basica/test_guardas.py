"""Pruebas offline: sin app, sin credenciales y sin conexiones MySQL."""
import json
from datetime import datetime
from unittest.mock import MagicMock, Mock

import pytest
from sqlalchemy import create_engine, text

import comun as c


@pytest.fixture
def entorno():
    return {'DB_NAME': c.SIM, 'DB_NAME_TURNOS': c.DEMO, 'DB_HOST': 'localhost',
            'DB_PORT': '3306', 'DB_USER': 'qa', 'DB_PASSWORD': 'secreto-ficticio-@:/'}


@pytest.mark.parametrize('nombre', c.REQUERIDAS)
def test_faltante_solo_muestra_nombre(entorno, nombre):
    del entorno[nombre]
    with pytest.raises(c.Abortado) as error:
        c.validar_entorno(entorno)
    assert str(error.value) == nombre


@pytest.mark.parametrize('nombre,valor', [
    ('DB_NAME', 'bd_nutricion'), ('DB_NAME', c.PROTEGIDA),
    ('DB_NAME_TURNOS', c.PROTEGIDA), ('DB_NAME', c.SIM + ' '),
    ('DB_NAME_TURNOS', c.DEMO.upper()), ('DB_PORT', '0'), ('DB_PORT', '65536'), ('DB_PORT', 'abc'),
])
def test_entorno_invalido_no_abre_motor(monkeypatch, entorno, nombre, valor):
    entorno[nombre] = valor
    monkeypatch.setattr(c.os, 'environ', entorno)
    crear = Mock(side_effect=AssertionError('no debe crear motores'))
    monkeypatch.setattr(c, 'create_engine', crear)
    with pytest.raises(c.Abortado, match=nombre):
        with c.entorno_seguro():
            pytest.fail('No debe llegar a una transacción')
    crear.assert_not_called()


def test_url_no_expone_password_y_admite_password_vacia_explicita(entorno):
    url = c.validar_entorno(entorno)
    assert url.password == entorno['DB_PASSWORD']
    assert entorno['DB_PASSWORD'] not in str(url)
    entorno['DB_PASSWORD'] = ''
    assert c.validar_entorno(entorno).password == ''


@pytest.mark.parametrize('presente', [False, True])
def test_sin_clave_explicita_admite_password_ausente_o_vacia(entorno, presente):
    entorno['QA_DB_SIN_CLAVE'] = '1'
    if presente:
        entorno['DB_PASSWORD'] = ''
    else:
        del entorno['DB_PASSWORD']
    assert c.validar_entorno(entorno).password == ''


@pytest.mark.parametrize('flag', [None, '', '0', 'true', ' 1', '1 '])
def test_password_ausente_sin_opt_in_exacto_aborta_antes_del_motor(monkeypatch, entorno, flag):
    del entorno['DB_PASSWORD']
    if flag is not None:
        entorno['QA_DB_SIN_CLAVE'] = flag
    monkeypatch.setattr(c.os, 'environ', entorno)
    crear = Mock(side_effect=AssertionError('No abrir motor'))
    monkeypatch.setattr(c, 'create_engine', crear)
    with pytest.raises(c.Abortado) as error:
        with c.entorno_seguro():
            pytest.fail('No debe entrar')
    assert str(error.value) == 'DB_PASSWORD'
    crear.assert_not_called()


def test_password_y_sin_clave_ambiguos_no_abren_motor(monkeypatch, entorno):
    entorno['QA_DB_SIN_CLAVE'] = '1'
    monkeypatch.setattr(c.os, 'environ', entorno)
    crear = Mock(side_effect=AssertionError('No abrir motor'))
    monkeypatch.setattr(c, 'create_engine', crear)
    with pytest.raises(c.Abortado, match='ambigua') as error:
        with c.entorno_seguro():
            pytest.fail('No debe entrar')
    assert entorno['DB_PASSWORD'] not in str(error.value)
    crear.assert_not_called()


def test_password_con_flag_cero_conserva_clave(entorno):
    entorno['QA_DB_SIN_CLAVE'] = '0'
    assert c.validar_entorno(entorno).password == entorno['DB_PASSWORD']


@pytest.fixture
def control_huellas(monkeypatch, entorno):
    monkeypatch.setattr(c.os, 'environ', entorno)
    control, motor = MagicMock(), Mock()
    monkeypatch.setattr(c, 'create_engine', Mock(side_effect=[control, motor]))
    quitar = Mock()
    monkeypatch.setattr(c, 'instalar_auditor', Mock(return_value=quitar))
    monkeypatch.setattr(c, 'preflight', Mock(return_value='servidor-falso'))
    inicial = {'sha256': 'a', 'tablas': {'tabla': 1}}
    final = {'sha256': 'b', 'tablas': {'tabla': 2}}
    medir = Mock(side_effect=[inicial, final])
    monkeypatch.setattr(c, 'huella_protegida', medir)
    return control, motor, quitar, medir, inicial


@pytest.mark.parametrize('original', [c.Abortado('Fallo de la operación'),
                                    RuntimeError('SQL con secreto-ficticio')])
def test_doble_error_se_muestra_sin_exponer_secretos(control_huellas, capsys, original):
    control, motor, quitar, medir, _ = control_huellas

    def operacion():
        with c.entorno_seguro():
            raise original

    with pytest.raises(c.Abortado) as combinado:
        operacion()
    assert combinado.value.__cause__ is original
    # La salida pública también debe incluir ambos errores.
    with pytest.raises(SystemExit) as salida:
        c.ejecutar(lambda: lanzar(combinado.value))
    assert salida.value.code == 1
    mensaje = capsys.readouterr().err
    assert 'Error original:' in mensaje
    assert 'La huella protegida cambió' in mensaje
    assert (str(original) if isinstance(original, c.Abortado) else 'RuntimeError') in mensaje
    assert 'secreto-ficticio' not in mensaje
    assert medir.call_count == 2
    motor.dispose.assert_called_once()
    control.dispose.assert_called_once()
    quitar.assert_called_once()


def lanzar(error):
    raise error


def test_error_original_se_conserva_si_huella_no_cambia(control_huellas):
    _, _, _, medir, inicial = control_huellas
    medir.side_effect = [inicial, inicial]
    original = c.Abortado('Fallo original')
    with pytest.raises(c.Abortado) as error:
        with c.entorno_seguro():
            raise original
    assert error.value is original


def test_cambio_huella_sin_error_interno(control_huellas):
    with pytest.raises(c.Abortado) as error:
        with c.entorno_seguro():
            pass
    assert str(error.value) == 'La huella protegida cambió; detener la prueba'


@pytest.mark.parametrize('fila', [None, {}, {'clave': 'ajena', 'version': 2, 'base_sim': c.SIM},
                                         {'clave': c.MARCADOR, 'version': 1, 'base_sim': c.SIM},
                                         {'clave': c.MARCADOR, 'version': 2, 'base_sim': 'bd_nutricion'}])
def test_marcador_obligatorio(fila):
    with pytest.raises(c.Abortado):
        c.validar_marcador(fila)


def test_marcador_valido():
    c.validar_marcador({'clave': c.MARCADOR, 'version': 2, 'base_sim': c.SIM})


def test_preflight_sin_marcador_no_abre_transaccion():
    conn = Mock()
    conn.execute.return_value.mappings.return_value.one_or_none.return_value = None
    with pytest.raises(c.Abortado, match='Marcador'):
        c.preflight(conn)
    assert conn.execute.call_count == 1
    conn.begin.assert_not_called()


PERMITIDAS = c.permisos((c.SIM, 'lecturas_biometricas', 'INSERT'),
                        (c.SIM, 'intervenciones_lectura', 'DELETE'),
                        (c.DEMO, 'turnos_asignados', 'UPDATE'))


@pytest.mark.parametrize('sql', [
    'INSERT INTO lecturas_biometricas (usuario_id, motivo) VALUES (%(uid)s, %(motivo)s)',
    f'INSERT INTO `{c.SIM}`.`lecturas_biometricas` (usuario_id) VALUES (NULL)',
    f'UPDATE `{c.DEMO}`.turnos_asignados SET fecha=:fecha WHERE id=:id AND usuario_id=:uid',
    'DELETE FROM intervenciones_lectura WHERE lectura_id=:id',
    'SELECT id FROM lecturas_biometricas WHERE id=:id FOR UPDATE',
    'SELECT id FROM asistencias WHERE id=:id LOCK IN SHARE MODE',
    'SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=:base',
    f'CHECKSUM TABLE `{c.PROTEGIDA}`.`users` EXTENDED',
    'SAVEPOINT sa_savepoint_1', 'RELEASE SAVEPOINT sa_savepoint_1', 'ROLLBACK TO SAVEPOINT sa_savepoint_1',
])
def test_sql_del_circuito_permitido(sql):
    c.revisar_sql(sql, c.SIM, PERMITIDAS)


@pytest.mark.parametrize('sql', [
    f'INSERT INTO {c.PROTEGIDA}.lecturas_biometricas (id) VALUES (1)',
    'INSERT INTO bd_nutricion.lecturas_biometricas (id) VALUES (1)',
    'UPDATE users SET name=:name WHERE id=900001',
    'DELETE FROM lecturas_biometricas WHERE id=1',  # Otro verbo que el autorizado.
    'INSERT INTO v_comensales (usuario_id) VALUES (900001)',
    'UPDATE turnos_asignados SET fecha=:fecha WHERE id=91739904',  # Base implícita SIM.
    f'UPDATE {c.DEMO}.turnos_asignados SET fecha=:fecha',
    'DELETE FROM intervenciones_lectura',
    'DELETE i FROM intervenciones_lectura i JOIN bd_nutricion.users u ON 1=1',
    f'UPDATE {c.DEMO}.turnos_asignados t, bd_nutricion.users u SET t.fecha=:f',
    f'UPDATE {c.DEMO}.turnos_asignados SET fecha=(SELECT NOW()) WHERE id=1',
    'INSERT INTO lecturas_biometricas (id) SELECT id FROM bd_nutricion.users',
    'WITH x AS (SELECT 1) DELETE FROM intervenciones_lectura WHERE id=1',
    '/*!50000 DELETE FROM bd_proyecto_backend.users */',
    '/* pista */ INSERT INTO lecturas_biometricas (id) VALUES (1)',
    'SELECT 1; DELETE FROM bd_nutricion.users',
    'SELECT 1 INTO OUTFILE :ruta', 'SELECT LOAD_FILE(:ruta)',
    'SELECT @x := 1', 'CALL procedimiento()', 'USE bd_nutricion',
    'SET FOREIGN_KEY_CHECKS=0', 'TRUNCATE TABLE lecturas_biometricas',
    'REPLACE INTO lecturas_biometricas (id) VALUES (1)',
    'ALTER TABLE lecturas_biometricas ADD COLUMN otra INT',
    'DROP TABLE lecturas_biometricas', 'CREATE TABLE otra (id INT)',
    f'CHECKSUM TABLE `{c.SIM}`.`users` EXTENDED',
])
def test_auditor_cierra_escrituras_ajenas_y_sintaxis_desconocida(sql):
    with pytest.raises(c.Abortado):
        c.revisar_sql(sql, c.SIM, PERMITIDAS)


def test_base_implicita_no_resoluble_o_protegida():
    for base in (None, c.PROTEGIDA, 'bd_nutricion'):
        with pytest.raises(c.Abortado):
            c.revisar_sql('INSERT INTO lecturas_biometricas (id) VALUES (1)', base, PERMITIDAS)


def test_listener_real_impide_escritura_antes_del_cursor():
    # SQLite únicamente para comprobar que el evento intercepta SQL real.
    motor = create_engine('sqlite://')
    with motor.begin() as conn:
        conn.exec_driver_sql(f"ATTACH DATABASE ':memory:' AS {c.SIM}")
        conn.exec_driver_sql(f"ATTACH DATABASE ':memory:' AS {c.PROTEGIDA}")
        conn.exec_driver_sql(f'CREATE TABLE {c.SIM}.lecturas_biometricas (id INTEGER)')
        conn.exec_driver_sql(f'CREATE TABLE {c.PROTEGIDA}.lecturas_biometricas (id INTEGER)')
    quitar = c.instalar_auditor(PERMITIDAS, objetivo=motor)
    try:
        with motor.begin() as conn:
            conn.execute(text(f'INSERT INTO {c.SIM}.lecturas_biometricas (id) VALUES (:id)'), {'id': 1})
            with pytest.raises(c.Abortado):
                conn.execute(text(f'INSERT INTO {c.PROTEGIDA}.lecturas_biometricas (id) VALUES (1)'))
            assert conn.execute(text(f'SELECT COUNT(*) FROM {c.PROTEGIDA}.lecturas_biometricas')).scalar_one() == 0
            assert conn.execute(text(f'SELECT COUNT(*) FROM {c.SIM}.lecturas_biometricas')).scalar_one() == 1
    finally:
        quitar()
        motor.dispose()


def test_simulacro_no_permite_dml():
    for sql in ('INSERT INTO lecturas_biometricas (id) VALUES (1)',
                'DELETE FROM intervenciones_lectura WHERE id=1'):
        with pytest.raises(c.Abortado):
            c.revisar_sql(sql, c.SIM, set())


def test_no_se_consulta_dotenv(monkeypatch):
    from pydantic_settings import BaseSettings, SettingsConfigDict
    from pydantic_settings.sources import DotEnvSettingsSource
    leer_archivo = Mock(side_effect=AssertionError('Prohibido leer archivos dotenv'))
    monkeypatch.setattr(DotEnvSettingsSource, '_read_env_file', leer_archivo)
    rutas = list(c.sys.path)
    bytecode = c.sys.dont_write_bytecode
    try:
        with c.app_sin_dotenv():
            class Ajustes(BaseSettings):
                model_config = SettingsConfigDict(env_file='archivo-prohibido')
                prueba: str = 'correcto'
            assert Ajustes().prueba == 'correcto'
        leer_archivo.assert_not_called()
    finally:
        c.sys.path[:] = rutas
        c.sys.dont_write_bytecode = bytecode


def test_diario_atomico_y_servidor_equivocado(monkeypatch, tmp_path):
    monkeypatch.setattr(c, 'CORRIDA', tmp_path / 'corrida.json')
    datos = {'version': 1, 'servidor': 'servidor-falso', 'bases': [c.SIM, c.DEMO],
             'usuario_id': c.USUARIO, 'asignacion_id': c.ASIGNACION,
             'inicio': datetime(2026, 10, 16, 11).isoformat(), 'lectura_id': 42,
             'fecha_original': '2026-10-15', 'fecha_destino': '2026-10-16'}
    c.guardar_corrida(datos)
    assert c.leer_corrida('servidor-falso') == datos
    assert not c.CORRIDA.with_suffix('.json.tmp').exists()
    with pytest.raises(c.Abortado, match='servidor'):
        c.leer_corrida('otro')
    assert json.loads(c.CORRIDA.read_text())['lectura_id'] == 42


def test_bloqueo_impide_dos_scripts(monkeypatch, tmp_path):
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    with c.bloqueo_corrida():
        with pytest.raises(c.Abortado, match='corrida.lock'):
            with c.bloqueo_corrida():
                pytest.fail('No debe entrar')
    assert not (tmp_path / 'corrida.lock').exists()


def test_huella_distinta_aborta():
    with pytest.raises(c.Abortado, match='huella'):
        c.comprobar_base({'huella_base': {'sha256': 'a'}}, {'sha256': 'b'})
