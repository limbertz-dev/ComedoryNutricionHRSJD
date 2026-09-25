"""Formas del ingreso. CONTRATO con el front: no cambiar sin avisar."""

from datetime import datetime

from pydantic import BaseModel, Field


class SolicitudLogin(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=200)


class SesionIniciada(BaseModel):
    """200 de login, cambio de clave y refresh."""

    access: str = Field(description="Token de acceso. Va en Authorization: Bearer")
    refresh: str = Field(description="Token para POST /auth/refresh")
    rol: str = Field(description="jefa | cocinera | sistemas")
    debe_cambiar: bool = Field(description="Siempre false acá: si fuera true, la respuesta es 428")


class ErrorConMotivo(BaseModel):
    detail: str
    motivo: str


class CuentaBloqueada(ErrorConMotivo):
    """423: demasiados intentos fallidos."""

    reintento_en: datetime = Field(description="Desde cuándo se puede volver a intentar")


class CambioPendiente(ErrorConMotivo):
    """428: la clave es temporal y hay que cambiarla antes de seguir."""

    temporal: str = Field(
        description="Token que SOLO sirve para POST /auth/cambio-password"
    )


class SolicitudCambioPassword(BaseModel):
    password_nueva: str = Field(min_length=1, max_length=200)
    password_actual: str | None = Field(
        default=None,
        max_length=200,
        description=(
            "Obligatoria con token de acceso (cambio voluntario). Con el token "
            "temporal del 428 no se pide: la clave se acaba de verificar."
        ),
    )


class SolicitudRefresh(BaseModel):
    refresh: str


class Yo(BaseModel):
    id: int
    username: str
    rol: str
    debe_cambiar: bool
