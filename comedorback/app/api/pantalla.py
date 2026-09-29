"""Estado de la pantalla en vivo del comedor."""

from dataclasses import asdict
from datetime import date, datetime, time
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.consultas import historial as consultas_historial
from app.consultas import pantalla as consultas
from app.core import reloj
from app.core.autorizacion import UsuarioActual
from app.core.db import SesionDep
from app.esquemas.historial import ComensalDelDia, ComidaListada, HistorialDiario
from app.esquemas.pantalla import ComidasDelDia, EstadoPantalla, Marcacion
from app.modelos.heredados import Comensal

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


@router.get(
    "/comidas-del-dia",
    response_model=ComidasDelDia,
    summary="Las comidas del día, con su avance",
)
def comidas_del_dia(
    sesion: SesionDep,
    fecha: Annotated[
        date | None,
        Query(description="Fecha a consultar. Por defecto hoy."),
    ] = None,
) -> ComidasDelDia:
    """Una fila por comida vigente: previstas, servidas, manuales y rechazos.

    Solo lectura, para la supervisión del día. El estado de cada franja sale
    del reloj del servidor: nunca se acepta hora del cliente.
    """
    return ComidasDelDia(**asdict(consultas.comidas_del_dia(sesion, fecha=fecha)))


@router.get(
    "/dia-personal",
    response_model=HistorialDiario,
    summary="Ficha del día de una persona",
)
def dia_personal(
    sesion: SesionDep,
    usuario: UsuarioActual,
    persona_id: Annotated[int, Query(gt=0, description="users.id, no personas.id")],
    fecha: Annotated[date | None, Query(description="Por defecto, hoy")] = None,
) -> HistorialDiario:
    """La tira del día que la pantalla muestra tras una marcación.

    Misma forma y mismas reglas que GET /historial/diario, acotada a una
    persona, para que la cocinera la vea sin abrir el historial completo.
    `datos` trae su ficha, o viene vacío si ese día no tenía derecho ni
    recibió ración (tampoco aparecería en el historial).
    """
    if sesion.get(Comensal, persona_id) is None:
        raise HTTPException(status_code=404, detail="No existe ese comensal")
    fecha = fecha or reloj.hoy()
    total, comidas, datos = consultas_historial.historial_diario(
        sesion, fecha, limite=1, usuario_id=persona_id
    )
    fichas = [ComensalDelDia(**asdict(d)) for d in datos]
    if usuario.rol == "cocinera":
        for ficha in fichas:
            ficha.carnet_identidad = None
    return HistorialDiario(
        fecha=fecha,
        total=total,
        limite=1,
        desplazamiento=0,
        comidas=[ComidaListada(**asdict(c)) for c in comidas],
        datos=fichas,
    )
