"""retirar columna servicio

Revision ID: a7c9e1b3d5f6
Revises: f4c6e8a0b2d4
Create Date: 2026-10-28

Como «Administrativo» (f4c6e8a0b2d4): a la columna «Servicio» solo iban
Manual, Mantenimiento y Camillero, que no están entre las categorías que
comen (CATEGORIAS_PERMITIDAS); si sobra comida se les da sin registro. La
columna quedaba siempre vacía. Se desactiva (no se borra: un período viejo
con raciones en ella la sigue mostrando) y se quita su mapeo.

El downgrade la reactiva; el mapeo no se restaura.
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'a7c9e1b3d5f6'
down_revision: Union[str, Sequence[str], None] = 'f4c6e8a0b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "DELETE FROM categoria_reporte_map WHERE categoria_reporte_id IN "
        "(SELECT id FROM (SELECT id FROM categorias_reporte WHERE codigo = 'servicio') AS c)"
    )
    op.execute("UPDATE categorias_reporte SET activo = 0 WHERE codigo = 'servicio'")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("UPDATE categorias_reporte SET activo = 1 WHERE codigo = 'servicio'")
