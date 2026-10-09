"""Diagnóstico técnico del comedor. Solo sistemas (ACCESO["monitoreo"]).

CONTRATO con el front R3-1-20261009 (no cambiar sin avisar):

    GET /monitoreo/estado   {momento_real, entorno, reloj_negocio, base,
                             lector, actividad}   (ver app/esquemas/monitoreo.py)

Responde 200 también con la base incompleta, siempre que el diagnóstico se
pueda armar. Cada petición consulta de nuevo: no hay caché entre peticiones.

Límites, a propósito:
  · La autenticación lee usuarios_sistema antes de llegar acá. Si MySQL no
    responde, falla ahí con un error genérico, sin cuerpo de diagnóstico:
    el front muestra «Diagnóstico no disponible» sin adivinar qué falló.
    Tampoco hay cuerpo estructurado si falla el catálogo o la revisión.
  · Un fallo de las consultas de actividad no tumba el diagnóstico: esa
    sección sale no disponible, con null, nunca con ceros.
  · El lector queda `desconocido` en todos los entornos: sin telemetría no
    hay señal de conectividad, y una lectura (ni un rechazo) no lo prueba.
"""

import logging
from datetime import date

from fastapi import APIRouter
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.consultas import monitoreo as consultas
from app.core import reloj
from app.core.config import config
from app.core.db import SesionDep
from app.esquemas.auth import ErrorConMotivo
from app.esquemas.monitoreo import (
    Actividad,
    EstadoBase,
    EstadoLector,
    EstadoMonitoreo,
    RegistroMayorId,
    RelojNegocio,
)

registro = logging.getLogger(__name__)

router = APIRouter(prefix="/monitoreo", tags=["monitoreo"])


def _sin_actividad(razon: str) -> Actividad:
    return Actividad(
        fuente=consultas.TABLA_ACTIVIDAD,
        disponible=False,
        razon=razon,
        aceptadas_dia=None,
        rechazadas_dia=None,
        registro_mayor_id=None,
    )


def _actividad(sesion: Session, catalogo: consultas.Catalogo, dia: date) -> Actividad:
    if consultas.TABLA_ACTIVIDAD not in catalogo.tablas:
        # Ni se intenta: una tabla ausente es dato no disponible, no cero.
        return _sin_actividad("tabla_ausente")
    try:
        datos = consultas.leer_actividad(sesion, dia)
    except SQLAlchemyError as error:
        # Solo el tipo: ni el SQL ni el texto del error salen de acá.
        registro.warning(
            "Diagnóstico: falló la consulta de actividad (%s)", type(error).__name__
        )
        # Si la recuperación también falla, sube como error genérico.
        sesion.rollback()
        return _sin_actividad("error_consulta")

    mayor = datos.registro_mayor_id
    return Actividad(
        fuente=consultas.TABLA_ACTIVIDAD,
        disponible=True,
        razon=None,
        aceptadas_dia=datos.aceptadas_dia,
        rechazadas_dia=datos.rechazadas_dia,
        registro_mayor_id=(
            None
            if mayor is None
            else RegistroMayorId(
                id=mayor.id,
                fecha_hora=mayor.fecha_hora,
                resultado=mayor.resultado,
                motivo=mayor.motivo,
                created_at=mayor.created_at,
            )
        ),
    )


@router.get(
    "/estado",
    response_model=EstadoMonitoreo,
    summary="Diagnóstico técnico: base, reloj, lector y actividad",
    responses={401: {"model": ErrorConMotivo}, 403: {"model": ErrorConMotivo}},
)
def estado(sesion: SesionDep) -> EstadoMonitoreo:
    """Todo sale de valores ya leídos: después de un rollback por la
    actividad no se toca ningún objeto de la sesión (la cuenta del token
    incluida), así no hay lecturas implícitas de más."""
    # Una sola foto del reloj: momento_real y reloj_negocio son coherentes.
    foto = reloj.estado()
    catalogo = consultas.leer_catalogo(sesion)
    base = EstadoBase(
        estado="incompleta" if catalogo.faltan else "ok",
        revision_alembic=catalogo.revision_alembic,
        tablas_propias=catalogo.tablas_propias,
        vistas_contrato=catalogo.vistas_contrato,
        faltan=catalogo.faltan,
    )
    return EstadoMonitoreo(
        momento_real=foto.real,
        entorno=config.entorno,
        reloj_negocio=RelojNegocio(
            ahora=foto.ahora,
            fecha=foto.ahora.date(),
            simulado=foto.simulado,
            congelado=foto.congelado,
        ),
        base=base,
        lector=EstadoLector(estado="desconocido", razon="sin_telemetria"),
        actividad=_actividad(sesion, catalogo, foto.ahora.date()),
    )
