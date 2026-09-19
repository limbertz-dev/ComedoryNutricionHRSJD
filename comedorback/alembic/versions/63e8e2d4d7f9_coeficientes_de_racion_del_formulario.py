"""coeficientes de racion del formulario

Revision ID: 63e8e2d4d7f9
Revises: b20dd32f5de6
Create Date: 2026-09-09

Siembra los coeficientes que reducen cada tiempo de comida a ración completa.

Van en una migración, como las columnas del formulario, porque están impresos
en el papel del Servicio de Estadística: no son una decisión abierta. Sin ellos
el informe mensual no puede calcular el equivalente en raciones completas.

Cada fila es la PRIMERA versión de su grupo. Si mañana la jefatura cambia un
coeficiente, no se edita esta fila: se cierra con `vigente_hasta` y se inserta
otra con la nueva vigencia. Así los informes ya firmados siguen dando el mismo
número cuando se recalculan, que es la razón de que el vínculo entre `comidas`
y `coeficientes_racion` sea por (grupo, fecha) y no por clave foránea.

Desayuno y Sobrealimentación comparten grupo, igual que Cena y Café nocturno:
el 0,15 y el 0,30 viven en un solo lugar, como en el formulario.

`definido_por` apunta al usuario 1. Es el dato que hay: la carga inicial no la
autorizó nadie desde el sistema porque el sistema todavía no existía.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "63e8e2d4d7f9"
down_revision: Union[str, Sequence[str], None] = "b20dd32f5de6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VIGENTE_DESDE = "2026-01-01"

GRUPOS = [
    ("desayuno_sobrealimentacion", "0.150"),
    ("almuerzo", "0.500"),
    ("te", "0.050"),
    ("cena_cafe_nocturno", "0.300"),
]


def upgrade() -> None:
    tabla = sa.table(
        "coeficientes_racion",
        sa.column("grupo", sa.String),
        sa.column("coeficiente", sa.Numeric),
        sa.column("vigente_desde", sa.Date),
        sa.column("respaldo", sa.String),
        sa.column("definido_por", sa.BigInteger),
    )
    op.bulk_insert(
        tabla,
        [
            {
                "grupo": grupo,
                "coeficiente": coeficiente,
                "vigente_desde": VIGENTE_DESDE,
                "respaldo": "Formulario del Servicio de Estadistica",
                "definido_por": 1,
            }
            for grupo, coeficiente in GRUPOS
        ],
    )


def downgrade() -> None:
    grupos = ", ".join("'%s'" % g for g, _ in GRUPOS)
    op.execute(
        f"DELETE FROM coeficientes_racion WHERE grupo IN ({grupos}) "
        f"AND vigente_desde = '{VIGENTE_DESDE}'"
    )
