"""Formas del selector de períodos."""

from pydantic import BaseModel, Field


class MesDisponible(BaseModel):
    mes: int = Field(description="1 a 12")
    nombre: str
    situacion: str = Field(
        description="cerrado | curso | futuro, según el calendario"
    )
    cerrado: bool = Field(
        description="Si la jefatura le dio el visto bueno. Distinto de `situacion`."
    )
    raciones: int = Field(
        description="Raciones servidas. En cero, el mes va en blanco."
    )


class GestionDisponible(BaseModel):
    gestion: int
    activo: bool
    situacion: str
    raciones: int
    meses: list[MesDisponible]
