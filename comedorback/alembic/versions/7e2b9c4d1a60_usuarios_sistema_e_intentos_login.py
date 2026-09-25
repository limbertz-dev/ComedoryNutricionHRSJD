"""cuentas propias del sistema e intentos de ingreso

Revision ID: 7e2b9c4d1a60
Revises: 0c294cd98c3a
Create Date: 2026-09-24

Dos tablas propias de `bd_nutricion` para la autenticación:

  · usuarios_sistema  las cuentas del comedor (jefa, cocinera, sistemas), con
                      la clave solo como hash bcrypt. NO son los `users` de la
                      base de turnos, y no hay FK hacia allá.
  · intentos_login    bitácora de cada intento. El bloqueo por intentos
                      fallidos se deriva de acá; no es un estado guardado.

Ninguna sentencia toca la base de turnos ni las vistas v_*. La cuenta
inicial NO se crea acá (una clave en una migración queda en el historial de
git): se crea con `python -m app.semillas.admin`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "7e2b9c4d1a60"
down_revision: Union[str, Sequence[str], None] = "0c294cd98c3a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ID = mysql.BIGINT(unsigned=True)
OPCIONES = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}


def upgrade() -> None:
    op.create_table(
        "usuarios_sistema",
        sa.Column("id", ID, nullable=False),
        sa.Column(
            "username",
            sa.String(length=50),
            nullable=False,
            comment="Siempre en minusculas y sin espacios en los extremos.",
        ),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "rol",
            sa.Enum("jefa", "cocinera", "sistemas", name="rol_sistema"),
            nullable=False,
        ),
        sa.Column(
            "debe_cambiar",
            mysql.TINYINT(display_width=1),
            nullable=False,
            comment="1 = clave temporal: el ingreso solo habilita el cambio de clave.",
        ),
        sa.Column("activo", mysql.TINYINT(display_width=1), nullable=False),
        sa.Column(
            "version_token",
            sa.Integer(),
            nullable=False,
            comment=(
                "Va dentro de cada token. Cambiar la clave la incrementa y "
                "anula todas las sesiones abiertas."
            ),
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usuarios_sistema")),
        sa.UniqueConstraint("username", name=op.f("uq_usuarios_sistema_username")),
        comment=(
            "Cuentas propias del comedor. NO son los users de la base de turnos. "
            "La clave se guarda solo como hash bcrypt."
        ),
        **OPCIONES,
    )
    op.create_table(
        "intentos_login",
        sa.Column("id", ID, nullable=False),
        sa.Column(
            "username",
            sa.String(length=50),
            nullable=False,
            comment="Lo que se tipeo, normalizado. Puede no existir.",
        ),
        sa.Column(
            "resultado",
            sa.Enum("exitoso", "fallido", "bloqueado", name="resultado_login"),
            nullable=False,
            comment="bloqueado = llego con la cuenta bloqueada; no se verifico la clave.",
        ),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("fecha_hora", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_intentos_login")),
        comment=(
            "Bitacora de ingresos. El bloqueo por intentos fallidos se deriva de "
            "aqui; se registra tambien el username que no existe."
        ),
        **OPCIONES,
    )
    op.create_index(
        "idx_intentos_login_username_fecha",
        "intentos_login",
        ["username", "fecha_hora"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_intentos_login_username_fecha", table_name="intentos_login")
    op.drop_table("intentos_login")
    op.drop_table("usuarios_sistema")
