"""columnas del formulario de estadistica

Revision ID: b20dd32f5de6
Revises: 717b68938e26
Create Date: 2026-09-09

Siembra las columnas del formulario del Servicio de Estadística.

Van en una migración y no en un script de carga porque NO son una decisión
pendiente: son las columnas impresas en el formulario que el hospital ya usa.
Sin ellas el sistema no puede registrar una ración, porque
`asistencias.categoria_reporte_id` es obligatorio.

Lo que sí sigue pendiente es el MAPEO: qué categoría real del hospital va a
cada columna. Eso vive en `categoria_reporte_map` y lo decide el hospital,
sobre todo para los internos y residentes, que no tienen columna propia en el
formulario de papel.

Por eso se siembra también "Sin clasificar". Mientras no exista el mapeo, la
ración se registra ahí en vez de rechazarse. El criterio es el mismo que en
cupos_racion: no negarle la comida a nadie por una decisión administrativa
que todavía no se tomó. Las raciones sin clasificar quedan visibles en el
informe para que la jefatura vea el hueco y lo resuelva.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b20dd32f5de6"
down_revision: Union[str, Sequence[str], None] = "717b68938e26"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNAS = [
    ("Médico", "medico", 1),
    ("Enfermería", "enfermeria", 2),
    ("Servicio", "servicio", 3),
    ("Administrativo", "administrativo", 4),
    ("Técnicos", "tecnicos", 5),
    ("Policías", "policias", 6),
    ("Sin clasificar", "sin_clasificar", 99),
]


def upgrade() -> None:
    tabla = sa.table(
        "categorias_reporte",
        sa.column("nombre", sa.String),
        sa.column("codigo", sa.String),
        sa.column("orden", sa.Integer),
        sa.column("activo", sa.Boolean),
    )
    op.bulk_insert(
        tabla,
        [
            {"nombre": nombre, "codigo": codigo, "orden": orden, "activo": True}
            for nombre, codigo, orden in COLUMNAS
        ],
    )


def downgrade() -> None:
    codigos = ", ".join("'%s'" % c for _, c, _ in COLUMNAS)
    op.execute(f"DELETE FROM categorias_reporte WHERE codigo IN ({codigos})")
