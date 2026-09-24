"""tabla raciones_servicio_dia

Revision ID: 221c583eedf4
Revises: c3d4e5f6a7b8
Create Date: 2026-09-24

Crea la tabla `raciones_servicio_dia` para el registro del Control de Dietas
como matriz de servicios × tipos de dieta por día.

Cada fila es un hecho:
"El día fecha, el servicio/fila fila_informe tiene cantidad raciones de la
columna columna_informe_id".

Semántica:
- Solo INSERT: para corregir una celda se inserta otra fila con su `momento`;
  la celda vigente para (fecha, fila_informe, columna_informe_id) es la última
  por `momento` (y a igual momento por `id`).
- Sin UPDATE ni DELETE desde la aplicación.
- `cantidad >= 0` garantizado por CHECK constraint.
- La foreign key `columna_informe_id` referencia `columnas_informe_dieta.id` con RESTRICT.
- `registrado_por` referencia `bd_proyecto_backend.users.id` con SET NULL (misma que dietas_cama).

El downgrade elimina la tabla `raciones_servicio_dia` (DROP TABLE se lleva
sus propios índices y restricciones).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = '221c583eedf4'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'raciones_servicio_dia',
        sa.Column('id', mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False, comment='Dia al que corresponde la racion.'),
        sa.Column('fila_informe', sa.String(length=40), nullable=False, comment="Codigo de fila de FILAS_DISTRIBUCION (ej: 'pediatria_gral')."),
        sa.Column('columna_informe_id', mysql.BIGINT(unsigned=True), nullable=False, comment='Columna del informe mensual a la que suma.'),
        sa.Column('cantidad', sa.Integer(), nullable=False, comment='Numero de raciones servidas (>= 0).'),
        sa.Column('momento', sa.DateTime(), nullable=False, comment='Hora del hecho. Ordena los cambios: la ultima por celda manda.'),
        sa.Column('registrado_por', mysql.BIGINT(unsigned=True), nullable=True, comment='Usuario que registro o modifico la celda.'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('`cantidad` >= 0', name=op.f('ck_raciones_servicio_dia_cantidad')),
        sa.ForeignKeyConstraint(['columna_informe_id'], ['columnas_informe_dieta.id'], name=op.f('fk_raciones_servicio_dia_columna_informe_id'), ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['registrado_por'], ['bd_proyecto_backend.users.id'], name=op.f('fk_raciones_servicio_dia_registrado_por'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_raciones_servicio_dia')),
        comment='Una fila = un hecho: el dia F, el servicio S tiene N raciones de la columna C. Celda vigente = ultima por momento.',
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_unicode_ci'
    )
    op.create_index(
        'ix_raciones_servicio_dia_ultima',
        'raciones_servicio_dia',
        ['fecha', 'fila_informe', 'columna_informe_id', 'momento'],
        unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('raciones_servicio_dia')
