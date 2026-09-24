"""Borrado lógico de dietas: DELETE /pacientes/dietas/{id} pone visible = 0.

Sin MySQL: las dos tablas del catálogo se crean en un SQLite en memoria, con
ids explícitos y datos ficticios. Cada sentencia SQL que se ejecuta queda
registrada para comprobar que eliminar es un UPDATE y nunca un DELETE.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.mysql import BIGINT, TINYINT
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.consultas import control as consultas_control
from app.consultas import dietas as consultas_dietas
from app.core.db import obtener_sesion
from app.main import app
from app.modelos.pacientes import ColumnaInformeDieta, TipoDieta


# Los modelos usan tipos de MySQL; SQLite no los conoce. Solo para el dialecto
# sqlite (el de este test) se escriben como INTEGER. MySQL no se ve afectado.
@compiles(TINYINT, "sqlite")
@compiles(BIGINT, "sqlite")
def _entero_en_sqlite(_tipo, _compilador, **_kw):
    return "INTEGER"


@pytest.fixture
def base():
    motor = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    sentencias: list[str] = []
    event.listen(
        motor, "before_cursor_execute",
        lambda _c, _cur, sql, *_a: sentencias.append(sql.strip().upper()),
    )
    ColumnaInformeDieta.metadata.create_all(
        motor, tables=[ColumnaInformeDieta.__table__, TipoDieta.__table__]
    )
    Sesion = sessionmaker(bind=motor, expire_on_commit=False)
    with Sesion() as s:
        s.add_all([
            ColumnaInformeDieta(id=1, nombre="CORRIENTE", codigo="corriente", orden=1, activo=True),
            ColumnaInformeDieta(id=9, nombre="OTROS", codigo="otros", orden=9, activo=True),
            TipoDieta(id=1, nombre="Corriente", codigo="corriente", columna_informe_id=1,
                      cuenta_racion=True, orden=1, activo=True),
            TipoDieta(id=2, nombre="Papilla", codigo="papilla", columna_informe_id=9,
                      cuenta_racion=True, orden=2, activo=True),
            TipoDieta(id=3, nombre="Liquida", codigo="liquida", columna_informe_id=9,
                      cuenta_racion=True, orden=3, activo=False),
            TipoDieta(id=12, nombre="NPO (nada por via oral)", codigo="npo", columna_informe_id=9,
                      cuenta_racion=False, orden=12, activo=True),
        ])
        s.commit()
    sentencias.clear()
    return Sesion, sentencias


@pytest.fixture
def cliente(base):
    Sesion, sentencias = base

    def sesion_de_prueba():
        with Sesion() as s:
            yield s

    app.dependency_overrides[obtener_sesion] = sesion_de_prueba
    try:
        yield TestClient(app), Sesion, sentencias
    finally:
        app.dependency_overrides.pop(obtener_sesion, None)


# --- consultas -------------------------------------------------------------


def test_eliminar_pone_visible_en_cero_y_la_fila_queda(base):
    Sesion, sentencias = base
    with Sesion() as s:
        assert consultas_dietas.eliminar_dieta(s, 2) == {"eliminado": True, "id": 2}

    with Sesion() as s:
        fila = s.get(TipoDieta, 2)
        assert fila is not None  # la fila sigue en la tabla
        assert fila.visible is False or fila.visible == 0
        assert [d["id"] for d in consultas_dietas.listar_dietas(s)] == [1, 3, 12]

    assert any(sql.startswith("UPDATE TIPOS_DIETA") for sql in sentencias)
    assert not any(sql.startswith("DELETE") for sql in sentencias)


def test_npo_no_se_elimina(base):
    Sesion, _ = base
    with Sesion() as s, pytest.raises(consultas_dietas.DietaNoEliminable, match="NPO es especial"):
        consultas_dietas.eliminar_dieta(s, 12)
    with Sesion() as s:
        assert s.get(TipoDieta, 12).visible


def test_inexistente_o_ya_eliminada_es_no_encontrada(base):
    Sesion, _ = base
    with Sesion() as s:
        with pytest.raises(consultas_dietas.DietaNoEncontrada):
            consultas_dietas.eliminar_dieta(s, 999)
        consultas_dietas.eliminar_dieta(s, 2)
        with pytest.raises(consultas_dietas.DietaNoEncontrada):
            consultas_dietas.eliminar_dieta(s, 2)


def test_una_dieta_eliminada_o_inactiva_no_se_puede_asignar(base, monkeypatch):
    Sesion, _ = base
    # La cama sale del SIH; acá se simula para llegar hasta la validación de la dieta.
    monkeypatch.setattr(consultas_control, "_cama_vigente", lambda _s, cam: object())
    with Sesion() as s:
        consultas_dietas.eliminar_dieta(s, 2)
        with pytest.raises(ValueError, match="no existe o fue eliminado"):
            consultas_control.asignar_dieta(s, cam_codigo=5, tipo_dieta_id=2)
        with pytest.raises(ValueError, match="dado de baja"):
            consultas_control.asignar_dieta(s, cam_codigo=5, tipo_dieta_id=3)
        assert consultas_control._tipo_activo(s, 1).id == 1


def test_el_nombre_de_una_eliminada_sigue_ocupado(base):
    Sesion, _ = base
    with Sesion() as s:
        consultas_dietas.eliminar_dieta(s, 2)
        with pytest.raises(consultas_dietas.NombreDietaDuplicado, match="dieta eliminada"):
            consultas_dietas.crear_dieta(s, nombre="Papilla", columna_informe="OTROS")


# --- la API ----------------------------------------------------------------


def test_delete_elimina_y_get_ya_no_la_lista(cliente):
    http, Sesion, sentencias = cliente

    r = http.delete("/pacientes/dietas/2")
    assert r.status_code == 200
    assert r.json() == {"eliminado": True, "id": 2}

    ids = [d["id"] for d in http.get("/pacientes/dietas").json()]
    assert ids == [1, 3, 12]

    with Sesion() as s:
        assert s.get(TipoDieta, 2) is not None
    assert not any(sql.startswith("DELETE") for sql in sentencias)


def test_delete_npo_da_422(cliente):
    http, _, _ = cliente
    r = http.delete("/pacientes/dietas/12")
    assert r.status_code == 422
    assert "NPO es especial" in r.json()["detail"]


def test_delete_inexistente_da_404_y_repetir_tambien(cliente):
    http, _, _ = cliente
    assert http.delete("/pacientes/dietas/999").status_code == 404
    assert http.delete("/pacientes/dietas/2").status_code == 200
    assert http.delete("/pacientes/dietas/2").status_code == 404


def test_una_eliminada_no_se_edita_ni_se_recrea_con_su_nombre(cliente):
    http, _, _ = cliente
    http.delete("/pacientes/dietas/2")
    assert http.put("/pacientes/dietas/2", json={"activa": True}).status_code == 404
    r = http.post("/pacientes/dietas", json={"nombre": "Papilla", "columna_informe": "OTROS"})
    assert r.status_code == 409
    assert "eliminada" in r.json()["detail"]
