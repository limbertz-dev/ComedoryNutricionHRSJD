"""Estado de la pantalla en vivo del comedor."""

from dataclasses import asdict
from datetime import date, datetime, time
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.consultas import pantalla as consultas
from app.core.db import SesionDep
from app.esquemas.pantalla import EstadoPantalla, Marcacion

router = APIRouter(prefix="/pantalla", tags=["pantalla en vivo"])


@router.get("/estado", response_model=EstadoPantalla, summary="Estado del comedor ahora")
def estado(
    sesion: SesionDep,
    fecha: Annotated[
        date | None,
        Query(description="Fecha a simular. Por defecto, hoy."),
    ] = None,
    hora: Annotated[
        str | None,
        Query(description="Hora a simular en formato HH:MM. Por defecto, la actual."),
    ] = None,
) -> EstadoPantalla:
    """Lo que la pantalla necesita para pintarse entera.

    Todo se calcula en el momento, sobre `asistencias` y `lecturas_biometricas`.
    No hay contadores acumulados: un contador que se incrementa se desincroniza
    tarde o temprano, y entonces la pantalla y el informe del mismo día dicen
    cosas distintas.
    """
    hora_simulada: time | None = None
    if hora is not None:
        try:
            hora_simulada = datetime.strptime(hora, "%H:%M").time()
        except ValueError as error:
            raise HTTPException(
                status_code=422,
                detail="hora debe tener el formato HH:MM",
            ) from error
    return EstadoPantalla(
        **asdict(consultas.estado(sesion, fecha=fecha, hora=hora_simulada))
    )


@router.get(
    "/ultimas-marcaciones",
    response_model=list[Marcacion],
    summary="Lo último que pasó en el lector",
)
def ultimas_marcaciones(
    sesion: SesionDep,
    fecha: Annotated[
        date | None,
        Query(description="Fecha a consultar. Por defecto hoy."),
    ] = None,
    comida_id: Annotated[
        int | None,
        Query(description="Filtrar por ID de comida"),
    ] = None,
    limite: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[Marcacion]:
    """Incluye los rechazos: son justamente lo que la persona parada frente al
    lector necesita ver."""
    return [
        Marcacion(**asdict(m))
        for m in consultas.ultimas_marcaciones(
            sesion, fecha=fecha, comida_id=comida_id, limite=limite
        )
    ]
