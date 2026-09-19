"""Agregar indices criticos para consultas por fecha.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-11
"""

from alembic import op


revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "idx_asistencias_fecha_comida",
        "asistencias",
        ["fecha_comida", "comida_id"],
    )
    op.create_index(
        "idx_lecturas_fecha_hora",
        "lecturas_biometricas",
        ["fecha_hora"],
    )


def downgrade() -> None:
    op.drop_index("idx_lecturas_fecha_hora", table_name="lecturas_biometricas")
    op.drop_index("idx_asistencias_fecha_comida", table_name="asistencias")
