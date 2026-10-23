"""policia identificado por cocina

Revision ID: d5a7c9e1f3b5
Revises: c1f4e6a8b0d3
Create Date: 2026-10-22

Si el lector no reconoce la huella de un policia, la cocinera puede elegirlo
en «Huellas por identificar». Su racion queda ligada a esa lectura, como la
entrega identificada del personal:

  · raciones_policia.lectura_id (UNIQUE, FK): una lectura da, como mucho, una
    racion; tambien la cruzan las validaciones de la identificacion del
    personal, asi que una lectura no se puede resolver dos veces.
  · raciones_policia.registrado_por_cuenta: la cocinera que lo identifico.
  · raciones_policia.clave_idempotencia (UNIQUE): un reintento no da dos.

Solo agrega columnas nulas: las raciones existentes (las del lector) quedan
igual. Solo toca bd_nutricion.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = 'd5a7c9e1f3b5'
down_revision: Union[str, Sequence[str], None] = 'c1f4e6a8b0d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('raciones_policia', sa.Column('lectura_id', mysql.BIGINT(unsigned=True), nullable=True, comment='Solo si cocina identifico como policia una huella no reconocida: esa lectura. UNIQUE: una lectura da, como mucho, una racion.'))
    op.add_column('raciones_policia', sa.Column('registrado_por_cuenta', mysql.BIGINT(unsigned=True), nullable=True, comment='La cocinera que identifico al policia. NULL si la leyo el lector.'))
    op.add_column('raciones_policia', sa.Column('clave_idempotencia', sa.CHAR(length=36), nullable=True, comment='Idempotency-Key de la identificacion por cocina: un reintento no da dos raciones.'))
    op.create_unique_constraint(op.f('uq_raciones_policia_clave_idempotencia'), 'raciones_policia', ['clave_idempotencia'])
    op.create_unique_constraint(op.f('uq_raciones_policia_lectura_id'), 'raciones_policia', ['lectura_id'])
    op.create_foreign_key(op.f('fk_raciones_policia_registrado_por_cuenta'), 'raciones_policia', 'usuarios_sistema', ['registrado_por_cuenta'], ['id'], ondelete='RESTRICT')
    op.create_foreign_key(op.f('fk_raciones_policia_lectura_id'), 'raciones_policia', 'lecturas_biometricas', ['lectura_id'], ['id'], ondelete='RESTRICT')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f('fk_raciones_policia_lectura_id'), 'raciones_policia', type_='foreignkey')
    op.drop_constraint(op.f('fk_raciones_policia_registrado_por_cuenta'), 'raciones_policia', type_='foreignkey')
    op.drop_constraint(op.f('uq_raciones_policia_lectura_id'), 'raciones_policia', type_='unique')
    op.drop_constraint(op.f('uq_raciones_policia_clave_idempotencia'), 'raciones_policia', type_='unique')
    op.drop_column('raciones_policia', 'clave_idempotencia')
    op.drop_column('raciones_policia', 'registrado_por_cuenta')
    op.drop_column('raciones_policia', 'lectura_id')
