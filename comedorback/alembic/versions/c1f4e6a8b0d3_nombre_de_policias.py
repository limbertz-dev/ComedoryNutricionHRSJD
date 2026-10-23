"""nombre y documento de policias en vinculos_lector

Revision ID: c1f4e6a8b0d3
Revises: a9d3c5e7f1b2
Create Date: 2026-10-22

Al registrar la huella de un policia se escribe su nombre completo y,
opcional, su CI o numero de placa: asi Control Biometrico y Supervision
muestran quien comio. Dos columnas nuevas y nulas en `vinculos_lector`; las
filas existentes quedan igual (un policia sin nombre se muestra «Policía»).
Solo toca bd_nutricion.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c1f4e6a8b0d3'
down_revision: Union[str, Sequence[str], None] = 'a9d3c5e7f1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('vinculos_lector', sa.Column('nombre', sa.String(length=100), nullable=True, comment='Solo policias: nombre completo, escrito al registrar la huella.'))
    op.add_column('vinculos_lector', sa.Column('documento', sa.String(length=30), nullable=True, comment='Solo policias, opcional: CI o numero de placa.'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('vinculos_lector', 'documento')
    op.drop_column('vinculos_lector', 'nombre')
