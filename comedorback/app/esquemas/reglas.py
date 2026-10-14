"""Formas de las reglas. CONTRATO con el front: no cambiar sin avisar."""

from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class VersionDerecho(BaseModel):
    """Una versión de los parámetros del derecho (solo lectura)."""

    id: int
    vigente_desde: date
    duracion_minima_horas: int = Field(description="Turno mínimo en horas, 1 a 48")
    novedades_que_anulan: list[str] = Field(description="Tipos que anulan, ordenados")
    excluir_enfermeria: bool
    motivo: str
    creada_por: str | None = Field(description="Username de root, o null en la base")
    creada: datetime
    estado: str = Field(description="programada | vigente | anterior")


class ListaDerecho(BaseModel):
    """La vigente de hoy y todas, de más nueva a más vieja."""

    vigente: VersionDerecho
    versiones: list[VersionDerecho]


class HorarioRegla(BaseModel):
    """Una versión del horario de una comida: rige en `[vigente_desde, vigente_hasta)`."""

    horario_id: int
    comida_id: int
    comida: str | None = Field(description="Nombre en v_comidas")
    hora_inicio: time
    hora_fin: time
    cruza_medianoche: bool = Field(description="True si hora_fin es menor que hora_inicio")
    vigente_desde: datetime = Field(
        description="Primer instante en que rige, inclusive. Con microsegundos."
    )
    vigente_hasta: datetime | None = Field(
        description="Instante en que deja de regir, EXCLUSIVO. null = versión abierta."
    )
    motivo: str | None = Field(
        description="Solo las filas anteriores a este cambio lo traen; las nuevas, null"
    )
    creada_por: str | None = Field(
        description="Username de la cuenta que guardó el cambio, o null en filas viejas"
    )
    creada: datetime = Field(description="Cuándo se guardó, según la base")
    estado: Literal["vigente", "anterior", "inactiva"] = Field(
        description=(
            "vigente = la versión abierta; anterior = ya cerrada; "
            "inactiva = fila heredada con activo=0, nunca se aplica"
        )
    )


CAMPOS_RETIRADOS = frozenset({"vigente_desde", "motivo"})


class CrearHorario(BaseModel):
    """Guardar el horario de una comida. Rige desde el instante del servidor.

    Sin `vigente_desde` ni `motivo`: un cliente que todavía los mande recibe
    422 en vez de que se ignoren en silencio.
    """

    model_config = ConfigDict(extra="forbid")

    comida_id: int = Field(gt=0)
    hora_inicio: time
    hora_fin: time
    base_horario_id: int | None = Field(
        ...,
        gt=0,
        description=(
            "OBLIGATORIO. `horario_id` de la versión abierta que el cliente "
            "editó; null solo si la comida no tiene versión abierta."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def rechazar_campos_retirados(cls, datos):
        if isinstance(datos, dict):
            retirados = sorted(CAMPOS_RETIRADOS & datos.keys())
            if retirados:
                raise ValueError(
                    f"campos retirados: {', '.join(retirados)}. El horario rige "
                    "desde el instante de guardar y no lleva motivo."
                )
        return datos

    @field_validator("hora_inicio", "hora_fin")
    @classmethod
    def hora_sin_fraccion_ni_zona(cls, hora: time) -> time:
        if hora.microsecond or hora.tzinfo is not None:
            raise ValueError("Use hora, minuto y segundo, sin fracción ni zona.")
        return hora
