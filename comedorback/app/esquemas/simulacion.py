"""Formas de los endpoints de simulación (solo con ENTORNO=simulacion)."""

from datetime import datetime, timedelta

from pydantic import BaseModel, Field, model_validator


class EstadoReloj(BaseModel):
    ahora: datetime = Field(description="La hora que ve el sistema.")
    real: datetime = Field(description="La hora real del servidor.")
    simulado: bool
    congelado: bool = Field(description="True si el reloj no avanza.")


class FijarReloj(BaseModel):
    momento: datetime = Field(
        description="Hora local. Con zona, se pasa a la hora local del servidor."
    )
    congelar: bool = Field(
        default=False,
        description="False: el reloj sigue corriendo desde `momento`.",
    )


class AvanzarReloj(BaseModel):
    dias: int = Field(default=0, ge=0)
    horas: int = Field(default=0, ge=0)
    minutos: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _algo_avanza(self) -> "AvanzarReloj":
        if not self.cuanto:
            raise ValueError("indique cuánto avanzar: dias, horas o minutos")
        return self

    @property
    def cuanto(self) -> timedelta:
        return timedelta(days=self.dias, hours=self.horas, minutes=self.minutos)


class ProximaFranja(BaseModel):
    comida_id: int
    comida: str
    inicio: datetime
    reloj: EstadoReloj
