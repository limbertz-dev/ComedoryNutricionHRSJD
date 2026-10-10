"""Formas del estado de la pantalla en vivo."""

from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, Field


class Cupo(BaseModel):
    previstas: int | None = Field(
        description="null = no hay cupo cargado para esta fecha y comida: sin límite"
    )
    servidas: int
    restantes: int | None
    porcentaje: int | None


class ConsumoCategoria(BaseModel):
    categoria: str
    raciones: int


class TotalesDia(BaseModel):
    raciones_servidas: int
    lecturas: int = Field(description="Toques de dedo del día, válidos o no")
    aceptadas: int
    rechazadas: int


class EstadoPantalla(BaseModel):
    momento: datetime
    fecha_comida: date | None = Field(
        description="Fecha a la que suman las raciones que se marquen ahora"
    )
    comida_id: int | None = None
    comida: str | None = None
    fuera_de_horario: bool = Field(
        description="True si el reloj no cae en ninguna franja: nadie puede marcar"
    )
    cupo: Cupo | None = None
    padron: int
    totales_del_dia: TotalesDia
    por_categoria: list[ConsumoCategoria] = Field(
        description="Siempre las 6 columnas, incluso en cero, para que el gráfico no cambie de forma"
    )


class Marcacion(BaseModel):
    id: int = Field(
        description=(
            "id en su tabla de origen. NO es único en la lista: una lectura y "
            "una asistencia manual pueden tener el mismo. Use clave_evento."
        )
    )
    fecha_hora: datetime
    usuario_id: int | None = None
    nombre: str | None = Field(
        default=None, description="null si el lector no reconoció la huella"
    )
    categoria: str | None = Field(
        default=None, description="Categoría del comensal o reporte"
    )
    comida_id: int | None = Field(
        default=None, description="ID de la comida asociada"
    )
    comida: str | None = Field(
        default=None,
        description="Nombre de la comida: Desayuno, Almuerzo, Cena, etc.",
    )
    resultado: str = Field(description="aceptada | rechazada")
    motivo: str | None = None
    valido: bool = Field(description="True si resultado == 'aceptada'")
    dispositivo: str
    origen: Literal["lectura_biometrica", "asistencia_manual"] = Field(
        description=(
            "Tabla de la que sale la fila, según la rama de la consulta; nunca "
            "del cliente ni del dispositivo. Una asistencia biométrica aparece "
            "solo como su lectura."
        )
    )
    clave_evento: str = Field(
        description=(
            "'<origen>:<id>'. Identifica la fila sin ambigüedad. No es un "
            "cursor ni refleja el orden de confirmación de las transacciones."
        ),
        examples=["lectura_biometrica:7", "asistencia_manual:7"],
    )


class ComidaDelDia(BaseModel):
    comida_id: int
    comida: str
    hora_inicio: time
    hora_fin: time
    estado: Literal["pendiente", "en_curso", "cerrada"] = Field(
        description="Dónde está la franja respecto al reloj del servidor"
    )
    previstas: int = Field(description="Personas distintas con derecho, según aplicar_reglas")
    servidas: int = Field(description="Raciones por fecha_comida, todos los métodos")
    manuales: int = Field(description="De las servidas, las registradas a mano")
    rechazos_por_motivo: dict[str, int] = Field(
        description="Siempre no_identificado, sin_derecho y duplicado, en 0 si no hay casos"
    )


class ComidasDelDia(BaseModel):
    fecha: date = Field(
        description="Día consultado. Las raciones suman por fecha_comida; los rechazos, por día del reloj"
    )
    comidas: list[ComidaDelDia] = Field(
        description="Una fila por comida vigente, en orden cronológico"
    )
    rechazos_sin_comida: int = Field(
        description="Rechazos del día que no resuelven a ninguna comida (fuera_horario, no_identificado fuera de franja)"
    )
