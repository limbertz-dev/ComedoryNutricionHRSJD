"""quien registro cada racion manual, desde el token

Revision ID: b7c4d2e8f1a3
Revises: 7e2b9c4d1a60
Create Date: 2026-09-28

`asistencias.registrado_por` guardaba un `users.id` de la base de turnos que
llegaba en el cuerpo del POST, pero el token identifica una cuenta de
`usuarios_sistema` (bd_nutricion): dos bases distintas en una sola columna.
La nueva `registrado_por_cuenta` guarda la cuenta del token, con FK interna
(RESTRICT: las cuentas se dan de baja, no se borran).

Sin backfill a propósito: los valores viejos son users.id, de otra base, y
no hay forma honesta de mapearlos a cuentas. La columna vieja queda
congelada (NULL en filas nuevas) y se retira en una oleada posterior.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "b7c4d2e8f1a3"
down_revision: Union[str, Sequence[str], None] = "7e2b9c4d1a60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COMENTARIO_CUENTA = (
    "usuarios_sistema.id de quien la registro a mano, tomado del "
    "token. FK interna: las cuentas se dan de baja, no se borran."
)

# Idéntico carácter por carácter al comment de Asistencia.registrado_por en
# app/modelos/comedor.py (mismo corte de línea para compararlo a ojo).
COMENTARIO_REGISTRADO_POR_LEGACY = (
    "LEGACY: users.id de quien la registro a mano, sin FK. Desde "
    "registrado_por_cuenta queda en NULL para las filas nuevas."
)
COMENTARIO_REGISTRADO_POR_ANTERIOR = (
    "users.id de quien la registro a mano, sin FK."
)


def upgrade() -> None:
    op.add_column(
        "asistencias",
        sa.Column(
            "registrado_por_cuenta",
            mysql.BIGINT(unsigned=True),
            nullable=True,
            comment=COMENTARIO_CUENTA,
        ),
    )
    op.create_foreign_key(
        op.f("fk_asistencias_registrado_por_cuenta"),
        "asistencias",
        "usuarios_sistema",
        ["registrado_por_cuenta"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.alter_column(
        "asistencias",
        "registrado_por",
        existing_type=mysql.BIGINT(unsigned=True),
        existing_nullable=True,
        comment=COMENTARIO_REGISTRADO_POR_LEGACY,
        existing_comment=COMENTARIO_REGISTRADO_POR_ANTERIOR,
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_asistencias_registrado_por_cuenta"),
        "asistencias",
        type_="foreignkey",
    )
    op.alter_column(
        "asistencias",
        "registrado_por",
        existing_type=mysql.BIGINT(unsigned=True),
        existing_nullable=True,
        comment=COMENTARIO_REGISTRADO_POR_ANTERIOR,
        existing_comment=COMENTARIO_REGISTRADO_POR_LEGACY,
    )
    op.drop_column("asistencias", "registrado_por_cuenta")
