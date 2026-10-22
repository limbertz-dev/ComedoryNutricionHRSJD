"""Formas del lector biométrico real y de sus vínculos."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.esquemas.marcacion import RespuestaMarcacion

# Lo que un lector puede entregar como identificador: el número de usuario de
# una terminal o el id de plantilla de un programa USB. Sin espacios.
PATRON_IDENTIFICADOR = r"^[A-Za-z0-9._-]{1,64}$"


class SolicitudLectura(BaseModel):
    """Un toque de dedo, tal como lo entrega el puente de la PC de cocina."""

    identificador: str | None = Field(
        default=None,
        pattern=PATRON_IDENTIFICADOR,
        description=(
            "Con el que el lector enroló la huella. null = el lector no reconoció "
            "la huella. Uno sin vínculo activo se registra como no_identificado, "
            "para que la cocinera identifique a la persona."
        ),
    )


class RespuestaLectura(RespuestaMarcacion):
    """La respuesta de la marcación, más lo que el puente necesita saber."""

    dispositivo: str = Field(description="El lector, según su clave en LECTORES.")
    vinculado: bool = Field(
        description="El identificador tenía un vínculo activo con una persona."
    )
    reintento: bool = Field(
        description="La Idempotency-Key ya se había recibido: es la respuesta guardada."
    )


class SaludLector(BaseModel):
    dispositivo: str
    momento: datetime = Field(description="Hora del servidor: la que se usa al registrar.")
    comida_en_curso: str | None = Field(description="null = fuera de horario de comida.")
    vinculos_activos: int


class SolicitudVinculo(BaseModel):
    identificador: str = Field(pattern=PATRON_IDENTIFICADOR)
    usuario_id: int = Field(gt=0, description="users.id de la persona en el padrón.")


class Vinculo(BaseModel):
    id: int
    identificador: str
    usuario_id: int
    nombre: str | None = Field(description="Del padrón; null si la persona ya no figura.")
    categoria: str | None
    activo: bool
    created_at: datetime
    updated_at: datetime
