"""columnas orden y grupo_coeficiente en comidas

Revision ID: fa64a5d4e912
Revises:
Create Date: 2026-09-09 22:15:07.067186

ÚNICA migración de este sistema que altera una tabla del módulo de turnos.

Está escrita a mano y no autogenerada, a propósito: `comidas` figura en
app/core/tablas_heredadas.py, así que el autogenerate la ignora por completo.
Cualquier cambio sobre una tabla heredada tiene que pasar por aquí, a la vista,
y solo con acuerdo previo con el otro ingeniero.

Las dos columnas son aditivas y anulables: el sistema de turnos sigue
funcionando exactamente igual sin conocerlas.

  · orden              posición del tiempo de comida en el formulario de
                       Estadística (Desayuno 1, Sobrealimentación 2, ...).
  · grupo_coeficiente  a qué grupo de coeficientes_racion pertenece. Es el
                       grupo lógico, no una FK a una versión: el coeficiente
                       se resuelve por (grupo, fecha) para que cambiarlo no
                       altere los informes ya firmados.

No inserta datos. Faltan dos filas en `comidas` (Sobrealimentación y Café
nocturno) que el informe necesita, pero eso es carga de datos y requiere
autorización del hospital, no una migración de esquema.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fa64a5d4e912"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "comidas",
        sa.Column(
            "orden",
            sa.Integer(),
            nullable=True,
            comment="Posicion de este tiempo de comida en el formulario de Estadistica.",
        ),
    )
    op.add_column(
        "comidas",
        sa.Column(
            "grupo_coeficiente",
            sa.String(length=50),
            nullable=True,
            comment=(
                "Grupo logico de coeficientes_racion.grupo. NO es una FK: el "
                "coeficiente se resuelve por (grupo, fecha) para que cambiarlo "
                "no altere los informes ya firmados."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("comidas", "grupo_coeficiente")
    op.drop_column("comidas", "orden")
