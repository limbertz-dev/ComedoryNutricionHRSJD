"""La cocinera frente al lector: padrón en solo lectura y la ficha del día
(GET /pantalla/dia-personal), sin abrir /historial/* ni escribir el padrón."""

from datetime import date

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.consultas.derecho import aplicar_reglas
from app.core import reloj
from app.core.autorizacion import ErrorAuth, requiere_rol
from app.core.db import SesionLocal
from app.core.permisos import ACCESO
from app.main import _error_auth, app
from app.modelos.heredados import Comensal, ComidaPorTurno
from conftest import encabezado, ingresar

ROLES = ("jefa", "cocinera", "sistemas")
DIA = "/pantalla/dia-personal"


@pytest.fixture
def tokens(cliente, crear_usuario) -> dict[str, dict[str, str]]:
    for rol in ROLES:
        crear_usuario(f"u_{rol}", rol=rol)
    return {rol: encabezado(ingresar(cliente, f"u_{rol}")["access"]) for rol in ROLES}


def _con_derecho() -> tuple[int, date]:
    """Alguien con derecho a alguna comida según las reglas (solo SELECT)."""
    with SesionLocal() as sesion:
        fila = sesion.execute(
            aplicar_reglas(
                select(ComidaPorTurno.usuario_id, ComidaPorTurno.fecha_comida)
            )
            .order_by(ComidaPorTurno.fecha_comida.desc(), ComidaPorTurno.usuario_id)
            .limit(1)
        ).first()
    if fila is None:
        pytest.skip("la base de turnos no tiene ninguna comida con derecho")
    return fila.usuario_id, fila.fecha_comida


def _ficha_del_historial(cliente, headers, usuario_id: int, fecha: date) -> dict | None:
    """La misma persona buscada página por página en GET /historial/diario."""
    desplazamiento = 0
    while True:
        r = cliente.get(
            "/historial/diario",
            params={"fecha": fecha.isoformat(), "limite": 200, "desplazamiento": desplazamiento},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        pagina = r.json()
        for persona in pagina["datos"]:
            if persona["usuario_id"] == usuario_id:
                return {"comidas": pagina["comidas"], "persona": persona}
        desplazamiento += len(pagina["datos"])
        if not pagina["datos"] or desplazamiento >= pagina["total"]:
            return None


# --- padrón en solo lectura ---------------------------------------------------


def test_cocinera_lee_el_padron(cliente, tokens):
    r = cliente.get("/personal", params={"limite": 5}, headers=tokens["cocinera"])
    assert r.status_code == 200, r.text
    assert set(r.json()) >= {"total", "limite", "desplazamiento", "datos"}


@pytest.mark.parametrize("metodo", ["POST", "PUT", "PATCH", "DELETE"])
def test_cocinera_no_escribe_el_padron(tokens, metodo):
    # Hoy /personal no tiene rutas de escritura: la puerta ni se abre (405).
    cliente = TestClient(app, raise_server_exceptions=False)
    for ruta in ("/personal", "/personal/1"):
        r = cliente.request(metodo, ruta, json={}, headers=tokens["cocinera"])
        assert r.status_code in (403, 405), (metodo, ruta, r.text)


def test_regla_del_padron_veda_escrituras_a_la_cocinera(cliente, crear_usuario):
    """La regla real de /personal: una escritura que alguien agregue mañana
    queda en jefatura sin que nadie tenga que acordarse."""
    router = APIRouter(prefix="/personal")

    @router.get("")
    def leer():
        return {"ok": True}

    @router.post("")
    def crear():
        return {"ok": True}

    @router.put("/{usuario_id}")
    def editar(usuario_id: int):
        return {"ok": True}

    regla = ACCESO["personal"]
    mini = FastAPI()
    mini.add_exception_handler(ErrorAuth, _error_auth)
    mini.include_router(
        router,
        dependencies=[Depends(requiere_rol(*regla.completo, lectura=regla.lectura))],
    )
    for rol in ROLES:
        crear_usuario(f"p_{rol}", rol=rol)
    cabeceras = {rol: encabezado(ingresar(cliente, f"p_{rol}")["access"]) for rol in ROLES}
    prueba = TestClient(mini)

    assert prueba.get("/personal", headers=cabeceras["cocinera"]).status_code == 200
    for metodo, ruta in (("POST", "/personal"), ("PUT", "/personal/1")):
        r = prueba.request(metodo, ruta, json={}, headers=cabeceras["cocinera"])
        assert r.status_code == 403, r.text
        assert r.json()["motivo"] == "rol_no_autorizado"
        for rol in ("jefa", "sistemas"):
            r = prueba.request(metodo, ruta, json={}, headers=cabeceras[rol])
            assert r.status_code == 200, (rol, r.text)


# --- /historial/* sigue siendo de jefatura -------------------------------------


@pytest.mark.parametrize("ruta", ["/historial/diario", "/historial/mensual"])
def test_historial_sigue_vedado_a_la_cocinera(cliente, tokens, ruta):
    r = cliente.get(ruta, headers=tokens["cocinera"])
    assert r.status_code == 403, r.text
    assert r.json()["motivo"] == "rol_no_autorizado"
    for rol in ("jefa", "sistemas"):
        assert cliente.get(ruta, headers=tokens[rol]).status_code == 200


# --- GET /pantalla/dia-personal ----------------------------------------------


@pytest.mark.parametrize("rol", ROLES)
def test_dia_personal_misma_ficha_que_el_historial(cliente, tokens, rol):
    usuario_id, fecha = _con_derecho()
    r = cliente.get(
        DIA, params={"persona_id": usuario_id, "fecha": fecha.isoformat()}, headers=tokens[rol]
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert set(cuerpo) == {"fecha", "total", "limite", "desplazamiento", "comidas", "datos"}
    assert cuerpo["fecha"] == fecha.isoformat()
    assert cuerpo["total"] == 1
    assert cuerpo["limite"] == 1 and cuerpo["desplazamiento"] == 0
    assert [p["usuario_id"] for p in cuerpo["datos"]] == [usuario_id]

    historial = _ficha_del_historial(cliente, tokens["jefa"], usuario_id, fecha)
    assert historial is not None
    assert cuerpo["comidas"] == historial["comidas"]
    assert cuerpo["datos"][0] == historial["persona"]


def test_dia_personal_por_defecto_es_hoy(cliente, tokens):
    usuario_id, _ = _con_derecho()
    r = cliente.get(DIA, params={"persona_id": usuario_id}, headers=tokens["cocinera"])
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["fecha"] == reloj.hoy().isoformat()

    historial = _ficha_del_historial(cliente, tokens["jefa"], usuario_id, reloj.hoy())
    if historial is None:
        assert cuerpo["total"] == 0 and cuerpo["datos"] == []
    else:
        assert cuerpo["datos"] == [historial["persona"]]


def test_dia_personal_sin_derecho_ni_racion_viene_vacio(cliente, tokens):
    usuario_id, _ = _con_derecho()
    r = cliente.get(
        DIA, params={"persona_id": usuario_id, "fecha": "2000-01-01"}, headers=tokens["cocinera"]
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["total"] == 0
    assert cuerpo["datos"] == []
    assert cuerpo["comidas"]  # las columnas llegan igual


def test_dia_personal_persona_inexistente_404(cliente, tokens):
    with SesionLocal() as sesion:
        mayor = sesion.execute(select(func.max(Comensal.usuario_id))).scalar() or 0
    r = cliente.get(DIA, params={"persona_id": mayor + 1000}, headers=tokens["cocinera"])
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "No existe ese comensal"


@pytest.mark.parametrize(
    "params",
    [{}, {"persona_id": 0}, {"persona_id": "x"}, {"persona_id": 1, "fecha": "ayer"}],
)
def test_dia_personal_parametros_invalidos_422(cliente, tokens, params):
    r = cliente.get(DIA, params=params, headers=tokens["cocinera"])
    assert r.status_code == 422, r.text
