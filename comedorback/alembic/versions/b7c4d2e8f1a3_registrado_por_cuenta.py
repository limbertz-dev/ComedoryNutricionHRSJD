"""quien registro cada racion manual, desde el token

Revision ID: b7c4d2e8f1a60
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

revision: str = "b7c4d2e8f1a60"
down_revision: Union[str, Sequence[str], None] = "7e2b9c4d1a60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COMENTARIO_CUENTA = (
    "usuarios_sistema.id de quien la registro a mano, tomado del "
    "token. FK interna: las cuentas se dan de baja, no se borran."
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


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_asistencias_registrado_por_cuenta"),
        "asistencias",
        type_="foreignkey",
    )
    op.drop_column("asistencias", "registrado_por_cuenta")
