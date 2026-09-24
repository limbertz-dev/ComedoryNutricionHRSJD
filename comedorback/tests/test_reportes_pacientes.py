"""Reporte de distribución de pacientes (servicios × dietas).

Sin MySQL: el catálogo y `raciones_servicio_dia` se crean en un SQLite en
memoria. Julio 2026 es un conjunto FICTICIO armado desde la matriz de la hoja
INFORMES de INFORME_MENSUAL_julio.xlsx: reproduce exactamente los 4680 hechos.
Encima se agrega ruido que NO debe contar (cambios más tempranos en el día,
días fuera del rango).
"""

from datetime import date, datetime, timedelta
from itertools import cycle

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.mysql import BIGINT, TINYINT
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.consultas import reportes_pacientes as reportes
from app.core.db import obtener_sesion
from app.main import app
from app.modelos.pacientes import ColumnaInformeDieta, RacionServicioDia


@compiles(TINYINT, "sqlite")
@compiles(BIGINT, "sqlite")
def _entero_en_sqlite(_tipo, _compilador, **_kw):
    return "INTEGER"


JULIO = (date(2026, 7, 1), date(2026, 7, 31))

# La hoja INFORMES del Excel de julio, tal cual: fila -> 9 columnas.
INFORMES_JULIO = {
    "cirugia_mujeres":   [21, 160, 3, 28, 51, 22, 1, 62, 14],
    "cirugia_varones":   [0, 263, 20, 20, 19, 12, 0, 79, 1],
    "ginecologia":       [27, 89, 0, 6, 0, 1, 15, 10, 57],
    "infectologia":      [0, 7, 0, 0, 5, 66, 0, 79, 7],
    "medicina_mujeres":  [2, 96, 65, 61, 58, 43, 97, 92, 49],
    "medicina_varones":  [2, 151, 163, 69, 64, 66, 92, 113, 61],
    "obstetricia":       [170, 161, 4, 9, 0, 0, 0, 0, 66],
    "hemodialisis":      [0, 0, 23, 0, 0, 0, 0, 0, 0],
    "neonatologia_ucin": [0] * 9,
    "uti":               [0, 38, 8, 0, 8, 1, 0, 162, 4],
    "traumatologia":     [0, 280, 39, 0, 25, 1, 0, 2, 0],
    "quemados":          [139, 186, 0, 0, 62, 3, 0, 12, 6],
    "emergencias":       [15, 63, 10, 13, 21, 3, 0, 26, 3],
    "pediatria_uci":     [0] * 9,
    "pediatria_gral":    [198, 106, 8, 11, 0, 1, 131, 58, 29],
    "oncologia":         [0, 0, 0, 0, 0, 0, 86, 0, 0],
}
TOTAL_JULIO = [574, 1600, 343, 217, 313, 219, 422, 695, 297]


def _crear_base():
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
            (1, "corriente", "CORRIENTE", None),
            (2, "blanda", "BLANDA", None),
            (3, "hiposodica", "HIPOSODICA", None),
            (4, "hiposograsa", "HIPOSOGRASA", None),
            (5, "diabetico", "DIABETICO", None),
            (6, "licuadas", "LICUADAS", None),
            (7, "quimioterapias", "QUIMIOTERAPIAS", None),
            (8, "sondas_liquidas", "SONDAS Y LIQUIDAS", None),
            (9, "otros", "OTROS", None),
            (10, "sondas", "SONDAS", 8),
            (11, "liquidas", "LIQUIDAS", 8),
        ]
        s.add_all(
            ColumnaInformeDieta(id=i, codigo=c, nombre=n, agrupa_en_id=a, orden=i)
            for i, c, n, a in columnas
        )
        s.commit()
    return Sesion


def _julio(Sesion):
    """Carga julio 2026 en raciones_servicio_dia reproduciendo la matriz de INFORMES_JULIO."""
    filas_a_insertar: list[RacionServicioDia] = []
    dias_del_mes = [JULIO[0] + timedelta(days=d) for d in range(31)]

    for fila_cod, valores in INFORMES_JULIO.items():
        for col_idx, cantidad_total in enumerate(valores):
            col_id = col_idx + 1  # 1..9
            if cantidad_total == 0:
                continue

            # Repartir la cantidad total entre los 31 días
            base = cantidad_total // 31
            resto = cantidad_total % 31
            for idx, dia in enumerate(dias_del_mes):
                cant_dia = base + (1 if idx < resto else 0)
                if cant_dia > 0:
                    filas_a_insertar.append(RacionServicioDia(
                        fecha=dia,
                        fila_informe=fila_cod,
                        columna_informe_id=col_id,
                        cantidad=cant_dia,
                        momento=datetime(dia.year, dia.month, dia.day, 12, 0),
                    ))

    # Ruido para verificar que la última del día manda:
    # A las 08:00 se había cargado 999 en pediatria_gral / corriente el 15 de julio,
    # pero a las 12:00 rige el valor real ya insertado arriba.
    filas_a_insertar.append(RacionServicioDia(
        fecha=date(2026, 7, 15),
        fila_informe="pediatria_gral",
        columna_informe_id=1,
        cantidad=999,
        momento=datetime(2026, 7, 15, 8, 0),
    ))

    # Ruido fuera del rango: junio 30 y agosto 1 no deben contar
    filas_a_insertar.append(RacionServicioDia(
        fecha=date(2026, 6, 30),
        fila_informe="ginecologia",
        columna_informe_id=1,
        cantidad=50,
        momento=datetime(2026, 6, 30, 12, 0),
    ))
    filas_a_insertar.append(RacionServicioDia(
        fecha=date(2026, 8, 1),
        fila_informe="ginecologia",
        columna_informe_id=1,
        cantidad=50,
        momento=datetime(2026, 8, 1, 12, 0),
    ))

    with Sesion() as s:
        s.add_all(filas_a_insertar)
        s.commit()


@pytest.fixture(scope="module")
def julio():
    Sesion = _crear_base()
    _julio(Sesion)

    def sesion_de_prueba():
        with Sesion() as s:
            yield s

    app.dependency_overrides[obtener_sesion] = sesion_de_prueba
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(obtener_sesion, None)


def _get(http, ruta, desde, hasta):
    return http.get(ruta, params={"desde": desde.isoformat(), "hasta": hasta.isoformat()})


# --- el conjunto ficticio es el del Excel ------------------------------------


def test_la_matriz_ficticia_suma_lo_mismo_que_el_excel():
    por_columna = [sum(v[i] for v in INFORMES_JULIO.values()) for i in range(9)]
    assert por_columna == TOTAL_JULIO
    assert sum(TOTAL_JULIO) == 4680


# --- distribución --------------------------------------------------------------


def test_distribucion_julio_reproduce_la_hoja_informes(julio):
    http = julio
    r = _get(http, "/pacientes/reporte-distribucion", *JULIO)

    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["desde"], d["hasta"], d["dias"]) == ("2026-07-01", "2026-07-31", 31)
    assert d["titulo"] == "INFORME MENSUAL DE RACIONES SERVIDAS A PACIENTES"

    # Exactamente 16 filas (sin SIN CLASIFICAR)
    assert len(d["filas"]) == 16
    filas = {f["codigo"]: f for f in d["filas"]}
    assert "sin_clasificar" not in filas

    for codigo, valores in INFORMES_JULIO.items():
        assert filas[codigo]["valores"] == valores, codigo
        assert filas[codigo]["total"] == sum(valores), codigo

    assert d["total"] == {"valores": TOTAL_JULIO, "total": 4680}
    assert filas["cirugia_mujeres"]["total"] + filas["cirugia_varones"]["total"] == 776
    assert filas["medicina_mujeres"]["total"] + filas["medicina_varones"]["total"] == 1344


def test_distribucion_orden_exacto_de_filas_y_columnas(julio):
    http = julio
    d = _get(http, "/pacientes/reporte-distribucion", *JULIO).json()

    assert [c["etiqueta"] for c in d["columnas"]] == [
        "CORRIENTE", "BLANDA", "HIPOSODICA", "HIPOSOGRASA", "DIABETICO",
        "LICUADAS", "QUIMIOTERAPIAS", "SONDAS Y LIQUIDAS", "OTROS",
    ]
    assert [f["etiqueta"] for f in d["filas"]] == [
        "H. CIRUGIA MUJERES", "H. CIRUGIA VARONES", "H. GINECOLOGIA", "H. INFECTOLOGIA",
        "H. MEDICINA MUJERES", "H. MEDICINA VARONES", "H. OBSTETRICIA", "H. HEMODIALISIS",
        "H. NEONATOLOGIA UCIN", "H. U.T.I.", "H. TRAUMATOLOGIA", "H. QUEMADOS",
        "H. EMERGENCIAS", "H. PEDIATRIA UCI", "H. PEDIATRIA GRAL.", "H. ONCOLOGIA",
    ]
    assert all(len(f["valores"]) == 9 for f in d["filas"])
    assert d["criterio"] == {
        "fuente": "raciones_servicio_dia",
        "ultima_del_dia_manda": True,
        "pendiente_confirmar": [],
    }


def test_desde_posterior_a_hasta_es_422(julio):
    http = julio
    r = _get(http, "/pacientes/reporte-distribucion", date(2026, 7, 31), date(2026, 7, 1))
    assert r.status_code == 422
    assert http.get("/pacientes/reporte-distribucion").status_code == 422  # faltan los dos parámetros


def test_rango_sin_datos_devuelve_todas_las_filas_en_cero(julio):
    http = julio
    d = _get(http, "/pacientes/reporte-distribucion", date(2026, 1, 1), date(2026, 1, 1)).json()

    assert d["dias"] == 1
    assert len(d["filas"]) == 16
    assert all(f["total"] == 0 and f["valores"] == [0] * 9 for f in d["filas"])
    assert d["total"]["total"] == 0
