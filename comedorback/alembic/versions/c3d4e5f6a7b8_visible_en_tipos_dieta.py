"""Borrado lógico de dietas: columna `visible` en `tipos_dieta`.

Revision ID: c3d4e5f6a7b8
Revises: d977e591ac49
Create Date: 2026-09-23

Decidido por el dueño: "Eliminar" una dieta no la borra de la base; la marca
invisible (visible = 0) y desaparece del frontend. `activo` sigue significando
"no disponible pero listada". Las filas existentes quedan visibles por el
DEFAULT 1. Espejo en `sql/modulo_pacientes.sql`.

El downgrade quita la columna: las dietas eliminadas vuelven a verse.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "c3d4e5f6a7b8"
down_revision = "d977e591ac49"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tipos_dieta",
        sa.Column(
            "visible",
            mysql.TINYINT(display_width=1),
            server_default=sa.text("1"),
            nullable=False,
            comment="0 = eliminada (borrado logico): no se lista ni se asigna. La fila nunca se borra.",
        ),
    )


def downgrade() -> None:
    op.drop_column("tipos_dieta", "visible")
