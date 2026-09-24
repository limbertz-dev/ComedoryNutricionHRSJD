"""Retirar la tabla de sinonimos de dietas.

Revision ID: d977e591ac49
Revises: a1b2c3d4e5f6
Create Date: 2026-09-23

Decidido por el dueno: la captura de dieta usa solo los nombres oficiales de
`tipos_dieta`, sin sinonimos. La tabla se borra con sus filas.

El downgrade la recrea VACIA, con la misma forma que le dio `a1b2c3d4e5f6`:
sus filas no se recuperan desde aca.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "d977e591ac49"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # El DROP TABLE se lleva su FK y sus indices: no hay nada que borrar antes.
    op.drop_table("dieta_alias")


def downgrade() -> None:
    op.create_table(
        "dieta_alias",
        sa.Column("id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("tipo_dieta_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "texto",
            sa.String(length=60),
            nullable=False,
            comment="Tal cual lo escriben en la hojita. Sin acentos ni mayusculas que distingan.",
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tipo_dieta_id"],
            ["tipos_dieta.id"],
            name=op.f("fk_dieta_alias_tipo_dieta_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dieta_alias")),
        sa.UniqueConstraint("texto", name=op.f("uq_dieta_alias_texto")),
        comment="Sinonimos de cada dieta, tal como los escribe enfermeria.",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        op.f("ix_dieta_alias_tipo_dieta_id"), "dieta_alias", ["tipo_dieta_id"], unique=False
    )
