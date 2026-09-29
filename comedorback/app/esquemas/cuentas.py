"""Forma de solo lectura de cuentas para la jefa. CONTRATO: no cambiar sin avisar."""

from datetime import datetime

from pydantic import BaseModel, Field


class CuentaLectura(BaseModel):
    """Una cuenta sin datos del padrón ni usuario_turnos_id."""

    id: int
    username: str
    nombre: str | None
    rol: str = Field(description="jefa | cocinera | sistemas")
    activo: bool
    debe_cambiar: bool
    ultimo_ingreso: datetime | None
