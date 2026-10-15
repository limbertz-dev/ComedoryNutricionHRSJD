"""Formas de las intervenciones de cocina.

Identificar a mano una lectura no reconocida y confirmar la entrega es cosa de
la cocinera (POST). La jefa solo las consulta (GET). Sin nota, sin motivo
escrito: la causa la fija el servidor.

Vocabulario: `registrada` es la única que es una ENTREGA. `rechazada` es un
intento que no la tuvo; nunca se le llama entrega.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.esquemas.auth import ErrorConMotivo

Resultado = Literal["registrada", "rechazada"]
Estado = Literal["pendiente", "resuelta"]


class SolicitudIdentificacion(BaseModel):
    """Solo a quién se identifica. La lectura va en la ruta, la clave de
    idempotencia en la cabecera `Idempotency-Key`, la cuenta sale del token y
    la hora del reloj del servidor: ningún otro campo se acepta."""

    model_config = ConfigDict(extra="forbid")

    usuario_id: int = Field(gt=0, description="users.id de la persona identificada")


class RespuestaIdentificacion(BaseModel):
    valido: bool = Field(description="True solo si se registró la entrega")
    resultado: Resultado
    motivo: str | None = Field(
        default=None, description="sin_derecho | duplicado si el intento se rechazó"
    )
    titulo: str
    detalle: str
    reintento: bool = Field(
        description="True si es la respuesta guardada de una clave ya usada"
    )
    lectura_id: int
    asistencia_id: int | None = None
    intervencion_id: int
    usuario_id: int
    nombre: str | None = None
    comida: str | None = None
    comida_id: int | None = None
    fecha_comida: date | None = None
    servicio_id: int | None = None
    raciones_restantes: int | None = None
    causa: str
    momento: datetime


class ErrorIntervencionCuerpo(ErrorConMotivo):
    """Un error de la identificación. Los campos extra solo vienen en los
    conflictos que dejan una fila de auditoría."""

    resultado: Resultado | None = None
    lectura_id: int | None = None
    intervencion_id: int | None = None
    resuelta_por_mi: bool | None = Field(
        default=None, description="Solo en lectura_ya_resuelta; nunca dice quién fue"
    )
    reintento: bool | None = None


# --- GET /intervenciones-cocina ------------------------------------------------


class DecisionOriginalLectura(BaseModel):
    lectura_id: int
    resultado: str
    motivo: str | None = None
    fecha_hora: datetime
    dispositivo: str


class CuentaResponsable(BaseModel):
    id: int
    usuario: str
    nombre: str | None = None


class ComensalIntervenido(BaseModel):
    usuario_id: int
    nombre: str | None = None
    categoria: str | None = None


class ServicioUsado(BaseModel):
    comida_id: int | None = None
    comida: str | None = None
    fecha_comida: date | None = None
    ventana_inicio: datetime | None = None
    ventana_fin: datetime | None = None
    origen: str | None = Field(
        default=None,
        description="reconstruido_por_horario: no es un dato histórico de la lectura",
    )


class ResultadoDelIntento(BaseModel):
    entrega_registrada: bool
    asistencia_id: int | None = None


class Intervencion(BaseModel):
    id: int
    clave_evento: str = Field(examples=["intervencion_lectura:55"])
    resultado: Resultado
    motivo_rechazo: str | None = None
    causa: str
    momento: datetime
    decision_original: DecisionOriginalLectura
    cuenta: CuentaResponsable
    comensal: ComensalIntervenido
    servicio_usado: ServicioUsado
    resultado_final: ResultadoDelIntento = Field(
        description="Lo que pasó con ESTE intento, no con la lectura"
    )
    estado_actual_lectura: Estado = Field(
        description="Si la lectura ya tiene una entrega registrada (de cualquier intento)"
    )


class TotalesIntervenciones(BaseModel):
    registradas: int
    rechazadas: int


class PaginaIntervenciones(BaseModel):
    desde: date
    hasta: date
    total: int
    limite: int
    desplazamiento: int
    totales: TotalesIntervenciones = Field(
        description="Sobre todo el filtro, no solo la página"
    )
    datos: list[Intervencion]
