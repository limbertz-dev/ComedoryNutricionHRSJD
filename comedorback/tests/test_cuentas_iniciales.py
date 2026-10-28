"""Las tres cuentas con que se entrega el sistema (app/semillas/cuentas_iniciales.py)."""

from sqlalchemy import select

from app.core.db import SesionLocal
from app.modelos.usuarios import UsuarioSistema
from app.semillas import cuentas_iniciales


def _cuentas() -> dict[str, UsuarioSistema]:
    with SesionLocal() as sesion:
        filas = sesion.execute(
            select(UsuarioSistema).where(UsuarioSistema.username.in_(("root", "jefa", "cocinera")))
        ).scalars().all()
        return {c.username: c for c in filas}


def test_crea_root_jefa_y_cocinera_con_clave_temporal(cliente):
    cuentas_iniciales.sembrar()
    cuentas = _cuentas()
    assert {u: c.rol for u, c in cuentas.items()} == {
        "root": "sistemas", "jefa": "jefa", "cocinera": "cocinera",
    }
    assert all(c.debe_cambiar and c.activo for c in cuentas.values())
    for username in ("root", "jefa", "cocinera"):
        # La clave inicial entra, pero solo para cambiarla (428).
        r = cliente.post("/auth/login", json={"username": username, "password": f"{username}2026"})
        assert r.status_code == 428, r.text
        assert cliente.post("/auth/login", json={"username": username, "password": "otra-cosa"}).status_code == 401


def test_es_idempotente_y_no_toca_cuentas_existentes(cliente):
    cuentas_iniciales.sembrar()
    antes = {u: (c.id, c.password_hash) for u, c in _cuentas().items()}
    cuentas_iniciales.sembrar()
    assert {u: (c.id, c.password_hash) for u, c in _cuentas().items()} == antes
