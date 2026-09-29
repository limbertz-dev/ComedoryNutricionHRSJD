"""Formas de las reglas versionadas. CONTRATO con el front: no cambiar sin avisar."""

from datetime import date, datetime, time

from pydantic import BaseModel, Field


class VersionDerecho(BaseModel):
    """Una versión de los parámetros del derecho."""

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


class CrearVersionDerecho(BaseModel):
    """Nueva versión: siempre hoy o futuro, nunca hacia atrás."""

    vigente_desde: date
    duracion_minima_horas: int = Field(ge=1, le=48)
    novedades_que_anulan: list[str] = Field(default_factory=list)
    excluir_enfermeria: bool
    motivo: str = Field(description="Obligatorio, 10 o más caracteres")


class HorarioRegla(BaseModel):
    """Una versión del horario de una comida."""

    horario_id: int
    comida_id: int
    comida: str = Field(description="Nombre en v_comidas")
    hora_inicio: time
    hora_fin: time
    cruza_medianoche: bool = Field(description="True si hora_fin es menor que hora_inicio")
    vigente_desde: date
    vigente_hasta: date | None
    motivo: str | None
    creada_por: str | None = Field(description="Username de root, o null en filas viejas")


class CrearHorario(BaseModel):
    """Nueva versión de horario: cierra la anterior, no reescribe el pasado."""

    comida_id: int = Field(gt=0)
    hora_inicio: time
    hora_fin: time
    vigente_desde: date
    motivo: str = Field(description="Obligatorio, 10 o más caracteres")
