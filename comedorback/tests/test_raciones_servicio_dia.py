"""Pruebas del modelo RacionServicioDia y sus restricciones."""

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.mysql import BIGINT, TINYINT
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.modelos.pacientes import ColumnaInformeDieta, RacionServicioDia


@compiles(TINYINT, "sqlite")
@compiles(BIGINT, "sqlite")
def _entero_en_sqlite(_tipo, _compilador, **_kw):
    return "INTEGER"


@pytest.fixture
def sesion_sqlite():
    motor = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    ColumnaInformeDieta.metadata.create_all(
        motor,
        tables=[ColumnaInformeDieta.__table__, RacionServicioDia.__table__],
    )
    Sesion = sessionmaker(bind=motor, expire_on_commit=False)
    with Sesion() as s:
        s.add_all([
            ColumnaInformeDieta(id=1, nombre="CORRIENTE", codigo="corriente", orden=1, activo=True),
            ColumnaInformeDieta(id=2, nombre="BLANDA", codigo="blanda", orden=2, activo=True),
        ])
        s.commit()
    with Sesion() as s:
        yield s


def test_modelo_metadatos():
    tabla = RacionServicioDia.__table__
    assert tabla.name == "raciones_servicio_dia"
    assert "ix_raciones_servicio_dia_ultima" in [idx.name for idx in tabla.indexes]
    assert any("cantidad" in str(ck.sqltext) and ">= 0" in str(ck.sqltext) for ck in tabla.constraints if hasattr(ck, "sqltext"))
    assert tabla.comment is not None
    assert tabla.dialect_options["mysql"]["charset"] == "utf8mb4"
    assert tabla.dialect_options["mysql"]["collate"] == "utf8mb4_unicode_ci"


def test_insertar_y_consultar_hecho(sesion_sqlite):
    ahora = datetime(2026, 9, 24, 10, 30, 0)
    dia = date(2026, 9, 24)
    racion = RacionServicioDia(
        fecha=dia,
        fila_informe="pediatria_gral",
        columna_informe_id=1,
        cantidad=15,
        momento=ahora,
    )
    sesion_sqlite.add(racion)
    sesion_sqlite.commit()

    guardado = sesion_sqlite.execute(
        select(RacionServicioDia).where(RacionServicioDia.fila_informe == "pediatria_gral")
    ).scalar_one()

    assert guardado.id is not None
    assert guardado.fecha == dia
    assert guardado.fila_informe == "pediatria_gral"
    assert guardado.columna_informe_id == 1
    assert guardado.cantidad == 15
    assert guardado.momento == ahora
    assert guardado.registrado_por is None


def test_cantidad_cero_es_valida(sesion_sqlite):
    racion = RacionServicioDia(
        fecha=date(2026, 9, 24),
        fila_informe="cirugia_mujeres",
        columna_informe_id=1,
        cantidad=0,
        momento=datetime(2026, 9, 24, 8, 0, 0),
    )
    sesion_sqlite.add(racion)
    sesion_sqlite.commit()

    guardado = sesion_sqlite.get(RacionServicioDia, racion.id)
    assert guardado is not None
    assert guardado.cantidad == 0


def test_cantidad_negativa_viola_check_constraint(sesion_sqlite):
    racion = RacionServicioDia(
        fecha=date(2026, 9, 24),
        fila_informe="cirugia_mujeres",
        columna_informe_id=1,
        cantidad=-5,
        momento=datetime(2026, 9, 24, 8, 0, 0),
    )
    sesion_sqlite.add(racion)
    with pytest.raises(IntegrityError):
        sesion_sqlite.commit()


def test_resolucion_celda_vigente_ultima_por_momento(sesion_sqlite):
    dia = date(2026, 9, 24)
    t0 = datetime(2026, 9, 24, 8, 0, 0)
    t1 = t0 + timedelta(hours=2)

    # Registro inicial: 10 raciones
    sesion_sqlite.add(RacionServicioDia(
        fecha=dia,
        fila_informe="pediatria_gral",
        columna_informe_id=1,
        cantidad=10,
        momento=t0,
    ))
    # Corrección posterior: 12 raciones
    sesion_sqlite.add(RacionServicioDia(
        fecha=dia,
        fila_informe="pediatria_gral",
        columna_informe_id=1,
        cantidad=12,
        momento=t1,
    ))
    sesion_sqlite.commit()

    # La celda vigente se resuelve por la última (momento desc, id desc)
    vigente = sesion_sqlite.execute(
        select(RacionServicioDia)
        .where(
            RacionServicioDia.fecha == dia,
            RacionServicioDia.fila_informe == "pediatria_gral",
            RacionServicioDia.columna_informe_id == 1,
        )
        .order_by(RacionServicioDia.momento.desc(), RacionServicioDia.id.desc())
        .limit(1)
    ).scalar_one()

    assert vigente.cantidad == 12
    assert vigente.momento == t1
