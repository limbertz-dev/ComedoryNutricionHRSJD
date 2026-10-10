"""GET /monitoreo/estado: el diagnóstico técnico de sistemas (R3-1-20261009).

Las marcaciones se generan por la API (POST /asistencias) con el reloj de
simulación, nunca con INSERT directo. Las tablas ausentes y los fallos de
consulta se simulan reescribiendo el SQL que llega a MySQL desde el motor de
la app: sin DROP, sin DDL y sin tocar bases reales.
"""

import re
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.consultas import monitoreo as consultas_monitoreo
from app.core import reloj
from app.core.config import config
from app.core.db import Base, SesionLocal, motor, obtener_sesion
from app.main import app, crear_app
from app.semillas import horarios
from conftest import encabezado, ingresar
from test_simulacion import _candidato_almuerzo

RUTA = "/monitoreo/estado"
RELOJ = "/simulacion/reloj"
DIA = datetime(2026, 9, 24, 12, 30)  # dentro del almuerzo de la semilla
USUARIO_INEXISTENTE = 999_999_999  # da sin_derecho sin depender del padrón
DISPOSITIVO = "disp-marcador-r3"
SQL_QUE_FALLA = "SELECT 1 FROM r3_tabla_inexistente"

CONSULTA_CONTADOR = ("FROM lecturas_biometricas", "GROUP BY")
CONSULTA_MAYOR_ID = ("FROM lecturas_biometricas", "ORDER BY lecturas_biometricas.id DESC")
# Cualquier lectura de la tabla de actividad (FROM o columna calificada).
TOCA_LECTURAS = re.compile(
    r"\bFROM\s+`?lecturas_biometricas\b|\blecturas_biometricas`?\.", re.IGNORECASE
)

CLAVES = {"momento_real", "entorno", "reloj_negocio", "base", "lector", "actividad"}
CLAVES_RELOJ = {"ahora", "fecha", "simulado", "congelado"}
CLAVES_BASE = {"estado", "revision_alembic", "tablas_propias", "vistas_contrato", "faltan"}
CLAVES_ACTIVIDAD = {
    "fuente", "disponible", "razon", "aceptadas_dia", "rechazadas_dia", "registro_mayor_id",
}
CLAVES_REGISTRO = {"id", "fecha_hora", "resultado", "motivo", "created_at"}
LECTOR = {"estado": "desconocido", "razon": "sin_telemetria"}
PROHIBIDAS = {
    "usuario_id", "nombre", "nombre_completo", "carnet_identidad", "login",
    "username", "dispositivo", "base_datos", "base_turnos", "motor", "detail",
}
CLAVES_SALUD = {
    "estado", "base_de_datos", "entorno", "reloj", "base_datos", "base_turnos",
    "motor", "revision_alembic", "tablas_propias", "vistas_contrato", "faltan",
}


def _sin_actividad(razon: str) -> dict:
    return {
        "fuente": "lecturas_biometricas",
        "disponible": False,
        "razon": razon,
        "aceptadas_dia": None,
        "rechazadas_dia": None,
        "registro_mayor_id": None,
    }


# --- fixtures -----------------------------------------------------------------


@pytest.fixture(autouse=True)
def reloj_real():
    reloj.volver_a_real()
    yield
    reloj.volver_a_real()


@pytest.fixture
def sim() -> TestClient:
    return TestClient(crear_app("simulacion"))


@pytest.fixture
def tokens(cliente, crear_usuario) -> dict[str, dict[str, str]]:
    for rol in ("jefa", "cocinera", "sistemas"):
        crear_usuario(f"u_{rol}", rol=rol)
    return {
        rol: encabezado(ingresar(cliente, f"u_{rol}")["access"])
        for rol in ("jefa", "cocinera", "sistemas")
    }


def _vaciar_marcaciones() -> None:
    with SesionLocal() as sesion:
        sesion.execute(text("DELETE FROM asistencias"))
        sesion.execute(text("DELETE FROM lecturas_biometricas"))
        sesion.commit()


@pytest.fixture
def sin_marcaciones():
    _vaciar_marcaciones()
    yield
    _vaciar_marcaciones()


@pytest.fixture
def con_horarios(sin_marcaciones):
    horarios.sembrar()
    yield
    with SesionLocal() as sesion:
        sesion.execute(text("DELETE FROM horarios_comida"))
        sesion.commit()


class ControlSQL:
    """Ve cada sentencia del motor de la app y, si se le pide, la reemplaza."""

    def __init__(self) -> None:
        self.vistas: list[str] = []
        self.reglas: list[tuple[tuple[str, ...], object]] = []

    def reemplazar(self, *fragmentos: str, por) -> None:
        """`por`: la sentencia nueva, o una función de la original."""
        self.reglas.append((fragmentos, por))

    def antes(self, conexion, cursor, sentencia, parametros, contexto, multiples):
        self.vistas.append(sentencia)
        for fragmentos, por in self.reglas:
            if all(f in sentencia for f in fragmentos):
                return (por(sentencia) if callable(por) else por), parametros
        return sentencia, parametros


@pytest.fixture
def sql():
    control = ControlSQL()
    event.listen(motor, "before_cursor_execute", control.antes, retval=True)
    yield control
    event.remove(motor, "before_cursor_execute", control.antes)


def _marcar(sim, tokens, momento: datetime, **cuerpo) -> dict:
    """Una marcación biométrica por la API, con el reloj congelado en `momento`."""
    r = sim.put(
        RELOJ, json={"momento": momento.isoformat(), "congelar": True}, headers=tokens["jefa"]
    )
    assert r.status_code == 200, r.text
    r = sim.post(
        "/asistencias", json={"metodo": "biometrico", **cuerpo}, headers=tokens["cocinera"]
    )
    assert r.status_code == 200, r.text
    return r.json()


def _claves(valor) -> set[str]:
    if isinstance(valor, dict):
        return set(valor) | {c for v in valor.values() for c in _claves(v)}
    if isinstance(valor, list):
        return {c for v in valor for c in _claves(v)}
    return set()


def _sin_cuerpo_de_diagnostico(respuesta) -> None:
    assert respuesta.status_code == 500
    for clave in ("momento_real", "reloj_negocio", "actividad", "lector"):
        assert clave not in respuesta.text
    assert "simulad" not in respuesta.text  # ni el texto de la excepción


# --- permisos -----------------------------------------------------------------


@pytest.mark.parametrize("rol", ["jefa", "cocinera"])
def test_solo_sistemas(cliente, tokens, rol):
    r = cliente.get(RUTA, headers=tokens[rol])
    assert r.status_code == 403
    assert r.json()["motivo"] == "rol_no_autorizado"
    assert r.json()["detail"]
    assert cliente.get(RUTA, headers=tokens["sistemas"]).status_code == 200


def test_sin_token_401(cliente):
    r = cliente.get(RUTA)
    assert r.status_code == 401
    assert r.json()["motivo"] == "falta_token"
    assert r.json()["detail"]


def test_token_temporal_403(cliente, crear_usuario):
    crear_usuario("nueva", rol="sistemas", clave="temporal-123", debe_cambiar=True)
    temporal = cliente.post(
        "/auth/login", json={"username": "nueva", "password": "temporal-123"}
    ).json()["temporal"]
    r = cliente.get(RUTA, headers=encabezado(temporal))
    assert r.status_code == 403
    assert r.json()["motivo"] == "cambio_password_pendiente"
    assert r.json()["detail"]


# --- forma y datos ------------------------------------------------------------


def test_tabla_vacia_da_ceros_y_registro_null(cliente, tokens, sin_marcaciones):
    r = cliente.get(RUTA, headers=tokens["sistemas"])
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert set(cuerpo) == CLAVES
    assert set(cuerpo["reloj_negocio"]) == CLAVES_RELOJ
    assert set(cuerpo["base"]) == CLAVES_BASE
    assert cuerpo["base"]["estado"] == "ok"
    assert cuerpo["base"]["faltan"] == []
    assert cuerpo["lector"] == LECTOR
    assert cuerpo["entorno"] == config.entorno
    assert cuerpo["actividad"] == {
        "fuente": "lecturas_biometricas",
        "disponible": True,
        "razon": None,
        "aceptadas_dia": 0,
        "rechazadas_dia": 0,
        "registro_mayor_id": None,
    }


@pytest.mark.usefixtures("con_horarios")
def test_diagnostico_normal_sin_cache(sim, tokens):
    antes = _marcar(sim, tokens, DIA)
    assert antes["motivo"] == "no_identificado", antes
    primera = sim.get(RUTA, headers=tokens["sistemas"]).json()["actividad"]
    assert (primera["aceptadas_dia"], primera["rechazadas_dia"]) == (0, 1)

    ultima = _marcar(sim, tokens, DIA + timedelta(minutes=1), usuario_id=USUARIO_INEXISTENTE)
    assert ultima["motivo"] == "sin_derecho", ultima

    # Cada petición consulta de nuevo: la segunda ve la marcación nueva.
    cuerpo = sim.get(RUTA, headers=tokens["sistemas"]).json()
    actividad = cuerpo["actividad"]
    assert set(actividad) == CLAVES_ACTIVIDAD
    assert actividad["disponible"] is True and actividad["razon"] is None
    assert (actividad["aceptadas_dia"], actividad["rechazadas_dia"]) == (0, 2)
    registro = actividad["registro_mayor_id"]
    assert set(registro) == CLAVES_REGISTRO
    assert registro["id"] == ultima["lectura_id"]
    assert registro["fecha_hora"] == "2026-09-24T12:31:00"
    assert (registro["resultado"], registro["motivo"]) == ("rechazada", "sin_derecho")
    assert datetime.fromisoformat(registro["created_at"]).tzinfo is None
    # Un rechazo de negocio no dice nada del lector.
    assert cuerpo["lector"] == LECTOR


@pytest.mark.usefixtures("con_horarios")
def test_aceptada_cuenta_en_aceptadas(sim, tokens):
    usuario_id, fecha = _candidato_almuerzo()
    marcada = _marcar(sim, tokens, datetime.combine(fecha, DIA.time()), usuario_id=usuario_id)
    assert marcada["valido"] is True, marcada

    cuerpo = sim.get(RUTA, headers=tokens["sistemas"]).json()
    actividad = cuerpo["actividad"]
    assert (actividad["aceptadas_dia"], actividad["rechazadas_dia"]) == (1, 0)
    registro = actividad["registro_mayor_id"]
    assert registro["id"] == marcada["lectura_id"]
    assert (registro["resultado"], registro["motivo"]) == ("aceptada", None)
    assert cuerpo["lector"] == LECTOR


@pytest.mark.usefixtures("con_horarios")
def test_mayor_id_fuera_del_dia_consultado(sim, tokens):
    del_dia = _marcar(sim, tokens, DIA)
    assert del_dia["motivo"] == "no_identificado", del_dia
    # La última en escribirse es de la madrugada del día ANTERIOR.
    anterior = _marcar(sim, tokens, datetime(2026, 9, 23, 3, 0))
    assert anterior["motivo"] == "fuera_horario", anterior

    r = sim.put(
        RELOJ, json={"momento": "2026-09-24T13:00:00", "congelar": True}, headers=tokens["jefa"]
    )
    assert r.status_code == 200, r.text
    actividad = sim.get(RUTA, headers=tokens["sistemas"]).json()["actividad"]
    # Los contadores son del día de negocio; el registro, de toda la tabla.
    assert (actividad["aceptadas_dia"], actividad["rechazadas_dia"]) == (0, 1)
    registro = actividad["registro_mayor_id"]
    assert registro["id"] == anterior["lectura_id"] > del_dia["lectura_id"]
    assert registro["fecha_hora"] == "2026-09-23T03:00:00"
    assert registro["motivo"] == "fuera_horario"


@pytest.mark.usefixtures("con_horarios")
def test_sin_datos_personales_ni_dispositivo(sim, tokens):
    _marcar(sim, tokens, DIA, dispositivo=DISPOSITIVO)
    _marcar(sim, tokens, DIA, usuario_id=USUARIO_INEXISTENTE, dispositivo=DISPOSITIVO)

    r = sim.get(RUTA, headers=tokens["sistemas"])
    assert r.status_code == 200, r.text
    assert _claves(r.json()) & PROHIBIDAS == set()
    assert DISPOSITIVO not in r.text
    assert str(USUARIO_INEXISTENTE) not in r.text
    assert config.db_name not in r.text
    assert "u_sistemas" not in r.text


@pytest.mark.parametrize("entorno", ["produccion", "desarrollo", "simulacion"])
def test_lector_desconocido_en_todos_los_entornos(tokens, entorno):
    r = TestClient(crear_app(entorno)).get(RUTA, headers=tokens["sistemas"])
    assert r.status_code == 200, r.text
    assert r.json()["lector"] == LECTOR
    # El de la app que respondió, no el de config.
    assert r.json()["entorno"] == entorno


# --- relojes ------------------------------------------------------------------


@pytest.mark.parametrize("congelar", [True, False])
def test_reloj_fijado_frente_a_momento_real(sim, tokens, monkeypatch, congelar):
    r = sim.put(
        RELOJ, json={"momento": DIA.isoformat(), "congelar": congelar}, headers=tokens["jefa"]
    )
    assert r.status_code == 200, r.text

    llamadas = []
    original = reloj.estado

    def espia():
        llamadas.append(1)
        return original()

    monkeypatch.setattr(reloj, "estado", espia)
    cuerpo = sim.get(RUTA, headers=tokens["sistemas"]).json()

    assert llamadas == [1]  # una sola foto del reloj por petición
    negocio = cuerpo["reloj_negocio"]
    assert negocio["simulado"] is True
    assert negocio["congelado"] is congelar
    assert negocio["fecha"] == "2026-09-24"
    ahora = datetime.fromisoformat(negocio["ahora"])
    assert ahora.tzinfo is None
    assert timedelta(0) <= ahora - DIA < timedelta(seconds=5)
    momento_real = datetime.fromisoformat(cuerpo["momento_real"])
    assert momento_real.tzinfo is None
    assert abs(momento_real - datetime.now()) < timedelta(seconds=5)


# --- tabla ausente y fallos -----------------------------------------------------


@pytest.mark.usefixtures("con_horarios")
def test_tabla_ausente_no_se_consulta(sim, tokens, sql):
    _marcar(sim, tokens, DIA)  # la tabla tiene datos: lo que sale no puede ser cero
    sql.reemplazar(
        "information_schema.TABLES",
        por=lambda s: s.replace(
            "WHERE TABLE_SCHEMA = DATABASE()",
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME <> 'lecturas_biometricas'",
        ),
    )
    desde = len(sql.vistas)
    r = sim.get(RUTA, headers=tokens["sistemas"])

    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert [s for s in sql.vistas[desde:] if TOCA_LECTURAS.search(s)] == []
    assert cuerpo["actividad"] == _sin_actividad("tabla_ausente")
    assert cuerpo["base"]["estado"] == "incompleta"
    assert cuerpo["base"]["faltan"] == ["lecturas_biometricas"]
    assert cuerpo["base"]["tablas_propias"] == len(Base.metadata.tables) - 1
    assert cuerpo["lector"] == LECTOR


@pytest.mark.usefixtures("con_horarios")
@pytest.mark.parametrize(
    "consulta", [CONSULTA_CONTADOR, CONSULTA_MAYOR_ID], ids=["contador", "mayor_id"]
)
def test_fallo_de_actividad_no_da_ceros_y_recupera_la_sesion(
    sim, tokens, sql, monkeypatch, consulta
):
    _marcar(sim, tokens, DIA)
    rollbacks = []
    original = Session.rollback

    def espia(self):
        rollbacks.append(1)
        return original(self)

    monkeypatch.setattr(Session, "rollback", espia)
    sql.reemplazar(*consulta, por=SQL_QUE_FALLA)
    desde = len(sql.vistas)
    r = sim.get(RUTA, headers=tokens["sistemas"])

    assert r.status_code == 200, r.text
    cuerpo = r.json()
    # Si falla la segunda, la primera (que funcionó) también se descarta.
    assert cuerpo["actividad"] == _sin_actividad("error_consulta")
    assert cuerpo["base"]["estado"] == "ok"
    assert cuerpo["lector"] == LECTOR
    assert rollbacks
    # Nada se lee después del fallo: ni la otra consulta ni recargas implícitas.
    ejecutadas = sql.vistas[desde:]
    assert all(f in ejecutadas[-1] for f in consulta)
    assert "r3_tabla_inexistente" not in r.text

    # La sesión siguiente funciona: el fallo no dejó nada roto.
    sql.reglas.clear()
    actividad = sim.get(RUTA, headers=tokens["sistemas"]).json()["actividad"]
    assert actividad["disponible"] is True
    assert actividad["rechazadas_dia"] == 1


def test_si_falla_el_rollback_no_hay_diagnostico(tokens, sql, monkeypatch, sin_marcaciones):
    def rollback_roto(self):
        raise OperationalError("ROLLBACK", {}, Exception("rollback simulado"))

    monkeypatch.setattr(Session, "rollback", rollback_roto)
    sql.reemplazar(*CONSULTA_CONTADOR, por=SQL_QUE_FALLA)
    r = TestClient(app, raise_server_exceptions=False).get(RUTA, headers=tokens["sistemas"])
    _sin_cuerpo_de_diagnostico(r)


@pytest.mark.parametrize(
    "fragmento", ["information_schema.TABLES", "FROM alembic_version"],
    ids=["catalogo", "revision"],
)
def test_fallo_de_catalogo_no_da_diagnostico(tokens, sql, fragmento):
    sql.reemplazar(fragmento, por=SQL_QUE_FALLA)
    r = TestClient(app, raise_server_exceptions=False).get(RUTA, headers=tokens["sistemas"])
    _sin_cuerpo_de_diagnostico(r)


class _SesionCaida:
    """Una sesión cuyo MySQL no responde: falla la primera lectura."""

    def get(self, *args, **kwargs):
        raise OperationalError("SELECT", {}, Exception("mysql caido simulado"))

    def close(self) -> None:
        pass


def test_mysql_caido_en_la_autenticacion(tokens, monkeypatch):
    llamadas = []
    original = consultas_monitoreo.leer_catalogo

    def espia(sesion):
        llamadas.append(1)
        return original(sesion)

    monkeypatch.setattr(consultas_monitoreo, "leer_catalogo", espia)

    def sesion_caida():
        yield _SesionCaida()

    caida = crear_app(config.entorno)
    caida.dependency_overrides[obtener_sesion] = sesion_caida
    cliente = TestClient(caida, raise_server_exceptions=False)

    _sin_cuerpo_de_diagnostico(cliente.get(RUTA, headers=tokens["sistemas"]))
    assert llamadas == []  # el endpoint ni se ejecutó

    # Sin token se responde antes de tocar la base: un 401 no prueba que
    # MySQL esté arriba.
    r = cliente.get(RUTA)
    assert r.status_code == 401
    assert r.json()["motivo"] == "falta_token"


# --- /salud no cambia -----------------------------------------------------------


def test_salud_sin_cambios_y_coherente_con_monitoreo(cliente, tokens):
    salud = cliente.get("/salud")  # sigue siendo pública
    assert salud.status_code == 200, salud.text
    datos = salud.json()
    assert set(datos) == CLAVES_SALUD
    assert set(datos["reloj"]) == {"ahora", "real", "simulado"}

    base = cliente.get(RUTA, headers=tokens["sistemas"]).json()["base"]
    assert base == {
        "estado": datos["estado"],
        "revision_alembic": datos["revision_alembic"],
        "tablas_propias": datos["tablas_propias"],
        "vistas_contrato": datos["vistas_contrato"],
        "faltan": datos["faltan"],
    }
