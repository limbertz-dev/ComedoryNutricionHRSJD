"""Raciones manuales: POST y GET /pacientes/raciones-manuales (LEGADO).

Sin MySQL: base ficticia en SQLite. Cada sentencia SQL queda registrada
para comprobar que cargar es solo INSERT.
"""

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.mysql import BIGINT, TINYINT
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import obtener_sesion
from app.main import app
from app.modelos.pacientes import ColumnaInformeDieta, DietasCama, ServicioNutricion, TipoDieta


@compiles(TINYINT, "sqlite")
@compiles(BIGINT, "sqlite")
def _entero_en_sqlite(_tipo, _compilador, **_kw):
    return "INTEGER"


DIA = date(2026, 9, 23)
HIPOSODICA, BLANDA, CORRIENTE, NPO = 3, 2, 1, 12


def _crear_base():
    motor = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    ColumnaInformeDieta.metadata.create_all(
        motor,
        tables=[
            ColumnaInformeDieta.__table__, TipoDieta.__table__,
            ServicioNutricion.__table__, DietasCama.__table__,
        ],
    )
    Sesion = sessionmaker(bind=motor, expire_on_commit=False)
    with Sesion() as s:
        columnas = [
            (1, "corriente", "CORRIENTE", None), (2, "blanda", "BLANDA", None),
            (3, "hiposodica", "HIPOSODICA", None), (4, "hiposograsa", "HIPOSOGRASA", None),
            (5, "diabetico", "DIABETICO", None), (6, "licuadas", "LICUADAS", None),
            (7, "quimioterapias", "QUIMIOTERAPIAS", None),
            (8, "sondas_liquidas", "SONDAS Y LIQUIDAS", None), (9, "otros", "OTROS", None),
            (10, "sondas", "SONDAS", 8), (11, "liquidas", "LIQUIDAS", 8),
        ]
        s.add_all(
            ColumnaInformeDieta(id=i, codigo=c, nombre=n, agrupa_en_id=a, orden=i)
            for i, c, n, a in columnas
        )
        s.flush()
        tipos = [
            (1, "corriente", 1, 1), (2, "blanda", 2, 1), (3, "hiposodica", 3, 1),
            (4, "hiposograsa", 4, 1), (5, "diabetico", 5, 1), (6, "licuada", 6, 1),
            (7, "quimioterapia", 7, 1), (8, "sonda", 10, 1), (9, "liquida", 11, 1),
            (10, "papilla", 9, 1), (11, "otros", 9, 1), (12, "npo", 9, 0),
        ]
        s.add_all(
            TipoDieta(id=i, codigo=c, nombre=c.title(), columna_informe_id=col,
                      cuenta_racion=cuenta, orden=i)
            for i, c, col, cuenta in tipos
        )
        mapeo = [
            (19, "sih_216", 216, None, "EMERGENCIAS", "EMERGENCIAS", "cantidad"),
            (30, "hemodialisis", None, None, "HEMODIALISIS", "H. HEMODIALISIS", "cantidad"),
        ]
        s.add_all(
            ServicioNutricion(id=i, codigo=c, codigo_sih=sih, sa_codigo=sala,
                              nombre_sih=c, hoja_informe=h, grupo_informe=g, modo=m)
            for i, c, sih, sala, h, g, m in mapeo
        )
        s.commit()
    return Sesion


@pytest.fixture
def cliente():
    Sesion = _crear_base()
    with Sesion() as s:
        s.get(TipoDieta, 4).activo = False     # dada de baja
        s.get(TipoDieta, 5).visible = False    # eliminada
        s.commit()
    sentencias: list[str] = []
    event.listen(
        Sesion.kw["bind"], "before_cursor_execute",
        lambda _c, _cur, sql, *_a: sentencias.append(sql.strip().upper()),
    )

    def sesion_de_prueba():
        with Sesion() as s:
            yield s

    app.dependency_overrides[obtener_sesion] = sesion_de_prueba
    try:
        yield TestClient(app), Sesion, sentencias
    finally:
        app.dependency_overrides.pop(obtener_sesion, None)


def _cargar(http, concepto="hemodialisis", tipo=HIPOSODICA, cantidad=5, fecha=DIA, **extra):
    return http.post("/pacientes/raciones-manuales", json={
        "fecha": fecha.isoformat(), "concepto": concepto,
        "tipo_dieta_id": tipo, "cantidad": cantidad, **extra,
    })


def test_post_inserta_una_fila_por_racion_sin_cama(cliente):
    http, Sesion, sentencias = cliente

    r = _cargar(http, cantidad=5, motivo="  turno manana  ")

    assert r.status_code == 201, r.text
    cuerpo = r.json()
    assert {k: cuerpo[k] for k in ("fecha", "concepto", "tipo_dieta_id", "cantidad")} == {
        "fecha": "2026-09-23", "concepto": "hemodialisis", "tipo_dieta_id": HIPOSODICA, "cantidad": 5,
    }
    assert len(cuerpo["dietas_cama_ids"]) == len(set(cuerpo["dietas_cama_ids"])) == 5

    with Sesion() as s:
        filas = s.execute(select(DietasCama)).scalars().all()
    assert sorted(f.id for f in filas) == sorted(cuerpo["dietas_cama_ids"])
    assert all(f.cam_codigo is None and f.sa_codigo is None and f.sexo is None for f in filas)
    assert {f.servicio_nutricion_id for f in filas} == {30}  # fila 'hemodialisis' del mapeo
    assert {f.motivo for f in filas} == {"turno manana"}
    assert all(f.momento.microsecond == 0 for f in filas)
    assert not [q for q in sentencias if q.startswith(("UPDATE", "DELETE"))]


def test_emergencias_va_a_su_fila_del_mapeo(cliente):
    http, Sesion, _ = cliente

    assert _cargar(http, concepto="emergencias", tipo=BLANDA, cantidad=2).status_code == 201

    with Sesion() as s:
        ids = {f.servicio_nutricion_id for f in s.execute(select(DietasCama)).scalars()}
    assert ids == {19}  # fila 'sih_216' del mapeo


def test_get_agrupa_por_fecha_concepto_y_dieta_en_orden(cliente):
    http, _, _ = cliente
    otro_dia = date(2026, 9, 24)
    _cargar(http, concepto="emergencias", tipo=BLANDA, cantidad=2)
    _cargar(http, concepto="emergencias", tipo=CORRIENTE, cantidad=1)
    _cargar(http, concepto="hemodialisis", tipo=HIPOSODICA, cantidad=3)
    _cargar(http, concepto="hemodialisis", tipo=HIPOSODICA, cantidad=2)  # se suma a la de arriba
    _cargar(http, concepto="hemodialisis", tipo=HIPOSODICA, cantidad=1, fecha=otro_dia)
    _cargar(http, concepto="hemodialisis", tipo=HIPOSODICA, cantidad=9, fecha=date(2026, 10, 1))

    r = http.get("/pacientes/raciones-manuales",
                 params={"desde": "2026-09-01", "hasta": "2026-09-30"})

    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["desde"], d["hasta"]) == ("2026-09-01", "2026-09-30")
    assert d["conceptos"] == [
        {"codigo": "hemodialisis", "etiqueta": "Hemodiálisis"},
        {"codigo": "emergencias", "etiqueta": "Emergencias"},
    ]
    assert [(f["fecha"], f["concepto"], f["dieta"], f["cantidad"]) for f in d["filas"]] == [
        ("2026-09-23", "hemodialisis", "Hiposodica", 5),
        ("2026-09-23", "emergencias", "Corriente", 1),
        ("2026-09-23", "emergencias", "Blanda", 2),
        ("2026-09-24", "hemodialisis", "Hiposodica", 1),
    ]


def test_get_no_mezcla_raciones_de_cama(cliente):
    http, Sesion, _ = cliente
    _cargar(http, concepto="emergencias", tipo=BLANDA, cantidad=1)
    with Sesion() as s:
        # Una cama del censo de Emergencias: la misma fila del mapeo, pero con cama.
        s.add(DietasCama(fecha=DIA, momento=datetime(2026, 9, 23, 8), cam_codigo=77,
                         servicio_nutricion_id=19, tipo_dieta_id=BLANDA))
        s.commit()

    d = http.get("/pacientes/raciones-manuales",
                 params={"desde": DIA.isoformat(), "hasta": DIA.isoformat()}).json()

    assert [f["cantidad"] for f in d["filas"]] == [1]


@pytest.mark.parametrize(
    "cambios",
    [
        {"concepto": "acompanantes"},     # concepto que no existe
        {"cantidad": 0},
        {"cantidad": 201},
        {"tipo": NPO},                    # no suma ración
        {"tipo": 4},                      # dada de baja
        {"tipo": 5},                      # eliminada
        {"tipo": 777},                    # no existe
    ],
)
def test_cargas_invalidas_son_422_y_no_insertan(cliente, cambios):
    http, Sesion, _ = cliente

    r = _cargar(http, **cambios)

    assert r.status_code == 422, r.text
    with Sesion() as s:
        assert s.execute(select(DietasCama)).first() is None


def test_get_con_rango_invertido_o_sin_parametros_es_422(cliente):
    http, _, _ = cliente
    assert http.get("/pacientes/raciones-manuales",
                    params={"desde": "2026-09-30", "hasta": "2026-09-01"}).status_code == 422
    assert http.get("/pacientes/raciones-manuales").status_code == 422
