"""B0: una sesión humana no declara marcaciones biométricas fuera de simulación.

Contrato compartido con el front:

  · El entorno efectivo es el de la app que armó `crear_app`. /salud y
    /monitoreo/estado informan ese mismo entorno y ninguna petición lo cambia.
  · POST /asistencias con metodo='biometrico' (o sin metodo) solo se acepta
    en simulación. En producción y desarrollo: 403
    {"detail": DETALLE, "motivo": "biometrico_solo_lector"}, antes de la
    lógica de marcación y sin escribir lecturas ni asistencias.
  · La autenticación va primero y conserva sus errores. La manual conserva
    sus reglas y un biométrico rechazado nunca se convierte en manual.
  · En simulación el dispositivo lo fija el servidor: simulador-navegador.

Cada entorno es una app de `crear_app` sobre la misma base de tests.
"""

from datetime import datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app.core import reloj, seguridad
from app.core.config import config
from app.core.db import SesionLocal
from app.logica import marcacion
from app.main import app, crear_app
from app.modelos.comedor import Asistencia, LecturaBiometrica
from app.semillas import horarios
from conftest import SENTENCIAS, encabezado, ingresar
from test_simulacion import _candidato_almuerzo

ROLES = ("jefa", "cocinera", "sistemas")
FUERA_DE_SIMULACION = ("produccion", "desarrollo")
ENTORNOS = (*FUERA_DE_SIMULACION, "simulacion")
DIA = datetime(2026, 9, 24, 12, 30)  # dentro del almuerzo de la semilla
USUARIO_INEXISTENTE = 999_999_999  # da sin_derecho sin depender del padrón
DISPOSITIVO = "simulador-navegador"
DETALLE = "La marcación biométrica requiere un lector autorizado fuera de simulación."
RECHAZO = {"detail": DETALLE, "motivo": "biometrico_solo_lector"}

# Lo que un cliente podría mandar como biométrico: explícito, con el método
# omitido (vale biometrico) y haciéndose pasar por el lector.
BIOMETRICOS = {
    "explicito": {"metodo": "biometrico"},
    "omitido": {},
    "omitido_con_usuario": {"usuario_id": USUARIO_INEXISTENTE},
    "dispositivo_manipulado": {
        "metodo": "biometrico",
        "usuario_id": USUARIO_INEXISTENTE,
        "dispositivo": "lector-comedor-01",
    },
}


# --- fixtures -----------------------------------------------------------------


@pytest.fixture(autouse=True)
def reloj_real():
    reloj.volver_a_real()
    yield
    reloj.volver_a_real()


@pytest.fixture
def tokens(cliente, crear_usuario) -> dict[str, dict[str, str]]:
    for rol in ROLES:
        crear_usuario(f"u_{rol}", rol=rol)
    return {rol: encabezado(ingresar(cliente, f"u_{rol}")["access"]) for rol in ROLES}


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
    """Horarios de la semilla: con el reloj en DIA, una marcación que llegara
    a la lógica caería en franja y escribiría una lectura."""
    with SesionLocal() as sesion:
        sesion.execute(text("DELETE FROM horarios_comida"))
        sesion.commit()
    horarios.sembrar()
    yield
    with SesionLocal() as sesion:
        sesion.execute(text("DELETE FROM horarios_comida"))
        sesion.commit()


@pytest.fixture
def espia_logica(monkeypatch) -> list[dict]:
    """Registra cada llamada a la lógica de marcación (y la deja correr)."""
    llamadas: list[dict] = []
    original = marcacion.registrar_marcacion

    def espia(*args, **kwargs):
        llamadas.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(marcacion, "registrar_marcacion", espia)
    return llamadas


def _conteos() -> tuple[int, int]:
    """(asistencias, lecturas_biometricas)."""
    with SesionLocal() as sesion:
        return (
            sesion.execute(select(func.count()).select_from(Asistencia)).scalar_one(),
            sesion.execute(select(func.count()).select_from(LecturaBiometrica)).scalar_one(),
        )


def _escrituras_desde(indice: int) -> list[str]:
    return [
        s for s in SENTENCIAS[indice:]
        if s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
    ]


def _lectura(lectura_id: int) -> LecturaBiometrica:
    with SesionLocal() as sesion:
        fila = sesion.get(LecturaBiometrica, lectura_id)
        sesion.expunge(fila)
        return fila


# --- fuera de simulación: 403 antes de la lógica ------------------------------


@pytest.mark.usefixtures("con_horarios")
@pytest.mark.parametrize("cuerpo", BIOMETRICOS.values(), ids=BIOMETRICOS.keys())
@pytest.mark.parametrize("rol", ROLES)
@pytest.mark.parametrize("entorno", FUERA_DE_SIMULACION)
def test_biometrico_fuera_de_simulacion_403_sin_escrituras(
    tokens, espia_logica, entorno, rol, cuerpo
):
    reloj.fijar(DIA, congelar=True)
    cliente = TestClient(crear_app(entorno))
    antes = _conteos()
    desde = len(SENTENCIAS)

    r = cliente.post("/asistencias", json=cuerpo, headers=tokens[rol])

    assert r.status_code == 403, r.text
    assert r.json() == RECHAZO
    assert espia_logica == []  # la lógica ni se ejecutó
    assert _escrituras_desde(desde) == []
    assert _conteos() == antes == (0, 0)


@pytest.mark.usefixtures("con_horarios")
@pytest.mark.parametrize("entorno", FUERA_DE_SIMULACION)
def test_fuera_de_simulacion_el_origen_va_antes_que_el_momento(tokens, espia_logica, entorno):
    """Con momento del cliente sigue siendo 403: el origen se decide primero."""
    r = TestClient(crear_app(entorno)).post(
        "/asistencias",
        json={"metodo": "biometrico", "usuario_id": 1, "momento": DIA.isoformat()},
        headers=tokens["jefa"],
    )
    assert r.status_code == 403, r.text
    assert r.json() == RECHAZO
    assert espia_logica == []
    assert _conteos() == (0, 0)


# --- simulación: se acepta, con el dispositivo del servidor --------------------


@pytest.mark.usefixtures("con_horarios")
@pytest.mark.parametrize("cuerpo", BIOMETRICOS.values(), ids=BIOMETRICOS.keys())
@pytest.mark.parametrize("rol", ROLES)
def test_simulacion_acepta_biometrico_de_los_tres_roles(tokens, espia_logica, rol, cuerpo):
    reloj.fijar(DIA, congelar=True)
    r = TestClient(crear_app("simulacion")).post(
        "/asistencias", json=cuerpo, headers=tokens[rol]
    )
    assert r.status_code == 200, r.text
    respuesta = r.json()
    esperado = "sin_derecho" if "usuario_id" in cuerpo else "no_identificado"
    assert (respuesta["valido"], respuesta["motivo"]) == (False, esperado)
    assert [llamada["metodo"] for llamada in espia_logica] == ["biometrico"]

    lectura = _lectura(respuesta["lectura_id"])
    assert lectura.dispositivo == DISPOSITIVO
    assert (lectura.resultado, lectura.motivo) == ("rechazada", esperado)
    assert _conteos() == (0, 1)


@pytest.mark.usefixtures("con_horarios")
@pytest.mark.parametrize(
    "dispositivo",
    ["lector-comedor-01", "", "x" * 200, None],
    ids=["lector_real", "vacio", "largo", "null"],
)
def test_simulacion_ignora_el_dispositivo_del_cliente(tokens, dispositivo):
    reloj.fijar(DIA, congelar=True)
    r = TestClient(crear_app("simulacion")).post(
        "/asistencias",
        json={"metodo": "biometrico", "dispositivo": dispositivo},
        headers=tokens["cocinera"],
    )
    assert r.status_code == 200, r.text
    assert _lectura(r.json()["lectura_id"]).dispositivo == DISPOSITIVO


@pytest.mark.usefixtures("con_horarios")
def test_simulacion_conserva_las_reglas(tokens):
    sim = TestClient(crear_app("simulacion"))
    coci = tokens["cocinera"]
    usuario_id, fecha = _candidato_almuerzo()
    reloj.fijar(datetime.combine(fecha, DIA.time()), congelar=True)

    primera = sim.post(
        "/asistencias", json={"usuario_id": usuario_id, "metodo": "biometrico"}, headers=coci
    )
    assert primera.status_code == 200, primera.text
    assert primera.json()["valido"] is True, primera.json()
    with SesionLocal() as sesion:
        fila = sesion.get(Asistencia, primera.json()["asistencia_id"])
        assert fila.metodo == "biometrico"
        assert fila.registrado_por_cuenta is None
    assert _lectura(primera.json()["lectura_id"]).dispositivo == DISPOSITIVO

    segunda = sim.post("/asistencias", json={"usuario_id": usuario_id}, headers=coci)
    assert (segunda.json()["valido"], segunda.json()["motivo"]) == (False, "duplicado")

    # La semilla deja 10:00-11:00 sin cubrir a propósito.
    reloj.fijar(datetime.combine(fecha, time(10, 30)), congelar=True)
    fuera = sim.post("/asistencias", json={"usuario_id": usuario_id}, headers=coci)
    assert (fuera.json()["valido"], fuera.json()["motivo"]) == (False, "fuera_horario")
    assert _conteos() == (1, 3)


@pytest.mark.usefixtures("con_horarios")
@pytest.mark.parametrize("cuerpo", [{"metodo": "biometrico"}, {}], ids=["explicito", "omitido"])
def test_simulacion_sigue_rechazando_el_momento_del_cliente(tokens, espia_logica, cuerpo):
    r = TestClient(crear_app("simulacion")).post(
        "/asistencias",
        json={**cuerpo, "usuario_id": 1, "momento": DIA.isoformat()},
        headers=tokens["jefa"],
    )
    assert r.status_code == 422, r.text
    assert espia_logica == []
    assert _conteos() == (0, 0)


# --- manual: sin cambios en ningún entorno -------------------------------------


@pytest.mark.usefixtures("con_horarios")
@pytest.mark.parametrize("entorno", ENTORNOS)
def test_manual_conserva_sus_reglas(tokens, entorno):
    cliente = TestClient(crear_app(entorno))
    usuario_id, fecha = _candidato_almuerzo()
    momento = datetime.combine(fecha, DIA.time()).isoformat()
    cuerpo = {"usuario_id": usuario_id, "metodo": "manual", "momento": momento}

    r = cliente.post("/asistencias", json=cuerpo, headers=tokens["cocinera"])
    assert r.status_code == 403, r.text
    assert r.json()["motivo"] == "metodo_no_autorizado"
    assert _conteos() == (0, 0)

    r = cliente.post("/asistencias", json=cuerpo, headers=tokens["jefa"])
    assert r.status_code == 200, r.text
    assert r.json()["valido"] is True, r.json()
    assert r.json()["lectura_id"] is None
    with SesionLocal() as sesion:
        fila = sesion.get(Asistencia, r.json()["asistencia_id"])
        assert fila.metodo == "manual"
        assert fila.registrado_por_cuenta is not None

    r = cliente.post("/asistencias", json=cuerpo, headers=tokens["sistemas"])
    assert (r.json()["valido"], r.json()["motivo"]) == (False, "duplicado")
    # La manual nunca escribe lecturas: ni la aceptada ni la rechazada.
    assert _conteos() == (1, 0)


@pytest.mark.usefixtures("con_horarios")
@pytest.mark.parametrize("entorno", FUERA_DE_SIMULACION)
def test_biometrico_rechazado_no_se_convierte_en_manual(tokens, entorno):
    """Una persona con derecho, marcada por jefatura como biométrico: 403, no
    una ración manual."""
    usuario_id, fecha = _candidato_almuerzo()
    reloj.fijar(datetime.combine(fecha, DIA.time()), congelar=True)
    r = TestClient(crear_app(entorno)).post(
        "/asistencias", json={"usuario_id": usuario_id}, headers=tokens["jefa"]
    )
    assert r.status_code == 403, r.text
    assert r.json() == RECHAZO
    assert _conteos() == (0, 0)


# --- la autenticación sigue primero --------------------------------------------


@pytest.fixture
def credenciales(cliente, crear_usuario) -> dict[str, dict[str, str]]:
    """Encabezados que la autenticación rechaza, cada uno con su motivo."""
    uid = crear_usuario("u_vencido", rol="jefa")
    vencido = seguridad.emitir_token(
        usuario_id=uid,
        tipo=seguridad.ACCESS,
        version=0,
        rol="jefa",
        duracion=timedelta(seconds=-1),
    )
    crear_usuario("u_temporal", rol="cocinera", clave="temporal-123", debe_cambiar=True)
    temporal = cliente.post(
        "/auth/login", json={"username": "u_temporal", "password": "temporal-123"}
    ).json()["temporal"]
    return {
        "sin_token": {},
        "token_invalido": encabezado("no-es-un-jwt"),
        "token_expirado": encabezado(vencido),
        "cambio_password_pendiente": encabezado(temporal),
    }


ERRORES_AUTH = {
    "sin_token": (401, "falta_token"),
    "token_invalido": (401, "token_invalido"),
    "token_expirado": (401, "token_expirado"),
    "cambio_password_pendiente": (403, "cambio_password_pendiente"),
}


@pytest.mark.usefixtures("sin_marcaciones")
@pytest.mark.parametrize("cuerpo", [{"metodo": "biometrico"}, {}], ids=["explicito", "omitido"])
@pytest.mark.parametrize("caso", ERRORES_AUTH)
@pytest.mark.parametrize("entorno", ENTORNOS)
def test_errores_de_autenticacion_sin_cambios(credenciales, espia_logica, entorno, caso, cuerpo):
    r = TestClient(crear_app(entorno)).post(
        "/asistencias", json=cuerpo, headers=credenciales[caso]
    )
    estado, motivo = ERRORES_AUTH[caso]
    assert r.status_code == estado, r.text
    assert r.json()["motivo"] == motivo
    assert espia_logica == []
    assert _conteos() == (0, 0)


# --- un solo entorno por app ----------------------------------------------------


@pytest.mark.usefixtures("sin_marcaciones")
@pytest.mark.parametrize("entorno", ENTORNOS)
def test_entorno_coherente_y_fuera_del_alcance_del_cliente(tokens, monkeypatch, entorno):
    """/salud, /monitoreo/estado y la autorización dicen el mismo entorno: el
    de la app. Ni config.entorno ni la petición lo cambian."""
    aplicacion = crear_app(entorno)
    otro = "produccion" if entorno == "simulacion" else "simulacion"
    monkeypatch.setattr(config, "entorno", otro)
    cliente = TestClient(aplicacion)
    trampa = {"params": {"entorno": otro}}

    def con(rol: str) -> dict[str, str]:
        return {**tokens[rol], "X-Entorno": otro}

    salud = cliente.get("/salud", headers={"X-Entorno": otro}, **trampa)
    monitoreo = cliente.get("/monitoreo/estado", headers=con("sistemas"), **trampa)
    assert monitoreo.status_code == 200, monitoreo.text
    assert aplicacion.state.entorno == entorno
    assert salud.json()["entorno"] == monitoreo.json()["entorno"] == entorno

    r = cliente.post(
        "/asistencias",
        json={"metodo": "biometrico", "entorno": otro},
        headers=con("cocinera"),
        **trampa,
    )
    if entorno == "simulacion":
        assert r.status_code == 200, r.text
    else:
        assert r.status_code == 403, r.text
        assert r.json() == RECHAZO


def test_la_app_del_proceso_toma_el_entorno_de_la_configuracion():
    assert app.state.entorno == config.entorno


@pytest.mark.parametrize("entorno", ["SIMULACION", "produccíon", ""])
def test_crear_app_rechaza_un_entorno_desconocido(entorno):
    with pytest.raises(ValueError):
        crear_app(entorno)
