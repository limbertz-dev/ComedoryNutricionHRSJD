"""Errores de caso distintos de conectividad y arranque sin limpiar ni resetear."""
from datetime import datetime
from unittest.mock import Mock
import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from sqlalchemy.exc import OperationalError

import comun as c
import laboratorio as lab
import arrancar_qa as arranque
from test_perfiles_lectura import circuito


def test_estado_informa_reserva_incorrecta_sin_perder_conexion_ni_alterar_diario(circuito, monkeypatch):
    import enrolamiento
    motor, _ = circuito
    previo = c.CORRIDA.read_bytes()
    control = lab.Laboratorio(motor, 'srv', {})
    datos = c.leer_corrida('srv')
    datos.update(fecha_original='2026-10-15', reloj={'lab':'2026-10-15T12:00:00','real':'2026-10-15T12:00:00','modo':'fijo'})
    control.diario = lambda: datos
    monkeypatch.setattr(enrolamiento, 'leer_registro', lambda: {'registros': {}})
    monkeypatch.setattr(c, 'validar_cuentas_limpieza', lambda *_: {'cocinera2':2})
    reserva = Mock(side_effect=c.Abortado('QA03 no es una reserva vacía'))
    monkeypatch.setattr(lab.verificar, 'verificar_reserva_qa03', reserva)
    estado = control.estado()
    assert estado['servicio'] == 'Almuerzo'
    assert estado['reserva']['resultado'] == 'REVISAR'
    assert estado['advertencias'] and 'QA 03' in estado['advertencias'][0]
    assert estado['casos']['qa02']['comprobado'] is False
    assert c.CORRIDA.read_bytes() == previo
    reserva.side_effect = OperationalError('SELECT', {}, Exception('cursor cerrado'))
    with pytest.raises(OperationalError):
        control.estado()


def test_http_distingue_salud_caso_invalido_y_error_sql_sin_filtrar_detalles():
    control = lab.Laboratorio(Mock(), 'srv', {})
    control.estado = Mock(side_effect=c.Abortado('La corrida no está lista.'))
    servidor = ThreadingHTTPServer(('127.0.0.1', 0), lab.crear_handler(control))
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    base = f'http://127.0.0.1:{servidor.server_port}'
    try:
        assert json.load(urlopen(base + '/salud'))['servicio'] == 'laboratorio-qa'
        solicitud = Request(base + '/estado', headers={'X-QA-Control':control.token})
        with pytest.raises(HTTPError) as error:
            urlopen(solicitud)
        assert error.value.code == 409
        assert json.load(error.value)['error'] == 'La corrida no está lista.'
        control.estado.side_effect = OperationalError('SQL-no-exponer', {}, Exception('detalle-no-exponer'))
        with pytest.raises(HTTPError) as error:
            urlopen(solicitud)
        assert error.value.code == 503
        texto = error.value.read().decode()
        assert 'MySQL' in texto and 'SQL-no-exponer' not in texto and 'detalle-no-exponer' not in texto
    finally:
        servidor.shutdown()
        servidor.server_close()
        hilo.join(timeout=3)


def test_arranque_reutiliza_servicios_sin_lanzar_procesos_ni_resetear(monkeypatch):
    monkeypatch.setenv('ENTORNO','desarrollo')
    monkeypatch.setattr(arranque.subprocess, 'check_output', lambda *_args, **_kw: 'qa\n')
    monkeypatch.setattr(arranque.shutil, 'which', lambda _: 'node')
    monkeypatch.setattr(arranque, 'ocupado', lambda _: True)
    monkeypatch.setattr(arranque, 'estado_servicio', lambda _: True)
    lanzar = Mock(side_effect=AssertionError('No iniciar otro proceso'))
    monkeypatch.setattr(arranque.subprocess, 'Popen', lanzar)
    arranque.main()
    lanzar.assert_not_called()
    arranque.detener_propio('laboratorio', None)


def test_arranque_rechaza_api_ajena_y_no_detiene_procesos(monkeypatch):
    monkeypatch.setenv('ENTORNO','desarrollo')
    monkeypatch.setattr(arranque.subprocess, 'check_output', lambda *_args, **_kw: 'qa\n')
    monkeypatch.setattr(arranque.shutil, 'which', lambda _: 'node')
    monkeypatch.setattr(arranque, 'ocupado', lambda puerto: puerto in (3306,8001))
    with pytest.raises(c.Abortado, match='API anterior'):
        arranque.main()
    assert not arranque.salud_api({'estado':'ok','entorno':'produccion','base_datos':c.SIM,'base_turnos':c.DEMO})


def test_arranque_fallido_cierra_solo_los_procesos_que_acaba_de_crear(monkeypatch, tmp_path):
    monkeypatch.setenv('ENTORNO','desarrollo')
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    monkeypatch.setattr(arranque.subprocess, 'check_output', lambda *_args, **_kw: 'qa\n')
    monkeypatch.setattr(arranque.shutil, 'which', lambda _: 'node')
    monkeypatch.setattr(arranque, 'ocupado', lambda puerto: puerto == 3306)
    proceso_lab, proceso_front = Mock(), Mock()
    monkeypatch.setattr(arranque.subprocess, 'Popen', Mock(side_effect=[proceso_lab,proceso_front]))
    esperar = Mock(side_effect=[None,None,c.Abortado('No inició frontend')])
    monkeypatch.setattr(arranque, 'esperar', esperar)
    detener = Mock()
    monkeypatch.setattr(arranque, 'detener_propio', detener)
    with pytest.raises(c.Abortado, match='No inició frontend'):
        arranque.main()
    assert [(llamada.args[0],llamada.args[1]) for llamada in detener.call_args_list] == [
        ('frontend',proceso_front),('laboratorio',proceso_lab)]
