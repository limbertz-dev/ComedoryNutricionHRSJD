"""policias sin identidad

Revision ID: e3b5d7f9a1c2
Revises: c7e9a1b3d5f7
Create Date: 2026-10-28

Los policías son solo un contador: la cocinera confirma «registrar policía»
(en el checklist o en Control Biométrico) y queda una ración en la columna
Policías, sin nombre ni huella. Se retira el CHECK `huella_o_nombre`; las
raciones por huella o con nombre ya registradas quedan como están.

Solo toca bd_nutricion. El downgrade falla si ya hay raciones de policía sin
huella ni nombre: hay que decidir antes qué hacer con ellas.
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'e3b5d7f9a1c2'
down_revision: Union[str, Sequence[str], None] = 'c7e9a1b3d5f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(op.f('ck_raciones_policia_huella_o_nombre'), 'raciones_policia', type_='check')


def downgrade() -> None:
    """Downgrade schema."""
    op.create_check_constraint(
        op.f('ck_raciones_policia_huella_o_nombre'), 'raciones_policia',
        'vinculo_id IS NOT NULL OR nombre IS NOT NULL',
    )
