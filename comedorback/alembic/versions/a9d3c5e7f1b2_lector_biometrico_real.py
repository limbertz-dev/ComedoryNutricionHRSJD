"""lector biometrico real: vinculos y solicitudes

Revision ID: a9d3c5e7f1b2
Revises: 8d4a2b7c9f10
Create Date: 2026-10-22

Dos tablas nuevas para conectar un lector biometrico real (app/api/lector.py):

  · `vinculos_lector`: el identificador con que el lector enrolo la huella
    (numero de usuario de una terminal o id de plantilla de un lector USB) ->
    users.id del padron. Baja logica con `activo`.
  · `solicitudes_lector`: cada envio del puente por su Idempotency-Key, con la
    respuesta enviada, para que un reintento no escriba otra lectura.

Solo agrega tablas: no modifica ninguna existente. Solo toca bd_nutricion.
Sobre la base de turnos no se ejecuta nada.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = 'a9d3c5e7f1b2'
down_revision: Union[str, Sequence[str], None] = '8d4a2b7c9f10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('solicitudes_lector',
    sa.Column('clave', sa.CHAR(length=36), nullable=False, comment='Idempotency-Key (UUID v4) del envio.'),
    sa.Column('dispositivo', sa.String(length=50), nullable=False, comment='Nombre del lector, fijado por su clave en LECTORES.'),
    sa.Column('identificador', sa.String(length=64), nullable=True, comment='Lo que entrego el lector. NULL = huella no reconocida.'),
    sa.Column('lectura_id', mysql.BIGINT(unsigned=True), nullable=False),
    sa.Column('respuesta', sa.JSON(), nullable=False, comment='Respuesta enviada al lector, para repetirla ante un reintento.'),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['lectura_id'], ['lecturas_biometricas.id'], name=op.f('fk_solicitudes_lector_lectura_id'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('clave', name=op.f('pk_solicitudes_lector')),
    comment='Cada envio de un lector autorizado, por su Idempotency-Key: un reintento devuelve lo guardado en vez de escribir otra lectura.',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci'
    )
    op.create_index('idx_solicitudes_lector_lectura', 'solicitudes_lector', ['lectura_id'], unique=False)
    op.create_table('vinculos_lector',
    sa.Column('id', mysql.BIGINT(unsigned=True), nullable=False),
    sa.Column('identificador', sa.String(length=64), nullable=False, comment='Numero de usuario o id de plantilla con que el lector enrolo la huella.'),
    sa.Column('usuario_id', mysql.BIGINT(unsigned=True), nullable=False, comment='users.id de la base de turnos (v_comensales), sin FK entre bases.'),
    sa.Column('activo', mysql.TINYINT(display_width=1), nullable=False),
    sa.Column('creado_por_cuenta', mysql.BIGINT(unsigned=True), nullable=True, comment='Cuenta de jefatura que creo o reasigno el vinculo.'),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['creado_por_cuenta'], ['usuarios_sistema.id'], name=op.f('fk_vinculos_lector_creado_por_cuenta'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_vinculos_lector')),
    sa.UniqueConstraint('identificador', name=op.f('uq_vinculos_lector_identificador')),
    comment='Traduce el identificador que entrega el lector a la persona del padron. Baja logica: un vinculo se desactiva, no se borra.',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci'
    )
    op.create_index('idx_vinculos_lector_usuario', 'vinculos_lector', ['usuario_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # DROP TABLE se lleva sus indices. Soltar antes idx_solicitudes_lector_lectura
    # falla: MySQL lo usa para sostener la FK hacia lecturas_biometricas.
    op.drop_table('vinculos_lector')
    op.drop_table('solicitudes_lector')
