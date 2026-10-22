"""SQL real offline para diario concurrente; las carreras MySQL se prueban con Playwright."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

import comun as c
import concurrencia as cc
import enrolamiento
from test_perfiles_lectura import circuito  # fixture aislada con modelos ORM reales


@pytest.fixture
def entorno(circuito, monkeypatch):
    motor, momento = circuito
    with c.app_sin_dotenv():
        from app.core import reloj
        monkeypatch.setattr(reloj, 'ahora', lambda: momento.valor)
        cc._solicitudes.clear()
        referencia = enrolamiento.registrar(900101, 2, str(uuid4()))['referencia']
        yield motor, referencia


def leer(motor, referencia, clave=None, desconocida=False):
    return cc.procesar(motor, 'srv', {}, 2, referencia, desconocida, clave or str(uuid4()))


def test_reenvios_concurrentes_del_mismo_contacto_crean_una_sola_fila(entorno):
    motor, referencia = entorno
    clave = str(uuid4())
    with ThreadPoolExecutor(max_workers=6) as hilos:
        resultados = list(hilos.map(lambda _: leer(motor, referencia, clave), range(6)))
    assert all(r == resultados[0] for r in resultados)
    with motor.connect() as conn:
        assert conn.scalar(text('SELECT COUNT(*) FROM asistencias')) == 1
        assert conn.scalar(text('SELECT COUNT(*) FROM lecturas_biometricas')) == 1
        assert cc.validar(conn, c.leer_corrida('srv')) == {resultados[0]['lectura_id']}


def test_clave_no_cambia_de_persona_y_rechazo_duplicado_no_crea_racion(entorno):
    motor, referencia = entorno
    clave = str(uuid4())
    primero = leer(motor, referencia, clave)
    otra = enrolamiento.registrar(900102, 2, str(uuid4()))['referencia']
    with pytest.raises(c.Abortado, match='otra identidad'):
        leer(motor, otra, clave)
    segundo = leer(motor, referencia)
    assert primero['valido'] and not segundo['valido']
    assert segundo['motivo'] == 'duplicado'
    with motor.connect() as conn:
        assert len(cc.validar(conn, c.leer_corrida('srv'))) == 2


def test_desconocida_identificacion_real_y_reintento_preservan_relaciones(entorno):
    motor, referencia = entorno
    original = leer(motor, referencia, desconocida=True)
    from app.logica.intervencion import identificar_lectura
    clave = str(uuid4())
    with Session(motor) as sesion:
        primero = identificar_lectura(sesion, cuenta_id=2, lectura_id=original['lectura_id'], usuario_id=900101, clave=clave)
        segundo = identificar_lectura(sesion, cuenta_id=2, lectura_id=original['lectura_id'], usuario_id=900101, clave=clave)
        assert primero.valido and segundo.reintento
        assert primero.asistencia_id == segundo.asistencia_id
    with motor.connect() as conn:
        assert cc.validar(conn, c.leer_corrida('srv')) == {original['lectura_id']}
        assert conn.scalar(text('SELECT COUNT(*) FROM intervenciones_lectura')) == 1


@pytest.mark.parametrize('sql', [
    "UPDATE lecturas_biometricas SET dispositivo='ajeno'",
    "UPDATE lecturas_biometricas SET usuario_id=900102",
    "UPDATE asistencias SET comida_id=1",
    "UPDATE asistencias SET turno_asignado_id=193739904",
    "UPDATE asistencias SET registrado_por_cuenta=2",
    "DELETE FROM asistencias",
])
def test_limpieza_rechaza_propiedad_alterada_sin_modificar_diario(entorno, sql):
    motor, referencia = entorno
    leer(motor, referencia)
    antes = c.CORRIDA.read_bytes()
    with motor.begin() as conn:
        conn.execute(text(sql))
    with motor.connect() as conn, pytest.raises(c.Abortado):
        cc.validar(conn, c.leer_corrida('srv'))
    assert c.CORRIDA.read_bytes() == antes


def test_id_rollback_no_se_confunde_con_lectura_de_otro_dispositivo(entorno):
    motor, referencia = entorno
    leer(motor, referencia)
    datos = c.leer_corrida('srv')
    datos['lecturas_concurrentes'][0]['emitidos'].append(999)
    with motor.connect() as conn:
        assert 999 in cc.validar(conn, datos)
    with motor.begin() as conn:
        conn.execute(text("INSERT INTO lecturas_biometricas (id,usuario_id,fecha_hora,resultado,motivo,dispositivo) VALUES (999,NULL,'2026-10-15 12:00:00','rechazada','no_identificado','otro')"))
    with motor.connect() as conn, pytest.raises(c.Abortado):
        cc.validar(conn, datos)


def test_reserva_qa03_admite_solo_sus_lecturas_concurrentes_verificadas(entorno):
    from verificar_casos import verificar_reserva_qa03
    motor, _ = entorno
    referencia = enrolamiento.registrar(900103, 2, str(uuid4()))['referencia']
    leer(motor, referencia)
    with motor.connect() as conn:
        assert verificar_reserva_qa03(conn, c.leer_corrida('srv'))['resultado'] == 'USADO_EN_CONCURRENCIA'
    with motor.begin() as conn:
        conn.execute(text("INSERT INTO lecturas_biometricas (id,usuario_id,fecha_hora,resultado,motivo,dispositivo) VALUES (999,900103,'2026-10-15 12:00:00','rechazada','duplicado','otro')"))
    with motor.connect() as conn, pytest.raises(c.Abortado, match='ajenos'):
        verificar_reserva_qa03(conn, c.leer_corrida('srv'))


def test_diario_reintenta_reemplazo_windows_sin_truncar_el_anterior(tmp_path, monkeypatch):
    monkeypatch.setattr(c, 'CORRIDA', tmp_path / 'corrida.json')
    c.guardar_corrida({'estado': 'anterior'})
    anterior = c.CORRIDA.read_bytes()
    reemplazar = c.os.replace
    llamadas = []

    def bloqueo_transitorio(origen, destino):
        llamadas.append(1)
        assert c.CORRIDA.read_bytes() == anterior
        if len(llamadas) < 3:
            error = PermissionError('Archivo abierto por otro lector')
            error.winerror = 5
            raise error
        reemplazar(origen, destino)

    monkeypatch.setattr(c.os, 'replace', bloqueo_transitorio)
    monkeypatch.setattr(c.time, 'sleep', lambda _: None)
    c.guardar_corrida({'estado': 'nuevo'})
    assert len(llamadas) == 3
    assert '"nuevo"' in c.CORRIDA.read_text()
    assert not c.CORRIDA.with_suffix('.json.tmp').exists()


@pytest.mark.parametrize('winerror,esperadas', [(5, 40), (None, 1)])
def test_diario_propaga_permiso_persistente_conservando_anterior(tmp_path, monkeypatch, winerror, esperadas):
    monkeypatch.setattr(c, 'CORRIDA', tmp_path / 'corrida.json')
    c.guardar_corrida({'estado': 'anterior'})
    anterior = c.CORRIDA.read_bytes()
    llamadas = []

    def denegar(*_):
        llamadas.append(1)
        error = PermissionError('No se puede reemplazar')
        if winerror is not None:
            error.winerror = winerror
        raise error

    monkeypatch.setattr(c.os, 'replace', denegar)
    monkeypatch.setattr(c.time, 'sleep', lambda _: None)
    with pytest.raises(PermissionError):
        c.guardar_corrida({'estado': 'nuevo'})
    assert len(llamadas) == esperadas
    assert c.CORRIDA.read_bytes() == anterior
