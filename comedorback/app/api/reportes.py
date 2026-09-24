"""Los tres informes del Servicio de Estadística."""

from dataclasses import asdict
from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.consultas import informes as consultas
from app.consultas import periodos as consultas_periodos
from app.core.db import SesionDep
from app.esquemas.informes import Informe
from app.esquemas.periodos import GestionDisponible

router = APIRouter(prefix="/reportes", tags=["reportes"])

Gestion = Annotated[int, Query(ge=2000, le=2100, description="Año")]
NumeroMes = Annotated[int, Query(ge=1, le=12)]


def _hoy() -> date:
    return date.today()


@router.get(
    "/periodos",
    response_model=list[GestionDisponible],
    summary="Gestiones y meses que se pueden consultar",
)
def periodos(sesion: SesionDep) -> list[GestionDisponible]:
    """Lo que necesita el selector de período de la pantalla de informes.

    Las gestiones son el año en curso más los años con raciones registradas,
    así que un año nuevo aparece solo sin tocar el código. Cada mes trae su
    conteo de raciones para poder mostrar en blanco los que no tienen registro.
    """
    return [
        GestionDisponible(**asdict(g))
        for g in consultas_periodos.periodos_disponibles(sesion)
    ]


@router.get(
    "/registro-diario",
    response_model=Informe,
    summary="Registro diario de raciones del mes",
)
def registro_diario(
    sesion: SesionDep,
    gestion: Gestion = None,
    mes: NumeroMes = None,
) -> Informe:
    """La planilla del cuaderno: una fila por día, columnas por categoría."""
    hoy = _hoy()
    informe = consultas.registro_diario(
        sesion, gestion or hoy.year, mes or hoy.month
    )
    return Informe(**asdict(informe))


@router.get("/mensual", response_model=Informe, summary="Informe mensual de raciones")
def mensual(
    sesion: SesionDep,
    gestion: Gestion = None,
    mes: NumeroMes = None,
) -> Informe:
    """El formulario de Estadística: tiempos de comida × categorías.

    Incluye la reducción a ración completa. El `total_general` tiene que dar
    exactamente igual al del registro diario del mismo mes: son la misma suma,
    abierta por criterios distintos.
    """
    hoy = _hoy()
    informe = consultas.informe_mensual(sesion, gestion or hoy.year, mes or hoy.month)
    return Informe(**asdict(informe))


@router.get("/gestion", response_model=Informe, summary="Resumen anual de raciones")
def resumen_gestion(sesion: SesionDep, gestion: Gestion = None) -> Informe:
    """El año entero, un mes por fila."""
    informe = consultas.resumen_gestion(sesion, gestion or _hoy().year)
    return Informe(**asdict(informe))


@router.get(
    "/informe",
    response_model=Informe,
    summary="Informe oficial de raciones servidas por rango de fechas",
)
def informe_por_rango(
    sesion: SesionDep,
    desde: date = Query(..., description="Fecha inicial (YYYY-MM-DD)"),
    hasta: date = Query(..., description="Fecha final (YYYY-MM-DD)"),
) -> Informe:
    """Retorna el informe de raciones discriminado por tiempo de comida y
    categoría, con coeficientes de reducción a ración completa para el rango solicitado."""
    if desde > hasta:
        raise HTTPException(
            status_code=422,
            detail="La fecha inicial ('desde') no puede ser posterior a la fecha final ('hasta').",
        )
    informe = consultas.informe_rango(sesion, desde, hasta)
    return Informe(**asdict(informe))
