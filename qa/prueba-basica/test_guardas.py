"""Pruebas offline: sin app, sin credenciales y sin conexiones MySQL."""
import json
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
                'revision_alembic': 'e1a7c3b9d5f2',
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
           'base_turnos': c.DEMO, 'revision_alembic': 'e1a7c3b9d5f2'}),
    (200, {'estado': 'ok', 'entorno': 'desarrollo', 'base_datos': c.SIM,
           'base_turnos': c.PROTEGIDA, 'revision_alembic': 'e1a7c3b9d5f2'}),
    (200, {'estado': 'ok', 'entorno': 'desarrollo', 'base_datos': c.SIM,
           'base_turnos': c.DEMO, 'revision_alembic': 'otra'}),
    (200, {'estado': 'ok', 'entorno': 'produccion', 'base_datos': c.SIM,
           'base_turnos': c.DEMO, 'revision_alembic': 'e1a7c3b9d5f2'}),
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
