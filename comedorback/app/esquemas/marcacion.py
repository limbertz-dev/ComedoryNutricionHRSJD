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


class SolicitudIdentificacionPolicia(BaseModel):
    vinculo_id: int = Field(gt=0, description="vinculos_lector.id del policía elegido.")


class RespuestaIdentificacionPolicia(BaseModel):
    valido: bool
    lectura_id: int
    racion_id: int
    vinculo_id: int
    nombre: str
    comida: str | None = None
    fecha_comida: date
    reintento: bool


class PoliciaActivo(BaseModel):
    id: int = Field(description="vinculos_lector.id")
    nombre: str
    documento: str | None = None


class SolicitudMarcacion(BaseModel):
    """Lo que manda el navegador cuando la jefatura registra a mano."""

    usuario_id: int | None = Field(default=None, gt=0)
    dispositivo: str | None = Field(
        default=None,
        description=(
            "DEPRECADO: se ignora. El servidor registra 'registro-manual': "
            "el cliente no puede hacerse pasar por un lector."
        ),
    )
    metodo: Literal["biometrico", "manual"] = Field(
        default="biometrico",
        description=(
            "Omitido vale 'biometrico' y tiene su misma restricción: "
            "403 biometrico_solo_lector."
        ),
    )
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


class PersonaChecklist(BaseModel):
    """Una persona con derecho a la comida en curso."""

    usuario_id: int
    nombre: str | None = None
    categoria: str | None = None
    servicio: str | None = Field(default=None, description="Sala del hospital del turno")
    turno: str
    servida: bool
    metodo: Literal["biometrico", "manual", "checklist"] | None = None
    asistencia_id: int | None = None
    fecha_hora: datetime | None = None
    anulable: bool = Field(
        default=False,
        description="True en las marcas propias del checklist: se pueden desmarcar mientras la comida siga abierta.",
    )


class PoliciaChecklist(BaseModel):
    """Un policía por número (servido o pendiente) o una ración de policía sin
    número de la comida en curso (por huella o por nombre, siempre servida)."""

    nombre: str = Field(description="«Policía 3», o el nombre de la huella/ración vieja")
    servida: bool
    policia_id: int | None = Field(default=None, description="policias.id; NULL en raciones sin número")
    numero: int | None = None
    racion_id: int | None = None
    fecha_hora: datetime | None = None
    origen: Literal["checklist", "huella"] | None = None
    anulable: bool = False


class Checklist(BaseModel):
    momento: datetime
    fuera_de_horario: bool
    comida_id: int | None = None
    comida: str | None = None
    fecha_comida: date | None = None
    personas: list[PersonaChecklist]
    policias: list[PoliciaChecklist] = []


class SolicitudChecklist(BaseModel):
    usuario_id: int = Field(gt=0, description="users.id de quien recibe la ración.")


class SolicitudPoliciaChecklist(BaseModel):
    policia_id: int = Field(gt=0, description="policias.id del policía que recibe la ración.")


class RespuestaPoliciaChecklist(BaseModel):
    valido: bool
    motivo: str | None = Field(default=None, description="fuera_horario | duplicado | sin_columna_policias")
    policia_id: int
    nombre: str
    detalle: str
    racion_id: int | None = None
    comida: str | None = None
    fecha_comida: date | None = None


class RespuestaAnulacionPolicia(BaseModel):
    racion_id: int
    nombre: str | None
    anulada_en: datetime


class RespuestaAnulacion(BaseModel):
    asistencia_id: int
    usuario_id: int
    anulada_en: datetime


class PoliciaNumerado(BaseModel):
    """Un policía por número, para la jefatura."""

    id: int
    numero: int
    nombre: str = Field(description="«Policía 3»")
    activo: bool


class SolicitudEstadoPolicia(BaseModel):
    activo: bool = Field(description="false = dar de baja (sus raciones se conservan)")
