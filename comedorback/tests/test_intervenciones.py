"""Intervenciones de cocina: la cocinera identifica una lectura no reconocida y
confirma la entrega; la jefa solo consulta.

Contrato (contrato-intervenciones-cocina-definitivo.md, con las correcciones de
implementación):

  · POST /asistencias/lecturas/{id}/identificar  → solo cocinera. Cabecera
    `Idempotency-Key` (UUID v4) y cuerpo {usuario_id}. Sin nota, motivo ni límite
    de minutos: la lectura tiene que ser del MISMO servicio efectivo.
  · GET /intervenciones-cocina → solo jefa.
  · GET /pantalla/ultimas-marcaciones → campos nuevos por rol.

Las lecturas las registra el lector de prueba (tests/lector_prueba.py) con el
reloj fijado; lo demás va por la API. Las pruebas de concurrencia corren bajo los dos aislamientos y retienen
el bloqueo de la lectura desde otra conexión, para que el orden sea
determinista: son solo lecturas bloqueantes, no escrituras.
"""

import json
import threading
import time as tiempo
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.consultas import pantalla as consultas_pantalla
from app.consultas.derecho import Derecho, aplicar_reglas
import reloj_prueba
from app.core.config import config
from app.core.db import SesionLocal, motor
from app.logica import intervencion
from app.main import app
from app.modelos.comedor import (
    Asistencia,
    CategoriaReporte,
    IntervencionLectura,
    LecturaBiometrica,
)
from app.modelos.heredados import Comensal, Comida, ComidaPorTurno
from app.semillas import horarios
from conftest import encabezado, ingresar
from soporte_horarios import (  # noqa: F401  fixtures y ayudas compartidas
    abierta,
    comida_id,
    fijar,
    guardar,
    reloj_libre,
    root,
)
from soporte_derecho import candidato_almuerzo

POST = "/asistencias/lecturas/{}/identificar"
LISTA = "/intervenciones-cocina"
POR_IDENTIFICAR = "/pantalla/lecturas-por-identificar"
PANTALLA = "/pantalla/ultimas-marcaciones"
CAUSA = "identificacion_manual_por_no_identificado"
USUARIO_INEXISTENTE = 999_999_999
ESPERA = 1.5  # segundos que se deja a los hilos bloqueados antes de comprobarlos


# --- fixtures -----------------------------------------------------------------


@pytest.fixture(autouse=True)
def reloj_real():
    reloj_prueba.liberar()
    yield
    reloj_prueba.liberar()


@pytest.fixture
def tokens(cliente, crear_usuario) -> dict[str, dict[str, str]]:
    roles = {"jefa": "jefa", "cocinera": "cocinera", "cocinera2": "cocinera", "sistemas": "sistemas"}
    for nombre, rol in roles.items():
        crear_usuario(f"u_{nombre}", rol=rol)
    return {n: encabezado(ingresar(cliente, f"u_{n}")["access"]) for n in roles}


def _vaciar() -> None:
    """La auditoría primero: apunta (RESTRICT) a lecturas y asistencias."""
    with SesionLocal() as sesion:
        sesion.execute(text("DELETE FROM intervenciones_lectura"))
        sesion.execute(text("DELETE FROM asistencias"))
        sesion.execute(text("DELETE FROM lecturas_biometricas"))
        sesion.execute(text("DELETE FROM horarios_comida"))
        sesion.commit()


def _verificar_coherencia() -> None:
    """La relación entre `resultado` y `asistencia_id` NO la impone ninguna
    restricción de la base (el CHECK de la tabla solo cubre `motivo_rechazo`, y
    no se verificó si MySQL admite uno sobre una columna con FK RESTRICT). La
    sostiene el único camino de inserción; esto la comprueba sobre lo que
    quedó en la base, con carreras y fallos incluidos:

      · `registrada` siempre tiene asistencia, y es la que corresponde (manual,
        de esa lectura, esa persona y esa cuenta);
      · `rechazada` nunca la tiene;
      · una lectura tiene, como mucho, una `registrada`;
      · toda asistencia vinculada a una lectura rechazada tiene exactamente una
        intervención `registrada` que la explique (ninguna ración huérfana).
    """
    sin_asistencia = _filas(
        "SELECT id FROM intervenciones_lectura "
        "WHERE resultado = 'registrada' AND asistencia_id IS NULL"
    )
    con_asistencia = _filas(
        "SELECT id FROM intervenciones_lectura "
        "WHERE resultado = 'rechazada' AND asistencia_id IS NOT NULL"
    )
    equivocadas = _filas(
        "SELECT i.id FROM intervenciones_lectura i "
        "LEFT JOIN asistencias a ON a.id = i.asistencia_id "
        "WHERE i.resultado = 'registrada' AND (a.id IS NULL OR a.metodo <> 'manual' "
        "OR NOT (a.lectura_id <=> i.lectura_id) OR a.usuario_id <> i.usuario_id "
        "OR NOT (a.registrado_por_cuenta <=> i.cuenta_id))"
    )
    dobles = _filas(
        "SELECT lectura_id FROM intervenciones_lectura WHERE resultado = 'registrada' "
        "GROUP BY lectura_id HAVING COUNT(*) > 1"
    )
    huerfanas = _filas(
        "SELECT a.id FROM asistencias a JOIN lecturas_biometricas l ON l.id = a.lectura_id "
        "WHERE l.resultado = 'rechazada' AND (SELECT COUNT(*) FROM intervenciones_lectura i "
        "WHERE i.asistencia_id = a.id AND i.resultado = 'registrada') <> 1"
    )
    assert sin_asistencia == [], f"registrada sin asistencia: {sin_asistencia}"
    assert con_asistencia == [], f"rechazada con asistencia: {con_asistencia}"
    assert equivocadas == [], f"registrada con la asistencia que no es: {equivocadas}"
    assert dobles == [], f"lecturas con dos entregas registradas: {dobles}"
    assert huerfanas == [], f"raciones vinculadas sin intervención registrada: {huerfanas}"


@pytest.fixture
def con_horarios():
    _vaciar()
    horarios.sembrar()
    try:
        yield
        _verificar_coherencia()  # la haya roto o no la prueba, al final nada queda incoherente
    finally:
        _vaciar()


@pytest.fixture
def vacio():
    _vaciar()
    try:
        yield
        _verificar_coherencia()
    finally:
        _vaciar()


@pytest.fixture(params=["REPEATABLE READ", "READ COMMITTED"])
def aislamiento(request):
    """El mismo código bajo cada aislamiento: la app usa `SesionLocal`, que
    aquí se liga a un motor con ese nivel."""
    motor_prueba = create_engine(
        config.url_base_datos, isolation_level=request.param, pool_pre_ping=True, future=True
    )
    SesionLocal.configure(bind=motor_prueba)
    yield request.param
    SesionLocal.configure(bind=motor)
    motor_prueba.dispose()


@dataclass
class Escenario:
    usuario_id: int
    fecha: date
    momento: datetime  # 12:30, dentro del almuerzo de la semilla


@pytest.fixture
def escenario(con_horarios) -> Escenario:
    usuario_id, fecha = candidato_almuerzo()
    if fecha <= horarios.VIGENTE_DESDE:
        pytest.skip("el almuerzo candidato es anterior a la semilla")
    return Escenario(usuario_id, fecha, datetime.combine(fecha, time(12, 30)))


# --- ayudas -------------------------------------------------------------------


def _clave() -> str:
    return str(uuid.uuid4())


def _lectura(lector, momento: datetime, **cuerpo) -> int:
    """Una lectura del lector de prueba, con el reloj fijado en `momento`."""
    reloj_prueba.fijar(momento)
    return lector.leer(**cuerpo)["lectura_id"]


def _identificar(cliente, headers, lectura_id, usuario_id, *, clave=None, ahora=None):
    if ahora is not None:
        reloj_prueba.fijar(ahora)
    return cliente.post(
        POST.format(lectura_id),
        json={"usuario_id": usuario_id},
        headers={**headers, "Idempotency-Key": clave or _clave()},
    )


def _filas(consulta: str, **params) -> list[tuple]:
    with SesionLocal() as sesion:
        return [tuple(f) for f in sesion.execute(text(consulta), params).all()]


def _contar(tabla: str) -> int:
    return _filas(f"SELECT COUNT(*) FROM {tabla}")[0][0]


def _id_de_cuenta(username: str) -> int:
    return _filas("SELECT id FROM usuarios_sistema WHERE username = :u", u=username)[0][0]


def _sin_derecho(fecha: date) -> int:
    """Alguien del padrón SIN derecho al almuerzo de `fecha` (solo SELECT)."""
    with SesionLocal() as sesion:
        almuerzo = sesion.execute(select(Comida.id).where(Comida.codigo == "almuerzo")).scalar_one()
        con = aplicar_reglas(
            select(ComidaPorTurno.usuario_id).where(
                ComidaPorTurno.comida_id == almuerzo, ComidaPorTurno.fecha_comida == fecha
            )
        )
        persona = sesion.execute(
            select(Comensal.usuario_id).where(Comensal.usuario_id.not_in(con)).limit(1)
        ).scalar_one_or_none()
    if persona is None:
        pytest.skip("todo el padrón tiene derecho a ese almuerzo")
    return persona


# --- personas sintéticas: dos o tres con derecho, sin depender de turnos ---------------------

# Lejos de cualquier users.id real. Una prueba comprueba que ninguno existe en el
# padrón, y que lo que no es sintético sigue yendo a las consultas reales.
SINTETICO_BASE = 2_000_000_000


@dataclass
class Sintetico:
    """El mismo escenario del almuerzo, con N personas que TIENEN derecho y están
    en el padrón porque la prueba lo dice, no porque turnos tenga a tanta gente."""

    comida_id: int
    fecha: date
    momento: datetime  # 12:30, dentro del almuerzo de la semilla
    personas: list[int]

    @property
    def usuario_id(self) -> int:
        return self.personas[0]


@pytest.fixture
def sintetico(con_horarios, monkeypatch) -> Sintetico:
    """Sustituye, SOLO en las pruebas, las dos consultas que lee el padrón y el
    derecho: `buscar_derecho` y `nombre_en_padron`, que la operación llama por su
    nombre en `app.logica.intervencion`.

    Qué es real y qué es sintético:
      · sintético: que estas personas existan en el padrón y tengan derecho al
        almuerzo de `fecha`. Es un DATO DE ENTRADA, como lo sería una fila de
        turnos; la operación no sabe si viene de turnos.
      · real: todo lo que la operación decide y escribe: la elegibilidad de la
        lectura, el servicio efectivo (horarios de la base `_test`), el duplicado,
        las transacciones, el bloqueo FOR UPDATE, el SAVEPOINT, las restricciones
        únicas, la asistencia y la auditoría. Nada del resultado ni de los
        conflictos se falsea.
      · real también: cualquier persona que no sea sintética va a la consulta
        real de turnos (solo SELECT), y el reemplazo es global al proceso, así que
        lo ven todas las sesiones y los hilos de la prueba. `monkeypatch` lo
        restaura al terminar.
    No se escribe en turnos ni se toca ninguna configuración.
    """
    with SesionLocal() as sesion:
        almuerzo, nombre_almuerzo = sesion.execute(
            select(Comida.id, Comida.nombre).where(Comida.codigo == "almuerzo")
        ).one()
    fecha = date(2026, 9, 24)  # dentro de la vigencia de la semilla (desde 2026-01-01)
    personas = [SINTETICO_BASE + k for k in range(1, 6)]
    derecho_real = intervencion.buscar_derecho
    padron_real = intervencion.nombre_en_padron

    def derecho(sesion, usuario_id, comida_id, fecha_comida):
        if usuario_id in personas and comida_id == almuerzo and fecha_comida == fecha:
            return Derecho(
                comida_id=almuerzo,
                comida=nombre_almuerzo,
                fecha_comida=fecha,
                turno_asignado_id=usuario_id,
                servicio_id=usuario_id,
                turno="Turno sintético",
                fecha_turno=fecha,
                dia_relativo=0,
            )
        return derecho_real(sesion, usuario_id, comida_id, fecha_comida)

    def padron(sesion, usuario_id):
        if usuario_id in personas:
            return (f"Persona sintética {usuario_id - SINTETICO_BASE}",)
        return padron_real(sesion, usuario_id)

    monkeypatch.setattr(intervencion, "buscar_derecho", derecho)
    monkeypatch.setattr(intervencion, "nombre_en_padron", padron)
    return Sintetico(almuerzo, fecha, datetime.combine(fecha, time(12, 30)), personas)


def _lista(cliente, headers, fecha: date) -> list[dict]:
    r = cliente.get(PANTALLA, params={"fecha": fecha.isoformat(), "limite": 100}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _de_la_lectura(filas: list[dict], lectura_id: int) -> dict:
    return next(f for f in filas if f["clave_evento"] == f"lectura_biometrica:{lectura_id}")


@contextmanager
def retener_lectura(lectura_id: int):
    """Una transacción que tiene el bloqueo de la lectura (solo lectura)."""
    conexion = motor.connect()
    transaccion = conexion.begin()
    conexion.execute(
        text("SELECT id FROM lecturas_biometricas WHERE id = :i FOR UPDATE"), {"i": lectura_id}
    )
    try:
        yield
    finally:
        transaccion.rollback()
        conexion.close()


def _lanzar(resultados: dict, nombre: str, headers, lectura_id: int, usuario_id: int, clave: str):
    def tarea():
        resultados[nombre] = TestClient(app).post(
            POST.format(lectura_id),
            json={"usuario_id": usuario_id},
            headers={**headers, "Idempotency-Key": clave},
        )

    hilo = threading.Thread(target=tarea, daemon=True)
    hilo.start()
    return hilo


def _terminar(hilos) -> None:
    for hilo in hilos:
        hilo.join(30)
        assert not hilo.is_alive(), "una solicitud no terminó al soltar el bloqueo"


# --- permisos y forma -----------------------------------------------------------


@pytest.mark.parametrize("rol", ["jefa", "sistemas"])
def test_solo_la_cocinera_identifica_y_el_403_va_antes_que_el_422(cliente, tokens, rol):
    # Sin cabecera y sin cuerpo: quien no tiene el rol no se entera de qué faltaba.
    r = cliente.post(POST.format(1), headers=tokens[rol])
    assert r.status_code == 403, r.text
    assert r.json()["motivo"] == "rol_no_autorizado"


def test_solo_la_jefa_consulta(cliente, tokens):
    for quien in ("cocinera", "sistemas"):
        r = cliente.get(LISTA, headers=tokens[quien])
        assert r.status_code == 403, r.text
        assert r.json()["motivo"] == "rol_no_autorizado"
    assert cliente.get(LISTA, headers=tokens["jefa"]).status_code == 200


@pytest.mark.parametrize(
    "cabecera",
    [None, "", "no-es-un-uuid", "6f1c2a9e-3b7d-1e0a-9d52-1c8f0b7a4e11"],  # la última es v1
    ids=["falta", "vacia", "sin_forma", "no_es_v4"],
)
def test_la_clave_de_idempotencia_es_obligatoria_y_v4(cliente, tokens, cabecera):
    headers = dict(tokens["cocinera"])
    if cabecera is not None:
        headers["Idempotency-Key"] = cabecera
    r = cliente.post(POST.format(1), json={"usuario_id": 1}, headers=headers)
    assert r.status_code == 422, r.text
    assert r.json()["motivo"] == "clave_idempotencia_invalida"


@pytest.mark.parametrize(
    "extra",
    [{"nota": "huella dañada"}, {"motivo": "x"}, {"momento": "2026-01-01T12:00:00"}, {"cuenta_id": 1}],
)
def test_el_cuerpo_no_acepta_nada_mas_que_el_usuario(cliente, tokens, extra):
    r = cliente.post(
        POST.format(1),
        json={"usuario_id": 1, **extra},
        headers={**tokens["cocinera"], "Idempotency-Key": _clave()},
    )
    assert r.status_code == 422, r.text


def test_la_lectura_inexistente_es_404(cliente, tokens, con_horarios):
    r = _identificar(cliente, tokens["cocinera"], 999_999_999, 1)
    assert r.status_code == 404, r.text
    assert r.json()["motivo"] == "lectura_inexistente"
    assert _contar("intervenciones_lectura") == 0


def test_el_comensal_inexistente_es_404_y_no_consume_la_clave(
    cliente, lector, tokens, escenario
):
    e = escenario
    lectura = _lectura(lector, e.momento)
    clave = _clave()
    r = _identificar(cliente, tokens["cocinera"], lectura, USUARIO_INEXISTENTE, clave=clave, ahora=e.momento)
    assert r.status_code == 404, r.text
    assert r.json()["motivo"] == "comensal_inexistente"
    assert _contar("intervenciones_lectura") == 0
    # La clave sigue libre.
    ok = _identificar(cliente, tokens["cocinera"], lectura, e.usuario_id, clave=clave)
    assert ok.status_code == 200 and ok.json()["reintento"] is False, ok.text


def test_el_post_manual_de_asistencias_conserva_sus_permisos(cliente, tokens, escenario):
    e = escenario
    reloj_prueba.fijar(e.momento)
    cuerpo = {"usuario_id": e.usuario_id, "metodo": "manual"}
    r = cliente.post("/asistencias", json=cuerpo, headers=tokens["cocinera"])
    assert r.status_code == 403 and r.json()["motivo"] == "metodo_no_autorizado"
    assert cliente.post("/asistencias", json=cuerpo, headers=tokens["jefa"]).json()["valido"] is True


# --- la entrega registrada ------------------------------------------------------


def test_identificar_registra_la_entrega_y_deja_la_lectura_intacta(
    cliente, lector, tokens, escenario
):
    e = escenario
    coci = tokens["cocinera"]
    lectura = _lectura(lector, e.momento)
    consulta = (
        "SELECT usuario_id, dispositivo, fecha_hora, resultado, motivo "
        "FROM lecturas_biometricas WHERE id = :i"
    )
    antes = _filas(consulta, i=lectura)
    ahora = e.momento + timedelta(minutes=5)

    r = _identificar(cliente, coci, lectura, e.usuario_id, ahora=ahora)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert (cuerpo["valido"], cuerpo["resultado"], cuerpo["reintento"]) == (True, "registrada", False)
    assert cuerpo["titulo"] == "Entrega registrada" and cuerpo["motivo"] is None
    assert cuerpo["causa"] == CAUSA
    assert cuerpo["lectura_id"] == lectura and cuerpo["usuario_id"] == e.usuario_id
    assert cuerpo["fecha_comida"] == e.fecha.isoformat()
    assert datetime.fromisoformat(cuerpo["momento"]) == ahora  # la hora la pone el servidor

    # La lectura original no se tocó: sigue sin usuario y rechazada.
    assert _filas(consulta, i=lectura) == antes
    assert antes[0][0] is None and antes[0][3:] == ("rechazada", "no_identificado")

    cuenta = _id_de_cuenta("u_cocinera")
    (racion,) = _filas(
        "SELECT metodo, lectura_id, registrado_por_cuenta, usuario_id, fecha_comida, fecha_hora "
        "FROM asistencias"
    )
    assert racion[:5] == ("manual", lectura, cuenta, e.usuario_id, e.fecha)
    assert racion[5] == ahora
    (fila,) = _filas(
        "SELECT cuenta_id, resultado, motivo_rechazo, asistencia_id, causa, momento "
        "FROM intervenciones_lectura"
    )
    assert fila[:3] == (cuenta, "registrada", None)
    assert fila[3] == cuerpo["asistencia_id"] and fila[4] == CAUSA and fila[5] == ahora


def test_la_entrega_cuenta_una_sola_racion_y_el_rechazo_original_sigue_contando(
    cliente, lector, tokens, escenario
):
    e = escenario
    coci = tokens["cocinera"]
    lectura = _lectura(lector, e.momento)
    assert _identificar(cliente, coci, lectura, e.usuario_id, ahora=e.momento).status_code == 200

    r = cliente.get("/pantalla/estado", headers=tokens["jefa"])
    assert r.status_code == 200, r.text
    estado = r.json()
    # Una ración, un toque de dedo, y ese toque sigue siendo un rechazo: no hay
    # lectura aceptada ni una segunda ración por la intervención.
    assert estado["totales_del_dia"]["raciones_servidas"] == 1
    assert (estado["totales_del_dia"]["lecturas"], estado["totales_del_dia"]["aceptadas"]) == (1, 0)
    assert estado["totales_del_dia"]["rechazadas"] == 1
    assert estado["cupo"]["servidas"] == 1


# --- los rechazos de la persona --------------------------------------------------


def test_sin_derecho_es_un_intento_rechazado_y_no_una_entrega(
    cliente, lector, tokens, escenario
):
    e = escenario
    coci = tokens["cocinera"]
    persona = _sin_derecho(e.fecha)
    lectura = _lectura(lector, e.momento)
    r = _identificar(cliente, coci, lectura, persona, ahora=e.momento)
    assert r.status_code == 200, r.text
    c = r.json()
    assert (c["valido"], c["resultado"], c["motivo"]) == (False, "rechazada", "sin_derecho")
    assert c["asistencia_id"] is None and c["intervencion_id"]
    assert c["titulo"] == "Intento rechazado" and "No se registró entrega" in c["detalle"]
    assert "Entrega registrada" not in json.dumps(c)
    assert _contar("asistencias") == 0
    assert _filas("SELECT resultado, motivo_rechazo, asistencia_id FROM intervenciones_lectura") == [
        ("rechazada", "sin_derecho", None)
    ]
    # La lectura sigue pendiente: otra persona todavía se puede identificar.
    assert _identificar(cliente, coci, lectura, e.usuario_id).status_code == 200


def test_duplicado_es_un_intento_rechazado(cliente, lector, tokens, escenario):
    e = escenario
    coci = tokens["cocinera"]
    reloj_prueba.fijar(e.momento)
    manual = cliente.post(
        "/asistencias", json={"usuario_id": e.usuario_id, "metodo": "manual"}, headers=tokens["jefa"]
    )
    assert manual.json()["valido"] is True, manual.text
    lectura = _lectura(lector, e.momento + timedelta(minutes=1))
    r = _identificar(cliente, coci, lectura, e.usuario_id, ahora=e.momento + timedelta(minutes=2))
    assert r.status_code == 200, r.text
    c = r.json()
    assert (c["valido"], c["resultado"], c["motivo"]) == (False, "rechazada", "duplicado")
    assert "No se registró entrega" in c["detalle"]
    assert _contar("asistencias") == 1  # solo la manual de jefatura


# --- los conflictos sobre la lectura ---------------------------------------------


def test_lectura_ya_resuelta_por_otra_cuenta_no_se_atribuye_a_quien_repite(
    cliente, lector, tokens, sintetico
):
    e = sintetico
    a, b = e.personas[:2]
    lectura = _lectura(lector, e.momento)
    assert _identificar(cliente, tokens["cocinera"], lectura, a, ahora=e.momento).status_code == 200

    # Otra cocinera, otra persona, clave nueva.
    r = _identificar(cliente, tokens["cocinera2"], lectura, b)
    assert r.status_code == 409, r.text
    cuerpo = r.json()
    assert cuerpo["motivo"] == "lectura_ya_resuelta"
    assert (cuerpo["resultado"], cuerpo["reintento"], cuerpo["resuelta_por_mi"]) == ("rechazada", False, False)
    # Ni la cuenta que la resolvió, ni su ración.
    assert "u_cocinera" not in json.dumps(cuerpo) and "asistencia_id" not in cuerpo

    # La misma cuenta que la resolvió, con clave nueva: ya resuelta, y es suya.
    otra = _identificar(cliente, tokens["cocinera"], lectura, a)
    assert otra.status_code == 409 and otra.json()["resuelta_por_mi"] is True

    assert _contar("asistencias") == 1
    assert _filas(
        "SELECT resultado, motivo_rechazo FROM intervenciones_lectura ORDER BY id"
    ) == [("registrada", None), ("rechazada", "lectura_ya_resuelta"), ("rechazada", "lectura_ya_resuelta")]


@pytest.mark.parametrize("caso", ["fuera_horario_sin_usuario", "aceptada", "rechazada_con_usuario"])
def test_el_rechazo_original_no_elegible_no_se_resuelve(
    cliente, lector, tokens, escenario, caso
):
    e = escenario
    coci = tokens["cocinera"]
    if caso == "fuera_horario_sin_usuario":
        # 10:00-11:00 no tiene horario en la semilla: se guarda fuera_horario.
        momento = datetime.combine(e.fecha, time(10, 30))
        lectura = _lectura(lector, momento)
        assert _filas("SELECT motivo FROM lecturas_biometricas WHERE id = :i", i=lectura) == [("fuera_horario",)]
    elif caso == "aceptada":
        momento = e.momento
        lectura = _lectura(lector, momento, usuario_id=e.usuario_id)
    else:
        momento = e.momento
        lectura = _lectura(lector, momento, usuario_id=USUARIO_INEXISTENTE)

    r = _identificar(cliente, coci, lectura, e.usuario_id, ahora=momento)
    assert r.status_code == 409, r.text
    assert r.json()["motivo"] == "lectura_no_resoluble"
    # Una lectura aceptada tiene asistencia vinculada, y aun así NO es
    # "ya resuelta": no era un rechazo elegible.
    assert _filas(
        "SELECT motivo_rechazo FROM intervenciones_lectura WHERE lectura_id = :i", i=lectura
    ) == [("lectura_no_resoluble",)]


# --- el servicio efectivo --------------------------------------------------------


@pytest.mark.parametrize(
    "desfase",
    [
        pytest.param(("mismo_dia", time(16, 0)), id="otra_comida_el_mismo_dia"),
        pytest.param(("mismo_dia", time(20, 0)), id="otra_comida_mas_tarde"),
        pytest.param(("dia_siguiente", time(12, 30)), id="misma_comida_otra_fecha_comida"),
    ],
)
def test_otro_servicio_no_se_resuelve_aunque_la_comida_sea_la_misma(
    cliente, lector, tokens, escenario, desfase
):
    e = escenario
    lectura = _lectura(lector, e.momento)
    dia = e.fecha + timedelta(days=1 if desfase[0] == "dia_siguiente" else 0)
    r = _identificar(
        cliente, tokens["cocinera"], lectura, e.usuario_id, ahora=datetime.combine(dia, desfase[1])
    )
    assert r.status_code == 409, r.text
    assert r.json()["motivo"] == "servicio_distinto"
    assert _contar("asistencias") == 0


def test_reloj_retrocedido_no_resuelve(cliente, lector, tokens, escenario):
    e = escenario
    lectura = _lectura(lector, e.momento)
    r = _identificar(cliente, tokens["cocinera"], lectura, e.usuario_id, ahora=e.momento - timedelta(minutes=1))
    assert r.status_code == 409, r.text
    assert r.json()["motivo"] == "reloj_inconsistente"
    assert _contar("asistencias") == 0


def _candidato_cena() -> tuple[int, date]:
    """Alguien con derecho a una cena, la más reciente (solo SELECT)."""
    with SesionLocal() as sesion:
        cena = sesion.execute(select(Comida.id).where(Comida.codigo == "cena")).scalar_one_or_none()
        if cena is None:
            pytest.skip("v_comidas no tiene la cena")
        fila = sesion.execute(
            aplicar_reglas(
                select(ComidaPorTurno.usuario_id, ComidaPorTurno.fecha_comida).where(
                    ComidaPorTurno.comida_id == cena,
                    ComidaPorTurno.fecha_comida > horarios.VIGENTE_DESDE,
                )
            )
            .order_by(ComidaPorTurno.fecha_comida.desc(), ComidaPorTurno.usuario_id)
            .limit(1)
        ).first()
    if fila is None:
        pytest.skip("la base de turnos no tiene ninguna cena con derecho")
    return fila.usuario_id, fila.fecha_comida


def test_la_medianoche_no_corta_un_servicio_nocturno(
    cliente, lector, tokens, root, vacio
):
    """Una franja que cruza la medianoche: la lectura de las 23:58 y la
    solicitud de las 00:02 son el mismo servicio, con la misma fecha_comida."""
    persona, fecha = _candidato_cena()
    cena = comida_id("cena")
    fijar(datetime.combine(fecha, time(9)))
    assert guardar(cliente, root, cena, "22:00:00", "02:00:00", None).status_code == 201
    lectura = _lectura(lector, datetime.combine(fecha, time(23, 58)))
    r = _identificar(
        cliente, tokens["cocinera"], lectura, persona,
        ahora=datetime.combine(fecha + timedelta(days=1), time(0, 2)),
    )
    assert r.status_code == 200, r.text
    assert r.json()["valido"] is True
    assert r.json()["fecha_comida"] == fecha.isoformat()


def test_un_cambio_de_horario_contiguo_mantiene_el_servicio(
    cliente, lector, tokens, root, vacio
):
    usuario_id, fecha = candidato_almuerzo()
    almuerzo = comida_id("almuerzo")
    fijar(datetime.combine(fecha, time(9)))
    assert guardar(cliente, root, almuerzo, "11:00:00", "15:00:00", None).status_code == 201
    lectura = _lectura(lector, datetime.combine(fecha, time(12, 30)))

    # A las 12:40 root acorta el almuerzo a 14:00: las dos versiones se unen en
    # una sola ventana, la lectura y la solicitud siguen en el mismo servicio.
    fijar(datetime.combine(fecha, time(12, 40)))
    base = abierta(cliente, root, almuerzo)["horario_id"]
    assert guardar(cliente, root, almuerzo, "11:00:00", "14:00:00", base).status_code == 201

    r = _identificar(cliente, tokens["cocinera"], lectura, usuario_id, ahora=datetime.combine(fecha, time(12, 50)))
    assert r.status_code == 200, r.text
    assert r.json()["valido"] is True


def test_un_cambio_de_horario_con_hueco_separa_los_servicios(
    cliente, lector, tokens, root, vacio
):
    usuario_id, fecha = candidato_almuerzo()
    almuerzo = comida_id("almuerzo")
    fijar(datetime.combine(fecha, time(9)))
    assert guardar(cliente, root, almuerzo, "11:00:00", "15:00:00", None).status_code == 201
    lectura = _lectura(lector, datetime.combine(fecha, time(12, 30)))

    # A las 16:00 root lo extiende a 20:00: quedan [11:00, 15:00) y [16:00, 20:00).
    fijar(datetime.combine(fecha, time(16, 0)))
    base = abierta(cliente, root, almuerzo)["horario_id"]
    assert guardar(cliente, root, almuerzo, "11:00:00", "20:00:00", base).status_code == 201

    r = _identificar(cliente, tokens["cocinera"], lectura, usuario_id, ahora=datetime.combine(fecha, time(16, 30)))
    assert r.status_code == 409, r.text
    assert r.json()["motivo"] == "servicio_distinto"


def test_una_lectura_sin_ventana_que_la_contenga_no_es_determinable(
    cliente, lector, tokens, escenario
):
    """Si la versión de horario que cubría la lectura pasó a activo=0, la
    reconstrucción ya no existe y no se inventa una."""
    e = escenario
    lectura = _lectura(lector, e.momento)
    with SesionLocal() as sesion:
        sesion.execute(text("UPDATE horarios_comida SET activo = 0"))
        sesion.commit()
    r = _identificar(cliente, tokens["cocinera"], lectura, e.usuario_id, ahora=e.momento)
    assert r.status_code == 409, r.text
    assert r.json()["motivo"] == "servicio_no_determinable"


# --- idempotencia -----------------------------------------------------------------


def test_un_reintento_identico_no_duplica_ni_racion_ni_auditoria(
    cliente, lector, tokens, escenario
):
    e = escenario
    lectura = _lectura(lector, e.momento)
    clave = _clave()
    primera = _identificar(cliente, tokens["cocinera"], lectura, e.usuario_id, clave=clave, ahora=e.momento)
    segunda = _identificar(cliente, tokens["cocinera"], lectura, e.usuario_id, clave=clave)
    assert primera.status_code == segunda.status_code == 200
    assert (primera.json()["reintento"], segunda.json()["reintento"]) == (False, True)
    iguales = {k: v for k, v in segunda.json().items() if k != "reintento"}
    assert iguales == {k: v for k, v in primera.json().items() if k != "reintento"}
    assert (_contar("asistencias"), _contar("intervenciones_lectura")) == (1, 1)


def test_un_reintento_de_un_rechazo_devuelve_lo_mismo_sin_otra_fila(
    cliente, lector, tokens, escenario
):
    e = escenario
    persona = _sin_derecho(e.fecha)
    lectura = _lectura(lector, e.momento)
    clave = _clave()
    primera = _identificar(cliente, tokens["cocinera"], lectura, persona, clave=clave, ahora=e.momento)
    segunda = _identificar(cliente, tokens["cocinera"], lectura, persona, clave=clave)
    assert (primera.json()["motivo"], segunda.json()["motivo"]) == ("sin_derecho", "sin_derecho")
    assert (primera.json()["reintento"], segunda.json()["reintento"]) == (False, True)
    assert segunda.json()["intervencion_id"] == primera.json()["intervencion_id"]
    assert _contar("intervenciones_lectura") == 1


def test_la_misma_clave_con_otro_contenido_es_un_conflicto(
    cliente, lector, tokens, sintetico
):
    e = sintetico
    a, b = e.personas[:2]
    lectura = _lectura(lector, e.momento)
    clave = _clave()
    assert _identificar(cliente, tokens["cocinera"], lectura, a, clave=clave, ahora=e.momento).status_code == 200
    r = _identificar(cliente, tokens["cocinera"], lectura, b, clave=clave)
    assert r.status_code == 409, r.text
    assert r.json()["motivo"] == "clave_reutilizada_con_otro_contenido"
    assert (_contar("asistencias"), _contar("intervenciones_lectura")) == (1, 1)


def test_el_replay_no_reevalua_nada(cliente, lector, tokens, escenario):
    """Con el reloj ya en otro servicio, el reintento de una entrega devuelve
    la entrega, y el de un conflicto devuelve el MISMO conflicto: nada se
    vuelve a decidir, ni para bien ni para mal."""
    e = escenario
    coci = tokens["cocinera"]
    lectura = _lectura(lector, e.momento)
    clave_mala, clave_buena = _clave(), _clave()
    tarde = datetime.combine(e.fecha, time(20, 0))
    malo = _identificar(cliente, coci, lectura, e.usuario_id, clave=clave_mala, ahora=tarde)
    assert malo.status_code == 409 and malo.json()["motivo"] == "servicio_distinto"
    bueno = _identificar(cliente, coci, lectura, e.usuario_id, clave=clave_buena, ahora=e.momento)
    assert bueno.status_code == 200 and bueno.json()["reintento"] is False

    reloj_prueba.fijar(datetime.combine(e.fecha + timedelta(days=2), time(3, 0)))
    de_nuevo = cliente.post(
        POST.format(lectura), json={"usuario_id": e.usuario_id},
        headers={**coci, "Idempotency-Key": clave_buena},
    )
    assert de_nuevo.status_code == 200 and de_nuevo.json()["reintento"] is True
    assert de_nuevo.json()["asistencia_id"] == bueno.json()["asistencia_id"]

    reloj_prueba.fijar(e.momento)  # ahora sí sería el servicio correcto
    repite_malo = cliente.post(
        POST.format(lectura), json={"usuario_id": e.usuario_id},
        headers={**coci, "Idempotency-Key": clave_mala},
    )
    assert repite_malo.status_code == 409
    assert (repite_malo.json()["motivo"], repite_malo.json()["reintento"]) == ("servicio_distinto", True)
    assert _contar("intervenciones_lectura") == 2


def test_la_clave_es_de_la_cuenta(cliente, lector, tokens, escenario):
    e = escenario
    lectura = _lectura(lector, e.momento)
    clave = _clave()
    assert _identificar(cliente, tokens["cocinera"], lectura, e.usuario_id, clave=clave, ahora=e.momento).status_code == 200
    # La misma clave en otra cuenta no recupera la fila de la primera.
    r = _identificar(cliente, tokens["cocinera2"], lectura, e.usuario_id, clave=clave)
    assert r.status_code == 409 and r.json()["motivo"] == "lectura_ya_resuelta"
    assert r.json()["reintento"] is False and r.json()["resuelta_por_mi"] is False


# --- confirmación incierta ----------------------------------------------------------


def _commit_que_pierde_la_respuesta(confirmar: bool):
    """Un `Session.commit` que falla una vez como lo haría una desconexión:
    `confirmar=True` lo deja confirmado en el servidor y pierde la respuesta;
    `confirmar=False` cae antes de confirmar."""
    original = Session.commit
    estado = {"n": 0}

    def commit(self):
        estado["n"] += 1
        if estado["n"] == 1:
            if confirmar:
                original(self)
            raise OperationalError("COMMIT", {}, Exception("conexión perdida"))
        return original(self)

    return commit


@pytest.mark.parametrize("confirmar", [True, False], ids=["quedo_confirmado", "no_quedo"])
def test_un_commit_incierto_no_afirma_nada_y_se_recupera_con_la_misma_clave(
    cliente, lector, tokens, escenario, monkeypatch, confirmar
):
    e = escenario
    coci = tokens["cocinera"]
    lectura = _lectura(lector, e.momento)
    clave = _clave()
    reloj_prueba.fijar(e.momento)
    with monkeypatch.context() as parche:
        parche.setattr(Session, "commit", _commit_que_pierde_la_respuesta(confirmar))
        r = _identificar(cliente, coci, lectura, e.usuario_id, clave=clave)
    assert r.status_code == 503, r.text
    assert r.json()["motivo"] == "resultado_incierto"
    # No dice que no hubo entrega: no lo sabe.
    assert "no se registró" not in r.json()["detail"].lower()
    assert _contar("asistencias") == (1 if confirmar else 0)

    de_nuevo = _identificar(cliente, coci, lectura, e.usuario_id, clave=clave)
    assert de_nuevo.status_code == 200, de_nuevo.text
    assert de_nuevo.json()["valido"] is True
    assert de_nuevo.json()["reintento"] is confirmar  # recupera lo confirmado, o lo hace ahora
    assert (_contar("asistencias"), _contar("intervenciones_lectura")) == (1, 1)


def test_el_bloqueo_agotado_es_un_conflicto_reintentable(
    cliente, lector, tokens, escenario
):
    e = escenario
    coci = tokens["cocinera"]
    lectura = _lectura(lector, e.momento)
    corto = create_engine(config.url_base_datos, pool_pre_ping=True, future=True)

    @event.listens_for(corto, "connect")
    def _espera(dbapi, _registro):
        cursor = dbapi.cursor()
        cursor.execute("SET SESSION innodb_lock_wait_timeout = 1")
        cursor.close()

    SesionLocal.configure(bind=corto)
    try:
        clave = _clave()
        with retener_lectura(lectura):
            r = _identificar(cliente, coci, lectura, e.usuario_id, clave=clave, ahora=e.momento)
        assert r.status_code == 409, r.text
        assert r.json()["motivo"] == "intervencion_en_curso"
        assert _contar("intervenciones_lectura") == 0
    finally:
        SesionLocal.configure(bind=motor)
        corto.dispose()
    ok = _identificar(cliente, coci, lectura, e.usuario_id, clave=clave)
    assert ok.status_code == 200 and ok.json()["reintento"] is False


# --- concurrencia (los dos aislamientos) ---------------------------------------------


def test_la_misma_clave_a_la_vez_deja_una_sola_entrega(
    cliente, lector, tokens, escenario, aislamiento
):
    e = escenario
    coci = tokens["cocinera"]
    lectura = _lectura(lector, e.momento)
    reloj_prueba.fijar(e.momento)
    clave = _clave()
    resultados: dict = {}
    with retener_lectura(lectura):
        hilos = [_lanzar(resultados, f"h{i}", coci, lectura, e.usuario_id, clave) for i in range(2)]
        tiempo.sleep(ESPERA)
        assert all(h.is_alive() for h in hilos), "una solicitud no esperó el bloqueo de la lectura"
        assert resultados == {}
    _terminar(hilos)

    assert [r.status_code for r in resultados.values()] == [200, 200]
    assert sorted(r.json()["reintento"] for r in resultados.values()) == [False, True]
    assert len({r.json()["asistencia_id"] for r in resultados.values()}) == 1
    assert (_contar("asistencias"), _contar("intervenciones_lectura")) == (1, 1)


def test_dos_personas_a_la_vez_sobre_la_misma_lectura_dan_una_sola_racion(
    cliente, lector, tokens, sintetico, aislamiento
):
    e = sintetico
    a, b = e.personas[:2]
    lectura = _lectura(lector, e.momento)
    reloj_prueba.fijar(e.momento)
    resultados: dict = {}
    with retener_lectura(lectura):
        hilos = [
            _lanzar(resultados, "a", tokens["cocinera"], lectura, a, _clave()),
            _lanzar(resultados, "b", tokens["cocinera2"], lectura, b, _clave()),
        ]
        tiempo.sleep(ESPERA)
        assert all(h.is_alive() for h in hilos)
    _terminar(hilos)

    estados = sorted(r.status_code for r in resultados.values())
    assert estados == [200, 409], {k: v.text for k, v in resultados.items()}
    perdedor = next(r for r in resultados.values() if r.status_code == 409)
    assert perdedor.json()["motivo"] == "lectura_ya_resuelta"
    assert _contar("asistencias") == 1
    assert sorted(f[0] for f in _filas("SELECT resultado FROM intervenciones_lectura")) == ["rechazada", "registrada"]


def test_el_choque_de_la_racion_deja_la_auditoria_y_no_pierde_el_bloqueo(
    cliente, lector, tokens, escenario, aislamiento, monkeypatch
):
    """Otra vía le dio la ración a la persona entre la comprobación de
    duplicado y el INSERT (se provoca saltando la comprobación). El INSERT choca
    con `uq_asistencias_racion`; el rollback se limita al SAVEPOINT y la fila
    `rechazada` se confirma en la misma transacción."""
    e = escenario
    coci = tokens["cocinera"]
    reloj_prueba.fijar(e.momento)
    manual = cliente.post(
        "/asistencias", json={"usuario_id": e.usuario_id, "metodo": "manual"}, headers=tokens["jefa"]
    )
    assert manual.json()["valido"] is True, manual.text
    lectura = _lectura(lector, e.momento)
    monkeypatch.setattr(intervencion, "ya_comio", lambda *a, **k: False)

    r = _identificar(cliente, coci, lectura, e.usuario_id, ahora=e.momento)
    assert r.status_code == 200, r.text
    assert (r.json()["valido"], r.json()["motivo"], r.json()["resultado"]) == (False, "duplicado", "rechazada")
    assert _contar("asistencias") == 1  # solo la manual
    assert _filas("SELECT resultado, motivo_rechazo, asistencia_id FROM intervenciones_lectura") == [
        ("rechazada", "duplicado", None)
    ]
    # La lectura sigue pendiente: el rechazo no la consumió.
    assert _filas("SELECT COUNT(*) FROM asistencias WHERE lectura_id = :i", i=lectura) == [(0,)]


def test_un_choque_de_la_clave_se_resuelve_repitiendo_la_decision(
    cliente, lector, tokens, escenario, aislamiento, monkeypatch
):
    """Se provoca la carrera: el segundo intento no ve la fila de la clave (ni
    en el paso 2 ni en el 4), llega al INSERT y choca con el UNIQUE (cuenta,
    clave). Rollback total y una segunda pasada que ya la encuentra."""
    e = escenario
    coci = tokens["cocinera"]
    lectura = _lectura(lector, e.momento)
    clave = _clave()
    primera = _identificar(cliente, coci, lectura, e.usuario_id, clave=clave, ahora=e.momento)
    assert primera.status_code == 200

    real = intervencion._recuperar
    llamadas = {"n": 0}

    def ciega(sesion, ctx):
        llamadas["n"] += 1
        return None if llamadas["n"] <= 2 else real(sesion, ctx)

    monkeypatch.setattr(intervencion, "_recuperar", ciega)
    segunda = _identificar(cliente, coci, lectura, e.usuario_id, clave=clave)
    assert segunda.status_code == 200, segunda.text
    assert segunda.json()["reintento"] is True
    assert segunda.json()["asistencia_id"] == primera.json()["asistencia_id"]
    assert (_contar("asistencias"), _contar("intervenciones_lectura")) == (1, 1)


# --- los errores del driver: se OBSERVAN, el contrato no los garantiza ------------------


def test_el_driver_informa_el_1062_de_cada_unicidad(crear_usuario, con_horarios):
    """Provoca los tres choques y comprueba lo que entrega el driver instalado.
    La clasificación del código NO depende de este texto (consulta con
    bloqueo); esta prueba solo documenta lo observado y avisa si cambia."""
    cuenta = crear_usuario("coci_driver", rol="cocinera")
    base = datetime(2026, 9, 24, 12, 30)
    with SesionLocal() as sesion:
        categoria = sesion.execute(select(CategoriaReporte.id).limit(1)).scalar_one()
        lecturas = [
            LecturaBiometrica(
                usuario_id=None, dispositivo="prueba", fecha_hora=base + timedelta(minutes=i),
                resultado="rechazada", motivo="no_identificado",
            )
            for i in range(3)
        ]
        sesion.add_all(lecturas)
        sesion.commit()
        ids = [l.id for l in lecturas]

    def asistencia(usuario: int, lectura: int | None) -> Asistencia:
        return Asistencia(
            usuario_id=usuario, fecha_comida=base.date(), comida_id=1,
            categoria_reporte_id=categoria, metodo="manual", lectura_id=lectura,
            fecha_hora=base, registrado_por_cuenta=cuenta,
        )

    def intervencion_fila(lectura: int, clave: str) -> IntervencionLectura:
        return IntervencionLectura(
            lectura_id=lectura, usuario_id=1, cuenta_id=cuenta, clave_idempotencia=clave,
            huella_solicitud="0" * 64, resultado="rechazada", motivo_rechazo="sin_derecho",
            causa=CAUSA, momento=base,
        )

    casos = [
        ("uq_asistencias_racion", [asistencia(1, None), asistencia(1, None)]),
        ("uq_asistencias_lectura_id", [asistencia(2, ids[0]), asistencia(3, ids[0])]),
        (
            "uq_intervenciones_lectura_cuenta_clave",
            [intervencion_fila(ids[1], _clave_fija()), intervencion_fila(ids[2], _clave_fija())],
        ),
    ]
    try:
        for nombre, filas in casos:
            with SesionLocal() as sesion:
                sesion.add(filas[0])
                sesion.commit()
                sesion.add(filas[1])
                with pytest.raises(IntegrityError) as choque:
                    sesion.commit()
                assert choque.value.orig.args[0] == 1062, nombre
                assert nombre in str(choque.value.orig), (nombre, str(choque.value.orig))
    finally:
        _vaciar()


def _clave_fija() -> str:
    return "6f1c2a9e-3b7d-4e0a-9d52-1c8f0b7a4e11"


# --- lo que ve cada rol en ultimas-marcaciones ---------------------------------------


def test_los_valores_iniciales_sin_intervencion_por_rol(cliente, lector, tokens, escenario):
    e = escenario
    lectura = _lectura(lector, e.momento)

    c = _de_la_lectura(_lista(cliente, tokens["cocinera"], e.fecha), lectura)
    assert (c["resultado"], c["motivo"], c["valido"]) == ("rechazada", "no_identificado", False)
    assert c["decision_original"]["resultado"] == "rechazada"
    assert c["decision_original"]["motivo"] == "no_identificado"
    assert c["estado_final"] == "sin_racion" and c["resultado_final"] is None
    assert c["comida_origen"] == "reconstruida_por_horario"
    assert c["puede_identificar"] is True and c["motivo_no_identificable"] is None
    assert datetime.fromisoformat(c["identificable_hasta"]) == datetime.combine(e.fecha, time(15, 0))
    assert c["intervencion"] == {
        "revision": 0, "actualizado_en": None, "resuelta": False, "resuelta_por_mi": False,
    }

    j = _de_la_lectura(_lista(cliente, tokens["jefa"], e.fecha), lectura)
    assert j["puede_identificar"] is False and j["motivo_no_identificable"] is None
    assert j["identificable_hasta"] is None
    assert j["intervencion"] == {
        "revision": 0, "actualizado_en": None, "resuelta": False, "resuelta_por_mi": False,
        "registrada_por": None, "intentos_rechazados": 0,
    }

    s = _de_la_lectura(_lista(cliente, tokens["sistemas"], e.fecha), lectura)
    assert s["puede_identificar"] is False and s["intervencion"] is None
    assert s["decision_original"] == c["decision_original"]  # la separación no identifica a nadie


def test_una_lectura_fuera_de_horario_sin_usuario_se_muestra_como_tal_y_no_es_identificable(
    cliente, lector, tokens, escenario
):
    e = escenario
    lectura = _lectura(lector, datetime.combine(e.fecha, time(10, 30)))
    for rol in ("cocinera", "jefa", "sistemas"):
        f = _de_la_lectura(_lista(cliente, tokens[rol], e.fecha), lectura)
        assert f["motivo"] == "fuera_horario", rol  # el guardado, no no_identificado
        assert f["decision_original"]["motivo"] == "fuera_horario"
        assert (f["puede_identificar"], f["motivo_no_identificable"]) == (False, "lectura_no_resoluble")
        assert f["intervencion"] is None
        assert f["comida_origen"] is None


def test_otro_servicio_se_ve_como_no_identificable_en_la_lista(
    cliente, lector, tokens, escenario
):
    e = escenario
    lectura = _lectura(lector, e.momento)
    reloj_prueba.fijar(datetime.combine(e.fecha, time(16, 0)))
    f = _de_la_lectura(_lista(cliente, tokens["cocinera"], e.fecha), lectura)
    assert (f["puede_identificar"], f["motivo_no_identificable"]) == (False, "servicio_distinto")
    assert f["identificable_hasta"] is None


def test_un_registro_manual_independiente_sigue_separado(cliente, tokens, escenario):
    e = escenario
    reloj_prueba.fijar(e.momento)
    manual = cliente.post(
        "/asistencias", json={"usuario_id": e.usuario_id, "metodo": "manual"}, headers=tokens["jefa"]
    ).json()
    fila = next(f for f in _lista(cliente, tokens["jefa"], e.fecha) if f["origen"] == "asistencia_manual")
    assert fila["clave_evento"] == f"asistencia_manual:{manual['asistencia_id']}"
    assert fila["decision_original"] is None
    assert fila["resultado_final"]["via"] == "registro_manual"
    assert (fila["puede_identificar"], fila["motivo_no_identificable"]) == (False, "no_aplica")
    assert fila["intervencion"] is None
    # Y no aparece entre las intervenciones de cocina.
    assert cliente.get(LISTA, params={"desde": e.fecha.isoformat(), "hasta": e.fecha.isoformat()}, headers=tokens["jefa"]).json()["total"] == 0


def test_revision_sube_con_la_entrega_de_otra_cocinera_sin_revelar_sus_intentos_ni_su_cuenta(
    cliente, lector, tokens, escenario
):
    e = escenario
    a = e.usuario_id
    persona_mala = _sin_derecho(e.fecha)
    lectura = _lectura(lector, e.momento)

    def vista(rol):
        return _de_la_lectura(_lista(cliente, tokens[rol], e.fecha), lectura)

    # cocinera2 prueba una persona sin derecho: un intento rechazado SUYO.
    assert _identificar(cliente, tokens["cocinera2"], lectura, persona_mala, ahora=e.momento).json()["motivo"] == "sin_derecho"
    assert vista("cocinera")["intervencion"]["revision"] == 0  # no se entera de nada
    assert vista("cocinera2")["intervencion"]["revision"] == 1
    assert vista("jefa")["intervencion"]["revision"] == 1
    assert vista("jefa")["intervencion"]["intentos_rechazados"] == 1

    antes = vista("cocinera")
    # cocinera2 registra la entrega.
    assert _identificar(cliente, tokens["cocinera2"], lectura, a, ahora=e.momento + timedelta(minutes=1)).status_code == 200

    despues = vista("cocinera")
    assert despues["clave_evento"] == antes["clave_evento"]  # el mismo evento, ya existía
    assert despues["intervencion"]["revision"] == antes["intervencion"]["revision"] + 1
    assert despues["intervencion"]["resuelta"] is True
    assert despues["intervencion"]["resuelta_por_mi"] is False
    assert set(despues["intervencion"]) == {"revision", "actualizado_en", "resuelta", "resuelta_por_mi"}
    assert despues["estado_final"] == "racion_servida"
    assert despues["resultado_final"]["via"] == "identificacion_manual"
    assert despues["resultado_final"]["comensal"]["usuario_id"] == a
    assert (despues["puede_identificar"], despues["motivo_no_identificable"]) == (False, "lectura_ya_resuelta")
    # La decisión original no se sobrescribió.
    assert despues["decision_original"] == antes["decision_original"]
    assert (despues["resultado"], despues["motivo"], despues["valido"]) == ("rechazada", "no_identificado", False)
    # Nada de la otra cuenta en toda la fila de la cocinera.
    assert "u_cocinera2" not in json.dumps(despues)

    # La que lo hizo ve que fue suya; la jefa ve quién.
    assert vista("cocinera2")["intervencion"]["resuelta_por_mi"] is True
    jefa = vista("jefa")["intervencion"]
    assert jefa["revision"] == 2 and jefa["intentos_rechazados"] == 1
    assert jefa["registrada_por"]["usuario"] == "u_cocinera2"
    assert vista("sistemas")["intervencion"] is None


# --- el listado de la jefa -------------------------------------------------------------


def test_el_listado_de_la_jefa(cliente, lector, tokens, escenario):
    e = escenario
    persona_mala = _sin_derecho(e.fecha)
    lectura = _lectura(lector, e.momento)
    rechazo = _identificar(cliente, tokens["cocinera"], lectura, persona_mala, ahora=e.momento)
    entrega = _identificar(cliente, tokens["cocinera"], lectura, e.usuario_id, ahora=e.momento + timedelta(minutes=1))
    assert (rechazo.status_code, entrega.status_code) == (200, 200)

    dia = e.fecha.isoformat()
    r = cliente.get(LISTA, params={"desde": dia, "hasta": dia}, headers=tokens["jefa"])
    assert r.status_code == 200, r.text
    pagina = r.json()
    assert (pagina["desde"], pagina["hasta"], pagina["total"]) == (dia, dia, 2)
    assert (pagina["limite"], pagina["desplazamiento"]) == (50, 0)
    assert pagina["totales"] == {"registradas": 1, "rechazadas": 1}
    registrada, rechazada = pagina["datos"]  # la más reciente primero
    assert registrada["resultado"] == "registrada" and rechazada["resultado"] == "rechazada"
    assert registrada["clave_evento"] == f"intervencion_lectura:{registrada['id']}"
    assert registrada["motivo_rechazo"] is None and rechazada["motivo_rechazo"] == "sin_derecho"
    assert registrada["causa"] == rechazada["causa"] == CAUSA
    assert registrada["decision_original"]["lectura_id"] == lectura
    assert registrada["decision_original"]["motivo"] == "no_identificado"
    assert registrada["cuenta"]["usuario"] == "u_cocinera"
    assert registrada["comensal"]["usuario_id"] == e.usuario_id
    assert registrada["servicio_usado"]["origen"] == "reconstruido_por_horario"
    assert registrada["servicio_usado"]["fecha_comida"] == dia
    assert registrada["resultado_final"] == {"entrega_registrada": True, "asistencia_id": entrega.json()["asistencia_id"]}
    # El intento rechazado nunca es una entrega, aunque la lectura ya esté resuelta.
    assert rechazada["resultado_final"] == {"entrega_registrada": False, "asistencia_id": None}
    assert registrada["estado_actual_lectura"] == rechazada["estado_actual_lectura"] == "resuelta"

    # Filtros, paginación y totales sobre todo el filtro.
    sola = cliente.get(LISTA, params={"desde": dia, "hasta": dia, "resultado": "rechazada"}, headers=tokens["jefa"]).json()
    assert [d["resultado"] for d in sola["datos"]] == ["rechazada"] and sola["total"] == 1
    primera = cliente.get(LISTA, params={"desde": dia, "hasta": dia, "limite": 1}, headers=tokens["jefa"]).json()
    assert len(primera["datos"]) == 1 and primera["total"] == 2
    assert primera["totales"] == {"registradas": 1, "rechazadas": 1}
    otra_cuenta = cliente.get(
        LISTA, params={"desde": dia, "hasta": dia, "cuenta_id": _id_de_cuenta("u_cocinera2")}, headers=tokens["jefa"]
    ).json()
    assert otra_cuenta["total"] == 0 and otra_cuenta["datos"] == []


def test_el_listado_vacio_y_sus_limites(cliente, tokens, vacio):
    jefa = tokens["jefa"]
    reloj_prueba.fijar(datetime(2026, 9, 24, 12, 0))
    r = cliente.get(LISTA, headers=jefa)  # por defecto, hoy
    assert r.status_code == 200
    assert r.json()["desde"] == r.json()["hasta"] == "2026-09-24"
    assert r.json()["datos"] == [] and r.json()["totales"] == {"registradas": 0, "rechazadas": 0}

    largo = cliente.get(LISTA, params={"desde": "2026-01-01", "hasta": "2026-02-01"}, headers=jefa)
    assert largo.status_code == 422 and largo.json()["motivo"] == "rango_demasiado_largo"
    justo = cliente.get(LISTA, params={"desde": "2026-01-01", "hasta": "2026-01-31"}, headers=jefa)
    assert justo.status_code == 200
    al_reves = cliente.get(LISTA, params={"desde": "2026-02-01", "hasta": "2026-01-01"}, headers=jefa)
    assert al_reves.status_code == 422 and al_reves.json()["motivo"] == "rango_invalido"
    assert cliente.get(LISTA, params={"limite": 0}, headers=jefa).status_code == 422
    assert cliente.get(LISTA, params={"limite": 101}, headers=jefa).status_code == 422
    assert cliente.get(LISTA, params={"resultado": "otra"}, headers=jefa).status_code == 422


def test_los_motivos_del_filtro_son_los_del_modelo():
    from typing import get_args

    from app.api.intervenciones import MotivoRechazo
    from app.modelos.comedor import MOTIVOS_RECHAZO_INTERVENCION

    assert set(get_args(MotivoRechazo)) == set(MOTIVOS_RECHAZO_INTERVENCION)


# --- errores de integridad que NO son concurrencia ---------------------------------------


def _servidor_sin_propagar() -> TestClient:
    """Para ver el 500 que recibiría el cliente en vez de que la prueba reviente."""
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("camino", ["entrega", "rechazo"])
def test_un_fallo_de_integridad_ajeno_en_la_auditoria_no_se_disfraza_de_concurrencia(
    cliente, lector, tokens, escenario, monkeypatch, camino
):
    """La FK de `cuenta_id` falla al insertar la auditoría. No es un duplicado ni
    la clave existe: es un fallo interno (500), no `intervencion_en_curso`, y no
    queda NADA: ni la fila, ni la ración que ya estaba dentro de la transacción."""
    e = escenario
    coci = tokens["cocinera"]
    persona = e.usuario_id if camino == "entrega" else _sin_derecho(e.fecha)
    lectura = _lectura(lector, e.momento)
    original = intervencion._nueva_fila

    def con_cuenta_inexistente(*args, **kwargs):
        fila = original(*args, **kwargs)
        fila.cuenta_id = 999_999_999
        return fila

    clave = _clave()
    with monkeypatch.context() as parche:
        parche.setattr(intervencion, "_nueva_fila", con_cuenta_inexistente)
        reloj_prueba.fijar(e.momento)
        r = _servidor_sin_propagar().post(
            POST.format(lectura),
            json={"usuario_id": persona},
            headers={**coci, "Idempotency-Key": clave},
        )
    assert r.status_code == 500, r.text
    assert "intervencion_en_curso" not in r.text
    assert (_contar("asistencias"), _contar("intervenciones_lectura")) == (0, 0)
    _verificar_coherencia()

    # Nada quedó trabado: sin el fallo, la misma clave se resuelve normalmente.
    ok = _identificar(cliente, coci, lectura, persona, clave=clave)
    assert ok.status_code == 200 and ok.json()["reintento"] is False, ok.text
    assert _contar("intervenciones_lectura") == 1


def test_un_fallo_de_integridad_ajeno_en_la_racion_no_se_clasifica_como_duplicado(
    cliente, lector, tokens, escenario, monkeypatch
):
    """La FK de `categoria_reporte_id` falla al insertar la ración (1452, no
    1062). No se consulta si "casualmente" hay otra ración: se propaga como
    fallo interno y no queda auditoría ni ración."""
    e = escenario
    coci = tokens["cocinera"]
    lectura = _lectura(lector, e.momento)
    with monkeypatch.context() as parche:
        parche.setattr(intervencion, "categoria_reporte_de", lambda *a, **k: 999_999_999)
        reloj_prueba.fijar(e.momento)
        r = _servidor_sin_propagar().post(
            POST.format(lectura),
            json={"usuario_id": e.usuario_id},
            headers={**coci, "Idempotency-Key": _clave()},
        )
    assert r.status_code == 500, r.text
    assert "duplicado" not in r.text and "intervencion_en_curso" not in r.text
    assert (_contar("asistencias"), _contar("intervenciones_lectura")) == (0, 0)
    _verificar_coherencia()
    # La lectura sigue pendiente.
    assert _identificar(cliente, coci, lectura, e.usuario_id).status_code == 200


def test_un_duplicado_que_no_es_de_la_clave_ni_de_la_racion_se_propaga(
    cliente, lector, tokens, sintetico, monkeypatch
):
    """Un 1062 sobre la auditoría cuando la clave NO existe (aquí, el UNIQUE de
    `asistencia_id`) no es la carrera reconocida: tampoco se disfraza."""
    e = sintetico
    coci = tokens["cocinera"]
    a, b = e.personas[:2]
    primera = _lectura(lector, e.momento)
    segunda = _lectura(lector, e.momento + timedelta(minutes=1))
    assert _identificar(cliente, coci, primera, a, ahora=e.momento + timedelta(minutes=2)).status_code == 200
    asistencia_ocupada = _filas("SELECT id FROM asistencias")[0][0]

    original = intervencion._nueva_fila

    def con_la_asistencia_de_otra(*args, **kwargs):
        fila = original(*args, **kwargs)
        if kwargs.get("resultado") == "registrada":
            fila.asistencia_id = asistencia_ocupada
        return fila

    with monkeypatch.context() as parche:
        parche.setattr(intervencion, "_nueva_fila", con_la_asistencia_de_otra)
        r = _servidor_sin_propagar().post(
            POST.format(segunda),
            json={"usuario_id": b},
            headers={**coci, "Idempotency-Key": _clave()},
        )
    assert r.status_code == 500, r.text
    assert "intervencion_en_curso" not in r.text
    # Solo sigue lo de la primera: la ración de la segunda se deshizo con la auditoría.
    assert (_contar("asistencias"), _contar("intervenciones_lectura")) == (1, 1)
    _verificar_coherencia()


# --- la coherencia resultado / asistencia_id ----------------------------------------------


def test_la_base_no_impide_una_registrada_sin_asistencia_pero_la_comprobacion_la_detecta(
    cliente, lector, tokens, escenario
):
    """Documenta que NINGÚN CHECK protege `resultado` contra `asistencia_id`: la
    base acepta la fila incoherente. Por eso `_verificar_coherencia` revisa cada
    prueba al final, y aquí se comprueba que de verdad detecta el problema."""
    e = escenario
    lectura = _lectura(lector, e.momento)
    cuenta = _id_de_cuenta("u_cocinera")
    try:
        with SesionLocal() as sesion:
            sesion.execute(
                text(
                    "INSERT INTO intervenciones_lectura (lectura_id, usuario_id, cuenta_id, "
                    "clave_idempotencia, huella_solicitud, resultado, motivo_rechazo, causa, momento) "
                    "VALUES (:l, 1, :c, :k, :h, 'registrada', NULL, :causa, '2026-09-24 12:31:00.000000')"
                ),
                {"l": lectura, "c": cuenta, "k": _clave(), "h": "0" * 64, "causa": CAUSA},
            )
            sesion.commit()
        with pytest.raises(AssertionError, match="registrada sin asistencia"):
            _verificar_coherencia()
    finally:
        _vaciar()


def test_varias_personas_a_la_vez_dejan_una_registrada_y_el_resto_rechazadas(
    cliente, lector, tokens, sintetico, aislamiento
):
    e = sintetico
    personas = e.personas[:3]
    lectura = _lectura(lector, e.momento)
    reloj_prueba.fijar(e.momento)
    resultados: dict = {}
    cuentas = ["cocinera", "cocinera2"]
    with retener_lectura(lectura):
        hilos = [
            _lanzar(resultados, f"h{i}", tokens[cuentas[i % 2]], lectura, persona, _clave())
            for i, persona in enumerate(personas)
        ]
        tiempo.sleep(ESPERA)
        assert all(h.is_alive() for h in hilos)
    _terminar(hilos)

    estados = sorted(r.status_code for r in resultados.values())
    assert estados == [200] + [409] * (len(personas) - 1), {k: v.text for k, v in resultados.items()}
    assert _contar("asistencias") == 1
    assert _filas(
        "SELECT resultado, COUNT(*) FROM intervenciones_lectura GROUP BY resultado ORDER BY resultado"
    ) == [("registrada", 1), ("rechazada", len(personas) - 1)]
    _verificar_coherencia()


# --- las lecturas por identificar: ni la fecha ni las 100 filas --------------------------------


def test_lecturas_por_identificar_es_solo_de_la_cocinera(cliente, tokens, con_horarios):
    for quien in ("jefa", "sistemas"):
        r = cliente.get(POR_IDENTIFICAR, headers=tokens[quien])
        assert r.status_code == 403, r.text
        assert r.json()["motivo"] == "rol_no_autorizado"
    assert cliente.get(POR_IDENTIFICAR, headers=tokens["cocinera"]).status_code == 200
    assert cliente.get(POR_IDENTIFICAR).status_code == 401


def test_lecturas_por_identificar_trae_solo_las_del_servicio_actual_y_pendientes(
    cliente, lector, tokens, sintetico
):
    e = sintetico
    coci = tokens["cocinera"]
    a, b = e.personas[:2]
    temprana = _lectura(lector, datetime.combine(e.fecha, time(11, 5)))
    resuelta = _lectura(lector, datetime.combine(e.fecha, time(11, 10)))
    con_usuario = _lectura(
        lector, datetime.combine(e.fecha, time(11, 20)), usuario_id=USUARIO_INEXISTENTE
    )
    fuera_de_servicio = _lectura(lector, datetime.combine(e.fecha, time(10, 30)))
    otro_servicio = _lectura(lector, datetime.combine(e.fecha, time(15, 30)))
    reciente = _lectura(lector, e.momento)
    assert _identificar(cliente, coci, resuelta, a, ahora=datetime.combine(e.fecha, time(11, 30))).status_code == 200

    reloj_prueba.fijar(datetime.combine(e.fecha, time(13, 0)))
    r = cliente.get(POR_IDENTIFICAR, headers=coci)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["servicio"]["fecha_comida"] == e.fecha.isoformat()
    assert datetime.fromisoformat(cuerpo["servicio"]["inicio"]) == datetime.combine(e.fecha, time(11, 0))
    assert datetime.fromisoformat(cuerpo["servicio"]["fin"]) == datetime.combine(e.fecha, time(15, 0))
    # Solo las pendientes del almuerzo, la más reciente primero.
    assert [f["id"] for f in cuerpo["lecturas"]] == [reciente, temprana]
    assert (cuerpo["total"], cuerpo["truncado"]) == (2, False)
    for fila in cuerpo["lecturas"]:
        assert fila["puede_identificar"] is True and fila["motivo_no_identificable"] is None
        assert fila["clave_evento"] == f"lectura_biometrica:{fila['id']}"
        assert fila["intervencion"] == {
            "revision": 0, "actualizado_en": None, "resuelta": False, "resuelta_por_mi": False,
        }
        assert fila["comida_origen"] == "reconstruida_por_horario"
    excluidas = {resuelta, con_usuario, fuera_de_servicio, otro_servicio}
    assert excluidas.isdisjoint({f["id"] for f in cuerpo["lecturas"]})


def test_lecturas_por_identificar_no_depende_de_la_ventana_de_la_lista_ni_del_limite(
    cliente, lector, tokens, escenario
):
    e = escenario
    coci = tokens["cocinera"]
    ids = [
        _lectura(lector, e.momento + timedelta(minutes=m)) for m in range(3)
    ]
    # La lista por fecha corta: con límite 1 solo trae la más reciente.
    corta = cliente.get(PANTALLA, params={"fecha": e.fecha.isoformat(), "limite": 1}, headers=coci).json()
    assert len(corta) == 1
    # La específica trae las tres, sin pasar por esa ventana.
    cuerpo = cliente.get(POR_IDENTIFICAR, headers=coci).json()
    assert sorted(f["id"] for f in cuerpo["lecturas"]) == sorted(ids)


def test_lecturas_por_identificar_avisa_si_llega_al_tope(
    cliente, lector, tokens, escenario, monkeypatch
):
    e = escenario
    coci = tokens["cocinera"]
    for m in range(3):
        _lectura(lector, e.momento + timedelta(minutes=m))
    monkeypatch.setattr(consultas_pantalla, "MAXIMO_POR_IDENTIFICAR", 2)
    cuerpo = cliente.get(POR_IDENTIFICAR, headers=coci).json()
    assert cuerpo["truncado"] is True
    assert len(cuerpo["lecturas"]) == 2 == cuerpo["total"]


def test_lecturas_por_identificar_sin_servicio_va_vacia(cliente, lector, tokens, escenario):
    e = escenario
    coci = tokens["cocinera"]
    _lectura(lector, datetime.combine(e.fecha, time(10, 30)))  # franja sin cubrir
    cuerpo = cliente.get(POR_IDENTIFICAR, headers=coci).json()
    assert cuerpo == {"servicio": None, "total": 0, "truncado": False, "lecturas": []}


def test_lecturas_por_identificar_no_revela_nada_de_otras_cuentas(
    cliente, lector, tokens, escenario
):
    e = escenario
    persona_mala = _sin_derecho(e.fecha)
    lectura = _lectura(lector, e.momento)
    assert _identificar(cliente, tokens["cocinera2"], lectura, persona_mala, ahora=e.momento).json()["motivo"] == "sin_derecho"
    fila = cliente.get(POR_IDENTIFICAR, headers=tokens["cocinera"]).json()["lecturas"][0]
    assert fila["intervencion"]["revision"] == 0  # el intento rechazado ajeno no cuenta ni se nota
    assert "u_cocinera2" not in json.dumps(fila)
    propia = cliente.get(POR_IDENTIFICAR, headers=tokens["cocinera2"]).json()["lecturas"][0]
    assert propia["intervencion"]["revision"] == 1


def test_una_lectura_de_ayer_en_un_servicio_nocturno_se_recupera_y_se_sigue(
    cliente, lector, tokens, root, vacio
):
    """El caso que `ultimas-marcaciones` no puede cubrir: a las 00:30 la lectura
    de las 23:58 sigue en el servicio, pero la consulta por la fecha de hoy no la
    trae. La cocina la sigue con `lecturas-por-identificar`."""
    persona, fecha = _candidato_cena()
    coci = tokens["cocinera"]
    ayer, hoy = fecha, fecha + timedelta(days=1)
    cena = comida_id("cena")
    fijar(datetime.combine(ayer, time(9)))
    assert guardar(cliente, root, cena, "22:00:00", "02:00:00", None).status_code == 201
    lectura = _lectura(lector, datetime.combine(ayer, time(23, 58)))
    otra = _lectura(lector, datetime.combine(ayer, time(23, 59)))

    madrugada = datetime.combine(hoy, time(0, 30))
    reloj_prueba.fijar(madrugada)
    clave = f"lectura_biometrica:{lectura}"
    # La lista por fecha de HOY no la trae: es de ayer.
    assert clave not in [f["clave_evento"] for f in _lista(cliente, coci, hoy)]

    cuerpo = cliente.get(POR_IDENTIFICAR, headers=coci).json()
    assert cuerpo["servicio"]["fecha_comida"] == ayer.isoformat()
    assert sorted(f["clave_evento"] for f in cuerpo["lecturas"]) == sorted(
        [clave, f"lectura_biometrica:{otra}"]
    )
    fila = next(f for f in cuerpo["lecturas"] if f["clave_evento"] == clave)
    assert fila["puede_identificar"] is True and fila["intervencion"]["revision"] == 0

    # Se identifica a las 00:30: el POST y la lista dicen lo mismo.
    ok = _identificar(cliente, coci, lectura, persona)
    assert ok.status_code == 200, ok.text
    assert ok.json()["fecha_comida"] == ayer.isoformat()
    restantes = cliente.get(POR_IDENTIFICAR, headers=coci).json()["lecturas"]
    assert [f["clave_evento"] for f in restantes] == [f"lectura_biometrica:{otra}"]
    # Su estado final se ve en la lista de la fecha de la LECTURA (ayer).
    final = _de_la_lectura(_lista(cliente, coci, ayer), lectura)
    assert final["estado_final"] == "racion_servida" and final["intervencion"]["revision"] == 1

    # Termina el servicio (02:00): sale de la lista y el POST ya no la acepta.
    reloj_prueba.fijar(datetime.combine(hoy, time(2, 30)))
    vacia = cliente.get(POR_IDENTIFICAR, headers=coci).json()
    assert (vacia["servicio"], vacia["lecturas"]) == (None, [])
    tarde = _identificar(cliente, coci, otra, persona)
    assert tarde.status_code == 409 and tarde.json()["motivo"] == "servicio_distinto"


def test_los_reemplazos_sinteticos_solo_cubren_a_las_personas_sinteticas(sintetico):
    """Los ids sintéticos no existen en el padrón real, el reemplazo solo habla de
    ellas y todo lo demás llega a las consultas reales (solo SELECT)."""
    e = sintetico
    with SesionLocal() as sesion:
        reales = sesion.execute(select(Comensal.usuario_id).where(Comensal.usuario_id.in_(e.personas))).all()
        assert reales == []  # ninguna colisiona con una persona real

        for persona in e.personas:
            derecho = intervencion.buscar_derecho(sesion, persona, e.comida_id, e.fecha)
            assert derecho is not None and derecho.fecha_comida == e.fecha and derecho.comida_id == e.comida_id
            assert intervencion.nombre_en_padron(sesion, persona)[0].startswith("Persona sintética")
        # Otra fecha u otra comida de la misma persona: no hay derecho (consulta real).
        assert intervencion.buscar_derecho(sesion, e.personas[0], e.comida_id, e.fecha + timedelta(days=1)) is None
        assert intervencion.buscar_derecho(sesion, e.personas[0], e.comida_id + 10_000, e.fecha) is None
        # Quien no es sintético sigue yendo a las consultas reales.
        assert intervencion.nombre_en_padron(sesion, USUARIO_INEXISTENTE) is None
        assert intervencion.buscar_derecho(sesion, USUARIO_INEXISTENTE, e.comida_id, e.fecha) is None
