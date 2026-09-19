"""Historial nominal: quién recibió qué, persona por persona."""

from dataclasses import asdict
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.consultas import historial as consultas
from app.consultas.historial import MESES
from app.core.db import SesionDep
from app.esquemas.historial import (
    ComensalDelDia,
    ComensalDelMes,
    ComidaListada,
    HistorialDiario,
    HistorialMensual,
)

router = APIRouter(prefix="/historial", tags=["historial nominal"])


@router.get("/diario", response_model=HistorialDiario, summary="Lista nominal de un día")
def diario(
    sesion: SesionDep,
    fecha: Annotated[date | None, Query(description="Por defecto, hoy")] = None,
    limite: Annotated[int, Query(ge=1, le=200)] = 50,
    desplazamiento: Annotated[int, Query(ge=0)] = 0,
) -> HistorialDiario:
    """Cada persona con el estado de cada comida de ese día.

    Aparece quien tenía derecho ese día **o** quien recibió una ración: los
    segundos no siempre están entre los primeros, porque una autorización
    excepcional produce una ración sin turno que la respalde.

    Los cuatro estados se derivan al consultar, no se guardan en ninguna tabla.
    """
    fecha = fecha or date.today()
    total, comidas, datos = consultas.historial_diario(
        sesion, fecha, limite, desplazamiento
    )
    return HistorialDiario(
        fecha=fecha,
        total=total,
        limite=limite,
        desplazamiento=desplazamiento,
        comidas=[ComidaListada(**asdict(c)) for c in comidas],
        datos=[ComensalDelDia(**asdict(d)) for d in datos],
    )


@router.get(
    "/mensual", response_model=HistorialMensual, summary="Resumen nominal de un mes"
)
def mensual(
    sesion: SesionDep,
    gestion: Annotated[int | None, Query(ge=2000, le=2100)] = None,
    mes: Annotated[int | None, Query(ge=1, le=12)] = None,
    limite: Annotated[int, Query(ge=1, le=200)] = 50,
    desplazamiento: Annotated[int, Query(ge=0)] = 0,
) -> HistorialMensual:
    """Cuántas raciones recibió y cuántas no cada persona, por tiempo de comida."""
    hoy = date.today()
    gestion = gestion or hoy.year
    mes = mes or hoy.month
    total, comidas, datos = consultas.historial_mensual(
        sesion, gestion, mes, limite, desplazamiento
    )
    return HistorialMensual(
        gestion=gestion,
        mes=mes,
        mes_nombre=MESES[mes - 1],
        total=total,
        limite=limite,
        desplazamiento=desplazamiento,
        comidas=[ComidaListada(**asdict(c)) for c in comidas],
        datos=[ComensalDelMes(**asdict(d)) for d in datos],
    )
