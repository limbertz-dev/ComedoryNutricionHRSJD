"""Reloj/flujo QA offline: app real importada sin dotenv, MySQL prohibido."""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest
from sqlalchemy.engine import Engine

import comun as c
import ejecutar_app
import huella
import refechar


@pytest.fixture(autouse=True)
def sin_mysql(monkeypatch):
    monkeypatch.setattr(Engine, 'connect', Mock(side_effect=AssertionError('MySQL prohibido en tests')))
    monkeypatch.setattr(sys, 'dont_write_bytecode', True)
    monkeypatch.setattr(sys, 'path', list(sys.path))
    for nombre, valor in {'DB_NAME': c.SIM, 'DB_NAME_TURNOS': c.DEMO, 'DB_HOST': 'localhost',
                          'DB_PORT': '3306', 'DB_USER': 'qa', 'DB_PASSWORD': '',
                          'ENTORNO': 'desarrollo'}.items():
        monkeypatch.setenv(nombre, valor)


@pytest.fixture
def datos():
    return {'estado': 'iniciada', 'fecha_original': '2026-10-15', 'fecha_destino': None,
            'lectura_id': None, 'reloj': {'lab': '2026-10-15T11:30:00',
                                        'real': '2026-10-20T23:00:00'}}


@pytest.fixture
def reloj_controlado():
    with c.app_sin_dotenv():
        from app.core import reloj
        momento = SimpleNamespace(real=datetime(2026, 10, 20, 23, 0))
        # Cambia la fuente datetime del test, nunca las funciones real/real_utc.
        with patch.object(reloj, 'datetime') as fuente:
            fuente.now.side_effect = lambda tz=None: momento.real.replace(tzinfo=tz)
            yield reloj, momento


def test_reloj_avanza_y_no_toca_seguridad(datos, reloj_controlado, capsys):
    reloj, momento = reloj_controlado
    real, real_utc, antes = reloj.real, reloj.real_utc, reloj.ahora
    with c.app_sin_dotenv():
        from app.logica import autenticacion
        with c.reloj_laboratorio(datos):
            assert reloj.ahora() == datetime(2026, 10, 15, 11, 30)
            momento.real += timedelta(minutes=8, seconds=7, microseconds=123)
            assert reloj.ahora() == datetime(2026, 10, 15, 11, 38, 7, 123)
            assert reloj.hoy().isoformat() == '2026-10-15'
            assert reloj.real is real and reloj.real_utc is real_utc
            assert reloj.real() == momento.real
            assert reloj.real_utc() == momento.real.replace(tzinfo=timezone.utc)
            assert autenticacion.ahora() == momento.real.replace(microsecond=0)
        assert reloj.ahora is antes
    assert 'Reloj de laboratorio: 2026-10-15T11:30:00 (real: 2026-10-20T23:00:00)' in capsys.readouterr().out


def test_reiniciar_proceso_no_reinicia_ventana(datos, reloj_controlado):
    reloj, momento = reloj_controlado
    with c.reloj_laboratorio(datos):
        primero = reloj.ahora()
    momento.real += timedelta(hours=1)
    with c.reloj_laboratorio(datos):
        assert reloj.ahora() == primero + timedelta(hours=1)


def test_dos_procesos_comparten_ancla_persistida(datos, tmp_path):
    diario = tmp_path / 'corrida.json'
    diario.write_text(json.dumps(datos), encoding='utf-8')
    programa = """
import json, sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import comun as c
datos = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
with c.app_sin_dotenv():
    from app.core import reloj
    real, utc = reloj.real, reloj.real_utc
    with patch.object(reloj, 'datetime') as fuente:
        fuente.now.side_effect = lambda tz=None: datetime(2026, 10, 20, 23, 12, 34, tzinfo=tz)
        with c.reloj_laboratorio(datos):
            assert reloj.real is real and reloj.real_utc is utc
            print(json.dumps({'ahora': reloj.ahora().isoformat(), 'hoy': reloj.hoy().isoformat()}))
"""
    resultados = [subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c', programa, str(diario)],
                                cwd=c.CARPETA, capture_output=True, text=True, encoding='utf-8',
                                check=True, timeout=30) for _ in range(2)]
    salidas = [json.loads(r.stdout.splitlines()[-1]) for r in resultados]
    assert salidas[0] == salidas[1] == {'ahora': '2026-10-15T11:42:34', 'hoy': '2026-10-15'}


@pytest.mark.parametrize('valor', ['2026-10-15', '2026-10-15T11:30', '2026-02-30T11:30:00',
                                  '2026-10-15T11:30:00Z', '2026-10-15T11:30:00-04:00'])
def test_argumento_reloj_invalido(valor):
    with pytest.raises(argparse.ArgumentTypeError):
        c.argumento_reloj(valor)


@pytest.mark.parametrize('elegido', [None, '2026-11-02T12:15:10'])
def test_ancla_default_y_cli_crean_diario_con_hora_real(monkeypatch, tmp_path, elegido):
    monkeypatch.setattr(c, 'CORRIDA', tmp_path / 'corrida.json')
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    control = MagicMock()
    motor = MagicMock()
    control.__enter__.return_value = (motor, {'sha256': 'huella'}, 'servidor')
    monkeypatch.setattr(c, 'entorno_seguro', Mock(return_value=control))
    monkeypatch.setattr(c, 'fila_asignacion', Mock(return_value={'fecha': datetime(2026, 10, 15).date()}))
    monkeypatch.setattr(c, 'existe_tabla', Mock(return_value=False))
    monkeypatch.setattr(c, 'contrato_sesiones', Mock(return_value=None))
    conn = motor.connect.return_value.__enter__.return_value
    conn.execute.return_value.mappings.return_value.all.return_value = [
        {'username': n, 'id': i, 'rol': 'cocinera', 'usuario_turnos_id': None}
        for i, n in enumerate(c.CUENTAS, 1)]
    conn.execute.return_value.scalar_one.return_value = 0
    monkeypatch.setattr(sys, 'argv', ['comun.py', '--huella-base'] + (['--reloj', elegido] if elegido else []))
    antes = datetime.now()
    c.main()
    guardado = json.loads(c.CORRIDA.read_text(encoding='utf-8'))
    assert guardado['reloj']['lab'] == (elegido or c.RELOJ_POR_DEFECTO)
    assert antes <= datetime.fromisoformat(guardado['reloj']['real']) <= datetime.now()
    assert datetime.fromisoformat(guardado['inicio']).date() == datetime.now().date()
    assert guardado['estado'] == 'iniciada' and guardado['fecha_destino'] is None


@pytest.mark.parametrize('ancla', [None, {}, {'lab': 'incorrecta', 'real': '2026-10-20T23:00:00'},
                                  {'lab': '2026-10-15T11:30:00Z', 'real': '2026-10-20T23:00:00'}])
def test_sin_ancla_valida_no_se_instala_reloj(datos, reloj_controlado, ancla):
    reloj, _ = reloj_controlado
    antes = reloj.ahora
    datos['reloj'] = ancla
    with pytest.raises(c.Abortado, match='Ancla'):
        with c.reloj_laboratorio(datos):
            pytest.fail('No instalar ancla inválida')
    assert reloj.ahora is antes


@pytest.mark.parametrize('estado,destino,lectura,api,aceptado', [
    ('iniciada', None, None, False, True), ('iniciada', None, None, True, True),
    ('iniciada', '2026-10-15', None, True, False), ('iniciada', None, 4, True, False),
    ('refechada', '2026-10-15', None, False, True), ('refechada', None, None, True, False),
    ('lectura_creada', None, 4, True, True), ('lectura_creada', None, 4, False, False),
    ('lectura_creada', None, None, True, False), ('lectura_pendiente', None, 4, True, False),
    ('refechado_pendiente', '2026-10-15', None, False, False),
    ('limpieza_pendiente', None, 4, True, False), ('limpia', None, None, True, False),
])
def test_estados_flujo(datos, estado, destino, lectura, api, aceptado):
    datos.update(estado=estado, fecha_destino=destino, lectura_id=lectura)
    momento = datetime(2026, 10, 15, 12)
    copia = dict(datos)
    if aceptado:
        assert c.fecha_para_operar(datos, momento, permitir_lectura=api) == momento.date()
    else:
        with pytest.raises(c.Abortado):
            c.fecha_para_operar(datos, momento, permitir_lectura=api)
    assert datos == copia


def test_otra_fecha_requiere_refechar(datos):
    momento = datetime(2026, 10, 16, 12)
    with pytest.raises(c.Abortado, match='refechar'):
        c.fecha_para_operar(datos, momento)
    datos.update(estado='refechada', fecha_destino='2026-10-16')
    assert c.fecha_para_operar(datos, momento) == momento.date()


@pytest.mark.parametrize('modo', ['api', 'admin'])
def test_lanzador_acepta_iniciada_y_aplica_reloj_antes_de_logica(datos, reloj_controlado, monkeypatch, tmp_path, modo):
    reloj, _ = reloj_controlado
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    observado = []

    def logica(*args, **kwargs):
        observado.append(reloj.ahora())

    if modo == 'admin':
        monkeypatch.setattr(ejecutar_app.runpy, 'run_module', logica)
        monkeypatch.setattr(sys, 'argv', list(sys.argv))
    else:
        import uvicorn
        monkeypatch.setattr(uvicorn, 'run', logica)
    ejecutar_app.iniciar(SimpleNamespace(modo=modo, username='cocinera2', port=8001), datos)
    assert observado == [datetime(2026, 10, 15, 11, 30)]
    assert datos['estado'] == 'iniciada'
    assert not (tmp_path / 'api.activa').exists()


@pytest.mark.parametrize('en_curso', [True, False])
def test_lector_iniciado_valida_almuerzo_del_laboratorio(datos, reloj_controlado, monkeypatch, en_curso):
    from app.logica import marcacion
    from app.consultas import derecho, servicio
    _, control = reloj_controlado
    if not en_curso:
        control.real += timedelta(hours=3, minutes=30)
    esperado = datetime(2026, 10, 15, 11, 30) if en_curso else datetime(2026, 10, 15, 15)
    sesion = MagicMock()
    sesion.__enter__.return_value = sesion
    sesion.execute.return_value.scalar_one.return_value = 0
    monkeypatch.setattr(huella, 'Session', Mock(return_value=sesion))
    comida = marcacion.ComidaEnCurso(c.COMIDA, 'Almuerzo', datetime(2026, 10, 15).date())
    resolver = Mock(return_value=comida if en_curso else None)
    monkeypatch.setattr(marcacion, 'resolver_comida_en_curso', resolver)
    monkeypatch.setattr(derecho, 'buscar_derecho', Mock(return_value=SimpleNamespace(turno_asignado_id=c.ASIGNACION)))
    monkeypatch.setattr(marcacion, 'ya_comio', Mock(return_value=False))
    monkeypatch.setattr(servicio, 'evaluar_servicio', Mock(return_value=SimpleNamespace(motivo=None)))
    registrar = Mock(return_value=marcacion.Resultado(False, 'no_identificado', 'Huella no reconocida',
                                                     'Prueba', lectura_id=4))
    monkeypatch.setattr(marcacion, 'registrar_marcacion', registrar)
    monkeypatch.setattr(huella.event, 'listen', Mock())
    diario = Mock()
    monkeypatch.setattr(c, 'guardar_corrida', diario)
    if en_curso:
        huella.leer(Mock(), datos)
        assert registrar.call_count == 1
        assert registrar.call_args.kwargs['momento'] == datetime(2026, 10, 15, 11, 30)
        assert datos['estado'] == 'lectura_creada' and datos['fecha_destino'] is None
    else:
        with pytest.raises(c.Abortado, match='limpiar y abrir una corrida nueva con otra ancla'):
            huella.leer(Mock(), datos)
        registrar.assert_not_called()
        diario.assert_not_called()
    assert resolver.call_args.args[1] == esperado


def test_refechar_usa_dia_laboratorio_por_omision(datos, reloj_controlado, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    monkeypatch.setattr(c, 'fila_asignacion', Mock(return_value={'fecha': datetime(2026, 10, 14).date()}))
    datos['fecha_original'] = '2026-10-14'
    cambiar = Mock()
    monkeypatch.setattr(c, 'cambiar_fecha', cambiar)
    refechar.refechar(MagicMock(), datos, SimpleNamespace(fecha=None, dry_run=True))
    assert '2026-10-14 -> 2026-10-15' in capsys.readouterr().out
    cambiar.assert_not_called()
