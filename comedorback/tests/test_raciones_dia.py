"""Pruebas de la matriz diaria de raciones: GET y PUT /pacientes/raciones-dia."""

from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.mysql import BIGINT, TINYINT
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import obtener_sesion
from app.main import app
from app.modelos.pacientes import ColumnaInformeDieta, RacionServicioDia


@compiles(TINYINT, "sqlite")
@compiles(BIGINT, "sqlite")
def _entero_en_sqlite(_tipo, _compilador, **_kw):
    return "INTEGER"


@pytest.fixture
def cliente():
    motor = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    ColumnaInformeDieta.metadata.create_all(
        motor,
        tables=[ColumnaInformeDieta.__table__, RacionServicioDia.__table__],
    )
    Sesion = sessionmaker(bind=motor, expire_on_commit=False)
    with Sesion() as s:
        columnas = [
            (1, "corriente", "CORRIENTE", None, 1),
            (2, "blanda", "BLANDA", None, 2),
            (3, "hiposodica", "HIPOSODICA", None, 3),
            (4, "hiposograsa", "HIPOSOGRASA", None, 4),
            (5, "diabetico", "DIABETICO", None, 5),
            (6, "licuadas", "LICUADAS", None, 6),
            (7, "quimioterapias", "QUIMIOTERAPIAS", None, 7),
            (8, "sondas_liquidas", "SONDAS Y LIQUIDAS", None, 8),
            (9, "otros", "OTROS", None, 9),
            (10, "sondas", "SONDAS", 8, 10),
            (11, "liquidas", "LIQUIDAS", 8, 11),
        ]
        s.add_all([
            ColumnaInformeDieta(id=i, codigo=c, nombre=n, agrupa_en_id=a, orden=o)
            for i, c, n, a, o in columnas
        ])
        s.commit()

    def sesion_de_prueba():
        with Sesion() as s:
            yield s

    app.dependency_overrides[obtener_sesion] = sesion_de_prueba
    try:
        yield TestClient(app), Sesion
    finally:
        app.dependency_overrides.pop(obtener_sesion, None)


def test_get_matriz_dia_vacia_devuelve_ceros_y_actualizado_null(cliente):
    http, _ = cliente
    dia = "2026-09-24"
    r = http.get("/pacientes/raciones-dia", params={"fecha": dia})

    assert r.status_code == 200, r.text
    d = r.json()
    assert d["fecha"] == dia
    assert len(d["columnas"]) == 9
    assert [c["codigo"] for c in d["columnas"]] == [
        "corriente", "blanda", "hiposodica", "hiposograsa", "diabetico",
        "licuadas", "quimioterapias", "sondas_liquidas", "otros",
    ]
    assert len(d["filas"]) == 16
    assert d["filas"][0]["codigo"] == "cirugia_mujeres"
    assert d["filas"][-1]["codigo"] == "oncologia"
    assert all(f["celdas"] == [0] * 9 and f["total"] == 0 for f in d["filas"])
    assert d["total"] == {"celdas": [0] * 9, "total": 0}
    assert d["actualizado"] is None


def test_put_matriz_dia_inserta_solo_cambios(cliente):
    http, Sesion = cliente
    dia = date.today().isoformat()

    # 1. Primera carga: pediatria_gral tiene 15 corrientes
    r1 = http.put("/pacientes/raciones-dia", json={
        "fecha": dia,
        "celdas": [{"fila": "pediatria_gral", "columna": "corriente", "cantidad": 15}],
    })
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    fila_pediatria = next(f for f in d1["filas"] if f["codigo"] == "pediatria_gral")
    assert fila_pediatria["celdas"][0] == 15
    assert fila_pediatria["total"] == 15
    assert d1["total"]["celdas"][0] == 15
    assert d1["total"]["total"] == 15
    assert d1["actualizado"] is not None

    with Sesion() as s:
        filas_db = s.execute(select(RacionServicioDia)).scalars().all()
        assert len(filas_db) == 1
        assert filas_db[0].cantidad == 15

    # 2. Segunda carga con el MISMO valor: no debe insertar nada nuevo
    r2 = http.put("/pacientes/raciones-dia", json={
        "fecha": dia,
        "celdas": [{"fila": "pediatria_gral", "columna": "corriente", "cantidad": 15}],
    })
    assert r2.status_code == 200
    with Sesion() as s:
        filas_db = s.execute(select(RacionServicioDia)).scalars().all()
        assert len(filas_db) == 1

    # 3. Tercera carga con valor DISTINTO: inserta un nuevo hecho (la última manda)
    r3 = http.put("/pacientes/raciones-dia", json={
        "fecha": dia,
        "celdas": [{"fila": "pediatria_gral", "columna": "corriente", "cantidad": 20}],
    })
    assert r3.status_code == 200
    d3 = r3.json()
    fila_pediatria = next(f for f in d3["filas"] if f["codigo"] == "pediatria_gral")
    assert fila_pediatria["celdas"][0] == 20
    assert fila_pediatria["total"] == 20

    with Sesion() as s:
        filas_db = s.execute(select(RacionServicioDia)).scalars().all()
        assert len(filas_db) == 2
        assert [f.cantidad for f in filas_db] == [15, 20]


def test_put_matriz_dia_permite_cero_para_corregir_o_vaciar(cliente):
    http, Sesion = cliente
    dia = date.today().isoformat()

    http.put("/pacientes/raciones-dia", json={
        "fecha": dia,
        "celdas": [{"fila": "cirugia_mujeres", "columna": "blanda", "cantidad": 5}],
    })

    # Corregir a 0
    r = http.put("/pacientes/raciones-dia", json={
        "fecha": dia,
        "celdas": [{"fila": "cirugia_mujeres", "columna": "blanda", "cantidad": 0}],
    })
    assert r.status_code == 200
    fila_cirugia = next(f for f in r.json()["filas"] if f["codigo"] == "cirugia_mujeres")
    assert fila_cirugia["celdas"][1] == 0
    assert fila_cirugia["total"] == 0

    with Sesion() as s:
        filas_db = s.execute(select(RacionServicioDia)).scalars().all()
        assert len(filas_db) == 2
        assert filas_db[-1].cantidad == 0


def test_put_fecha_futura_responde_422(cliente):
    http, _ = cliente
    futuro = (date.today() + timedelta(days=1)).isoformat()
    r = http.put("/pacientes/raciones-dia", json={
        "fecha": futuro,
        "celdas": [{"fila": "pediatria_gral", "columna": "corriente", "cantidad": 1}],
    })
    assert r.status_code == 422
    assert "futura" in r.json()["detail"].lower()


def test_put_fila_invalida_responde_422(cliente):
    http, _ = cliente
    dia = date.today().isoformat()
    r = http.put("/pacientes/raciones-dia", json={
        "fecha": dia,
        "celdas": [{"fila": "servicio_fantasma", "columna": "corriente", "cantidad": 1}],
    })
    assert r.status_code == 422
    assert "Fila de distribución inválida" in r.json()["detail"]


def test_put_columna_invalida_responde_422(cliente):
    http, _ = cliente
    dia = date.today().isoformat()
    r = http.put("/pacientes/raciones-dia", json={
        "fecha": dia,
        "celdas": [{"fila": "pediatria_gral", "columna": "columna_inexistente", "cantidad": 1}],
    })
    assert r.status_code == 422
    assert "Columna de distribución inválida" in r.json()["detail"]


def test_put_cantidad_negativa_responde_422(cliente):
    http, _ = cliente
    dia = date.today().isoformat()
    r = http.put("/pacientes/raciones-dia", json={
        "fecha": dia,
        "celdas": [{"fila": "pediatria_gral", "columna": "corriente", "cantidad": -3}],
    })
    assert r.status_code == 422
