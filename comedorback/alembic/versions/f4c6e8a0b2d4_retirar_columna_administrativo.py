"""retirar columna administrativo

Revision ID: f4c6e8a0b2d4
Revises: e3b5d7f9a1c2
Create Date: 2026-10-28

El personal administrativo no come en el comedor (solo las categorías de
CATEGORIAS_PERMITIDAS), así que la columna «Administrativo» del formulario
quedaba siempre vacía. Se desactiva: no sale en el sistema, el Excel ni el
PDF. No se borra: si un período viejo tiene raciones en ella, el informe la
sigue mostrando (app/consultas/informes.py::_columnas).

Su mapeo de categorías se quita para que una ración de esa categoría, si
alguna vez la hubiera, caiga en «Sin clasificar» y quede a la vista.

El downgrade la reactiva; el mapeo no se restaura (python -m app.semillas lo
vuelve a cargar si se quiere).
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'f4c6e8a0b2d4'
down_revision: Union[str, Sequence[str], None] = 'e3b5d7f9a1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "DELETE FROM categoria_reporte_map WHERE categoria_reporte_id IN "
        "(SELECT id FROM (SELECT id FROM categorias_reporte WHERE codigo = 'administrativo') AS c)"
    )
    op.execute("UPDATE categorias_reporte SET activo = 0 WHERE codigo = 'administrativo'")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("UPDATE categorias_reporte SET activo = 1 WHERE codigo = 'administrativo'")
