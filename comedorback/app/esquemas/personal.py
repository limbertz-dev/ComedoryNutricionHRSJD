"""Formas de respuesta del padrón de comensales."""

from pydantic import BaseModel, Field


class Comensal(BaseModel):
    """Una persona del padrón, tal como la muestra la pantalla en vivo.

    El identificador es `usuario_id`, no el id de la persona: todo el sistema
    gira sobre `users.id` porque es lo que ya usan turnos_asignados y el resto
    del módulo heredado.
    """

    usuario_id: int = Field(description="users.id — eje de identidad del sistema")
    nombre_completo: str | None = Field(
        description="De personas.nombre_completo. Nunca de users.name, que es un usuario de acceso."
    )
    carnet_identidad: str | None = None
    numero_item: str | None = Field(
        default=None, description="numero_tipo_salario: el ítem con que figura en planilla"
    )
    tipo_trabajador: str | None = None
    categoria: str | None = Field(
        default=None, description="Categoría real del hospital (15 posibles)"
    )
    categoria_reporte: str | None = Field(
        default=None,
        description=(
            "Columna del formulario de Estadística. Queda en null mientras el "
            "hospital no defina el mapeo en categoria_reporte_map."
        ),
    )
    servicio: str | None = Field(
        default=None, description="Sala del hospital, no la categoría 'Servicio' del formulario"
    )
    tiene_ficha: bool = Field(
        description="False si el usuario no tiene fila en personas: aparece igual, señalado."
    )


class PaginaComensales(BaseModel):
    """Una página del padrón, con el total para que el front pueda paginar."""

    total: int
    limite: int
    desplazamiento: int
    sin_mapeo_de_categoria: int = Field(
        description=(
            "Cuántos de esta página no tienen columna de informe asignada. "
            "Mientras sea mayor que cero, el informe mensual no puede cuadrar."
        )
    )
    datos: list[Comensal]
