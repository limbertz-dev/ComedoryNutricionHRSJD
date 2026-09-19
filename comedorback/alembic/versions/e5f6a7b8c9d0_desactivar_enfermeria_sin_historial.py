"""Desactivar Enfermeria del reporte sin asistencias historicas.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-11
"""

from alembic import op


revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE categorias_reporte
        SET activo = FALSE
        WHERE codigo = 'enfermeria'
          AND NOT EXISTS (
              SELECT 1
              FROM asistencias
              WHERE asistencias.categoria_reporte_id = categorias_reporte.id
          )
        """
    )


def downgrade() -> None:
    op.execute(
        "UPDATE categorias_reporte SET activo = TRUE WHERE codigo = 'enfermeria'"
    )
