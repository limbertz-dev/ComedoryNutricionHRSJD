"""Matriz rol x endpoint, y que nada quede abierto sin querer."""

import re

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.core.autorizacion import ErrorAuth, requiere_rol
from app.main import _error_auth, app
from conftest import encabezado, ingresar

JEFATURA = {"jefa", "sistemas"}
TODOS = {"jefa", "cocinera", "sistemas"}

# (método, ruta, cuerpo, roles que pasan)
MATRIZ = [
    ("GET", "/pantalla/estado", None, TODOS),
    ("GET", "/pantalla/ultimas-marcaciones", None, TODOS),
    ("GET", "/pantalla/dia-personal?persona_id=1", None, TODOS),
    ("POST", "/asistencias", {"metodo": "biometrico"}, TODOS),
    ("POST", "/asistencias", {"metodo": "manual", "usuario_id": 1}, JEFATURA),
    # Padrón: la cocinera lo lee para operar el lector.
    ("GET", "/personal", None, TODOS),
    ("GET", "/personal/1", None, TODOS),
    ("GET", "/personal/1/derecho", None, TODOS),
    ("GET", "/historial/diario", None, JEFATURA),
    ("GET", "/historial/mensual", None, JEFATURA),
    ("GET", "/reportes/periodos", None, JEFATURA),
    ("GET", "/reportes/registro-diario", None, JEFATURA),
    ("GET", "/reportes/mensual", None, JEFATURA),
    ("GET", "/reportes/gestion", None, JEFATURA),
    ("GET", "/reportes/informe?desde=2026-01-01&hasta=2026-01-31", None, JEFATURA),
    ("GET", "/auth/yo", None, TODOS),
]

# Lo único que responde sin token de acceso.
RUTAS_PUBLICAS = {
    ("GET", "/salud"),
    ("POST", "/auth/login"),
    ("POST", "/auth/refresh"),  # el token viaja en el cuerpo
    ("POST", "/auth/cambio-password"),  # acepta el temporal; se prueba aparte
}


@pytest.fixture
def tokens(cliente, crear_usuario) -> dict[str, str]:
    for rol in sorted(TODOS):
        crear_usuario(f"u_{rol}", rol=rol)
    return {rol: ingresar(cliente, f"u_{rol}")["access"] for rol in TODOS}


@pytest.mark.parametrize("rol", sorted(TODOS))
@pytest.mark.parametrize(
    "metodo,ruta,cuerpo,permitidos",
    MATRIZ,
    ids=[f"{m} {r} {c or ''}" for m, r, c, _ in MATRIZ],
)
def test_matriz_rol_por_endpoint(tokens, rol, metodo, ruta, cuerpo, permitidos):
    # Sin propagar excepciones del servidor: acá se prueba solo si la puerta
    # se abre; lo que haga el endpoint después es de sus propios tests.
    cliente = TestClient(app, raise_server_exceptions=False)
    respuesta = cliente.request(metodo, ruta, json=cuerpo, headers=encabezado(tokens[rol]))

    if rol in permitidos:
        assert respuesta.status_code not in (401, 403), respuesta.text
    else:
        assert respuesta.status_code == 403, respuesta.text
        assert respuesta.json()["motivo"] in ("rol_no_autorizado", "metodo_no_autorizado")


def _rutas_de_la_app():
    for ruta in app.routes:
        if not isinstance(ruta, APIRoute):
            continue
        camino = re.sub(r"\{[^}]+\}", "1", ruta.path)
        for metodo in sorted(ruta.methods - {"HEAD", "OPTIONS"}):
            yield metodo, camino


def test_toda_ruta_no_publica_exige_token():
    cliente = TestClient(app, raise_server_exceptions=False)
    for metodo, camino in _rutas_de_la_app():
        if (metodo, camino) in RUTAS_PUBLICAS:
            continue
        respuesta = cliente.request(metodo, camino, json={})
        assert respuesta.status_code == 401, (metodo, camino, respuesta.text)
        assert respuesta.json()["motivo"] == "falta_token"


def test_temporal_no_autoriza_nada(cliente, crear_usuario):
    """Con el token del 428 no se abre NINGUNA ruta, salvo el cambio de clave."""
    crear_usuario("nueva", rol="sistemas", clave="temporal-123", debe_cambiar=True)
    respuesta = cliente.post("/auth/login", json={"username": "nueva", "password": "temporal-123"})
    temporal = respuesta.json()["temporal"]

    abiertas = []
    for metodo, camino in _rutas_de_la_app():
        if (metodo, camino) in RUTAS_PUBLICAS:
            continue
        r = cliente.request(metodo, camino, json={}, headers=encabezado(temporal))
        if r.status_code != 403 or r.json().get("motivo") != "cambio_password_pendiente":
            abiertas.append((metodo, camino, r.status_code))
    assert abiertas == []

    assert cliente.post("/auth/refresh", json={"refresh": temporal}).status_code == 401


def test_rol_de_solo_lectura_no_escribe(cliente, crear_usuario):
    """`lectura=`: una ruta de escritura nueva bajo un recurso de solo lectura
    no queda abierta para ese rol sin que nadie lo decida."""
    router = APIRouter(prefix="/prueba")

    @router.get("")
    def leer():
        return {"ok": True}

    @router.post("")
    def escribir():
        return {"ok": True}

    mini = FastAPI()
    mini.add_exception_handler(ErrorAuth, _error_auth)
    mini.include_router(
        router, dependencies=[Depends(requiere_rol("jefa", lectura=["cocinera"]))]
    )
    crear_usuario("coci", rol="cocinera")
    crear_usuario("jefa1", rol="jefa")
    coci = encabezado(ingresar(cliente, "coci")["access"])
    jefa = encabezado(ingresar(cliente, "jefa1")["access"])
    prueba = TestClient(mini)

    assert prueba.get("/prueba", headers=coci).status_code == 200
    assert prueba.post("/prueba", headers=coci).status_code == 403
    assert prueba.post("/prueba", headers=jefa).status_code == 200
