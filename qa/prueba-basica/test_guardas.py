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


@pytest.mark.parametrize('campo_secreto', sorted(c.CAMPOS_SECRETOS))
def test_diario_rechaza_claves_y_tokens(monkeypatch, tmp_path, campo_secreto):
    monkeypatch.setattr(c, 'CORRIDA', tmp_path / 'corrida.json')
    with pytest.raises(c.Abortado, match='claves o tokens'):
        c.guardar_corrida({'estado': 'iniciada', 'anidado': [{campo_secreto: 'valor-secreto'}]})
    assert not c.CORRIDA.exists()


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


def _simulador_http_cuentas(fallo_en=None):
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
            if cuerpo['password'].startswith('TEMP-'):
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
            if fallo_en == (cuenta, 'login_nueva'):
                return 401, {'motivo': 'Mensaje arbitrario con SECRETO-SERVIDOR-99'}
            return 200, {
                'access': f'JWT-ACCESS-{cuenta}',
                'refresh': f'JWT-REFRESH-{cuenta}',
                'rol': rol,
                'debe_cambiar': False,
            }
        if (metodo, ruta) == ('POST', '/auth/cambio-password'):
            cuenta = token.removeprefix('JWT-TEMP-')
            rol = c.rol_cuenta(cuenta)
            if fallo_en == (cuenta, 'cambio_password'):
                return 422, {
                    'motivo': 'password_rechazada',
                    'detail': 'La clave contiene SECRETO-SERVIDOR-99',
                }
            return 200, {
                'access': f'JWT-CAMBIO-{cuenta}',
                'refresh': f'JWT-REFRESH-{cuenta}',
                'rol': rol,
                'debe_cambiar': False,
            }
        cuenta = token.removeprefix('JWT-ACCESS-').removeprefix('JWT-CAMBIO-')
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


def _preparar_diario_base(tmp_path):
    diario = tmp_path / 'corrida.json'
    datos = {
        'version': 1,
        'servidor': 'servidor-qa',
        'bases': [c.SIM, c.DEMO],
        'usuario_id': c.USUARIO,
        'asignacion_id': c.ASIGNACION,
        'inicio': '2026-10-16T11:00:00',
        'fecha_original': '2026-10-15',
        'fecha_destino': None,
        'cuentas': {'cocinera2': 2, 'cocinera3': 3},
        'estado': 'iniciada',
        'lectura_id': None,
    }
    diario.write_text(json.dumps(datos), encoding='utf-8')
    return diario


def test_cuentas_py_pasa_las_4_cuentas_y_no_guarda_claves_ni_tokens(monkeypatch, tmp_path, capsys):
    import cuentas

    diario = _preparar_diario_base(tmp_path)
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    monkeypatch.setattr(c, 'CORRIDA', diario)
    solicitar, _ = _simulador_http_cuentas()
    monkeypatch.setattr(cuentas, 'cliente_http', lambda base: solicitar)

    claves_ingresadas = iter([
        'TEMP-secreta-c1', 'NUEVA-secreta-c1',
        'TEMP-secreta-c2', 'NUEVA-secreta-c2',
        'TEMP-secreta-c3', 'NUEVA-secreta-c3',
        'TEMP-secreta-jefa', 'NUEVA-secreta-jefa',
    ])
    monkeypatch.setattr(cuentas.getpass, 'getpass', lambda prompt: next(claves_ingresadas))

    cuentas.main([])
    salida = capsys.readouterr()
    assert '| Cuenta | Control | Esperado | Obtenido | PASA/FALLA |' in salida.out
    texto_diario = diario.read_text(encoding='utf-8')
    guardado = json.loads(texto_diario)

    for cuenta in ('cocinera1', 'cocinera2', 'cocinera3'):
        assert guardado['verificacion_cuentas'][cuenta]['resultado'] == 'PASA'
        assert len(guardado['verificacion_cuentas'][cuenta]['controles']) == 8
    assert guardado['verificacion_cuentas']['jefa']['resultado'] == 'PASA'
    assert len(guardado['verificacion_cuentas']['jefa']['controles']) == 6

    # Ninguna clave, token ni detalle arbitrario puede aparecer en corrida.json ni en la consola.
    for secreto in (
        'TEMP-secreta', 'NUEVA-secreta', 'JWT-TEMP-', 'JWT-ACCESS-', 'JWT-CAMBIO-',
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
    ('jefa', 'login_temporal'),
    ('jefa', 'cambio_password'),
    ('jefa', 'login_nueva'),
])
def test_cuentas_py_detecta_falla_sin_reintentar_credenciales_y_sale_con_error(
    monkeypatch, tmp_path, capsys, fallo
):
    import cuentas

    diario = _preparar_diario_base(tmp_path)
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    monkeypatch.setattr(c, 'CORRIDA', diario)
    cuenta_fallida, etapa = fallo
    solicitar, llamadas = _simulador_http_cuentas(fallo_en=fallo)
    monkeypatch.setattr(cuentas, 'cliente_http', lambda base: solicitar)
    claves = iter([f'TEMP-{cuenta_fallida}', f'NUEVA-{cuenta_fallida}'])
    monkeypatch.setattr(cuentas.getpass, 'getpass', lambda prompt: next(claves))

    with pytest.raises(SystemExit) as exc:
        c.ejecutar(lambda: cuentas.main(['--solo', cuenta_fallida]))
    assert exc.value.code != 0
    salida = capsys.readouterr()
    assert 'FALLA' in salida.out

    # Si falla el login temporal o el cambio de clave, no debe enviar otro POST /auth/login.
    logins = [ll for ll in llamadas if (ll[0], ll[1]) == ('POST', '/auth/login')]
    if etapa in ('login_temporal', 'cambio_password'):
        assert len(logins) == 1

    texto_diario = diario.read_text(encoding='utf-8')
    guardado = json.loads(texto_diario)
    resumen = guardado['verificacion_cuentas'][cuenta_fallida]
    assert resumen['resultado'] == 'FALLA'
    assert any(ctrl['resultado'] == 'FALLA' for ctrl in resumen['controles'])
    for prohibido in (
        f'TEMP-{cuenta_fallida}', f'NUEVA-{cuenta_fallida}', 'JWT-', 'SECRETO-SERVIDOR-99'
    ):
        assert prohibido not in texto_diario
        assert prohibido not in salida.out
        assert prohibido not in salida.err


def test_cuentas_py_solo_conserva_resultados_previos_de_otras_cuentas(monkeypatch, tmp_path):
    import cuentas

    diario = _preparar_diario_base(tmp_path)
    datos_iniciales = json.loads(diario.read_text(encoding='utf-8'))
    datos_iniciales['verificacion_cuentas'] = {
        'cocinera1': {'rol': 'cocinera', 'resultado': 'PASA', 'controles': [{'control': 'previo1', 'resultado': 'PASA'}]},
        'cocinera2': {'rol': 'cocinera', 'resultado': 'FALLA', 'controles': [{'control': 'previo2', 'resultado': 'FALLA'}]},
        'cocinera3': {'rol': 'cocinera', 'resultado': 'PASA', 'controles': [{'control': 'previo3', 'resultado': 'PASA'}]},
        'jefa': {'rol': 'jefa', 'resultado': 'PASA', 'controles': [{'control': 'previo4', 'resultado': 'PASA'}]},
    }
    diario.write_text(json.dumps(datos_iniciales), encoding='utf-8')

    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    monkeypatch.setattr(c, 'CORRIDA', diario)
    solicitar, llamadas = _simulador_http_cuentas()
    monkeypatch.setattr(cuentas, 'cliente_http', lambda base: solicitar)
    claves = iter(['TEMP-cocinera2', 'NUEVA-cocinera2'])
    monkeypatch.setattr(cuentas.getpass, 'getpass', lambda prompt: next(claves))

    cuentas.main(['--solo', 'cocinera2'])
    guardado = json.loads(diario.read_text(encoding='utf-8'))
    verif = guardado['verificacion_cuentas']

    assert verif['cocinera2']['resultado'] == 'PASA'
    assert len(verif['cocinera2']['controles']) == 8
    assert verif['cocinera1'] == datos_iniciales['verificacion_cuentas']['cocinera1']
    assert verif['cocinera3'] == datos_iniciales['verificacion_cuentas']['cocinera3']
    assert verif['jefa'] == datos_iniciales['verificacion_cuentas']['jefa']
    usuarios_autenticados = [
        ll[2]['username'] for ll in llamadas if (ll[0], ll[1]) == ('POST', '/auth/login')
    ]
    assert usuarios_autenticados == ['cocinera2', 'cocinera2']


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
    claves = iter(['TEMP-jefa', 'NUEVA-jefa'])
    monkeypatch.setattr(cuentas.getpass, 'getpass', lambda prompt: next(claves))

    with pytest.raises(SystemExit) as exc:
        c.ejecutar(lambda: cuentas.main(['--solo', 'jefa']))
    assert exc.value.code != 0

    salida = capsys.readouterr()
    texto_diario = diario.read_text(encoding='utf-8')
    guardado = json.loads(texto_diario)
    primer_control = guardado['verificacion_cuentas']['jefa']['controles'][0]
    assert primer_control['obtenido'] == '401'
    assert motivo_desconocido not in texto_diario
    assert motivo_desconocido not in salida.out
    assert motivo_desconocido not in salida.err
