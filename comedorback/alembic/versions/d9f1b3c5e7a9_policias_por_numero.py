"""policias por numero

Revision ID: d9f1b3c5e7a9
Revises: c7e9a1b3d5f7
Create Date: 2026-10-27

Los policías dejan de escribirse por nombre en el checklist: la jefatura da
de alta Policía 1, 2, ... y la cocinera marca a cada uno como al personal.

  · policias: número único, activo (baja lógica) y la cuenta que lo creó.
  · raciones_policia.policia_id (FK, NULL permitido): el policía por número.
    UNIQUE(policia_id, fecha_comida, comida_id): una ración por comida y día.
    La ración guarda además «Policía N» en `nombre`, así las pantallas y los
    informes que ya muestran el nombre no cambian. Las raciones por huella o
    por nombre ya registradas quedan como están.

Solo toca bd_nutricion. El downgrade conserva las raciones (con su nombre
«Policía N») y pierde solo el vínculo al número.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = 'd9f1b3c5e7a9'
down_revision: Union[str, Sequence[str], None] = 'c7e9a1b3d5f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('policias',
    sa.Column('id', mysql.BIGINT(unsigned=True), nullable=False),
    sa.Column('numero', mysql.SMALLINT(unsigned=True), nullable=False, comment='Policia 1, 2, ...: el siguiente libre al crearlo.'),
    sa.Column('activo', mysql.TINYINT(display_width=1), nullable=False),
    sa.Column('creado_por_cuenta', mysql.BIGINT(unsigned=True), nullable=True, comment='Cuenta de jefatura que lo dio de alta.'),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['creado_por_cuenta'], ['usuarios_sistema.id'], name=op.f('fk_policias_creado_por_cuenta'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_policias')),
    sa.UniqueConstraint('numero', name=op.f('uq_policias_numero')),
    comment='Policias que comen en el comedor, por numero (Policia 1, 2, ...): no estan en la base de turnos. Los da de alta la jefatura. Baja logica: se desactiva, no se borra.',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci'
    )
    op.add_column('raciones_policia', sa.Column('policia_id', mysql.BIGINT(unsigned=True), nullable=True, comment='El policia por numero marcado en el checklist. NULL en las raciones por huella o por nombre.'))
    op.create_foreign_key(op.f('fk_raciones_policia_policia_id'), 'raciones_policia', 'policias', ['policia_id'], ['id'], ondelete='RESTRICT')
    op.create_unique_constraint('uq_raciones_policia_policia_comida', 'raciones_policia', ['policia_id', 'fecha_comida', 'comida_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f('fk_raciones_policia_policia_id'), 'raciones_policia', type_='foreignkey')
    op.drop_constraint('uq_raciones_policia_policia_comida', 'raciones_policia', type_='unique')
    op.drop_column('raciones_policia', 'policia_id')
    op.drop_table('policias')
