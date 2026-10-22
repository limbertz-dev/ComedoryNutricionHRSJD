"""Controles offline del laboratorio: reloj, autorización HTTP y procesos propios."""
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
import json
from types import SimpleNamespace
import threading
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import comun as c
import laboratorio as lab


def test_reloj_fijo_y_continuo_preservan_reloj_de_seguridad(monkeypatch):
    datos = {'reloj': {'lab': '2026-10-15T11:30:00', 'real': '2026-10-19T02:00:00', 'modo': 'fijo'}}
    assert c.momento_laboratorio(datos, datetime(2026, 10, 19, 3)) == datetime(2026, 10, 15, 11, 30)
    datos['reloj']['modo'] = 'continuo'
    assert c.momento_laboratorio(datos, datetime(2026, 10, 19, 3)) == datetime(2026, 10, 15, 12, 30)
    with c.app_sin_dotenv():
        from app.core import reloj
        real, real_utc = reloj.real, reloj.real_utc
        datos['reloj']['modo'] = 'fijo'
        with c.reloj_laboratorio(datos):
            assert reloj.ahora() == datetime(2026, 10, 15, 11, 30)
            assert reloj.real is real and reloj.real_utc is real_utc
        assert reloj.real is real and reloj.real_utc is real_utc


def test_api_interactiva_lee_cambios_atomicos_sin_reiniciar_auth(monkeypatch):
    datos = {'inicio': 'misma-corrida', 'reloj': {'lab': '2026-10-15T11:30:00', 'real': '2026-10-19T02:00:00', 'modo': 'fijo'}}
    actual = {**datos, 'reloj': {**datos['reloj'], 'lab': '2026-10-15T15:00:00'}}
    monkeypatch.setattr(c, 'leer_corrida_local', lambda: actual)
    with c.app_sin_dotenv():
        from app.core import reloj
        with c.reloj_laboratorio(datos, interactivo=True):
            assert reloj.ahora() == datetime(2026, 10, 15, 15)
            actual['reloj']['lab'] = '2026-10-15T10:59:59'
            assert reloj.ahora() == datetime(2026, 10, 15, 10, 59, 59)
            actual['inicio'] = 'otra-corrida'
            with pytest.raises(c.Abortado, match='corrida cambió'):
                reloj.ahora()


def test_detener_api_solo_proceso_propio_y_sin_terminacion_forzada(tmp_path, monkeypatch):
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    control = lab.Laboratorio(Mock(), 'srv', {})
    control.detener_api()
    proceso = Mock()
    proceso.poll.return_value = None
    proceso.returncode = 0
    control.api = proceso
    control.detener_api()
    proceso.stdin.write.assert_called_once_with('detener\n')
    proceso.wait.assert_called_once_with(timeout=20)
    proceso.terminate.assert_not_called()
    proceso.kill.assert_not_called()
    assert control.api is None


def test_cierre_fallido_conserva_marca_y_aborta(tmp_path, monkeypatch):
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    (tmp_path / 'api.activa').touch()
    control = lab.Laboratorio(Mock(), 'srv', {})
    control.api = Mock()
    control.api.poll.return_value = 1
    control.api.returncode = 1
    with pytest.raises(c.Abortado, match='cerró con error'):
        control.detener_api()
    assert (tmp_path / 'api.activa').exists()


@pytest.mark.parametrize('cuerpo', [
    {}, {'momento': '2026-10-15'}, {'momento': '2026-10-15T11:30:00Z'},
    {'momento': '2026-10-15T11:30:00', 'modo': 'inventado'},
])
def test_horario_invalido_no_se_acepta(cuerpo):
    with pytest.raises(c.Abortado):
        lab.validar_horario(cuerpo)


def test_no_aprueba_caso_sin_resultado_real_ni_revision_visual():
    control = lab.Laboratorio(Mock(), 'srv', {})
    control.estado = Mock(return_value={'casos': {'qa01': {'comprobado': False}}})
    with pytest.raises(c.Abortado, match='completar'):
        control.revisar({'caso': 'qa01', 'resultado': 'aprobado', 'revisado': True})
    control.estado.return_value['casos']['qa01']['comprobado'] = True
    with pytest.raises(c.Abortado, match='revisaste'):
        control.revisar({'caso': 'qa01', 'resultado': 'aprobado', 'revisado': False})


def test_nuevo_ensayo_exige_confirmacion_y_no_resetea_cuentas(monkeypatch, tmp_path):
    control = lab.Laboratorio(Mock(), 'srv', {})
    control.diario = Mock(return_value={'fecha_original': '2026-10-15'})
    control.estado = Mock(return_value={'casos': {'qa02': {'estado': 'Sin simular'}}})
    control.detener_api = Mock()
    control.ejecutar_script = Mock()
    control.cambiar_horario = Mock()
    control.iniciar_api = Mock()
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    monkeypatch.setattr(c, 'CORRIDA', tmp_path / 'corrida.json')
    c.CORRIDA.write_text('{"evidencia":"previa"}', encoding='utf-8')
    cuerpo = {'momento': '2026-10-15T11:30:00', 'modo': 'fijo'}
    with pytest.raises(c.Abortado, match='Confirma'):
        control.nuevo_ensayo(cuerpo)
    control.detener_api.assert_not_called()
    control.nuevo_ensayo({**cuerpo, 'confirmar': True})
    scripts = [llamada.args[0] for llamada in control.ejecutar_script.call_args_list]
    assert scripts == ['policia_qa.py', 'limpiar.py', 'limpiar.py', 'comun.py', 'comun.py', 'preparar_servicios.py']
    assert '--conservar-cuentas-de' in control.ejecutar_script.call_args_list[-2].args
    archivo = next((tmp_path / 'evidencias').glob('*-ensayo-laboratorio.json'))
    assert archivo.read_text(encoding='utf-8') == '{"evidencia":"previa"}'
    control.iniciar_api.assert_called_once()


@pytest.mark.parametrize('comida', [1, 2, 3, 4])
def test_casos_y_validacion_admiten_cuatro_comidas(comida):
    import test_guardas as t
    datos = t._diario_multi_base()
    datos['comida_ensayo'] = comida
    datos['casos'] = c.casos_iniciales_diario(comida)
    c.validar_casos_diario(datos)
    assert c.comida_corrida(datos) == comida
    assert all(info['comida_id'] == comida for info in datos['casos'].values())
    assert lab.validar_comida({'comida_id': comida}) == comida


@pytest.mark.parametrize('comida', [True, 0, 5, '2', None])
def test_comida_invalida_no_limpia_ni_cambia_el_ensayo(comida):
    control = lab.Laboratorio(Mock(), 'srv', {})
    control.detener_api = Mock()
    with pytest.raises(c.Abortado, match='Elige'):
        control.nuevo_ensayo({'momento': '2026-10-15T12:00:00', 'comida_id': comida, 'confirmar': True})
    control.detener_api.assert_not_called()


def test_preparacion_cuatro_comidas_sqlite_no_altera_turnos_ajenos(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, event, text
    import preparar_servicios
    import test_guardas as t
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    monkeypatch.setattr(c, 'CORRIDA', tmp_path / 'corrida.json')
    datos = t._diario_multi_base()
    motor = create_engine('sqlite:///:memory:')

    @event.listens_for(motor, 'before_cursor_execute', retval=True)
    def bloqueo_sqlite(_conn, _cursor, sentencia, parametros, _contexto, _many):
        return sentencia.replace(' FOR UPDATE', ''), parametros

    with motor.begin() as conn:
        conn.execute(text(f"ATTACH DATABASE ':memory:' AS `{c.DEMO}`"))
        conn.execute(text(f'CREATE TABLE `{c.DEMO}`.turnos (id INTEGER PRIMARY KEY, nombre_turno TEXT, hora_inicio TEXT, hora_fin TEXT, duracion_horas INTEGER, categoria_id INTEGER)'))
        conn.execute(text(f'CREATE TABLE `{c.DEMO}`.turno_comida (id INTEGER PRIMARY KEY, turno_id INTEGER, comida_id INTEGER, dia_relativo INTEGER)'))
        conn.execute(text(f'CREATE TABLE `{c.DEMO}`.turnos_asignados (id INTEGER PRIMARY KEY,usuario_id INTEGER,fecha TEXT,turno_id INTEGER)'))
        conn.execute(text(f'CREATE TABLE `{c.DEMO}`.comidas (id INTEGER PRIMARY KEY,codigo TEXT,estado INTEGER)'))
        conn.execute(text(f"INSERT INTO `{c.DEMO}`.turnos VALUES (9001,'historico','07:00:00','19:00:00',12,9001)"))
        conn.execute(text(f'INSERT INTO `{c.DEMO}`.turno_comida VALUES (9001,9001,2,0)'))
        conn.execute(text(f"INSERT INTO `{c.DEMO}`.turnos_asignados VALUES (91739904,900001,'2026-10-15',9001)"))
        for spec in c.COMENSALES_QA.values():
            conn.execute(text(f'INSERT INTO `{c.DEMO}`.turnos_asignados VALUES (:id,:uid,:fecha,9001)'),
                         {'id': spec['asignacion_id'], 'uid': spec['usuario_id'], 'fecha': '2026-10-15'})
        for cid, comida in c.COMIDAS_LABORATORIO.items():
            conn.execute(text(f'INSERT INTO `{c.DEMO}`.comidas VALUES (:id,:codigo,1)'), {'id': cid, 'codigo': comida['codigo']})
        with c.app_sin_dotenv():
            from app.consultas import derecho
            por_uid = {spec['usuario_id']: spec['asignacion_id'] for spec in c.COMENSALES_QA.values()}
            buscar = Mock(side_effect=lambda _s, uid, _cid, _fecha: SimpleNamespace(turno_asignado_id=por_uid[uid]))
            monkeypatch.setattr(derecho, 'buscar_derecho', buscar)
            preparar_servicios.preparar(conn, datos)
            assert buscar.call_count == 12
            preparar_servicios.preparar(conn, datos)
        assert conn.execute(text(f'SELECT COUNT(*) FROM `{c.DEMO}`.turnos WHERE id=:id'), {'id': c.TURNO_LABORATORIO}).scalar_one() == 1
        assert conn.execute(text(f'SELECT COUNT(*) FROM `{c.DEMO}`.turno_comida WHERE turno_id=:id'), {'id': c.TURNO_LABORATORIO}).scalar_one() == 4
        assert conn.execute(text(f'SELECT turno_id FROM `{c.DEMO}`.turnos_asignados WHERE usuario_id=900001')).scalar_one() == 9001
        c.restaurar_turno_laboratorio(conn, datos)
        assert conn.execute(text(f'SELECT COUNT(*) FROM `{c.DEMO}`.turnos_asignados WHERE turno_id=9001')).scalar_one() == 4
        conn.execute(text(f"UPDATE `{c.DEMO}`.turnos SET nombre_turno='ajeno' WHERE id=:id"), {'id': c.TURNO_LABORATORIO})
        with pytest.raises(c.Abortado, match='Colisión'):
            preparar_servicios.preparar(conn, datos)


def test_cierre_fallido_conserva_falla_y_exige_propiedad_por_lectura():
    import copy
    import limpiar_fallido
    import test_guardas as t
    datos = t._diario_multi_base()
    datos['revision_operador'] = {'qa02': {'resultado': 'rechazado'}}
    datos['casos']['qa01'].update(estado='completado', lectura_id=101, asistencia_id=201, momento_lectura='2026-10-15T12:00:00')
    datos['casos']['qa02'].update(estado='lectura_creada', lectura_id=102, momento_lectura='2026-10-15T12:01:00')
    lecturas = [
        {'id': 101, 'usuario_id': 900101, 'dispositivo': c.DISPOSITIVO, 'fecha_hora': datetime(2026,10,15,12), 'resultado': 'aceptada', 'motivo': None},
        {'id': 102, 'usuario_id': None, 'dispositivo': c.DISPOSITIVO, 'fecha_hora': datetime(2026,10,15,12,1), 'resultado': 'rechazada', 'motivo': 'no_identificado'},
    ]
    asistencias = [
        {'id': 201, 'lectura_id': 101, 'usuario_id': 900101, 'comida_id': 2, 'fecha_comida': datetime(2026,10,15).date(), 'turno_asignado_id': 191739904, 'metodo': 'biometrico', 'registrado_por_cuenta': None},
        {'id': 202, 'lectura_id': 102, 'usuario_id': 900001, 'comida_id': 2, 'fecha_comida': datetime(2026,10,15).date(), 'turno_asignado_id': 91739904, 'metodo': 'manual', 'registrado_por_cuenta': 10},
    ]
    intervenciones = [{'id': 301, 'lectura_id': 102, 'usuario_id': 900001, 'cuenta_id': 10, 'asistencia_id': 202, 'resultado': 'registrada', 'motivo_rechazo': None}]
    previo = copy.deepcopy(datos)
    limpiar_fallido.validar_filas(datos, lecturas, asistencias, intervenciones, datos['cuentas'])
    assert datos == previo and datos['revision_operador']['qa02']['resultado'] == 'rechazado'
    for campo, valor in [('usuario_id', 777), ('cuenta_id', 999), ('asistencia_id', 999), ('lectura_id', 999)]:
        ajenas = copy.deepcopy(intervenciones)
        ajenas[0][campo] = valor
        with pytest.raises(c.Abortado):
            limpiar_fallido.validar_filas(datos, lecturas, asistencias, ajenas, datos['cuentas'])
    ajenas = copy.deepcopy(lecturas)
    ajenas[1]['dispositivo'] = 'lector-ajeno'
    with pytest.raises(c.Abortado):
        limpiar_fallido.validar_filas(datos, ajenas, asistencias, intervenciones, datos['cuentas'])
    with pytest.raises(c.Abortado):
        limpiar_fallido.validar_filas(datos, lecturas, asistencias, intervenciones + intervenciones, datos['cuentas'])


def test_http_rechaza_origen_ajeno_token_ausente_y_rutas_arbitrarias():
    control = lab.Laboratorio(Mock(), 'srv', {})
    control.estado = Mock(return_value={'prueba': 'solo QA'})
    control.simular = Mock()
    servidor = ThreadingHTTPServer(('127.0.0.1', 0), lab.crear_handler(control))
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    base = f'http://127.0.0.1:{servidor.server_port}'
    try:
        with urlopen(base) as respuesta:
            assert "frame-ancestors http://127.0.0.1:5173 http://localhost:5173" in respuesta.headers['Content-Security-Policy']
            html = respuesta.read().decode('utf-8')
        assert control.token in html and '__TOKEN_QA__' not in html
        for headers in ({}, {'X-QA-Control': control.token, 'Origin': 'https://ajeno.example'}):
            with pytest.raises(HTTPError) as error:
                urlopen(Request(base + '/simular', data=b'{"caso":"qa01"}', headers=headers))
            assert error.value.code == 403
        control.simular.assert_not_called()
        with urlopen(Request(base + '/estado', headers={'X-QA-Control': control.token})) as respuesta:
            assert json.load(respuesta) == {'prueba': 'solo QA'}
        with pytest.raises(HTTPError) as error:
            urlopen(base + '/../../comun.py')
        assert error.value.code == 404
    finally:
        servidor.shutdown()
        servidor.server_close()
        hilo.join(timeout=3)


# --- caso Policía ---------------------------------------------------------------


def _control_policia(vigente, salida=''):
    control = lab.Laboratorio(Mock(), 'srv', {})
    control.estado = Mock(return_value={'servicio_elegido_vigente': vigente})

    def ejecutar(archivo, *argumentos):
        control.ultima_salida = salida
    control.ejecutar_script = Mock(side_effect=ejecutar)
    return control


def test_policia_fuera_de_horario_no_ejecuta_nada():
    control = _control_policia(False)
    with pytest.raises(c.Abortado, match='Fuera de horario'):
        control.simular({'caso': 'policia'})
    control.ejecutar_script.assert_not_called()


def test_policia_usa_el_lector_y_lee_la_respuesta_entre_las_huellas():
    salida = ('bd_proyecto_backend antes: x (36 tablas)\n'
              '{"valido": true, "comida": "Cena", "detalle": "Ración habilitada · 2 de policía en esta comida"}\n'
              'bd_proyecto_backend después: x (36 tablas)\n')
    control = _control_policia(True, salida)
    control.simular({'caso': 'policia'})
    control.ejecutar_script.assert_called_once_with('policia_qa.py', '--leer')
    assert control.ultima_accion == 'Policía registrado en Cena. Ración habilitada · 2 de policía en esta comida.'


def test_policia_sin_racion_lo_dice():
    control = _control_policia(True, '{"valido": false, "detalle": "No hay un tiempo de comida vigente"}\n')
    control.simular({'caso': 'policia'})
    assert control.ultima_accion.startswith('La lectura del policía no dio ración')


def test_caso_desconocido_nombra_las_opciones():
    control = _control_policia(True)
    with pytest.raises(c.Abortado, match='Policía'):
        control.simular({'caso': 'qa09'})
