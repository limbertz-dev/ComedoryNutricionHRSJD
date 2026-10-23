"""Formas del lector biométrico real y de sus vínculos."""

from datetime import datetime

from typing import Literal

from pydantic import BaseModel, Field, model_validator

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
    tipo: Literal["personal", "policia"] = Field(
        default="personal",
        description="policia: huella sin persona del padrón; cada lectura es una ración en Policías.",
    )
    usuario_id: int | None = Field(
        default=None, gt=0, description="users.id de la persona. Obligatorio en personal; nunca en policia."
    )
    nombre: str | None = Field(
        default=None, min_length=3, max_length=100,
        description="Solo policia, obligatorio: nombre completo.",
    )
    documento: str | None = Field(
        default=None, min_length=1, max_length=30, pattern=r"^[A-Za-z0-9 ./-]+$",
        description="Solo policia, opcional: CI o número de placa.",
    )
    plantilla: str | None = Field(
        default=None,
        max_length=8192,
        pattern=r"^[A-Za-z0-9+/]+={0,2}$",
        description=(
            "Plantilla ZKFinger en base64, solo con lectores USB que comparan en la PC "
            "(ZK9500, ZK4500). Con terminales que reconocen solas, se omite."
        ),
    )


    @model_validator(mode="after")
    def _usuario_segun_tipo(self) -> "SolicitudVinculo":
        if self.nombre is not None:
            self.nombre = " ".join(self.nombre.split())
        if self.documento is not None:
            self.documento = self.documento.strip() or None
        if self.tipo == "personal":
            if self.usuario_id is None:
                raise ValueError("Un vínculo de personal necesita usuario_id.")
            if self.nombre is not None or self.documento is not None:
                raise ValueError("El nombre y el documento solo se escriben para un policía.")
        else:
            if self.usuario_id is not None:
                raise ValueError("Un vínculo de policía no lleva usuario_id.")
            if not self.nombre or len(self.nombre) < 3:
                raise ValueError("Escribe el nombre completo del policía.")
        return self


class Plantilla(BaseModel):
    """Lo que el puente carga en la memoria del SDK para comparar 1:N."""

    id: int = Field(description="vinculos_lector.id: el fid de la plantilla en el SDK.")
    identificador: str
    plantilla: str


class Vinculo(BaseModel):
    id: int
    identificador: str
    tipo: Literal["personal", "policia"]
    usuario_id: int | None
    nombre: str | None = Field(description="Del padrón, o el escrito para un policía.")
    documento: str | None = Field(default=None, description="Solo policías: CI o placa.")
    categoria: str | None
    activo: bool
    created_at: datetime
    updated_at: datetime
