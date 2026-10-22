"""Pruebas offline: sin app, sin credenciales y sin conexiones MySQL."""
import copy
import json
import sys
from datetime import datetime
from decimal import Decimal
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


@pytest.mark.parametrize('campo_secreto', sorted(c.CAMPOS_SECRETOS))
def test_diario_rechaza_claves_y_tokens(monkeypatch, tmp_path, campo_secreto):
    monkeypatch.setattr(c, 'CORRIDA', tmp_path / 'corrida.json')
    with pytest.raises(c.Abortado, match='claves o tokens'):
        c.guardar_corrida({'estado': 'iniciada', 'anidado': [{campo_secreto: 'valor-secreto'}]})
    assert not c.CORRIDA.exists()


@pytest.mark.parametrize('intento,sesion,esperado_intento,esperado_sesion', [
    (Decimal(0), None, 0, None),
    (Decimal(17), Decimal(9), 17, 9),
])
def test_diario_normaliza_contadores_decimal_y_sin_tabla_sesiones(
    monkeypatch, tmp_path, intento, sesion, esperado_intento, esperado_sesion
):
    monkeypatch.setattr(c, 'CORRIDA', tmp_path / 'corrida.json')
    datos = {
        'version': 1,
        'servidor': 'servidor-falso',
        'bases': [c.SIM, c.DEMO],
        'usuario_id': c.USUARIO,
        'asignacion_id': c.ASIGNACION,
        'inicio': datetime(2026, 10, 16, 11).isoformat(),
        'fecha_original': '2026-10-15',
        'fecha_destino': None,
        'max_intento_inicial': intento,
        'contrato_sesiones': 'id' if sesion is not None else None,
        'max_sesion_inicial': sesion,
    }
    c.guardar_corrida(datos)
    assert not c.CORRIDA.with_suffix('.json.tmp').exists()
    guardado = c.leer_corrida('servidor-falso')
    assert guardado['max_intento_inicial'] == esperado_intento
    assert type(guardado['max_intento_inicial']) is int
    assert guardado['max_sesion_inicial'] == esperado_sesion
    if esperado_sesion is not None:
        assert type(guardado['max_sesion_inicial']) is int
    assert datos['max_intento_inicial'] == esperado_intento
    assert datos['max_sesion_inicial'] == esperado_sesion


@pytest.mark.parametrize('invalido', [
    Decimal('-1'),
    Decimal('1.5'),
    Decimal('NaN'),
    Decimal('Infinity'),
    -1,
    True,
    False,
    '0',
    0.0,
    [0],
])
def test_normalizar_contador_rechaza_valores_invalidos(monkeypatch, tmp_path, invalido):
    monkeypatch.setattr(c, 'CORRIDA', tmp_path / 'corrida.json')
    with pytest.raises(c.Abortado):
        c.normalizar_contador(invalido)
    with pytest.raises(c.Abortado):
        c.guardar_corrida({'estado': 'iniciada', 'max_intento_inicial': invalido})
    assert not c.CORRIDA.exists()
    assert not c.CORRIDA.with_suffix('.json.tmp').exists()


def test_normalizar_contador_rechaza_none_cuando_no_se_permite():
    with pytest.raises(c.Abortado, match='ausente'):
        c.normalizar_contador(None, permitir_none=False)


@pytest.mark.parametrize('cambio,excepcion', [
    ({'no_serializable': object()}, TypeError),
    ({'numero': float('nan')}, ValueError),
    ({'max_intento_inicial': Decimal('1.5')}, c.Abortado),
    ({'password': 'valor-secreto'}, c.Abortado),
])
def test_fallo_serializacion_conserva_diario_anterior_sin_temporal(
    monkeypatch, tmp_path, cambio, excepcion
):
    monkeypatch.setattr(c, 'CORRIDA', tmp_path / 'corrida.json')
    inicial = {
        'version': 1,
        'servidor': 'servidor-falso',
        'bases': [c.SIM, c.DEMO],
        'usuario_id': c.USUARIO,
        'asignacion_id': c.ASIGNACION,
        'inicio': datetime(2026, 10, 16, 11).isoformat(),
        'fecha_original': '2026-10-15',
        'fecha_destino': None,
        'max_intento_inicial': 4,
        'max_sesion_inicial': None,
        'estado': 'iniciada',
    }
    c.guardar_corrida(inicial)
    contenido_original = c.CORRIDA.read_text(encoding='utf-8')
    candidato = {**inicial, 'max_intento_inicial': Decimal(12), **cambio}
    with pytest.raises(excepcion):
        c.guardar_corrida(candidato)
    assert c.CORRIDA.read_text(encoding='utf-8') == contenido_original
    assert c.leer_corrida('servidor-falso') == inicial
    assert not c.CORRIDA.with_suffix('.json.tmp').exists()


def test_cuentas_iniciales_acepta_cocinera1_y_jefa_ausentes_o_presentes():
    solo_base = [
        {'id': 2, 'username': 'cocinera2', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 3, 'username': 'cocinera3', 'rol': 'cocinera', 'usuario_turnos_id': None},
    ]
    assert c.validar_cuentas_iniciales(solo_base) == {'cocinera2': 2, 'cocinera3': 3}
    las_cuatro = solo_base + [
        {'id': 10, 'username': 'cocinera1', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 11, 'username': 'jefa', 'rol': 'jefa', 'usuario_turnos_id': None},
    ]
    assert c.validar_cuentas_iniciales(las_cuatro) == {
        'cocinera1': 10, 'cocinera2': 2, 'cocinera3': 3, 'jefa': 11,
    }


@pytest.mark.parametrize('filas_invalidas', [
    [{'id': 2, 'username': 'cocinera2', 'rol': 'cocinera', 'usuario_turnos_id': None}],
    [
        {'id': 2, 'username': 'cocinera2', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 3, 'username': 'cocinera3', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 10, 'username': 'cocinera1', 'rol': 'jefa', 'usuario_turnos_id': None},
    ],
    [
        {'id': 2, 'username': 'cocinera2', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 3, 'username': 'cocinera3', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 11, 'username': 'jefa', 'rol': 'cocinera', 'usuario_turnos_id': None},
    ],
    [
        {'id': 2, 'username': 'cocinera2', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 3, 'username': 'cocinera3', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 11, 'username': 'jefa', 'rol': 'jefa', 'usuario_turnos_id': 900001},
    ],
])
def test_cuentas_iniciales_aborta_ante_rol_distinto_o_vinculo(filas_invalidas):
    with pytest.raises(c.Abortado):
        c.validar_cuentas_iniciales(filas_invalidas)


def test_limpieza_acepta_cuentas_creadas_en_corrida_y_cierra_parte_a_o_ab(monkeypatch):
    import limpiar

    iniciales = {'cocinera2': 2, 'cocinera3': 3}
    filas_actuales = [
        {'id': 10, 'username': 'cocinera1', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 2, 'username': 'cocinera2', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 3, 'username': 'cocinera3', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 11, 'username': 'jefa', 'rol': 'jefa', 'usuario_turnos_id': None},
    ]
    actuales = c.validar_cuentas_limpieza(filas_actuales, iniciales)
    assert actuales == {'cocinera1': 10, 'cocinera2': 2, 'cocinera3': 3, 'jefa': 11}

    # Si cambia el id o rol de una cuenta inicial, o una nueva tiene otro rol, aborta.
    with pytest.raises(c.Abortado):
        c.validar_cuentas_limpieza(
            [{**filas_actuales[0], 'rol': 'sistemas'}, *filas_actuales[1:]], iniciales
        )
    with pytest.raises(c.Abortado):
        c.validar_cuentas_limpieza(
            [filas_actuales[0], {**filas_actuales[1], 'id': 99}, *filas_actuales[2:]], iniciales
        )

    monkeypatch.setattr(c, 'existe_tabla', lambda conn, t: t == 'intentos_login')
    datos_a = {
        'lectura_id': None,
        'inicio': '2026-10-16T11:00:00',
        'fecha_original': '2026-10-15',
        'fecha_destino': None,
        'max_intento_inicial': 5,
        'max_sesion_inicial': None,
        'cuentas': iniciales,
        'verificacion_cuentas': {n: {'resultado': 'PASA'} for n in c.CUENTAS},
    }
    filtros, _ = limpiar.objetivos(Mock(), datos_a, actuales)
    tablas_objetivo = dict(filtros)
    assert 'usuarios_sistema' not in tablas_objetivo
    filtro_intentos = tablas_objetivo['intentos_login']
    for cuenta in ('cocinera1', 'cocinera2', 'cocinera3', 'jefa'):
        assert f"'{cuenta}'" in filtro_intentos
    c.revisar_sql(f"DELETE FROM intentos_login WHERE {filtro_intentos}", c.SIM,
                  c.permisos((c.SIM, 'intentos_login', 'DELETE')))

    # Cierre solo Parte A (lectura_id=None) y cierre Parte A+B (lectura_id=42).
    monkeypatch.setattr(c, 'fila_asignacion', lambda conn, bloquear=False: {
        'fecha': datetime(2026, 10, 15).date()
    })

    def _conn_simulada(lecturas, intentos, asistencias, cuentas=filas_actuales):
        conn = MagicMock()
        res_cuentas, res_lecturas, res_intentos, res_asistencias = (
            MagicMock(), MagicMock(), MagicMock(), MagicMock()
        )
        res_cuentas.mappings.return_value.all.return_value = cuentas
        res_lecturas.mappings.return_value.all.return_value = lecturas
        res_intentos.all.return_value = intentos
        res_asistencias.all.return_value = asistencias
        conn.execute.side_effect = [res_cuentas, res_lecturas, res_intentos, res_asistencias]
        return conn

    _, act_a = limpiar.comprobar_propiedad(_conn_simulada([], [], []), datos_a, False)
    assert act_a == actuales

    datos_ab = {
        **datos_a,
        'lectura_id': 42,
        'momento_lectura': '2026-10-15T11:32:00',
    }
    lectura_valida = [{
        'id': 42,
        'usuario_id': None,
        'dispositivo': c.DISPOSITIVO,
        'fecha_hora': datetime(2026, 10, 15, 11, 32),
        'resultado': 'rechazada',
        'motivo': 'no_identificado',
    }]
    _, act_ab = limpiar.comprobar_propiedad(
        _conn_simulada(lectura_valida, [(2, c.USUARIO)], [(c.USUARIO, c.COMIDA, c.ASIGNACION, 2)]),
        datos_ab,
        True,
    )
    assert act_ab == actuales

    # Si desaparece una cuenta ya verificada en Parte A antes de limpiar, aborta.
    with pytest.raises(c.Abortado, match='identidad'):
        limpiar.comprobar_propiedad(_conn_simulada([], [], [], cuentas=filas_actuales[1:]), datos_a, False)


def _simulador_http_cuentas(fallo_en=None, temporales_esperadas=None):
    """Respuestas HTTP simuladas para cuentas.py, con tokens y detalles ficticios."""
    llamadas = []

    def solicitar(metodo, ruta, cuerpo=None, token=None):
        llamadas.append((metodo, ruta, cuerpo, token))
        if (metodo, ruta) == ('GET', '/salud'):
            return 200, {
                'estado': 'ok',
                'entorno': 'desarrollo',
                'base_datos': c.SIM,
                'base_turnos': c.DEMO,
                'revision_alembic': c.REVISION_APP,
            }
        if (metodo, ruta) == ('POST', '/auth/login'):
            cuenta = cuerpo['username']
            rol = c.rol_cuenta(cuenta)
            clave = cuerpo['password']
            es_temporal = (
                (temporales_esperadas is not None and clave == temporales_esperadas.get(cuenta))
                or clave.startswith('TEMP-')
            )
            if es_temporal:
                if fallo_en == (cuenta, 'login_temporal'):
                    return 401, {
                        'motivo': 'credenciales_invalidas',
                        'detail': 'Detalle arbitrario con SECRETO-SERVIDOR-99',
                    }
                return 428, {
                    'motivo': 'cambio_password_pendiente',
                    'temporal': f'JWT-TEMP-{cuenta}',
                    'detail': 'Detalle arbitrario con SECRETO-SERVIDOR-99',
                }
            if fallo_en == (cuenta, 'sin_cambio_frontend'):
                return 428, {
                    'motivo': 'cambio_password_pendiente',
                    'temporal': f'JWT-TEMP-{cuenta}',
                }
            if fallo_en == (cuenta, 'login_definitiva'):
                return 401, {'motivo': 'Mensaje arbitrario con SECRETO-SERVIDOR-99'}
            return 200, {
                'access': f'JWT-ACCESS-{cuenta}',
                'refresh': f'JWT-REFRESH-{cuenta}',
                'rol': rol,
                'debe_cambiar': False,
            }
        if (metodo, ruta) == ('POST', '/auth/cambio-password'):
            raise AssertionError('El kit no debe invocar /auth/cambio-password; el cambio es en el frontend')
        cuenta = token.removeprefix('JWT-ACCESS-')
        rol = c.rol_cuenta(cuenta)
        if (metodo, ruta) == ('GET', '/auth/yo'):
            rol_respuesta = 'sistemas' if fallo_en == (cuenta, 'auth_yo') else rol
            return 200, {'id': 1, 'username': cuenta, 'rol': rol_respuesta, 'debe_cambiar': False}
        if (metodo, ruta) == ('GET', '/pantalla/estado'):
            return (500 if fallo_en == (cuenta, 'pantalla_estado') else 200), {'comida': 'Almuerzo'}
        if (metodo, ruta) == ('POST', '/asistencias'):
            if fallo_en == (cuenta, 'asistencias_manual'):
                return 200, {'valido': True}
            return 403, {'motivo': 'metodo_no_autorizado'}
        if (metodo, ruta) == ('GET', '/intervenciones-cocina'):
            if rol == 'jefa':
                return (403 if fallo_en == (cuenta, 'intervenciones_cocina') else 200), {'datos': []}
            return (200 if fallo_en == (cuenta, 'intervenciones_cocina') else 403), {'motivo': 'rol_no_autorizado'}
        if (metodo, ruta) == ('GET', '/admin/cuentas'):
            return (200 if fallo_en == (cuenta, 'admin_cuentas') else 403), {'motivo': 'rol_no_autorizado'}
        if (metodo, ruta) == ('POST', '/asistencias/lecturas/1/identificar'):
            if fallo_en == (cuenta, 'identificar_lectura'):
                return 200, {'valido': True, 'resultado': 'registrada'}
            return 403, {'motivo': 'rol_no_autorizado'}
        raise AssertionError(f'Ruta inesperada: {metodo} {ruta}')

    return solicitar, llamadas


def _verificacion_temporales_previa():
    return {
        cuenta: {
            'rol': c.rol_cuenta(cuenta),
            'temporal_verificada': True,
            'cambio_frontend_completado': False,
            'resultado': 'PENDIENTE',
            'controles': [{
                'control': 'POST /auth/login (temporal)',
                'esperado': '428 cambio_password_pendiente',
                'codigo': 428,
                'obtenido': '428 cambio_password_pendiente',
                'resultado': 'PASA',
            }],
        }
        for cuenta in c.CUENTAS
    }


def _preparar_diario_base(tmp_path, con_temporales=True):
    diario = tmp_path / 'corrida.json'
    datos = {
        'version': 1,
        'servidor': 'servidor-qa',
        'bases': [c.SIM, c.DEMO],
        'reloj': {'lab': '2026-10-15T11:30:00', 'real': '2026-10-16T11:00:00'},
        'usuario_id': c.USUARIO,
        'asignacion_id': c.ASIGNACION,
        'inicio': '2026-10-16T11:00:00',
        'fecha_original': '2026-10-15',
        'fecha_destino': None,
        'cuentas': {'cocinera2': 2, 'cocinera3': 3},
        'huella_base': {'sha256': 'huella-inicial'},
        'estado': 'iniciada',
        'lectura_id': None,
    }
    if con_temporales:
        datos['verificacion_cuentas'] = _verificacion_temporales_previa()
        datos['parte_a'] = {'estado': 'pendiente_cambio_frontend', 'completa': False}
    diario.write_text(json.dumps(datos), encoding='utf-8')
    return diario


@pytest.mark.parametrize('invocador', ['cuentas', 'ejecutar_app'])
def test_preparacion_automatica_verifica_428_deja_parte_a_pendiente_y_mantiene_api(
    monkeypatch, tmp_path, capsys, invocador
):
    import cuentas
    import ejecutar_app

    diario = _preparar_diario_base(tmp_path, con_temporales=False)
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    monkeypatch.setattr(c, 'CORRIDA', diario)
    monkeypatch.setenv('ENTORNO', 'desarrollo')
    monkeypatch.setattr(cuentas, '_puerto_ocupado', lambda host, port: False)

    no_getpass = Mock(side_effect=AssertionError('La preparación automática no debe usar getpass'))
    monkeypatch.setattr(cuentas.getpass, 'getpass', no_getpass)

    control = MagicMock()
    motor = MagicMock()
    motor.connect.return_value.__enter__.return_value.execute.return_value.mappings.return_value.one_or_none.return_value = None
    control.__enter__.return_value = (motor, {'sha256': 'huella-inicial'}, 'servidor-qa')
    monkeypatch.setattr(c, 'entorno_seguro', Mock(return_value=control))

    fijadas = {}
    with c.app_sin_dotenv():
        from app.core import reloj as reloj_app
        from app.semillas import admin as semilla_admin

        monkeypatch.setattr(reloj_app, 'real', lambda: datetime(2026, 10, 16, 11, 0, 0))
        sesion_falsa = MagicMock()
        sesion_falsa.execute.return_value.scalar_one_or_none.return_value = None
        monkeypatch.setattr(semilla_admin, 'SesionLocal', Mock(return_value=sesion_falsa))

        def fijar_espia(sesion, usuario, clave, *, temporal):
            usuario.debe_cambiar = 1 if temporal else 0
            fijadas[usuario.username] = (usuario.rol, usuario.debe_cambiar, clave)

        monkeypatch.setattr(semilla_admin, 'fijar_clave', fijar_espia)
        generador_original = semilla_admin.clave_temporal

        proceso_api = MagicMock()
        proceso_api.poll.return_value = None
        proceso_api.wait.return_value = 0
        lanzar = Mock(return_value=proceso_api)
        monkeypatch.setattr(cuentas, 'lanzar_api_qa', lanzar)

        solicitar, llamadas_http = _simulador_http_cuentas(
            temporales_esperadas=type('VistaTemporales', (), {'get': lambda self, k: fijadas[k][2]})()
        )
        monkeypatch.setattr(cuentas, 'cliente_http', lambda base: solicitar)

        if invocador == 'cuentas':
            cuentas.main(['--preparar'])
        else:
            ejecutar_app.main(['preparar'])

        assert semilla_admin.clave_temporal is generador_original

    no_getpass.assert_not_called()
    lanzar.assert_called_once_with(8001)
    proceso_api.wait.assert_called_once()
    assert set(fijadas) == set(c.CUENTAS)

    salida = capsys.readouterr()
    texto_diario = diario.read_text(encoding='utf-8')
    guardado = json.loads(texto_diario)

    assert guardado['parte_a'] == {'estado': 'pendiente_cambio_frontend', 'completa': False}
    for cuenta in c.CUENTAS:
        rol_fijado, debe_cambiar, clave_generada = fijadas[cuenta]
        assert rol_fijado == c.rol_cuenta(cuenta)
        assert debe_cambiar == 1
        assert len(clave_generada) == 12
        assert salida.out.count(clave_generada) == 1
        assert clave_generada not in salida.err
        assert clave_generada not in texto_diario

        resumen = guardado['verificacion_cuentas'][cuenta]
        assert resumen['rol'] == c.rol_cuenta(cuenta)
        assert resumen['temporal_verificada'] is True
        assert resumen['cambio_frontend_completado'] is False
        assert resumen['resultado'] == 'PENDIENTE'
        assert len(resumen['controles']) == 1
        assert resumen['controles'][0]['control'] == 'POST /auth/login (temporal)'
        assert resumen['controles'][0]['resultado'] == 'PASA'

    assert [ll[1] for ll in llamadas_http if ll[0] == 'POST'] == ['/auth/login'] * 4
    for secreto in ('JWT-TEMP-', 'SECRETO-SERVIDOR-99'):
        assert secreto not in texto_diario
        assert secreto not in salida.out
        assert secreto not in salida.err


@pytest.mark.parametrize('causa', ['archivo_marca', 'puerto_ocupado'])
def test_preparacion_aborta_si_hay_api_anterior_activa_sin_matar_procesos(
    monkeypatch, tmp_path, causa
):
    import cuentas

    diario = _preparar_diario_base(tmp_path, con_temporales=False)
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    monkeypatch.setattr(c, 'CORRIDA', diario)
    monkeypatch.setenv('ENTORNO', 'desarrollo')
    if causa == 'archivo_marca':
        (tmp_path / 'api.activa').write_text('', encoding='utf-8')
        monkeypatch.setattr(cuentas, '_puerto_ocupado', lambda host, port: False)
    else:
        monkeypatch.setattr(cuentas, '_puerto_ocupado', lambda host, port: True)

    entorno_mock = Mock(side_effect=AssertionError('No debe abrir entorno ni tocar cuentas si hay API activa'))
    lanzar_mock = Mock(side_effect=AssertionError('No debe iniciar otra API'))
    detener_mock = Mock(side_effect=AssertionError('No debe matar procesos ajenos'))
    monkeypatch.setattr(c, 'entorno_seguro', entorno_mock)
    monkeypatch.setattr(cuentas, 'lanzar_api_qa', lanzar_mock)
    monkeypatch.setattr(cuentas, 'detener_proceso_api', detener_mock)

    with pytest.raises(c.Abortado, match=r'Ctrl\+C'):
        cuentas.main(['--preparar'])

    entorno_mock.assert_not_called()
    lanzar_mock.assert_not_called()
    detener_mock.assert_not_called()
    if causa == 'archivo_marca':
        assert (tmp_path / 'api.activa').exists()


def test_preparacion_detiene_proceso_api_propio_si_falla_control_temporal(
    monkeypatch, tmp_path, capsys
):
    import cuentas
    import ejecutar_app

    diario = _preparar_diario_base(tmp_path, con_temporales=False)
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    monkeypatch.setattr(c, 'CORRIDA', diario)
    monkeypatch.setenv('ENTORNO', 'desarrollo')
    monkeypatch.setattr(cuentas, '_puerto_ocupado', lambda host, port: False)

    control = MagicMock()
    motor = MagicMock()
    control.__enter__.return_value = (motor, {'sha256': 'huella-inicial'}, 'servidor-qa')
    monkeypatch.setattr(c, 'entorno_seguro', Mock(return_value=control))
    temporales_generadas = {cuenta: f'TEMP-gen-{cuenta}' for cuenta in c.CUENTAS}
    monkeypatch.setattr(
        ejecutar_app,
        'sembrar_cuentas_qa',
        Mock(return_value=dict(temporales_generadas)),
    )

    with c.app_sin_dotenv():
        from app.core import reloj as reloj_app
        monkeypatch.setattr(reloj_app, 'real', lambda: datetime(2026, 10, 16, 11, 0, 0))

        proceso_api = MagicMock()
        proceso_api.poll.return_value = None
        proceso_api.terminate.side_effect = lambda: setattr(proceso_api.poll, 'return_value', 0)

        def crear_marca_y_devolver_proceso(port=8001):
            (tmp_path / 'api.activa').write_text('', encoding='utf-8')
            return proceso_api

        monkeypatch.setattr(cuentas, 'lanzar_api_qa', crear_marca_y_devolver_proceso)
        solicitar, _ = _simulador_http_cuentas(
            fallo_en=('jefa', 'login_temporal'),
            temporales_esperadas=temporales_generadas,
        )
        monkeypatch.setattr(cuentas, 'cliente_http', lambda base: solicitar)

        with pytest.raises(c.Abortado, match='clave temporal'):
            cuentas.main(['--preparar'])

    proceso_api.terminate.assert_called_once()
    proceso_api.kill.assert_not_called()
    assert not (tmp_path / 'api.activa').exists()
    salida = capsys.readouterr()
    texto_diario = diario.read_text(encoding='utf-8')
    guardado = json.loads(texto_diario)
    assert guardado['parte_a'] == {'estado': 'falla', 'completa': False}
    assert guardado['verificacion_cuentas']['jefa']['resultado'] == 'FALLA'
    for clave_temp in temporales_generadas.values():
        assert clave_temp not in texto_diario
        assert clave_temp not in salida.out
        assert clave_temp not in salida.err


def test_detener_proceso_api_cierre_correcto_retira_marca_y_no_toca_procesos_ajenos(
    monkeypatch, tmp_path
):
    import cuentas

    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    marca = tmp_path / 'api.activa'
    marca.write_text('', encoding='utf-8')

    # Si no hay proceso propio iniciado por esta preparación, no toca api.activa.
    assert cuentas.detener_proceso_api(None) is False
    assert marca.exists()

    # Cierre correcto mediante terminate() con confirmación de fin (poll() == 0).
    proceso = MagicMock()
    proceso.poll.return_value = None
    proceso.terminate.side_effect = lambda: setattr(proceso.poll, 'return_value', 0)
    proceso.wait.return_value = 0

    assert cuentas.detener_proceso_api(proceso) is True
    proceso.terminate.assert_called_once()
    proceso.kill.assert_not_called()
    assert not marca.exists()

    # Cierre normal tras Ctrl+C en mantener_api_activa: espera fin limpio sin forzar terminate/kill.
    marca.write_text('', encoding='utf-8')
    proceso_ctrl_c = MagicMock()
    proceso_ctrl_c.poll.return_value = None

    def wait_side_effect(timeout=None):
        if timeout is None:
            raise KeyboardInterrupt()
        proceso_ctrl_c.poll.return_value = 0
        return 0

    proceso_ctrl_c.wait.side_effect = wait_side_effect
    cuentas.mantener_api_activa(proceso_ctrl_c, timeout_cierre=2.0)
    proceso_ctrl_c.terminate.assert_not_called()
    proceso_ctrl_c.kill.assert_not_called()
    assert not marca.exists()


@pytest.mark.parametrize('modo_fallo', ['excepcion_timeout', 'excepcion_oserror', 'sigue_vivo_sin_excepcion'])
def test_detener_proceso_api_conserva_marca_y_aborta_si_terminate_y_kill_fallan_con_proceso_vivo(
    monkeypatch, tmp_path, modo_fallo
):
    import subprocess
    import cuentas

    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    marca = tmp_path / 'api.activa'
    marca.write_text('', encoding='utf-8')

    proceso = MagicMock()
    proceso.poll.return_value = None
    if modo_fallo == 'excepcion_timeout':
        proceso.wait.side_effect = subprocess.TimeoutExpired(cmd='api', timeout=0.1)
    elif modo_fallo == 'excepcion_oserror':
        proceso.terminate.side_effect = OSError('detalle-interno-no-exponer')
        proceso.kill.side_effect = OSError('detalle-interno-no-exponer')

    with pytest.raises(c.Abortado, match=r'No se pudo detener.*api\.activa') as exc:
        cuentas.detener_proceso_api(proceso, timeout=0.1)

    proceso.terminate.assert_called_once()
    proceso.kill.assert_called_once()
    assert marca.exists()
    assert 'detalle-interno-no-exponer' not in str(exc.value)


@pytest.mark.parametrize('escenario', ['kill_forzado', 'ctrl_c_timeout_forzado', 'codigo_error'])
def test_detener_proceso_api_no_presenta_terminacion_forzada_como_cierre_normal(
    monkeypatch, tmp_path, escenario
):
    import subprocess
    import cuentas

    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    marca = tmp_path / 'api.activa'
    marca.write_text('', encoding='utf-8')

    proceso = MagicMock()
    proceso.poll.return_value = None

    if escenario == 'kill_forzado':
        proceso.terminate.side_effect = subprocess.TimeoutExpired(cmd='api', timeout=0.1)
        proceso.kill.side_effect = lambda: setattr(proceso.poll, 'return_value', -9)
        with pytest.raises(c.Abortado, match='huella final'):
            cuentas.detener_proceso_api(proceso, timeout=0.1)
        proceso.terminate.assert_called_once()
        proceso.kill.assert_called_once()
        assert not marca.exists()
    elif escenario == 'ctrl_c_timeout_forzado':
        llamadas_wait = []

        def wait_ctrl_c(timeout=None):
            llamadas_wait.append(timeout)
            if len(llamadas_wait) == 1:
                raise KeyboardInterrupt()
            if len(llamadas_wait) == 2:
                raise subprocess.TimeoutExpired(cmd='api', timeout=timeout)
            return 0

        proceso.wait.side_effect = wait_ctrl_c
        proceso.terminate.side_effect = lambda: setattr(proceso.poll, 'return_value', 0)
        with pytest.raises(c.Abortado, match='huella final'):
            cuentas.mantener_api_activa(proceso, timeout_cierre=0.1)
        proceso.terminate.assert_called_once()
        assert not marca.exists()
    else:
        proceso.terminate.side_effect = lambda: setattr(proceso.poll, 'return_value', 1)
        with pytest.raises(c.Abortado, match='huella final'):
            cuentas.detener_proceso_api(proceso, timeout=0.1)
        assert not marca.exists()


@pytest.mark.parametrize('etapa_fallo', ['durante_reseteo', 'arranque_api', 'control_428'])
def test_preparacion_invalida_parte_a_aprobada_antes_de_resetear_y_ante_fallo_posterior(
    monkeypatch, tmp_path, etapa_fallo
):
    import cuentas
    import ejecutar_app

    diario = _preparar_diario_base(tmp_path, con_temporales=True)
    datos_aprobados = json.loads(diario.read_text(encoding='utf-8'))
    for cuenta in c.CUENTAS:
        datos_aprobados['verificacion_cuentas'][cuenta] = {
            'rol': c.rol_cuenta(cuenta),
            'temporal_verificada': True,
            'cambio_frontend_completado': True,
            'resultado': 'PASA',
            'controles': [
                {'control': 'POST /auth/login (temporal)', 'resultado': 'PASA'},
                {'control': 'POST /auth/login (definitiva)', 'resultado': 'PASA'},
                {'control': 'GET /auth/yo', 'resultado': 'PASA'},
            ],
        }
    datos_aprobados['parte_a'] = {'estado': 'aprobada', 'completa': True}
    diario.write_text(json.dumps(datos_aprobados), encoding='utf-8')

    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    monkeypatch.setattr(c, 'CORRIDA', diario)
    monkeypatch.setenv('ENTORNO', 'desarrollo')
    monkeypatch.setattr(cuentas, '_puerto_ocupado', lambda host, port: False)

    control = MagicMock()
    motor = MagicMock()
    control.__enter__.return_value = (motor, {'sha256': 'huella-inicial'}, 'servidor-qa')
    monkeypatch.setattr(c, 'entorno_seguro', Mock(return_value=control))

    diario_al_resetear = {}
    temporales_generadas = {cuenta: f'TEMP-gen-{cuenta}' for cuenta in c.CUENTAS}

    def sembrar_espia(motor_arg, cuentas_arg):
        # En el instante del reseteo, el diario ya debe haber invalidado la aprobación anterior.
        diario_al_resetear.update(json.loads(diario.read_text(encoding='utf-8')))
        if etapa_fallo == 'durante_reseteo':
            raise c.Abortado('Fallo simulado tras iniciar el reseteo de credenciales')
        return dict(temporales_generadas)

    monkeypatch.setattr(ejecutar_app, 'sembrar_cuentas_qa', sembrar_espia)

    with c.app_sin_dotenv():
        from app.core import reloj as reloj_app
        monkeypatch.setattr(reloj_app, 'real', lambda: datetime(2026, 10, 16, 11, 0, 0))

        proceso_api = MagicMock()
        proceso_api.poll.return_value = None
        proceso_api.terminate.side_effect = lambda: setattr(proceso_api.poll, 'return_value', 0)
        monkeypatch.setattr(cuentas, 'lanzar_api_qa', Mock(return_value=proceso_api))

        if etapa_fallo == 'arranque_api':
            monkeypatch.setattr(
                cuentas,
                'esperar_api_lista',
                Mock(side_effect=c.Abortado('La API QA no pudo iniciar')),
            )
        else:
            solicitar, _ = _simulador_http_cuentas(
                fallo_en=('cocinera1', 'login_temporal'),
                temporales_esperadas=temporales_generadas,
            )
            monkeypatch.setattr(cuentas, 'cliente_http', lambda base: solicitar)

        with pytest.raises(c.Abortado):
            cuentas.main(['--preparar'])

    # 1. Antes del primer reseteo ya quedó invalidada la Parte A anterior en corrida.json.
    assert diario_al_resetear['parte_a'] == {'estado': 'preparacion_pendiente', 'completa': False}
    for cuenta in c.CUENTAS:
        info_prev = diario_al_resetear['verificacion_cuentas'][cuenta]
        assert info_prev['resultado'] == 'PENDIENTE'
        assert info_prev['temporal_verificada'] is False
        assert info_prev['cambio_frontend_completado'] is False
        assert info_prev['controles'] == []

    # 2. Tras el fallo posterior, el diario sigue incompleto y sin aprobación ni PASA previos vigentes.
    guardado = json.loads(diario.read_text(encoding='utf-8'))
    assert guardado['parte_a']['completa'] is False
    assert guardado['parte_a']['estado'] in {'preparacion_pendiente', 'falla'}
    assert guardado['parte_a']['estado'] != 'aprobada'
    for cuenta in c.CUENTAS:
        resumen = guardado['verificacion_cuentas'][cuenta]
        assert resumen['resultado'] != 'PASA'
        assert resumen['cambio_frontend_completado'] is False
        assert all(
            ctrl.get('control') != 'POST /auth/login (definitiva)'
            for ctrl in resumen.get('controles', [])
        )


def test_cuentas_py_exige_preparacion_previa_antes_de_pedir_claves_definitivas(
    monkeypatch, tmp_path
):
    import cuentas

    diario = _preparar_diario_base(tmp_path, con_temporales=False)
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    monkeypatch.setattr(c, 'CORRIDA', diario)
    solicitar, _ = _simulador_http_cuentas()
    monkeypatch.setattr(cuentas, 'cliente_http', lambda base: solicitar)
    pedir = Mock(side_effect=AssertionError('No debe pedir clave definitiva si falta --preparar'))
    monkeypatch.setattr(cuentas.getpass, 'getpass', pedir)

    with pytest.raises(c.Abortado, match='preparar'):
        cuentas.main([])
    pedir.assert_not_called()


def test_cuentas_py_pasa_las_4_cuentas_tras_cambio_en_frontend_y_no_guarda_claves_ni_tokens(
    monkeypatch, tmp_path, capsys
):
    import cuentas

    diario = _preparar_diario_base(tmp_path, con_temporales=True)
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    monkeypatch.setattr(c, 'CORRIDA', diario)
    solicitar, llamadas = _simulador_http_cuentas()
    monkeypatch.setattr(cuentas, 'cliente_http', lambda base: solicitar)

    claves_definitivas = iter([
        'DEFINITIVA-secreta-c1',
        'DEFINITIVA-secreta-c2',
        'DEFINITIVA-secreta-c3',
        'DEFINITIVA-secreta-jefa',
    ])
    monkeypatch.setattr(cuentas.getpass, 'getpass', lambda prompt: next(claves_definitivas))

    cuentas.main([])
    salida = capsys.readouterr()
    assert '| Cuenta | Control | Esperado | Obtenido | PASA/FALLA |' in salida.out
    texto_diario = diario.read_text(encoding='utf-8')
    guardado = json.loads(texto_diario)

    assert guardado['parte_a'] == {'estado': 'aprobada', 'completa': True}
    for cuenta in ('cocinera1', 'cocinera2', 'cocinera3'):
        assert guardado['verificacion_cuentas'][cuenta]['resultado'] == 'PASA'
        assert guardado['verificacion_cuentas'][cuenta]['cambio_frontend_completado'] is True
        assert len(guardado['verificacion_cuentas'][cuenta]['controles']) == 7
        assert guardado['verificacion_cuentas'][cuenta]['controles'][0]['control'] == 'POST /auth/login (temporal)'
        assert guardado['verificacion_cuentas'][cuenta]['controles'][1]['control'] == 'POST /auth/login (definitiva)'
    assert guardado['verificacion_cuentas']['jefa']['resultado'] == 'PASA'
    assert guardado['verificacion_cuentas']['jefa']['cambio_frontend_completado'] is True
    assert len(guardado['verificacion_cuentas']['jefa']['controles']) == 5
    assert all(ll[1] != '/auth/cambio-password' for ll in llamadas)

    # Ninguna clave, token ni detalle arbitrario puede aparecer en corrida.json ni en la consola.
    for secreto in (
        'DEFINITIVA-secreta', 'JWT-TEMP-', 'JWT-ACCESS-',
        'JWT-REFRESH-', 'SECRETO-SERVIDOR-99',
    ):
        assert secreto not in texto_diario
        assert secreto not in salida.out
        assert secreto not in salida.err


@pytest.mark.parametrize('fallo', [
    ('cocinera1', 'asistencias_manual'),
    ('cocinera1', 'auth_yo'),
    ('cocinera2', 'intervenciones_cocina'),
    ('cocinera3', 'admin_cuentas'),
    ('jefa', 'identificar_lectura'),
    ('jefa', 'sin_cambio_frontend'),
    ('jefa', 'login_definitiva'),
])
def test_cuentas_py_detecta_falla_sin_reintentar_credenciales_y_sale_con_error(
    monkeypatch, tmp_path, capsys, fallo
):
    import cuentas

    diario = _preparar_diario_base(tmp_path, con_temporales=True)
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    monkeypatch.setattr(c, 'CORRIDA', diario)
    cuenta_fallida, etapa = fallo
    solicitar, llamadas = _simulador_http_cuentas(fallo_en=fallo)
    monkeypatch.setattr(cuentas, 'cliente_http', lambda base: solicitar)
    claves = iter([f'DEFINITIVA-{cuenta_fallida}'])
    monkeypatch.setattr(cuentas.getpass, 'getpass', lambda prompt: next(claves))

    with pytest.raises(SystemExit) as exc:
        c.ejecutar(lambda: cuentas.main(['--solo', cuenta_fallida]))
    assert exc.value.code != 0
    salida = capsys.readouterr()
    assert 'FALLA' in salida.out

    # Nunca debe reintentar POST /auth/login tras un fallo de credenciales o falta de cambio en frontend.
    logins = [ll for ll in llamadas if (ll[0], ll[1]) == ('POST', '/auth/login')]
    assert len(logins) == 1
    if etapa in ('sin_cambio_frontend', 'login_definitiva'):
        assert len(llamadas) == 2  # Solo GET /salud y un POST /auth/login

    texto_diario = diario.read_text(encoding='utf-8')
    guardado = json.loads(texto_diario)
    resumen = guardado['verificacion_cuentas'][cuenta_fallida]
    assert resumen['resultado'] == 'FALLA'
    assert resumen['cambio_frontend_completado'] is False
    assert guardado['parte_a'] == {'estado': 'falla', 'completa': False}
    assert any(ctrl['resultado'] == 'FALLA' for ctrl in resumen['controles'])
    for prohibido in (
        f'DEFINITIVA-{cuenta_fallida}', 'JWT-', 'SECRETO-SERVIDOR-99'
    ):
        assert prohibido not in texto_diario
        assert prohibido not in salida.out
        assert prohibido not in salida.err


def test_cuentas_py_solo_conserva_resultados_previos_de_otras_cuentas(monkeypatch, tmp_path):
    import cuentas

    diario = _preparar_diario_base(tmp_path, con_temporales=True)
    datos_iniciales = json.loads(diario.read_text(encoding='utf-8'))
    control_temp = datos_iniciales['verificacion_cuentas']['cocinera2']['controles'][0]
    datos_iniciales['verificacion_cuentas'] = {
        'cocinera1': {
            'rol': 'cocinera',
            'temporal_verificada': True,
            'cambio_frontend_completado': True,
            'resultado': 'PASA',
            'controles': [control_temp, {'control': 'previo1', 'resultado': 'PASA'}],
        },
        'cocinera2': {
            'rol': 'cocinera',
            'temporal_verificada': True,
            'cambio_frontend_completado': False,
            'resultado': 'FALLA',
            'controles': [control_temp, {'control': 'previo2', 'resultado': 'FALLA'}],
        },
        'cocinera3': {
            'rol': 'cocinera',
            'temporal_verificada': True,
            'cambio_frontend_completado': True,
            'resultado': 'PASA',
            'controles': [control_temp, {'control': 'previo3', 'resultado': 'PASA'}],
        },
        'jefa': {
            'rol': 'jefa',
            'temporal_verificada': True,
            'cambio_frontend_completado': True,
            'resultado': 'PASA',
            'controles': [control_temp, {'control': 'previo4', 'resultado': 'PASA'}],
        },
    }
    diario.write_text(json.dumps(datos_iniciales), encoding='utf-8')

    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    monkeypatch.setattr(c, 'CORRIDA', diario)
    solicitar, llamadas = _simulador_http_cuentas()
    monkeypatch.setattr(cuentas, 'cliente_http', lambda base: solicitar)
    claves = iter(['DEFINITIVA-cocinera2'])
    monkeypatch.setattr(cuentas.getpass, 'getpass', lambda prompt: next(claves))

    cuentas.main(['--solo', 'cocinera2'])
    guardado = json.loads(diario.read_text(encoding='utf-8'))
    verif = guardado['verificacion_cuentas']

    assert verif['cocinera2']['resultado'] == 'PASA'
    assert verif['cocinera2']['cambio_frontend_completado'] is True
    assert len(verif['cocinera2']['controles']) == 7
    assert verif['cocinera1'] == datos_iniciales['verificacion_cuentas']['cocinera1']
    assert verif['cocinera3'] == datos_iniciales['verificacion_cuentas']['cocinera3']
    assert verif['jefa'] == datos_iniciales['verificacion_cuentas']['jefa']
    assert guardado['parte_a'] == {'estado': 'aprobada', 'completa': True}
    usuarios_autenticados = [
        ll[2]['username'] for ll in llamadas if (ll[0], ll[1]) == ('POST', '/auth/login')
    ]
    assert usuarios_autenticados == ['cocinera2']


@pytest.mark.parametrize('respuesta_salud', [
    (200, {'estado': 'ok', 'entorno': 'desarrollo', 'base_datos': 'bd_nutricion',
           'base_turnos': c.DEMO, 'revision_alembic': c.REVISION_APP}),
    (200, {'estado': 'ok', 'entorno': 'desarrollo', 'base_datos': c.SIM,
           'base_turnos': c.PROTEGIDA, 'revision_alembic': c.REVISION_APP}),
    (200, {'estado': 'ok', 'entorno': 'desarrollo', 'base_datos': c.SIM,
           'base_turnos': c.DEMO, 'revision_alembic': 'otra'}),
    (200, {'estado': 'ok', 'entorno': 'produccion', 'base_datos': c.SIM,
           'base_turnos': c.DEMO, 'revision_alembic': c.REVISION_APP}),
    (503, {'estado': 'error'}),
])
def test_cuentas_py_aborta_si_salud_no_coincide(monkeypatch, tmp_path, respuesta_salud):
    import cuentas

    diario = _preparar_diario_base(tmp_path)
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    monkeypatch.setattr(c, 'CORRIDA', diario)
    monkeypatch.setattr(
        cuentas,
        'cliente_http',
        lambda base: (lambda m, r, c_=None, t=None: respuesta_salud),
    )
    pedir = Mock(side_effect=AssertionError('No debe pedir claves si /salud falla'))
    monkeypatch.setattr(cuentas.getpass, 'getpass', pedir)
    with pytest.raises(c.Abortado, match='/salud'):
        cuentas.main([])
    pedir.assert_not_called()


def test_cuentas_py_omite_motivo_desconocido_aunque_cumpla_snake_case(monkeypatch, tmp_path, capsys):
    import re
    import cuentas

    motivo_desconocido = 'motivo_interno_no_autorizado_123'
    assert re.fullmatch(r'[a-z][a-z0-9_]{1,39}', motivo_desconocido)
    assert motivo_desconocido not in cuentas.MOTIVOS_CONOCIDOS

    diario = _preparar_diario_base(tmp_path)
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    monkeypatch.setattr(c, 'CORRIDA', diario)
    solicitar_base, _ = _simulador_http_cuentas()

    def solicitar_con_motivo_desconocido(metodo, ruta, cuerpo=None, token=None):
        if (metodo, ruta) == ('POST', '/auth/login'):
            return 401, {'motivo': motivo_desconocido}
        return solicitar_base(metodo, ruta, cuerpo, token)

    monkeypatch.setattr(cuentas, 'cliente_http', lambda base: solicitar_con_motivo_desconocido)
    claves = iter(['DEFINITIVA-jefa'])
    monkeypatch.setattr(cuentas.getpass, 'getpass', lambda prompt: next(claves))

    with pytest.raises(SystemExit) as exc:
        c.ejecutar(lambda: cuentas.main(['--solo', 'jefa']))
    assert exc.value.code != 0

    salida = capsys.readouterr()
    texto_diario = diario.read_text(encoding='utf-8')
    guardado = json.loads(texto_diario)
    control_login_def = guardado['verificacion_cuentas']['jefa']['controles'][1]
    assert control_login_def['obtenido'] == '401'
    assert motivo_desconocido not in texto_diario
    assert motivo_desconocido not in salida.out
    assert motivo_desconocido not in salida.err


def test_manifiesto_comensales_qa_valido_y_rechaza_colisiones(tmp_path):
    manifiesto = c.cargar_manifiesto_comensales()
    assert tuple(manifiesto['comensales']) == ('qa01', 'qa02', 'qa03')
    assert manifiesto['comensales']['qa01']['legajo'] == 'LEG-QA01'
    assert manifiesto['comensales']['qa02']['legajo'] == 'LEG-QA02'
    assert manifiesto['comensales']['qa03']['legajo'] == 'LEG-QA03'
    assert manifiesto['comensales']['qa02']['caso']['lectura_usuario_id'] is None
    assert manifiesto['comensales']['qa02']['caso']['comensal_previsto_id'] == 900102
    assert manifiesto['comensales']['qa03']['ejecutable'] is False

    # Colisión con usuario histórico (900001..900007)
    copia_colision = json.loads(json.dumps(manifiesto))
    copia_colision['comensales']['qa01']['usuario_id'] = 900001
    ruta_colision = tmp_path / 'colision.json'
    ruta_colision.write_text(json.dumps(copia_colision), encoding='utf-8')
    with pytest.raises(c.Abortado, match='históricos'):
        c.cargar_manifiesto_comensales(ruta_colision)

    # Atributo alterado respecto a la definición canónica
    copia_alterada = json.loads(json.dumps(manifiesto))
    copia_alterada['comensales']['qa02']['legajo'] = 'OTRO-LEGAJO'
    ruta_alterada = tmp_path / 'alterado.json'
    ruta_alterada.write_text(json.dumps(copia_alterada), encoding='utf-8')
    with pytest.raises(c.Abortado, match='legajo'):
        c.cargar_manifiesto_comensales(ruta_alterada)


def _conn_preparador_comensales(estado='ausente', tabla_colision=None, tabla_parcial=None):
    from datetime import date as _date

    conn = MagicMock()
    sentencias_ejecutadas = []

    def ejecutar_sql(clause, params=None):
        sql = str(clause)
        sentencias_ejecutadas.append((sql, params))
        res = MagicMock()
        if 'FROM `bd_turnos_escenario_demo`.categorias' in sql:
            res.mappings.return_value.one_or_none.return_value = {
                'id': 9001, 'nombre': 'Administrativo', 'nivel': 1, 'descripcion': 'Cat base',
            }
            return res
        if 'FROM `bd_turnos_escenario_demo`.servicios' in sql:
            res.mappings.return_value.one_or_none.return_value = {
                'id': 9001, 'nombre': 'Servicio simulado', 'descripcion': 'Srv base', 'cantidad_pacientes': 10,
            }
            return res
        if 'FROM `bd_turnos_escenario_demo`.turnos ' in sql:
            res.mappings.return_value.one_or_none.return_value = {
                'id': 9001, 'nombre_turno': 'Turno base', 'hora_inicio': '06:00:00',
                'hora_fin': '18:00:00', 'duracion_horas': 12, 'categoria_id': 9001,
            }
            return res
        if 'FROM `bd_turnos_escenario_demo`.comidas' in sql:
            res.mappings.return_value.one_or_none.return_value = {
                'id': c.COMIDA, 'nombre': 'Almuerzo', 'codigo': 'almuerzo', 'estado': 1,
            }
            return res
        if 'FROM `bd_turnos_escenario_demo`.turno_comida' in sql:
            res.mappings.return_value.one_or_none.return_value = {
                'id': 9001, 'turno_id': 9001, 'comida_id': c.COMIDA, 'dia_relativo': 0,
            }
            return res

        if sql.startswith('SELECT ') and params and 'uid' in params:
            uid = params['uid']
            spec = next(s for s in c.COMENSALES_QA.values() if s['usuario_id'] == uid)
            fecha_b = _date.fromisoformat(spec['fecha_base'])
            tablas = {
                'users': [{
                    'id': uid, 'name': spec['login'], 'categoria_id': spec['categoria_id'],
                }],
                'personas': [{
                    'id': uid,
                    'user_id': uid,
                    'nombre_completo': spec['nombre'],
                    'carnet_identidad': spec['carnet_identidad'],
                    'numero_tipo_salario': spec['legajo'],
                    'tipo_trabajador': spec['tipo_trabajador'],
                }],
                'usuario_servicios': [{
                    'id': uid,
                    'usuario_id': uid,
                    'servicio_id': spec['servicio_id'],
                    'estado': 1,
                    'fecha_ingreso': fecha_b,
                }],
                'turnos_asignados': [{
                    'id': spec['asignacion_id'],
                    'usuario_id': uid,
                    'servicio_id': spec['servicio_id'],
                    'area_id': None,
                    'fecha': fecha_b,
                    'estado': 'ACTIVO',
                    'es_intercambio': 0,
                    'turno_id': spec['turno_id'],
                }],
                'escenario_identificaciones': [{
                    'identificador': spec['identificador_unico'],
                    'usuario_id': uid,
                    'origen': 'simulado',
                    'descripcion': spec['nombre'],
                }],
            }
            for nombre_tabla, filas_validas in tablas.items():
                if f'.{nombre_tabla} ' in sql:
                    if tabla_colision == nombre_tabla and uid == 900101:
                        corrupta = dict(filas_validas[0])
                        if 'id' in corrupta:
                            corrupta['id'] = 900001
                        if 'identificador' in corrupta:
                            corrupta['identificador'] = 'SIM-ID-COLISION'
                        res.mappings.return_value.all.return_value = [corrupta]
                    elif tabla_parcial == nombre_tabla and uid == 900101:
                        res.mappings.return_value.all.return_value = []
                    elif estado == 'existente' or tabla_parcial is not None:
                        res.mappings.return_value.all.return_value = filas_validas
                    else:
                        res.mappings.return_value.all.return_value = []
                    return res
        if sql.startswith('INSERT INTO'):
            c.revisar_sql(
                sql,
                c.SIM,
                c.permisos(*((c.DEMO, t, 'INSERT') for t in (
                    'users', 'personas', 'usuario_servicios',
                    'turnos_asignados', 'escenario_identificaciones',
                ))),
            )
            return res
        raise AssertionError(f'SQL inesperado en preparador: {sql}')

    conn.execute.side_effect = ejecutar_sql
    return conn, sentencias_ejecutadas


def test_preparar_comensales_simulacro_aplicacion_idempotencia_y_colisiones(
    monkeypatch, tmp_path
):
    import preparar_comensales

    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    monkeypatch.setattr(c, 'CORRIDA', tmp_path / 'corrida.json')

    assert preparar_comensales.permisos_preparador(False) == ()
    permisos_aplicar = preparar_comensales.permisos_preparador(True)
    assert all(verbo in {'INSERT', 'UPDATE'} and base == c.DEMO for base, _, verbo in permisos_aplicar)
    assert {tabla for _, tabla, verbo in permisos_aplicar if verbo == 'UPDATE'} == {'users', 'usuario_servicios', 'turnos_asignados'}

    monkeypatch.setattr(preparar_comensales, 'verificar_comensales_en_app', Mock())
    import preparar_perfiles
    monkeypatch.setattr(preparar_perfiles, 'preparar', Mock())  # La migracion tiene pruebas SQL independientes.

    # 1. Simulacro por defecto: no emite ningún INSERT.
    motor_sim = MagicMock()
    conn_sim, sql_sim = _conn_preparador_comensales(estado='ausente')
    motor_sim.begin.return_value.__enter__.return_value = conn_sim
    res_sim = preparar_comensales.preparar(motor_sim, aplicar=False)
    assert all(r['estado'] == 'por_insertar' for r in res_sim.values())
    assert not any(s.startswith('INSERT') for s, _ in sql_sim)
    preparar_comensales.verificar_comensales_en_app.assert_not_called()

    # 2. Aplicación explícita (--aplicar): inserta los 3 comensales (15 INSERT en total) y verifica.
    motor_ap = MagicMock()
    conn_ap, sql_ap = _conn_preparador_comensales(estado='ausente')
    motor_ap.begin.return_value.__enter__.return_value = conn_ap
    res_ap = preparar_comensales.preparar(motor_ap, aplicar=True)
    assert all(r['estado'] == 'insertado' for r in res_ap.values())
    inserts = [s for s, _ in sql_ap if s.startswith('INSERT INTO')]
    assert len(inserts) == 15
    preparar_comensales.verificar_comensales_en_app.assert_called_once_with(conn_ap)

    # 3. Idempotencia: si ya existen con los mismos datos, no emite INSERT y verifica.
    preparar_comensales.verificar_comensales_en_app.reset_mock()
    motor_idem = MagicMock()
    conn_idem, sql_idem = _conn_preparador_comensales(estado='existente')
    motor_idem.begin.return_value.__enter__.return_value = conn_idem
    res_idem = preparar_comensales.preparar(motor_idem, aplicar=True)
    assert all(r['estado'] == 'existente_idempotente' for r in res_idem.values())
    assert not any(s.startswith('INSERT') for s, _ in sql_idem)
    preparar_comensales.verificar_comensales_en_app.assert_called_once_with(conn_idem)

    # 4. Colisión en cualquiera de las 5 tablas: aborta sin insertar ni sobrescribir.
    for tabla in preparar_comensales.TABLAS_DEMO_INSERCION:
        motor_col = MagicMock()
        conn_col, sql_col = _conn_preparador_comensales(estado='ausente', tabla_colision=tabla)
        motor_col.begin.return_value.__enter__.return_value = conn_col
        with pytest.raises(c.Abortado, match=f'Colisión en {c.DEMO}.{tabla}'):
            preparar_comensales.preparar(motor_col, aplicar=True)
        assert not any(s.startswith('INSERT') for s, _ in sql_col)

    # 5. Estado parcial inconsistente: aborta.
    motor_parc = MagicMock()
    conn_parc, _ = _conn_preparador_comensales(estado='existente', tabla_parcial='turnos_asignados')
    motor_parc.begin.return_value.__enter__.return_value = conn_parc
    with pytest.raises(c.Abortado, match='Estado parcial inconsistente'):
        preparar_comensales.preparar(motor_parc, aplicar=True)

    # 6. Aborta si existe corrida.json o api.activa.
    (tmp_path / 'corrida.json').write_text('{}', encoding='utf-8')
    with pytest.raises(c.Abortado, match='Existe corrida.json'):
        preparar_comensales.preparar(motor_sim, aplicar=False)
    (tmp_path / 'corrida.json').unlink()
    (tmp_path / 'api.activa').write_text('123\n', encoding='utf-8')
    with pytest.raises(c.Abortado, match='Detener la API QA'):
        preparar_comensales.preparar(motor_sim, aplicar=False)


def test_huella_base_conserva_cuentas_aprobadas_sin_resetear(monkeypatch, tmp_path):
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    monkeypatch.setattr(c, 'CORRIDA', tmp_path / 'corrida.json')

    evidencia = tmp_path / 'evidencia_parte_a.json'
    verif_aprobada = {
        nombre: {
            'rol': rol,
            'temporal_verificada': True,
            'cambio_frontend_completado': True,
            'resultado': 'PASA',
            'controles': [{'control': 'POST /auth/login (definitiva)', 'resultado': 'PASA'}],
        }
        for nombre, rol in c.CUENTAS.items()
    }
    evidencia.write_text(
        json.dumps({
            'version': 1,
            'servidor': 'servidor-qa',
            'bases': [c.SIM, c.DEMO],
            'cuentas': {'cocinera1': 10, 'cocinera2': 2, 'cocinera3': 3, 'jefa': 11},
            'verificacion_cuentas': verif_aprobada,
            'parte_a': {'estado': 'aprobada', 'completa': True},
        }),
        encoding='utf-8',
    )

    conn = MagicMock()
    conn.execute.return_value.mappings.return_value.all.return_value = [
        {'username': n, 'debe_cambiar': 0, 'activo': 1}
        for n in c.CUENTAS
    ]
    cuentas_actuales = {'cocinera1': 10, 'cocinera2': 2, 'cocinera3': 3, 'jefa': 11}
    verif, parte_a = c.heredar_parte_a_aprobada(conn, evidencia, cuentas_actuales, 'servidor-qa')
    assert parte_a == {'estado': 'aprobada', 'completa': True}
    assert verif == verif_aprobada

    # Si alguna cuenta tiene debe_cambiar=1 en la base, rechaza conservar Parte A.
    conn.execute.return_value.mappings.return_value.all.return_value = [
        {'username': n, 'debe_cambiar': 1 if n == 'cocinera2' else 0, 'activo': 1}
        for n in c.CUENTAS
    ]
    with pytest.raises(c.Abortado, match='requieren cambio de clave'):
        c.heredar_parte_a_aprobada(conn, evidencia, cuentas_actuales, 'servidor-qa')


def _diario_multi_base():
    return {
        'version': 2,
        'escenario': 'tres_comensales_qa',
        'servidor': 'servidor-qa',
        'bases': [c.SIM, c.DEMO],
        'reloj': {'lab': '2026-10-15T11:30:00', 'real': '2026-10-18T22:00:00'},
        'inicio': '2026-10-18T22:00:00',
        'fecha_original': '2026-10-15',
        'fecha_destino': None,
        'cuentas': {'cocinera1': 10, 'cocinera2': 2, 'cocinera3': 3, 'jefa': 11},
        'comensales': c.resumen_comensales_diario(),
        'casos': c.casos_iniciales_diario(),
        'max_intento_inicial': 5,
        'contrato_sesiones': None,
        'max_sesion_inicial': None,
        'huella_base': {'sha256': 'huella-base'},
        'estado': 'iniciada',
    }


def test_verificar_casos_normal_identificacion_consulta_jefa_y_reserva(
    monkeypatch, tmp_path, capsys
):
    from datetime import date as _date
    import verificar_casos

    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    monkeypatch.setattr(c, 'CORRIDA', tmp_path / 'corrida.json')

    datos = _diario_multi_base()
    datos['estado'] = 'lectura_creada'
    datos['casos']['qa01'].update(
        estado='completado',
        momento_lectura='2026-10-15T11:31:00',
        lectura_id=101,
        asistencia_id=201,
    )
    datos['casos']['qa02'].update(
        estado='lectura_creada',
        momento_lectura='2026-10-15T11:32:00',
        lectura_id=102,
    )
    c.guardar_corrida(datos)

    fecha_op = _date(2026, 10, 15)
    momento_1 = datetime(2026, 10, 15, 11, 31)
    momento_2 = datetime(2026, 10, 15, 11, 32)
    momento_int = datetime(2026, 10, 15, 11, 33)

    filas_cuentas = [
        {'id': 10, 'username': 'cocinera1', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 2, 'username': 'cocinera2', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 3, 'username': 'cocinera3', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 11, 'username': 'jefa', 'rol': 'jefa', 'usuario_turnos_id': None},
    ]
    lectura_qa01 = [{
        'id': 101,
        'usuario_id': 900101,
        'dispositivo': c.DISPOSITIVO,
        'fecha_hora': momento_1,
        'resultado': 'aceptada',
        'motivo': None,
    }]
    asist_qa01 = [{
        'id': 201,
        'usuario_id': 900101,
        'fecha_comida': fecha_op,
        'comida_id': c.COMIDA,
        'servicio_id': 9001,
        'turno_asignado_id': 191739904,
        'metodo': 'biometrico',
        'lectura_id': 101,
        'registrado_por_cuenta': None,
    }]
    lectura_qa02 = [{
        'id': 102,
        'usuario_id': None,
        'dispositivo': c.DISPOSITIVO,
        'fecha_hora': momento_2,
        'resultado': 'rechazada',
        'motivo': 'no_identificado',
    }]
    asist_qa02 = [{
        'id': 202,
        'usuario_id': 900102,
        'fecha_comida': fecha_op,
        'comida_id': c.COMIDA,
        'servicio_id': 9001,
        'turno_asignado_id': 192739904,
        'metodo': 'manual',
        'lectura_id': 102,
        'registrado_por_cuenta': 2,
    }]
    interv_qa02 = [{
        'id': 301,
        'lectura_id': 102,
        'usuario_id': 900102,
        'cuenta_id': 2,
        'resultado': 'registrada',
        'motivo_rechazo': None,
        'causa': 'identificacion_manual_por_no_identificado',
        'asistencia_id': 202,
        'comida_id': c.COMIDA,
        'fecha_comida': fecha_op,
        'nombre_comensal': 'QA 02 IDENTIFICACION',
    }]

    conn = MagicMock()
    respuestas = [
        MagicMock(**{'mappings.return_value.all.return_value': filas_cuentas}),
        MagicMock(**{'mappings.return_value.all.return_value': lectura_qa01}),
        MagicMock(**{'mappings.return_value.all.return_value': asist_qa01}),
        MagicMock(**{'scalar_one.return_value': 0}),
        MagicMock(**{'mappings.return_value.all.return_value': lectura_qa02}),
        MagicMock(**{'mappings.return_value.all.return_value': asist_qa02}),
        MagicMock(**{'mappings.return_value.all.return_value': interv_qa02}),
        MagicMock(**{'scalar_one.return_value': 0}),
        MagicMock(**{'scalar_one.return_value': 0}),
        MagicMock(**{'scalar_one.return_value': 0}),
    ]
    conn.execute.side_effect = respuestas
    motor = MagicMock()
    motor.connect.return_value.__enter__.return_value = conn

    fila_jefa = {
        'id': 301,
        'resultado': 'registrada',
        'motivo_rechazo': None,
        'causa': 'identificacion_manual_por_no_identificado',
        'momento': momento_int,
        'lectura_id': 102,
        'lectura_resultado': 'rechazada',
        'lectura_motivo': 'no_identificado',
        'lectura_fecha_hora': momento_2,
        'lectura_dispositivo': c.DISPOSITIVO,
        'cuenta_id': 2,
        'cuenta_usuario': 'cocinera2',
        'cuenta_nombre': 'Cocinera 2',
        'usuario_id': 900102,
        'comensal_nombre': 'QA 02 IDENTIFICACION',
        'comensal_categoria': 'Administrativo',
        'comida_id': c.COMIDA,
        'nombre_comida': 'Almuerzo',
        'fecha_comida': fecha_op,
        'ventana_inicio': datetime(2026, 10, 15, 11, 0),
        'ventana_fin': datetime(2026, 10, 15, 15, 0),
        'origen_servicio': 'horario_comida',
        'asistencia_id': 202,
        'lectura_resuelta': True,
    }

    with c.app_sin_dotenv():
        from app.consultas import intervenciones as consultas_intervenciones

        def listar_simulado(_sesion, filtros, limite=50, desplazamiento=0):
            assert limite == 50 and desplazamiento == 0
            if filtros.usuario_id == 900102:
                return 1, {'registradas': 1, 'rechazadas': 0}, [fila_jefa]
            return 0, {'registradas': 0, 'rechazadas': 0}, []

        monkeypatch.setattr(consultas_intervenciones, 'listar', listar_simulado)
        resumen = verificar_casos.ejecutar_comprobaciones(motor, datos, objetivo='todos')

    assert resumen['qa01']['resultado'] == 'PASA'
    assert resumen['qa02']['resultado'] == 'PASA'
    assert resumen['consulta_jefa']['resultado'] == 'PASA'
    assert resumen['qa03']['resultado'] == 'PASA'
    assert datos['estado'] == 'casos_ejecutados'
    assert datos['casos']['qa02']['asistencia_id'] == 202
    assert datos['casos']['qa02']['intervencion_id'] == 301
    salida = capsys.readouterr().out
    assert 'QA 01 (Normal)' in salida
    assert 'QA 02 (Identificación)' in salida
    assert 'Consulta de Jefa' in salida
    assert 'QA 03 (Reserva)' in salida


def test_limpieza_multi_comensales_valida_propiedad_estricta_y_filtros_sql(monkeypatch):
    import limpiar

    datos = _diario_multi_base()
    datos['estado'] = 'casos_ejecutados'
    datos['casos']['qa01'].update(
        estado='completado',
        momento_lectura='2026-10-15T11:31:00',
        lectura_id=101,
        asistencia_id=201,
    )
    datos['casos']['qa02'].update(
        estado='completado',
        momento_lectura='2026-10-15T11:32:00',
        lectura_id=102,
        asistencia_id=202,
        intervencion_id=301,
    )

    monkeypatch.setattr(c, 'existe_tabla', lambda _conn, t: t == 'intentos_login')
    monkeypatch.setattr(
        c, 'fila_asignacion', lambda _conn, bloquear=False: {'fecha': datetime(2026, 10, 15).date()}
    )

    filas_actuales = [
        {'id': 10, 'username': 'cocinera1', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 2, 'username': 'cocinera2', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 3, 'username': 'cocinera3', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 11, 'username': 'jefa', 'rol': 'jefa', 'usuario_turnos_id': None},
    ]
    filtros, params = limpiar.objetivos(Mock(), datos, datos['cuentas'])
    assert params['lectura_qa01'] == 101 and params['lectura_qa02'] == 102
    for tabla, filtro in filtros:
        c.revisar_sql(
            f"DELETE FROM `{tabla}` WHERE {filtro}",
            c.SIM,
            c.permisos((c.SIM, tabla, 'DELETE')),
        )

    lecturas_validas = [
        {
            'id': 101,
            'usuario_id': 900101,
            'dispositivo': c.DISPOSITIVO,
            'fecha_hora': datetime(2026, 10, 15, 11, 31),
            'resultado': 'aceptada',
            'motivo': None,
        },
        {
            'id': 102,
            'usuario_id': None,
            'dispositivo': c.DISPOSITIVO,
            'fecha_hora': datetime(2026, 10, 15, 11, 32),
            'resultado': 'rechazada',
            'motivo': 'no_identificado',
        },
    ]
    intentos_validos = [(1, 102, 2, 900102, 'registrada', None, 202)]
    asistencias_validas = [
        (201, 101, 900101, c.COMIDA, 191739904, 'biometrico', None),
        (202, 102, 900102, c.COMIDA, 192739904, 'manual', 2),
    ]

    def _conn_multi(lecturas, intentos, asistencias):
        conn = MagicMock()
        r_cuentas, r_lecturas, r_intentos, r_asist = (
            MagicMock(), MagicMock(), MagicMock(), MagicMock()
        )
        r_cuentas.mappings.return_value.all.return_value = filas_actuales
        r_lecturas.mappings.return_value.all.return_value = lecturas
        r_intentos.mappings.return_value.all.return_value = intentos
        r_asist.mappings.return_value.all.return_value = asistencias
        conn.execute.side_effect = [r_cuentas, r_lecturas, r_intentos, r_asist]
        return conn

    _, act = limpiar.comprobar_propiedad(
        _conn_multi(lecturas_validas, intentos_validos, asistencias_validas),
        datos,
        True,
    )
    assert act == datos['cuentas']

    # Rechaza si aparece una intervención asociada a qa01 o a otra cocinera
    with pytest.raises(c.Abortado, match='Intervenciones'):
        limpiar.comprobar_propiedad(
            _conn_multi(
                lecturas_validas,
                [(1, 101, 2, 900101, 'registrada', None, 201)],
                asistencias_validas,
            ),
            datos,
            True,
        )
    with pytest.raises(c.Abortado, match='Intervenciones'):
        limpiar.comprobar_propiedad(
            _conn_multi(
                lecturas_validas,
                [(1, 102, 3, 900102, 'registrada', None, 202)],
                asistencias_validas,
            ),
            datos,
            True,
        )

    # Rechaza si hay asistencia en qa03 (900103) o si la lectura de qa02 tiene usuario_id != None
    with pytest.raises(c.Abortado, match='Asistencia'):
        limpiar.comprobar_propiedad(
            _conn_multi(
                lecturas_validas,
                intentos_validos,
                asistencias_validas + [(203, 102, 900103, c.COMIDA, 193739904, 'manual', 2)],
            ),
            datos,
            True,
        )
    with pytest.raises(c.Abortado, match='Lectura de qa02'):
        limpiar.comprobar_propiedad(
            _conn_multi(
                [lecturas_validas[0], {**lecturas_validas[1], 'usuario_id': 900102}],
                intentos_validos,
                asistencias_validas,
            ),
            datos,
            True,
        )


def test_preparador_ejecuta_sql_real_offline_y_comprueba_modelo_comensal(tmp_path, monkeypatch):
    """Ejecuta offline consultas e inserciones del preparador sobre un esquema SQLite real.

    Verifica que el SQL no falle con columnas inexistentes, ejecuta la verificación
    contra el modelo Comensal real comprobando que no tiene ni servicio ni activo, y confirma
    que v_comensales rechaza consultas por servicio y activo.
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    from app.modelos.heredados import Comensal
    import preparar_comensales

    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    monkeypatch.setattr(c, 'CORRIDA', tmp_path / 'corrida.json')

    engine = create_engine('sqlite://')
    with engine.connect() as conn:
        conn.execute(text(f"ATTACH DATABASE ':memory:' AS `{c.DEMO}`"))

        conn.execute(text(f"""
            CREATE TABLE `{c.DEMO}`.categorias (
                id INTEGER PRIMARY KEY,
                nombre TEXT,
                nivel INTEGER,
                descripcion TEXT
            )
        """))
        conn.execute(text(f"""
            CREATE TABLE `{c.DEMO}`.servicios (
                id INTEGER PRIMARY KEY,
                nombre TEXT,
                descripcion TEXT,
                cantidad_pacientes INTEGER
            )
        """))
        conn.execute(text(f"""
            CREATE TABLE `{c.DEMO}`.turnos (
                id INTEGER PRIMARY KEY,
                nombre_turno TEXT,
                hora_inicio TEXT,
                hora_fin TEXT,
                duracion_horas INTEGER,
                categoria_id INTEGER
            )
        """))
        conn.execute(text(f"""
            CREATE TABLE `{c.DEMO}`.comidas (
                id INTEGER PRIMARY KEY,
                nombre TEXT,
                codigo TEXT,
                estado INTEGER
            )
        """))
        conn.execute(text(f"""
            CREATE TABLE `{c.DEMO}`.turno_comida (
                id INTEGER PRIMARY KEY,
                turno_id INTEGER,
                comida_id INTEGER,
                dia_relativo INTEGER
            )
        """))
        conn.execute(text(f"""
            CREATE TABLE `{c.DEMO}`.users (
                id INTEGER PRIMARY KEY,
                name TEXT,
                categoria_id INTEGER
            )
        """))
        conn.execute(text(f"""
            CREATE TABLE `{c.DEMO}`.personas (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                nombre_completo TEXT,
                carnet_identidad TEXT,
                tipo_trabajador TEXT,
                numero_tipo_salario TEXT
            )
        """))
        conn.execute(text(f"""
            CREATE TABLE `{c.DEMO}`.usuario_servicios (
                id INTEGER PRIMARY KEY,
                usuario_id INTEGER,
                servicio_id INTEGER,
                estado INTEGER,
                fecha_ingreso TEXT
            )
        """))
        conn.execute(text(f"""
            CREATE TABLE `{c.DEMO}`.turnos_asignados (
                id INTEGER PRIMARY KEY,
                usuario_id INTEGER,
                servicio_id INTEGER,
                area_id INTEGER,
                fecha TEXT,
                estado TEXT,
                es_intercambio INTEGER,
                turno_id INTEGER
            )
        """))
        conn.execute(text(f"""
            CREATE TABLE `{c.DEMO}`.escenario_identificaciones (
                identificador TEXT PRIMARY KEY,
                usuario_id INTEGER,
                origen TEXT CHECK (origen = 'simulado') NOT NULL,
                descripcion TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE v_comensales (
                usuario_id INTEGER PRIMARY KEY,
                login TEXT,
                nombre_completo TEXT,
                carnet_identidad TEXT,
                tipo_trabajador TEXT,
                numero_item TEXT,
                categoria_id INTEGER,
                categoria TEXT,
                categoria_nivel INTEGER,
                tiene_ficha INTEGER
            )
        """))
        conn.commit()

        # Sembrar catálogos base
        conn.execute(text(f"INSERT INTO `{c.DEMO}`.categorias VALUES (9001, 'Administrativo', 1, 'Cat desc')"))
        conn.execute(text(f"INSERT INTO `{c.DEMO}`.servicios VALUES (9001, 'Servicio simulado', 'Srv desc', 10)"))
        conn.execute(text(f"INSERT INTO `{c.DEMO}`.turnos VALUES (9001, 'Turno 12h', '06:00:00', '18:00:00', 12, 9001)"))
        conn.execute(text(f"INSERT INTO `{c.DEMO}`.comidas VALUES (2, 'Almuerzo', 'almuerzo', 1)"))
        conn.execute(text(f"INSERT INTO `{c.DEMO}`.turno_comida VALUES (9001, 9001, 2, 0)"))
        conn.commit()

        # 1. Validar catalogos con sentencias SQL reales
        preparar_comensales.validar_catalogos_base(conn)

        # 2. Ejecutar inspección real antes de insertar: los 3 comensales están ausentes ('por_insertar')
        c.cargar_manifiesto_comensales()
        for codigo, spec in c.COMENSALES_QA.items():
            assert preparar_comensales.inspeccionar_comensal(conn, spec) == 'por_insertar'

        # 3. Ejecutar inserción real de los 3 comensales: prueba los 15 INSERT reales en SQLite
        for codigo, spec in c.COMENSALES_QA.items():
            preparar_comensales.insertar_comensal(conn, spec)
        conn.commit()

        # 4. Inspección tras inserción: ahora deben ser existentes idempotentes
        for codigo, spec in c.COMENSALES_QA.items():
            assert preparar_comensales.inspeccionar_comensal(conn, spec) == 'existente_idempotente'

        # Comprobar que la restricción CHECK rechaza 'qa' en SQLite
        with pytest.raises(Exception):
            conn.execute(text(f"""
                INSERT INTO `{c.DEMO}`.escenario_identificaciones
                (identificador, usuario_id, origen, descripcion)
                VALUES ('SIM-TEST-QA-FAIL', 999999, 'qa', 'Incompatible')
            """))

        # 5. Insertar filas en v_comensales para comprobación del modelo Comensal
        for codigo, spec in c.COMENSALES_QA.items():
            conn.execute(text("""
                INSERT INTO v_comensales
                (usuario_id, login, nombre_completo, carnet_identidad, tipo_trabajador, numero_item,
                 categoria_id, categoria, categoria_nivel, tiene_ficha)
                VALUES (:uid, :login, :nom, :ci, :tipo, :leg, :cat, 'Administrativo', 1, 1)
            """), {
                'uid': spec['usuario_id'],
                'login': spec['login'],
                'nom': spec['nombre'],
                'ci': spec['carnet_identidad'],
                'tipo': spec['tipo_trabajador'],
                'leg': spec['legajo'],
                'cat': spec['categoria_id'],
            })
        conn.commit()

        # 6. Comprobación del modelo Comensal real mediante Session
        with Session(bind=conn) as sesion:
            for codigo, spec in c.COMENSALES_QA.items():
                ficha = sesion.get(Comensal, spec['usuario_id'])
                assert ficha is not None
                assert ficha.usuario_id == spec['usuario_id']
                assert ficha.nombre_completo == spec['nombre']
                assert ficha.numero_item == spec['legajo']
                assert ficha.carnet_identidad == spec['carnet_identidad']
                assert ficha.categoria == 'Administrativo'
                assert bool(ficha.tiene_ficha) is True

                # Demostrar que el modelo Comensal NO tiene los campos espurios
                assert not hasattr(ficha, 'servicio')
                assert not hasattr(ficha, 'activo')

        # 7. Demostrar que filas_asignaciones_qa funciona con las columnas reales de v_comensales
        res_asig = c.filas_asignaciones_qa(conn, bloquear=False)
        assert len(res_asig['asignaciones']) == 3

        # 8. Demostrar que una consulta con servicio o activo falla en SQL real contra v_comensales
        with pytest.raises(Exception):
            conn.execute(text("SELECT servicio, activo FROM v_comensales"))


def test_limpiar_recupera_casos_interrumpidos_sin_reenviar_ni_borrar_ajenos(tmp_path, monkeypatch):
    import limpiar

    diario = tmp_path / 'corrida.json'
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    monkeypatch.setattr(c, 'CORRIDA', diario)

    # Caso A: Corrida multi con qa01 interrumpido en lectura_pendiente y sin fila persistida en DB (rollback)
    c.cargar_manifiesto_comensales()
    datos_interrumpidos = {
        'version': 2,
        'escenario': 'tres_comensales_qa',
        'servidor': 'srv-test',
        'bases': [c.SIM, c.DEMO],
        'inicio': '2026-10-18T10:00:00',
        'fecha_original': '2026-10-15',
        'fecha_destino': None,
        'max_intento_inicial': 0,
        'contrato_sesiones': None,
        'max_sesion_inicial': None,
        'huella_base': {'sha256': 'abc', 'tablas': {}},
        'cuentas': {'cocinera2': 2},
        'comensales': c.resumen_comensales_diario(),
        'casos': c.casos_iniciales_diario(),
    }
    datos_interrumpidos['casos']['qa01']['estado'] = 'lectura_pendiente'
    datos_interrumpidos['casos']['qa01']['lectura_id'] = 888
    c.guardar_corrida(datos_interrumpidos)

    conn_sin_filas = MagicMock()
    conn_sin_filas.execute.return_value.mappings.return_value.one_or_none.return_value = None

    cambios = limpiar.contrastar_casos_interrumpidos(conn_sin_filas, datos_interrumpidos, guardar_diario=True)
    assert cambios is True
    assert datos_interrumpidos['casos']['qa01']['estado'] == 'pendiente'
    assert datos_interrumpidos['casos']['qa01']['lectura_id'] is None

    # Caso B: Corrida multi con qa01 en lectura_pendiente y fila persistida en DB (commit exitoso previo a crash)
    datos_interrumpidos['casos']['qa01']['estado'] = 'lectura_pendiente'
    datos_interrumpidos['casos']['qa01']['lectura_id'] = 999
    datos_interrumpidos['casos']['qa01']['momento_lectura'] = '2026-10-15T11:30:00'
    c.guardar_corrida(datos_interrumpidos)

    conn_con_filas = MagicMock()
    r_lect = MagicMock()
    r_lect.mappings.return_value.one_or_none.return_value = {
        'id': 999,
        'usuario_id': 900101,
        'dispositivo': c.DISPOSITIVO,
        'fecha_hora': datetime(2026, 10, 15, 11, 30),
        'resultado': 'aceptada',
        'motivo': None,
    }
    r_asist = MagicMock()
    r_asist.mappings.return_value.all.return_value = [{
        'id': 777,
        'usuario_id': 900101,
        'comida_id': c.COMIDA,
        'turno_asignado_id': c.COMENSALES_QA['qa01']['asignacion_id'],
        'metodo': 'biometrico',
        'registrado_por_cuenta': None,
    }]
    r_interv = MagicMock()
    r_interv.scalar_one.return_value = 0
    conn_con_filas.execute.side_effect = [r_lect, r_asist, r_interv]

    cambios2 = limpiar.contrastar_casos_interrumpidos(conn_con_filas, datos_interrumpidos, guardar_diario=True)
    assert cambios2 is True
    assert datos_interrumpidos['casos']['qa01']['estado'] == 'completado'
    assert datos_interrumpidos['casos']['qa01']['asistencia_id'] == 777
    assert datos_interrumpidos['casos']['qa01']['lectura_id'] == 999

    # Caso C: Fila ajena o alterada (dispositivo distinto) aborta
    datos_interrumpidos['casos']['qa01']['estado'] = 'lectura_pendiente'
    datos_interrumpidos['casos']['qa01']['lectura_id'] = 999
    datos_interrumpidos['casos']['qa01']['momento_lectura'] = '2026-10-15T11:30:00'
    r_ajena = MagicMock()
    r_ajena.mappings.return_value.one_or_none.return_value = {
        'id': 999,
        'usuario_id': 900101,
        'dispositivo': 'dispositivo_ajeno',
        'fecha_hora': datetime(2026, 10, 15, 11, 30),
        'resultado': 'aceptada',
        'motivo': None,
    }
    conn_ajena = MagicMock()
    conn_ajena.execute.return_value = r_ajena
    with pytest.raises(c.Abortado, match='otro dispositivo'):
        limpiar.contrastar_casos_interrumpidos(conn_ajena, datos_interrumpidos)


def test_limpiar_simulacro_con_caso_interrumpido_deja_diario_identico(tmp_path, monkeypatch, capsys):
    import limpiar

    diario = tmp_path / 'corrida.json'
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    monkeypatch.setattr(c, 'CORRIDA', diario)
    c.cargar_manifiesto_comensales()

    datos = {
        'version': 2,
        'escenario': 'tres_comensales_qa',
        'servidor': 'srv-test',
        'bases': [c.SIM, c.DEMO],
        'inicio': '2026-10-18T10:00:00',
        'fecha_original': '2026-10-15',
        'fecha_destino': None,
        'max_intento_inicial': 0,
        'contrato_sesiones': None,
        'max_sesion_inicial': None,
        'huella_base': {'sha256': 'abc', 'tablas': {}},
        'cuentas': {'cocinera1': 1, 'cocinera2': 2, 'cocinera3': 3, 'jefa': 4},
        'comensales': c.resumen_comensales_diario(),
        'casos': c.casos_iniciales_diario(),
    }
    datos['casos']['qa01']['estado'] = 'lectura_pendiente'
    datos['casos']['qa01']['lectura_id'] = 999
    datos['casos']['qa01']['momento_lectura'] = '2026-10-15T11:30:00'
    c.guardar_corrida(datos)
    contenido_antes = diario.read_text(encoding='utf-8')

    filas_cuentas = [
        {'id': 1, 'username': 'cocinera1', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 2, 'username': 'cocinera2', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 3, 'username': 'cocinera3', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 4, 'username': 'jefa', 'rol': 'jefa', 'usuario_turnos_id': None},
    ]
    conn = MagicMock()
    monkeypatch.setattr(c, 'filas_asignaciones_corrida', lambda conn, d, bloquear=False: {'fecha': datetime(2026, 10, 15).date()})
    r_cuentas = MagicMock()
    r_cuentas.mappings.return_value.all.return_value = filas_cuentas

    r_lect_dir = MagicMock()
    r_lect_dir.mappings.return_value.one_or_none.return_value = {
        'id': 999,
        'usuario_id': 900101,
        'dispositivo': c.DISPOSITIVO,
        'fecha_hora': datetime(2026, 10, 15, 11, 30),
        'resultado': 'aceptada',
        'motivo': None,
    }
    r_asist_c = MagicMock()
    r_asist_c.mappings.return_value.all.return_value = [{
        'id': 777,
        'lectura_id': 999,
        'usuario_id': 900101,
        'comida_id': c.COMIDA,
        'turno_asignado_id': c.COMENSALES_QA['qa01']['asignacion_id'],
        'metodo': 'biometrico',
        'registrado_por_cuenta': None,
    }]
    r_int_c = MagicMock()
    r_int_c.scalar_one.return_value = 0

    r_lecturas_all = MagicMock()
    r_lecturas_all.mappings.return_value.all.return_value = [{
        'id': 999,
        'usuario_id': 900101,
        'dispositivo': c.DISPOSITIVO,
        'fecha_hora': datetime(2026, 10, 15, 11, 30),
        'resultado': 'aceptada',
        'motivo': None,
    }]
    r_intentos_all = MagicMock()
    r_intentos_all.mappings.return_value.all.return_value = []
    r_asist_all = MagicMock()
    r_asist_all.mappings.return_value.all.return_value = [{
        'id': 777,
        'lectura_id': 999,
        'usuario_id': 900101,
        'comida_id': c.COMIDA,
        'turno_asignado_id': c.COMENSALES_QA['qa01']['asignacion_id'],
        'metodo': 'biometrico',
        'registrado_por_cuenta': None,
    }]

    r_count = MagicMock()
    r_count.scalar_one.return_value = 1

    conn.execute.side_effect = [
        r_cuentas,
        r_lect_dir,
        r_asist_c,
        r_int_c,
        r_lecturas_all,
        r_intentos_all,
        r_asist_all,
        r_count, r_count, r_count, r_count, r_count, r_count,
        r_count, r_count, r_count, r_count, r_count, r_count,
    ]

    motor = MagicMock()
    motor.begin.return_value.__enter__.return_value = conn
    control = MagicMock()
    control.__enter__.return_value = (motor, {'sha256': 'abc'}, 'srv-test')
    monkeypatch.setattr(c, 'entorno_seguro', Mock(return_value=control))
    monkeypatch.setattr(c, 'comprobar_base', Mock())
    monkeypatch.setattr(c, 'existe_tabla', lambda conn, t: False)
    monkeypatch.setattr(sys, 'argv', ['limpiar.py'])

    limpiar.main()

    contenido_despues = diario.read_text(encoding='utf-8')
    assert contenido_despues == contenido_antes
    out = capsys.readouterr().out
    assert 'Simulacro: no se emitieron DELETE/UPDATE ni se modificó corrida.json' in out


def test_limpiar_recuperacion_mismo_dispositivo_usuario_pero_hora_distinta_rechaza(tmp_path, monkeypatch):
    import limpiar

    diario = tmp_path / 'corrida.json'
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    monkeypatch.setattr(c, 'CORRIDA', diario)
    c.cargar_manifiesto_comensales()

    datos = {
        'version': 2,
        'escenario': 'tres_comensales_qa',
        'servidor': 'srv-test',
        'bases': [c.SIM, c.DEMO],
        'inicio': '2026-10-18T10:00:00',
        'fecha_original': '2026-10-15',
        'fecha_destino': None,
        'max_intento_inicial': 0,
        'contrato_sesiones': None,
        'max_sesion_inicial': None,
        'huella_base': {'sha256': 'abc', 'tablas': {}},
        'cuentas': {'cocinera2': 2},
        'comensales': c.resumen_comensales_diario(),
        'casos': c.casos_iniciales_diario(),
    }
    datos['casos']['qa01']['estado'] = 'lectura_pendiente'
    datos['casos']['qa01']['lectura_id'] = 999
    datos['casos']['qa01']['momento_lectura'] = '2026-10-15T11:30:00'

    conn = MagicMock()
    r_lect = MagicMock()
    r_lect.mappings.return_value.one_or_none.return_value = {
        'id': 999,
        'usuario_id': 900101,
        'dispositivo': c.DISPOSITIVO,
        'fecha_hora': datetime(2026, 10, 15, 12, 45, 0),
        'resultado': 'aceptada',
        'motivo': None,
    }
    conn.execute.return_value = r_lect

    with pytest.raises(c.Abortado, match='hora distinta'):
        limpiar.contrastar_casos_interrumpidos(conn, datos)


def test_limpiar_reconciliacion_ambigua_rechaza_sin_alterar_diario(tmp_path, monkeypatch):
    import limpiar

    diario = tmp_path / 'corrida.json'
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    monkeypatch.setattr(c, 'CORRIDA', diario)
    c.cargar_manifiesto_comensales()

    datos = {
        'version': 2,
        'escenario': 'tres_comensales_qa',
        'servidor': 'srv-test',
        'bases': [c.SIM, c.DEMO],
        'inicio': '2026-10-18T10:00:00',
        'fecha_original': '2026-10-15',
        'fecha_destino': None,
        'max_intento_inicial': 0,
        'contrato_sesiones': None,
        'max_sesion_inicial': None,
        'huella_base': {'sha256': 'abc', 'tablas': {}},
        'cuentas': {'cocinera2': 2},
        'comensales': c.resumen_comensales_diario(),
        'casos': c.casos_iniciales_diario(),
    }
    datos['casos']['qa01']['estado'] = 'lectura_pendiente'
    datos['casos']['qa01']['lectura_id'] = None
    datos['casos']['qa01']['momento_lectura'] = '2026-10-15T11:30:00'
    c.guardar_corrida(datos)
    contenido_antes = diario.read_text(encoding='utf-8')

    conn = MagicMock()
    r_disp = MagicMock()
    r_disp.mappings.return_value.all.return_value = [
        {
            'id': 101,
            'usuario_id': 900101,
            'dispositivo': c.DISPOSITIVO,
            'fecha_hora': datetime(2026, 10, 15, 11, 30),
            'resultado': 'aceptada',
            'motivo': None,
        },
        {
            'id': 102,
            'usuario_id': 900101,
            'dispositivo': c.DISPOSITIVO,
            'fecha_hora': datetime(2026, 10, 15, 11, 30),
            'resultado': 'aceptada',
            'motivo': None,
        },
    ]
    conn.execute.return_value = r_disp

    with pytest.raises(c.Abortado, match='ambigua|ambigüedad'):
        limpiar.contrastar_casos_interrumpidos(conn, datos, guardar_diario=True)

    assert diario.read_text(encoding='utf-8') == contenido_antes

    motor = MagicMock()
    motor.begin.return_value.__enter__.return_value = conn
    control = MagicMock()
    control.__enter__.return_value = (motor, {'sha256': 'abc'}, 'srv-test')
    monkeypatch.setattr(c, 'entorno_seguro', Mock(return_value=control))
    monkeypatch.setattr(c, 'comprobar_base', Mock())
    monkeypatch.setattr(sys, 'argv', ['limpiar.py', '--reconciliar'])

    with pytest.raises(c.Abortado, match='ambigua|ambigüedad'):
        limpiar.main()

    assert diario.read_text(encoding='utf-8') == contenido_antes


def test_limpiar_recuperacion_valida_tras_commit_vs_rollback(tmp_path, monkeypatch):
    import limpiar

    diario = tmp_path / 'corrida.json'
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    monkeypatch.setattr(c, 'CORRIDA', diario)
    c.cargar_manifiesto_comensales()

    base_datos = {
        'version': 2,
        'escenario': 'tres_comensales_qa',
        'servidor': 'srv-test',
        'bases': [c.SIM, c.DEMO],
        'inicio': '2026-10-18T10:00:00',
        'fecha_original': '2026-10-15',
        'fecha_destino': None,
        'max_intento_inicial': 0,
        'contrato_sesiones': None,
        'max_sesion_inicial': None,
        'huella_base': {'sha256': 'abc', 'tablas': {}},
        'cuentas': {'cocinera2': 2},
        'comensales': c.resumen_comensales_diario(),
        'casos': c.casos_iniciales_diario(),
    }

    # 1. Recuperación válida tras COMMIT:
    datos_commit = copy.deepcopy(base_datos)
    datos_commit['casos']['qa01']['estado'] = 'lectura_pendiente'
    datos_commit['casos']['qa01']['lectura_id'] = 999
    datos_commit['casos']['qa01']['momento_lectura'] = '2026-10-15T11:30:00'
    c.guardar_corrida(datos_commit)

    conn_commit = MagicMock()
    r_lect = MagicMock()
    r_lect.mappings.return_value.one_or_none.return_value = {
        'id': 999,
        'usuario_id': 900101,
        'dispositivo': c.DISPOSITIVO,
        'fecha_hora': datetime(2026, 10, 15, 11, 30),
        'resultado': 'aceptada',
        'motivo': None,
    }
    r_asist = MagicMock()
    r_asist.mappings.return_value.all.return_value = [{
        'id': 777,
        'lectura_id': 999,
        'usuario_id': 900101,
        'comida_id': c.COMIDA,
        'turno_asignado_id': c.COMENSALES_QA['qa01']['asignacion_id'],
        'metodo': 'biometrico',
        'registrado_por_cuenta': None,
    }]
    r_interv = MagicMock()
    r_interv.scalar_one.return_value = 0
    conn_commit.execute.side_effect = [r_lect, r_asist, r_interv]

    cambios_c = limpiar.contrastar_casos_interrumpidos(conn_commit, datos_commit, guardar_diario=True)
    assert cambios_c is True
    assert datos_commit['casos']['qa01']['estado'] == 'completado'
    assert datos_commit['casos']['qa01']['lectura_id'] == 999
    assert datos_commit['casos']['qa01']['asistencia_id'] == 777
    guardado_c = json.loads(diario.read_text(encoding='utf-8'))
    assert guardado_c['casos']['qa01']['estado'] == 'completado'

    # 2. Recuperación válida tras ROLLBACK (con lectura_id previo inexistente en DB):
    datos_rollback = copy.deepcopy(base_datos)
    datos_rollback['casos']['qa01']['estado'] = 'lectura_pendiente'
    datos_rollback['casos']['qa01']['lectura_id'] = 888
    datos_rollback['casos']['qa01']['momento_lectura'] = '2026-10-15T11:30:00'
    c.guardar_corrida(datos_rollback)

    conn_rollback = MagicMock()
    r_dir_vacia = MagicMock()
    r_dir_vacia.mappings.return_value.one_or_none.return_value = None
    r_disp_vacio = MagicMock()
    r_disp_vacio.mappings.return_value.all.return_value = []
    conn_rollback.execute.side_effect = [r_dir_vacia, r_disp_vacio]

    cambios_r = limpiar.contrastar_casos_interrumpidos(conn_rollback, datos_rollback, guardar_diario=True)
    assert cambios_r is True
    assert datos_rollback['casos']['qa01']['estado'] == 'pendiente'
    assert datos_rollback['casos']['qa01']['lectura_id'] is None
    assert datos_rollback['casos']['qa01']['asistencia_id'] is None
    guardado_r = json.loads(diario.read_text(encoding='utf-8'))
    assert guardado_r['casos']['qa01']['estado'] == 'pendiente'
    assert guardado_r['casos']['qa01']['lectura_id'] is None

    # 3. Recuperación válida tras ROLLBACK (con lectura_id None):
    datos_rollback_nolid = copy.deepcopy(base_datos)
    datos_rollback_nolid['casos']['qa01']['estado'] = 'lectura_pendiente'
    datos_rollback_nolid['casos']['qa01']['lectura_id'] = None
    datos_rollback_nolid['casos']['qa01']['momento_lectura'] = '2026-10-15T11:30:00'
    c.guardar_corrida(datos_rollback_nolid)

    conn_r2 = MagicMock()
    r_disp_v2 = MagicMock()
    r_disp_v2.mappings.return_value.all.return_value = []
    conn_r2.execute.return_value = r_disp_v2
    cambios_r2 = limpiar.contrastar_casos_interrumpidos(conn_r2, datos_rollback_nolid, guardar_diario=True)
    assert cambios_r2 is True
    assert datos_rollback_nolid['casos']['qa01']['estado'] == 'pendiente'
    assert datos_rollback_nolid['casos']['qa01']['lectura_id'] is None


def test_comprobar_propiedad_qa02_asistencia_manual_sin_intervencion_rechaza(monkeypatch):
    import limpiar

    monkeypatch.setattr(
        c, 'fila_asignacion', lambda _conn, bloquear=False: {'fecha': datetime(2026, 10, 15).date()}
    )
    datos = _diario_multi_base()
    datos['estado'] = 'casos_ejecutados'
    datos['casos']['qa01'].update(
        estado='completado',
        momento_lectura='2026-10-15T11:31:00',
        lectura_id=101,
        asistencia_id=201,
    )
    datos['casos']['qa02'].update(
        estado='completado',
        momento_lectura='2026-10-15T11:32:00',
        lectura_id=102,
        asistencia_id=202,
    )

    filas_actuales = [
        {'id': 10, 'username': 'cocinera1', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 2, 'username': 'cocinera2', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 3, 'username': 'cocinera3', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 11, 'username': 'jefa', 'rol': 'jefa', 'usuario_turnos_id': None},
    ]
    lecturas_validas = [
        {
            'id': 101,
            'usuario_id': 900101,
            'dispositivo': c.DISPOSITIVO,
            'fecha_hora': datetime(2026, 10, 15, 11, 31),
            'resultado': 'aceptada',
            'motivo': None,
        },
        {
            'id': 102,
            'usuario_id': None,
            'dispositivo': c.DISPOSITIVO,
            'fecha_hora': datetime(2026, 10, 15, 11, 32),
            'resultado': 'rechazada',
            'motivo': 'no_identificado',
        },
    ]
    asistencias_con_qa02 = [
        (201, 101, 900101, c.COMIDA, 191739904, 'biometrico', None),
        (202, 102, 900102, c.COMIDA, 192739904, 'manual', 2),
    ]

    def _conn(intentos, asistencias):
        conn = MagicMock()
        r_cuentas, r_lecturas, r_intentos, r_asist = (
            MagicMock(), MagicMock(), MagicMock(), MagicMock()
        )
        r_cuentas.mappings.return_value.all.return_value = filas_actuales
        r_lecturas.mappings.return_value.all.return_value = lecturas_validas
        r_intentos.mappings.return_value.all.return_value = intentos
        r_asist.mappings.return_value.all.return_value = asistencias
        conn.execute.side_effect = [r_cuentas, r_lecturas, r_intentos, r_asist]
        return conn

    # QA02 con asistencia pero 0 intervenciones:
    with pytest.raises(c.Abortado, match='QA02 con asistencia manual propia pero ninguna intervención registrada'):
        limpiar.comprobar_propiedad(_conn([], asistencias_con_qa02), datos, True)


def test_comprobar_propiedad_qa02_intervencion_sin_asistencia_rechaza(monkeypatch):
    import limpiar

    monkeypatch.setattr(
        c, 'fila_asignacion', lambda _conn, bloquear=False: {'fecha': datetime(2026, 10, 15).date()}
    )
    datos = _diario_multi_base()
    datos['estado'] = 'casos_ejecutados'
    datos['casos']['qa01'].update(
        estado='completado',
        momento_lectura='2026-10-15T11:31:00',
        lectura_id=101,
        asistencia_id=201,
    )
    datos['casos']['qa02'].update(
        estado='completado',
        momento_lectura='2026-10-15T11:32:00',
        lectura_id=102,
    )

    filas_actuales = [
        {'id': 10, 'username': 'cocinera1', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 2, 'username': 'cocinera2', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 3, 'username': 'cocinera3', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 11, 'username': 'jefa', 'rol': 'jefa', 'usuario_turnos_id': None},
    ]
    lecturas_validas = [
        {
            'id': 101,
            'usuario_id': 900101,
            'dispositivo': c.DISPOSITIVO,
            'fecha_hora': datetime(2026, 10, 15, 11, 31),
            'resultado': 'aceptada',
            'motivo': None,
        },
        {
            'id': 102,
            'usuario_id': None,
            'dispositivo': c.DISPOSITIVO,
            'fecha_hora': datetime(2026, 10, 15, 11, 32),
            'resultado': 'rechazada',
            'motivo': 'no_identificado',
        },
    ]
    asistencias_solo_qa01 = [
        (201, 101, 900101, c.COMIDA, 191739904, 'biometrico', None),
    ]
    intentos_con_qa02 = [
        (1, 102, 2, 900102, 'registrada', None, 202)
    ]

    def _conn(intentos, asistencias):
        conn = MagicMock()
        r_cuentas, r_lecturas, r_intentos, r_asist = (
            MagicMock(), MagicMock(), MagicMock(), MagicMock()
        )
        r_cuentas.mappings.return_value.all.return_value = filas_actuales
        r_lecturas.mappings.return_value.all.return_value = lecturas_validas
        r_intentos.mappings.return_value.all.return_value = intentos
        r_asist.mappings.return_value.all.return_value = asistencias
        conn.execute.side_effect = [r_cuentas, r_lecturas, r_intentos, r_asist]
        return conn

    # QA02 con intervención pero 0 asistencias:
    with pytest.raises(c.Abortado, match='QA02 con intervención registrada pero ninguna asistencia'):
        limpiar.comprobar_propiedad(_conn(intentos_con_qa02, asistencias_solo_qa01), datos, True)


def test_comprobar_propiedad_qa02_relaciones_cruzadas_y_nulas_rechaza(monkeypatch):
    import limpiar

    monkeypatch.setattr(
        c, 'fila_asignacion', lambda _conn, bloquear=False: {'fecha': datetime(2026, 10, 15).date()}
    )
    datos = _diario_multi_base()
    datos['estado'] = 'casos_ejecutados'
    datos['casos']['qa01'].update(
        estado='completado',
        momento_lectura='2026-10-15T11:31:00',
        lectura_id=101,
        asistencia_id=201,
    )
    datos['casos']['qa02'].update(
        estado='completado',
        momento_lectura='2026-10-15T11:32:00',
        lectura_id=102,
        asistencia_id=202,
    )

    filas_actuales = [
        {'id': 10, 'username': 'cocinera1', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 2, 'username': 'cocinera2', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 3, 'username': 'cocinera3', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 11, 'username': 'jefa', 'rol': 'jefa', 'usuario_turnos_id': None},
    ]
    lecturas_validas = [
        {
            'id': 101,
            'usuario_id': 900101,
            'dispositivo': c.DISPOSITIVO,
            'fecha_hora': datetime(2026, 10, 15, 11, 31),
            'resultado': 'aceptada',
            'motivo': None,
        },
        {
            'id': 102,
            'usuario_id': None,
            'dispositivo': c.DISPOSITIVO,
            'fecha_hora': datetime(2026, 10, 15, 11, 32),
            'resultado': 'rechazada',
            'motivo': 'no_identificado',
        },
    ]

    def _conn(intentos, asistencias):
        conn = MagicMock()
        r_cuentas, r_lecturas, r_intentos, r_asist = (
            MagicMock(), MagicMock(), MagicMock(), MagicMock()
        )
        r_cuentas.mappings.return_value.all.return_value = filas_actuales
        r_lecturas.mappings.return_value.all.return_value = lecturas_validas
        r_intentos.mappings.return_value.all.return_value = intentos
        r_asist.mappings.return_value.all.return_value = asistencias
        conn.execute.side_effect = [r_cuentas, r_lecturas, r_intentos, r_asist]
        return conn

    asist_base = [
        (201, 101, 900101, c.COMIDA, 191739904, 'biometrico', None),
        (202, 102, 900102, c.COMIDA, 192739904, 'manual', 2),
    ]

    # 1. intervencion.asistencia_id != asistencia.id (cruzada con 201 de qa01):
    int_cruzada = [(1, 102, 2, 900102, 'registrada', None, 201)]
    with pytest.raises(c.Abortado, match='Intervenciones fuera del caso básico|relaciones incompatibles'):
        limpiar.comprobar_propiedad(_conn(int_cruzada, asist_base), datos, True)

    # 2. intervencion.asistencia_id is None:
    int_sin_asist_id = [(1, 102, 2, 900102, 'registrada', None, None)]
    with pytest.raises(c.Abortado, match='Intervenciones fuera del caso básico|relaciones incompatibles'):
        limpiar.comprobar_propiedad(_conn(int_sin_asist_id, asist_base), datos, True)

    # 3. asistencia con comida_id nulo:
    asist_comida_nula = [
        (201, 101, 900101, c.COMIDA, 191739904, 'biometrico', None),
        (202, 102, 900102, None, 192739904, 'manual', 2),
    ]
    int_valido = [(1, 102, 2, 900102, 'registrada', None, 202)]
    with pytest.raises(c.Abortado, match='Asistencia de qa02 ajena o alterada: relaciones incompatibles'):
        limpiar.comprobar_propiedad(_conn(int_valido, asist_comida_nula), datos, True)

    # 4. asistencia con asignacion_id diferente/nula:
    asist_asig_invalida = [
        (201, 101, 900101, c.COMIDA, 191739904, 'biometrico', None),
        (202, 102, 900102, c.COMIDA, 99999999, 'manual', 2),
    ]
    with pytest.raises(c.Abortado, match='Asistencia de qa02 ajena o alterada: relaciones incompatibles'):
        limpiar.comprobar_propiedad(_conn(int_valido, asist_asig_invalida), datos, True)

    # 5. asistencia registrada_por_cuenta nula (no por cocinera2):
    asist_cuenta_nula = [
        (201, 101, 900101, c.COMIDA, 191739904, 'biometrico', None),
        (202, 102, 900102, c.COMIDA, 192739904, 'manual', None),
    ]
    with pytest.raises(c.Abortado, match='Asistencia de qa02 ajena o alterada: relaciones incompatibles'):
        limpiar.comprobar_propiedad(_conn(int_valido, asist_cuenta_nula), datos, True)

    # 6. asistencia_id en diario distinto al id real:
    datos_aid_distinto = copy.deepcopy(datos)
    datos_aid_distinto['casos']['qa02']['asistencia_id'] = 9999
    with pytest.raises(c.Abortado, match='Asistencia de qa02 ajena o alterada: relaciones incompatibles'):
        limpiar.comprobar_propiedad(_conn(int_valido, asist_base), datos_aid_distinto, True)


def test_comprobar_propiedad_duplicados_rechaza(monkeypatch):
    import limpiar

    monkeypatch.setattr(
        c, 'fila_asignacion', lambda _conn, bloquear=False: {'fecha': datetime(2026, 10, 15).date()}
    )
    datos = _diario_multi_base()
    datos['estado'] = 'casos_ejecutados'
    datos['casos']['qa01'].update(
        estado='completado',
        momento_lectura='2026-10-15T11:31:00',
        lectura_id=101,
        asistencia_id=201,
    )
    datos['casos']['qa02'].update(
        estado='completado',
        momento_lectura='2026-10-15T11:32:00',
        lectura_id=102,
        asistencia_id=202,
    )

    filas_actuales = [
        {'id': 10, 'username': 'cocinera1', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 2, 'username': 'cocinera2', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 3, 'username': 'cocinera3', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 11, 'username': 'jefa', 'rol': 'jefa', 'usuario_turnos_id': None},
    ]
    lecturas_validas = [
        {
            'id': 101,
            'usuario_id': 900101,
            'dispositivo': c.DISPOSITIVO,
            'fecha_hora': datetime(2026, 10, 15, 11, 31),
            'resultado': 'aceptada',
            'motivo': None,
        },
        {
            'id': 102,
            'usuario_id': None,
            'dispositivo': c.DISPOSITIVO,
            'fecha_hora': datetime(2026, 10, 15, 11, 32),
            'resultado': 'rechazada',
            'motivo': 'no_identificado',
        },
    ]

    def _conn(intentos, asistencias):
        conn = MagicMock()
        r_cuentas, r_lecturas, r_intentos, r_asist = (
            MagicMock(), MagicMock(), MagicMock(), MagicMock()
        )
        r_cuentas.mappings.return_value.all.return_value = filas_actuales
        r_lecturas.mappings.return_value.all.return_value = lecturas_validas
        r_intentos.mappings.return_value.all.return_value = intentos
        r_asist.mappings.return_value.all.return_value = asistencias
        conn.execute.side_effect = [r_cuentas, r_lecturas, r_intentos, r_asist]
        return conn

    int_valido = [(1, 102, 2, 900102, 'registrada', None, 202)]
    asist_base = [
        (201, 101, 900101, c.COMIDA, 191739904, 'biometrico', None),
        (202, 102, 900102, c.COMIDA, 192739904, 'manual', 2),
    ]

    # QA02 con 2 asistencias:
    asist_duplicada_qa02 = asist_base + [(203, 102, 900102, c.COMIDA, 192739904, 'manual', 2)]
    with pytest.raises(c.Abortado, match='Inconsistencia en QA02: 2 asistencias y 1 intervenciones'):
        limpiar.comprobar_propiedad(_conn(int_valido, asist_duplicada_qa02), datos, True)

    # QA02 con 2 intervenciones:
    int_duplicada_qa02 = int_valido + [(2, 102, 2, 900102, 'registrada', None, 202)]
    with pytest.raises(c.Abortado, match='Inconsistencia en QA02: 1 asistencias y 2 intervenciones'):
        limpiar.comprobar_propiedad(_conn(int_duplicada_qa02, asist_base), datos, True)

    # QA01 con 2 asistencias:
    asist_duplicada_qa01 = [
        (201, 101, 900101, c.COMIDA, 191739904, 'biometrico', None),
        (205, 101, 900101, c.COMIDA, 191739904, 'biometrico', None),
        (202, 102, 900102, c.COMIDA, 192739904, 'manual', 2),
    ]
    with pytest.raises(c.Abortado, match='El caso qa01 debe tener exactamente una asistencia propia, encontrados 2'):
        limpiar.comprobar_propiedad(_conn(int_valido, asist_duplicada_qa01), datos, True)


def test_contrastar_casos_interrumpidos_no_silencia_error_sql(tmp_path, monkeypatch):
    import limpiar
    from sqlalchemy.exc import OperationalError

    diario = tmp_path / 'corrida.json'
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    monkeypatch.setattr(c, 'CORRIDA', diario)
    c.cargar_manifiesto_comensales()

    datos = {
        'version': 2,
        'escenario': 'tres_comensales_qa',
        'servidor': 'srv-test',
        'bases': [c.SIM, c.DEMO],
        'inicio': '2026-10-18T10:00:00',
        'fecha_original': '2026-10-15',
        'fecha_destino': None,
        'max_intento_inicial': 0,
        'contrato_sesiones': None,
        'max_sesion_inicial': None,
        'huella_base': {'sha256': 'abc', 'tablas': {}},
        'cuentas': {'cocinera2': 2},
        'comensales': c.resumen_comensales_diario(),
        'casos': c.casos_iniciales_diario(),
    }
    datos['casos']['qa02']['estado'] = 'lectura_pendiente'
    datos['casos']['qa02']['lectura_id'] = 102
    datos['casos']['qa02']['momento_lectura'] = '2026-10-15T11:32:00'
    c.guardar_corrida(datos)
    contenido_original = diario.read_text(encoding='utf-8')

    conn = MagicMock()
    conn.execute.side_effect = OperationalError("SELECT * FROM asistencias", {}, Exception("MySQL server has gone away"))

    # Verifica que el error SQL NO se silencia ni se convierte en ausencia de filas
    with pytest.raises(OperationalError):
        limpiar.contrastar_casos_interrumpidos(conn, datos, guardar_diario=True)

    # El diario no debe haber cambiado
    assert diario.read_text(encoding='utf-8') == contenido_original

    # Con --reconciliar tampoco debe modificar el diario si hay error SQL
    motor = MagicMock()
    motor.begin.return_value.__enter__.return_value = conn
    control = MagicMock()
    control.__enter__.return_value = (motor, {'sha256': 'abc'}, 'srv-test')
    monkeypatch.setattr(c, 'entorno_seguro', Mock(return_value=control))
    monkeypatch.setattr(c, 'comprobar_base', Mock())
    monkeypatch.setattr(sys, 'argv', ['limpiar.py', '--reconciliar'])

    with pytest.raises(OperationalError):
        limpiar.main()

    assert diario.read_text(encoding='utf-8') == contenido_original


def test_comprobar_propiedad_casos_validos_qa02_pendiente_e_identificado(monkeypatch):
    import limpiar

    monkeypatch.setattr(
        c, 'fila_asignacion', lambda _conn, bloquear=False: {'fecha': datetime(2026, 10, 15).date()}
    )
    datos = _diario_multi_base()
    datos['estado'] = 'casos_ejecutados'
    datos['casos']['qa01'].update(
        estado='completado',
        momento_lectura='2026-10-15T11:31:00',
        lectura_id=101,
        asistencia_id=201,
    )
    # 1. QA02 pendiente de identificación (0 asistencias, 0 intervenciones)
    datos['casos']['qa02'].update(
        estado='lectura_creada',
        momento_lectura='2026-10-15T11:32:00',
        lectura_id=102,
        asistencia_id=None,
    )

    filas_actuales = [
        {'id': 10, 'username': 'cocinera1', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 2, 'username': 'cocinera2', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 3, 'username': 'cocinera3', 'rol': 'cocinera', 'usuario_turnos_id': None},
        {'id': 11, 'username': 'jefa', 'rol': 'jefa', 'usuario_turnos_id': None},
    ]
    lecturas_validas = [
        {
            'id': 101,
            'usuario_id': 900101,
            'dispositivo': c.DISPOSITIVO,
            'fecha_hora': datetime(2026, 10, 15, 11, 31),
            'resultado': 'aceptada',
            'motivo': None,
        },
        {
            'id': 102,
            'usuario_id': None,
            'dispositivo': c.DISPOSITIVO,
            'fecha_hora': datetime(2026, 10, 15, 11, 32),
            'resultado': 'rechazada',
            'motivo': 'no_identificado',
        },
    ]

    def _conn(intentos, asistencias):
        conn = MagicMock()
        r_cuentas, r_lecturas, r_intentos, r_asist = (
            MagicMock(), MagicMock(), MagicMock(), MagicMock()
        )
        r_cuentas.mappings.return_value.all.return_value = filas_actuales
        r_lecturas.mappings.return_value.all.return_value = lecturas_validas
        r_intentos.mappings.return_value.all.return_value = intentos
        r_asist.mappings.return_value.all.return_value = asistencias
        conn.execute.side_effect = [r_cuentas, r_lecturas, r_intentos, r_asist]
        return conn

    asist_qa01 = [(201, 101, 900101, c.COMIDA, 191739904, 'biometrico', None)]
    # QA02 pendiente con 0 asistencias y 0 intervenciones: DEBE PASAR
    _, act = limpiar.comprobar_propiedad(_conn([], asist_qa01), datos, True)
    assert act == datos['cuentas']

    # 2. QA02 identificado con 1 asistencia manual y 1 intervención registrada: DEBE PASAR
    datos['casos']['qa02'].update(
        estado='completado',
        asistencia_id=202,
    )
    asist_ambas = asist_qa01 + [(202, 102, 900102, c.COMIDA, 192739904, 'manual', 2)]
    int_qa02 = [(1, 102, 2, 900102, 'registrada', None, 202)]
    _, act2 = limpiar.comprobar_propiedad(_conn(int_qa02, asist_ambas), datos, True)
    assert act2 == datos['cuentas']


def test_reconciliacion_valida_sqlite_en_memoria(tmp_path, monkeypatch):
    import limpiar
    from sqlalchemy import create_engine

    diario = tmp_path / 'corrida.json'
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    monkeypatch.setattr(c, 'CORRIDA', diario)
    c.cargar_manifiesto_comensales()

    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE lecturas_biometricas (
                id INTEGER PRIMARY KEY,
                usuario_id INTEGER,
                dispositivo TEXT NOT NULL,
                fecha_hora TEXT NOT NULL,
                resultado TEXT NOT NULL,
                motivo TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE asistencias (
                id INTEGER PRIMARY KEY,
                lectura_id INTEGER,
                usuario_id INTEGER NOT NULL,
                comida_id INTEGER NOT NULL,
                turno_asignado_id INTEGER NOT NULL,
                metodo TEXT NOT NULL,
                registrado_por_cuenta INTEGER
            )
        """))
        conn.execute(text("""
            CREATE TABLE intervenciones_lectura (
                id INTEGER PRIMARY KEY,
                lectura_id INTEGER NOT NULL,
                cuenta_id INTEGER NOT NULL,
                usuario_id INTEGER NOT NULL,
                resultado TEXT NOT NULL,
                motivo_rechazo TEXT,
                asistencia_id INTEGER
            )
        """))
        conn.execute(text("""
            CREATE TABLE usuarios_sistema (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                rol TEXT NOT NULL,
                usuario_turnos_id INTEGER
            )
        """))
        conn.execute(text("""
            CREATE TABLE turnos_asignados (
                id INTEGER PRIMARY KEY,
                usuario_id INTEGER NOT NULL,
                servicio_id INTEGER,
                area_id INTEGER,
                fecha TEXT NOT NULL,
                estado TEXT,
                es_intercambio INTEGER,
                turno_id INTEGER
            )
        """))

        u1 = c.COMENSALES_QA['qa01']['usuario_id']
        u2 = c.COMENSALES_QA['qa02']['usuario_id']
        u3 = c.COMENSALES_QA['qa03']['usuario_id']
        a1 = c.COMENSALES_QA['qa01']['asignacion_id']
        a2 = c.COMENSALES_QA['qa02']['asignacion_id']
        a3 = c.COMENSALES_QA['qa03']['asignacion_id']

        conn.execute(text("""
            INSERT INTO usuarios_sistema (id, username, rol, usuario_turnos_id) VALUES
            (10, 'cocinera1', 'cocinera', NULL),
            (2, 'cocinera2', 'cocinera', NULL),
            (3, 'cocinera3', 'cocinera', NULL),
            (11, 'jefa', 'jefa', NULL)
        """))
        conn.execute(text(f"""
            INSERT INTO turnos_asignados (id, usuario_id, fecha) VALUES
            ({a1}, {u1}, '2026-10-15'),
            ({a2}, {u2}, '2026-10-15'),
            ({a3}, {u3}, '2026-10-15')
        """))
        conn.execute(text(f"""
            INSERT INTO lecturas_biometricas (id, usuario_id, dispositivo, fecha_hora, resultado, motivo) VALUES
            (101, {u1}, '{c.DISPOSITIVO}', '2026-10-15T11:31:00', 'aceptada', NULL),
            (102, NULL, '{c.DISPOSITIVO}', '2026-10-15T11:32:00', 'rechazada', 'no_identificado')
        """))
        conn.execute(text(f"""
            INSERT INTO asistencias (id, lectura_id, usuario_id, comida_id, turno_asignado_id, metodo, registrado_por_cuenta) VALUES
            (201, 101, {u1}, {c.COMIDA}, {a1}, 'biometrico', NULL),
            (202, 102, {u2}, {c.COMIDA}, {a2}, 'manual', 2)
        """))
        conn.execute(text(f"""
            INSERT INTO intervenciones_lectura (id, lectura_id, cuenta_id, usuario_id, resultado, motivo_rechazo, asistencia_id) VALUES
            (301, 102, 2, {u2}, 'registrada', NULL, 202)
        """))

        datos = _diario_multi_base()
        datos['casos']['qa01'].update(
            estado='lectura_pendiente',
            lectura_id=101,
            momento_lectura='2026-10-15T11:31:00',
        )
        datos['casos']['qa02'].update(
            estado='lectura_pendiente',
            lectura_id=102,
            momento_lectura='2026-10-15T11:32:00',
        )
        c.guardar_corrida(datos)

        cambios = limpiar.contrastar_casos_interrumpidos(conn, datos, guardar_diario=True)
        assert cambios is True
        assert datos['casos']['qa01']['estado'] == 'completado'
        assert datos['casos']['qa01']['asistencia_id'] == 201
        assert datos['casos']['qa02']['estado'] == 'completado'
        assert datos['casos']['qa02']['asistencia_id'] == 202

        monkeypatch.setattr(c, 'filas_asignaciones_corrida', lambda _conn, _d, bloquear=False: {'fecha': datetime(2026, 10, 15).date()})
        _, act = limpiar.comprobar_propiedad(conn, datos, False)
        assert act == datos['cuentas']


def test_fallo_recuperar_filas_mappings_all_propaga_sin_modificar_diario(tmp_path, monkeypatch):
    import limpiar
    from sqlalchemy.exc import OperationalError

    diario = tmp_path / 'corrida.json'
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    monkeypatch.setattr(c, 'CORRIDA', diario)
    c.cargar_manifiesto_comensales()

    datos = _diario_multi_base()
    datos['casos']['qa01'].update(
        estado='lectura_pendiente',
        lectura_id=101,
        momento_lectura='2026-10-15T11:31:00',
    )
    c.guardar_corrida(datos)
    contenido_original = diario.read_text(encoding='utf-8')

    conn = MagicMock()
    r_lectura = MagicMock()
    r_lectura.mappings.return_value.one_or_none.return_value = {
        'id': 101,
        'usuario_id': c.COMENSALES_QA['qa01']['usuario_id'],
        'dispositivo': c.DISPOSITIVO,
        'fecha_hora': datetime(2026, 10, 15, 11, 31),
        'resultado': 'aceptada',
        'motivo': None,
    }
    r_asistencias = MagicMock()
    r_asistencias.mappings.return_value.all.side_effect = OperationalError(
        "SELECT ...", {}, Exception("Error de lectura de cursor")
    )
    conn.execute.side_effect = [r_lectura, r_asistencias]

    with pytest.raises(OperationalError, match="Error de lectura de cursor"):
        limpiar.contrastar_casos_interrumpidos(conn, datos, guardar_diario=True)

    assert diario.read_text(encoding='utf-8') == contenido_original
