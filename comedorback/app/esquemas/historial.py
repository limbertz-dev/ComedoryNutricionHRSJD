"""Formas del historial nominal."""

from datetime import date, time

from pydantic import BaseModel, Field

ESTADOS = "recibida | no_recibida | pendiente | no_aplica"


class ComidaListada(BaseModel):
    comida_id: int
    codigo: str
    nombre: str


class ComidaDelDia(BaseModel):
    comida_id: int
    nombre: str
    estado: str = Field(description=ESTADOS)
    hora: time | None = Field(
        default=None, description="A qué hora marcó, si recibió la ración"
    )


class ComensalDelDia(BaseModel):
    usuario_id: int
    nombre_completo: str | None
    carnet_identidad: str | None = None
    categoria: str | None = None
    servicio: str | None = None
    turno: str | None = Field(
        default=None, description="Turno que le da derecho ese día"
    )
    comidas: list[ComidaDelDia]


class HistorialDiario(BaseModel):
    fecha: date
    total: int
    limite: int
    desplazamiento: int
    comidas: list[ComidaListada] = Field(
        description="Las columnas de la tabla, en el orden del formulario"
    )
    datos: list[ComensalDelDia]


class TotalesComida(BaseModel):
    comida_id: int
    nombre: str
    asignadas: int = Field(description="Días del mes en que le correspondía")
    recibidas: int
    no_recibidas: int
    pendientes: int


class ComensalDelMes(BaseModel):
    usuario_id: int
    nombre_completo: str | None
    carnet_identidad: str | None = None
    categoria: str | None = None
    servicio: str | None = None
    total_asignadas: int
    total_recibidas: int
    total_no_recibidas: int
    total_pendientes: int
    totales: list[TotalesComida]


class HistorialMensual(BaseModel):
    gestion: int
    mes: int
    mes_nombre: str
    total: int
    limite: int
    desplazamiento: int
    comidas: list[ComidaListada]
    datos: list[ComensalDelMes]
