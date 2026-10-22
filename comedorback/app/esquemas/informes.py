"""Formas de los tres informes."""

from datetime import date

from pydantic import BaseModel, Field


class FilaInforme(BaseModel):
    etiqueta: str = Field(description="Día, tiempo de comida o mes, según el informe")
    celdas: list[int] = Field(description="Una por categoría, en el orden de `categorias`")
    total: int
    registrado: bool = Field(
        description="False en días o meses que todavía no llegaron: van en blanco"
    )


class GrupoCoeficiente(BaseModel):
    grupo: str
    servidas: int
    coeficiente: float
    coeficientes_mixtos: bool = Field(default=False, description="El periodo usa varias versiones; no multiplicar todo por un unico coeficiente")
    equivalente: float = Field(
        description="servidas x coeficiente, calculado día por día con el coeficiente vigente"
    )


class Informe(BaseModel):
    tipo: str = Field(description="registro_diario | mensual | gestion")
    gestion: int
    mes: int | None = None
    mes_nombre: str | None = None
    desde: date
    hasta: date
    situacion: str = Field(description="cerrado | curso | futuro, según el calendario")
    cerrado: bool = Field(
        description="Si la jefatura dio el visto bueno. Distinto de que el mes ya pasó."
    )
    categorias: list[str]
    filas: list[FilaInforme]
    totales_por_categoria: list[int]
    total_general: int
    sin_clasificar: int = Field(
        description=(
            "Raciones cuya categoría todavía no está mapeada a una columna del "
            "formulario. Mientras sea mayor que cero, el informe no cuadra con "
            "el papel."
        )
    )
    sin_coeficiente: int = Field(
        description=(
            "Raciones de un tiempo de comida sin grupo de coeficiente: no suman "
            "al equivalente en raciones completas."
        )
    )
    grupos: list[GrupoCoeficiente] = Field(
        default_factory=list, description="Solo en el informe mensual"
    )
    total_equivalente: float | None = Field(
        default=None, description="Raciones completas equivalentes. Solo en el mensual."
    )
