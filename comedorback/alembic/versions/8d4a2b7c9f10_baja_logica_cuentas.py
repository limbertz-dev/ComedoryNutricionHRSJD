"""Conservar las cuentas eliminadas y su historial, ocultándolas del listado.

Revision ID: 8d4a2b7c9f10
Revises: e1a7c3b9d5f2
"""
from alembic import op
import sqlalchemy as sa

revision = "8d4a2b7c9f10"
down_revision = "e1a7c3b9d5f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("usuarios_sistema", sa.Column(
        "eliminada_en", sa.DateTime(), nullable=True,
        comment="Baja lógica: oculta la cuenta sin borrar su identidad ni registros. UTC.",
    ))


def downgrade() -> None:
    op.drop_column("usuarios_sistema", "eliminada_en")
