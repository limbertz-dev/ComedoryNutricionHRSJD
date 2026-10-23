"""policia en el checklist de cocina

Revision ID: c7e9a1b3d5f7
Revises: b3e5f7a9c1d4
Create Date: 2026-10-23

Un policía no está en el padrón ni necesita huella para el checklist: la
cocinera escribe su nombre y la ración va a Policías con las mismas reglas
que la huella de policía (vía libre, solo con una comida en curso).

  · raciones_policia.vinculo_id pasa a NULL permitido (sin huella) y suma
    `nombre`, escrito por cocina. Un CHECK exige uno de los dos.
  · anulaciones_checklist también guarda la ración de policía desmarcada:
    asistencia_id y usuario_id NULL permitido, más racion_policia_id y nombre.

Solo toca bd_nutricion. El downgrade falla si ya hay raciones de policía sin
huella o anulaciones de policía: hay que decidir antes qué hacer con ellas.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = 'c7e9a1b3d5f7'
down_revision: Union[str, Sequence[str], None] = 'b3e5f7a9c1d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COMENTARIO_VINCULO = 'La huella de policia que se leyo. NULL si cocina lo registro por nombre en el checklist.'
COMENTARIO_VINCULO_VIEJO = 'La huella de policia que se leyo. No identifica a una persona del padron.'
COMENTARIO_NOMBRE = 'Solo checklist: nombre del policia escrito por cocina (sin huella).'


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        'raciones_policia', 'vinculo_id',
        existing_type=mysql.BIGINT(unsigned=True), nullable=True,
        comment=COMENTARIO_VINCULO, existing_comment=COMENTARIO_VINCULO_VIEJO,
    )
    op.add_column('raciones_policia', sa.Column('nombre', sa.String(length=100), nullable=True, comment=COMENTARIO_NOMBRE))
    op.create_check_constraint(
        op.f('ck_raciones_policia_huella_o_nombre'), 'raciones_policia',
        'vinculo_id IS NOT NULL OR nombre IS NOT NULL',
    )
    op.alter_column(
        'anulaciones_checklist', 'asistencia_id',
        existing_type=mysql.BIGINT(unsigned=True), nullable=True,
        existing_comment='asistencias.id que se borro. Sin FK: la fila ya no existe.',
    )
    op.alter_column(
        'anulaciones_checklist', 'usuario_id',
        existing_type=mysql.BIGINT(unsigned=True), nullable=True,
        existing_comment='users.id del comensal desmarcado, sin FK entre bases.',
    )
    op.add_column('anulaciones_checklist', sa.Column('racion_policia_id', mysql.BIGINT(unsigned=True), nullable=True, comment='raciones_policia.id que se borro (policia del checklist). Sin FK.'))
    op.add_column('anulaciones_checklist', sa.Column('nombre', sa.String(length=100), nullable=True, comment='Solo policias: el nombre que tenia la racion anulada.'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('anulaciones_checklist', 'nombre')
    op.drop_column('anulaciones_checklist', 'racion_policia_id')
    op.alter_column(
        'anulaciones_checklist', 'usuario_id',
        existing_type=mysql.BIGINT(unsigned=True), nullable=False,
        existing_comment='users.id del comensal desmarcado, sin FK entre bases.',
    )
    op.alter_column(
        'anulaciones_checklist', 'asistencia_id',
        existing_type=mysql.BIGINT(unsigned=True), nullable=False,
        existing_comment='asistencias.id que se borro. Sin FK: la fila ya no existe.',
    )
    op.drop_constraint(op.f('ck_raciones_policia_huella_o_nombre'), 'raciones_policia', type_='check')
    op.drop_column('raciones_policia', 'nombre')
    op.alter_column(
        'raciones_policia', 'vinculo_id',
        existing_type=mysql.BIGINT(unsigned=True), nullable=False,
        comment=COMENTARIO_VINCULO_VIEJO, existing_comment=COMENTARIO_VINCULO,
    )
