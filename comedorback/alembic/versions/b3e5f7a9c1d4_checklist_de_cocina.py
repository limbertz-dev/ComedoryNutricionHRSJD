"""checklist de cocina

Revision ID: b3e5f7a9c1d4
Revises: d5a7c9e1f3b5
Create Date: 2026-10-23

Mientras no esté el lector, la cocinera marca en una lista a quien recibe su
ración de la comida en curso:

  · asistencias.metodo suma 'checklist'. Pasa por las mismas reglas que la
    huella (horario, duplicado, derecho: turno de 12 h y categorías
    permitidas) y guarda la cuenta en registrado_por_cuenta.
  · anulaciones_checklist: la misma cocinera puede desmarcar su marca a los
    pocos minutos si se equivocó; la asistencia se borra y su copia queda
    aquí.

Solo toca bd_nutricion. El downgrade falla si ya hay asistencias con
metodo='checklist' (MySQL no las puede convertir): hay que decidir antes qué
hacer con ellas.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = 'b3e5f7a9c1d4'
down_revision: Union[str, Sequence[str], None] = 'd5a7c9e1f3b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COMENTARIO_TABLA = (
    "Raciones del checklist que la misma cocinera desmarco a los pocos "
    "minutos. Solo inserciones: la asistencia se borra y aqui queda su copia."
)


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        'asistencias', 'metodo',
        existing_type=mysql.ENUM('biometrico', 'manual'),
        type_=sa.Enum('biometrico', 'manual', 'checklist', name='metodo_asistencia'),
        existing_nullable=False,
    )
    op.create_table(
        'anulaciones_checklist',
        sa.Column('id', mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column('asistencia_id', mysql.BIGINT(unsigned=True), nullable=False, comment='asistencias.id que se borro. Sin FK: la fila ya no existe.'),
        sa.Column('usuario_id', mysql.BIGINT(unsigned=True), nullable=False, comment='users.id del comensal desmarcado, sin FK entre bases.'),
        sa.Column('fecha_comida', sa.Date(), nullable=False),
        sa.Column('comida_id', mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column('marcada_en', sa.DateTime(), nullable=False, comment='asistencias.fecha_hora de la racion anulada.'),
        sa.Column('cuenta_id', mysql.BIGINT(unsigned=True), nullable=False, comment='La cocinera que marco y anulo (la misma cuenta, por regla).'),
        sa.Column('anulada_en', sa.DateTime(), nullable=False, comment='Instante del reloj del servidor al anular.'),
        sa.ForeignKeyConstraint(['cuenta_id'], ['usuarios_sistema.id'], name=op.f('fk_anulaciones_checklist_cuenta_id'), ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_anulaciones_checklist')),
        comment=COMENTARIO_TABLA,
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_unicode_ci',
    )
    op.create_index('idx_anulaciones_checklist_fecha_comida', 'anulaciones_checklist', ['fecha_comida', 'comida_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # drop_table directo: soltar antes el índice choca con la FK en MySQL.
    op.drop_table('anulaciones_checklist')
    op.alter_column(
        'asistencias', 'metodo',
        existing_type=mysql.ENUM('biometrico', 'manual', 'checklist'),
        type_=sa.Enum('biometrico', 'manual', name='metodo_asistencia'),
        existing_nullable=False,
    )
