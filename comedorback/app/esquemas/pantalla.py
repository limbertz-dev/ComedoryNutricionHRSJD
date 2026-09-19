"""Formas del estado de la pantalla en vivo."""

from datetime import date, datetime

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
    id: int
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
