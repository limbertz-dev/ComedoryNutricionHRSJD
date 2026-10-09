"""Forma de GET /monitoreo/estado (contrato R3-1-20261009).

Todas las claves son obligatorias: lo que no se sabe va en null, nunca se
omite. Las fechas viajan en ISO 8601 local sin zona, como en el resto de la
API. Sin datos personales, dispositivo, nombre de base, SQL ni texto de
excepciones: el `response_model` impide que se cuele un campo de más.
"""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

Int0 = Annotated[int, Field(ge=0)]


class RelojNegocio(BaseModel):
    ahora: datetime = Field(description="reloj.ahora(): la hora del negocio")
    fecha: date = Field(description="Fecha de `ahora`: el día de los contadores")
    simulado: bool
    congelado: bool


class EstadoBase(BaseModel):
    """Presencia de tablas y vistas en el catálogo de la base propia. No
    valida columnas, contenido ni vigencia de la migración."""

    estado: Literal["ok", "incompleta"]
    revision_alembic: str | None = Field(
        description="null si alembic_version no existe o está vacía"
    )
    tablas_propias: Int0
    vistas_contrato: Int0
    faltan: list[str] = Field(description="Ordenado")


class EstadoLector(BaseModel):
    """Sin telemetría del lector no hay cómo saber si está conectado: la
    actividad registrada no lo prueba, y la simulación tampoco prueba que
    falte el hardware."""

    estado: Literal["desconocido"]
    razon: Literal["sin_telemetria"]


class RegistroMayorId(BaseModel):
    """La lectura de mayor id visible en toda la tabla. No es necesariamente
    el último commit ni el último toque físico."""

    id: int = Field(gt=0)
    fecha_hora: datetime = Field(description="Hora del NEGOCIO al marcar")
    resultado: Literal["aceptada", "rechazada"]
    motivo: Literal["duplicado", "sin_derecho", "fuera_horario", "no_identificado"] | None
    created_at: datetime = Field(
        description="Hora de MySQL al escribir la fila. No se compara con fecha_hora "
        "ni con momento_real"
    )


class Actividad(BaseModel):
    fuente: Literal["lecturas_biometricas"]
    disponible: bool
    razon: Literal["tabla_ausente", "error_consulta"] | None = Field(
        description="null solo si disponible=true"
    )
    aceptadas_dia: Int0 | None = Field(description="null solo si disponible=false")
    rechazadas_dia: Int0 | None = Field(description="null solo si disponible=false")
    registro_mayor_id: RegistroMayorId | None = Field(
        description="null si disponible=false o si la tabla está vacía"
    )


class EstadoMonitoreo(BaseModel):
    momento_real: datetime = Field(description="reloj.real(): la hora del servidor")
    entorno: Literal["produccion", "desarrollo", "simulacion"]
    reloj_negocio: RelojNegocio
    base: EstadoBase
    lector: EstadoLector
    actividad: Actividad
