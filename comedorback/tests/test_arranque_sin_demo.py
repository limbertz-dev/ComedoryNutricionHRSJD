"""Regresiones del arranque y del origen biometrico, sin acceder a MySQL.

Desde la raiz: PYTHONPATH=comedorback python -m pytest --noconftest
comedorback/tests/test_arranque_sin_demo.py. Se sustituyen solo las
dependencias de sesion y usuario; la politica y las rutas son las reales.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core import reloj
from app.core.autorizacion import usuario_actual
from app.core.config import Configuracion
from app.core.db import obtener_sesion
from app.main import crear_app


@pytest.mark.parametrize("entorno", ["desarrollo", "produccion"])
@pytest.mark.parametrize("rol", ["cocinera", "jefa", "sistemas"])
@pytest.mark.parametrize("cuerpo", [
    {},
    {"metodo": "biometrico"},
    {"usuario_id": 900001},
    {"metodo": "biometrico", "dispositivo": "lector-inventado"},
])
def test_navegador_no_registra_biometria(entorno, rol, cuerpo):
    app = crear_app(entorno)
    app.dependency_overrides[usuario_actual] = lambda: SimpleNamespace(
        id=1, rol=rol, activo=True, debe_cambiar=False,
    )
    # Cualquier intento de usar una sesion real fallaria: no hay DB.
    app.dependency_overrides[obtener_sesion] = lambda: object()
    with TestClient(app) as cliente:
        respuesta = cliente.post("/asistencias", json=cuerpo)
    assert respuesta.status_code == 403
    assert respuesta.json()["motivo"] == "biometrico_solo_lector"


@pytest.mark.parametrize("entorno", ["desarrollo", "produccion"])
def test_no_hay_rutas_para_mover_el_reloj(entorno):
    app = crear_app(entorno)
    with TestClient(app) as cliente:
        for metodo, ruta in [
            ("GET", "/simulacion/reloj"),
            ("PUT", "/simulacion/reloj"),
            ("POST", "/simulacion/reloj/avanzar"),
            ("DELETE", "/simulacion/reloj"),
        ]:
            assert cliente.request(metodo, ruta).status_code == 404


def test_entorno_retirado_no_arranca():
    with pytest.raises(ValueError):
        crear_app("simulacion")
    with pytest.raises(ValidationError):
        Configuracion(_env_file=None, entorno="simulacion")


def test_reloj_real_sin_controles(monkeypatch):
    from datetime import datetime

    instante = datetime(2026, 10, 15, 13, 0)
    monkeypatch.setattr(reloj, "real", lambda: instante)
    assert reloj.ahora() == instante
    assert reloj.hoy() == instante.date()
    for nombre in ("fijar", "avanzar", "volver_a_real"):
        assert not hasattr(reloj, nombre)
