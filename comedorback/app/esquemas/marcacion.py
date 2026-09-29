"""Formas de la marcación y del derecho a comer."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class DerechoComida(BaseModel):
    """Una comida a la que la persona tiene derecho en una fecha."""

    comida_id: int
    comida: str
    fecha_comida: date = Field(
        description="fecha del turno + dia_relativo. No es la fecha del reloj."
    )
    fecha_turno: date
    dia_relativo: int = Field(
        description="0 = comida del mismo día del turno, 1 = del día siguiente"
    )
    turno: str
    turno_asignado_id: int
    servicio_id: int


class SolicitudMarcacion(BaseModel):
    """Lo que manda el lector, o la jefatura cuando registra a mano."""

    usuario_id: int | None = Field(default=None, gt=0)
    dispositivo: str = "lector-comedor-01"
    metodo: Literal["biometrico", "manual"] = "biometrico"
    momento: datetime | None = Field(
        default=None,
        description=(
            "Solo se acepta con metodo='manual', para registrar una ración que "
            "ya ocurrió. En biométrico manda siempre el reloj del servidor: si "
            "el cliente pudiera fijar la hora, podría antedatar raciones."
        ),
    )
    registrado_por: int | None = Field(
        default=None,
        description=(
            "DEPRECADO: se ignora. Quién registra sale del token "
            "(asistencias.registrado_por_cuenta)."
        ),
    )
    @model_validator(mode="after")
    def validar_usuario_para_metodo(self) -> "SolicitudMarcacion":
        if self.metodo == "manual" and self.usuario_id is None:
            raise ValueError("usuario_id es obligatorio cuando metodo='manual'")
        if self.usuario_id is None and self.metodo != "biometrico":
            raise ValueError("usuario_id solo puede omitirse en modo biometrico")
        return self


class RespuestaMarcacion(BaseModel):
    """La misma forma que ya espera la pantalla en vivo del front."""

    valido: bool
    motivo: str | None = Field(
        default=None,
        description="duplicado | sin_derecho | fuera_horario | no_identificado",
    )
    titulo: str
    detalle: str
    usuario_id: int | None = None
    nombre: str | None = None
    comida: str | None = None
    comida_id: int | None = None
    fecha_comida: date | None = None
    servicio_id: int | None = None
    lectura_id: int | None = None
    asistencia_id: int | None = None
    raciones_restantes: int | None = Field(
        default=None, description="null = no se aplica un limite manual de cupo"
    )
