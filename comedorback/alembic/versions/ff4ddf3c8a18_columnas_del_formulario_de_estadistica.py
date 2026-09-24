"""columnas del formulario de estadistica

Revision ID: ff4ddf3c8a18
Revises: 4b5a9ed9330e
Create Date: 2026-09-24

Siembra las columnas del formulario del Servicio de Estadística.

Van en una migración y no en app/semillas porque NO son una decisión
pendiente: son las columnas impresas en el formulario que el hospital ya usa,
y son datos 100 % propios (no dependen de ningún id de la base de turnos).
Sin ellas el sistema no puede registrar una ración, porque
`asistencias.categoria_reporte_id` es obligatorio.

Enfermería no tiene columna: está fuera del comedor (ver derecho.py). La
cadena vieja la sembraba y después la desactivaba; acá directamente no nace.

"Sin clasificar" existe para que una categoría todavía no mapeada no deje a
nadie sin comer: la ración se registra ahí y queda visible en el informe.

Lo que sí sigue pendiente es el MAPEO categoría -> columna, que decide el
hospital. Vive en `categoria_reporte_map` y se carga con
`python -m app.semillas`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ff4ddf3c8a18"
down_revision: Union[str, Sequence[str], None] = "4b5a9ed9330e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNAS = [
    ("Médico", "medico", 1),
    ("Servicio", "servicio", 2),
    ("Administrativo", "administrativo", 3),
    ("Técnicos", "tecnicos", 4),
    ("Policías", "policias", 5),
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
