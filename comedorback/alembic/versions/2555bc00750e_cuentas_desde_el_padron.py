"""cuentas vinculadas al padron y login en v_comensales

Revision ID: 2555bc00750e
Revises: b7c4d2e8f1a3
Create Date: 2026-09-29

Tres columnas nuevas en `usuarios_sistema`, para que root administre las
cuentas desde la API en vez de la consola:

  · usuario_turnos_id   users.id del padron al que esta vinculada la
                        cuenta. Referencia LOGICA, sin FK (como las
                        demas): una FK entre bases le impediria al otro
                        ingeniero borrar un usuario. UNIQUE: una persona,
                        una cuenta. NULL = cuenta sin vinculo.
  · nombre              nombre a mano, solo para las cuentas sin vinculo.
  · creada_por_cuenta   que cuenta root la creo. FK INTERNA a
                        usuarios_sistema.id (RESTRICT: las cuentas se dan
                        de baja, no se borran).

Ademas, `v_comensales` suma la columna `login` (= users.name), que es lo
que root ve en el buscador de candidatos y lo que se copia como username
al crear una cuenta vinculada. Ninguna columna sensible: ni password, ni
email, ni remember_token, ni email_verified_at. El resto de la vista
queda igual y el conteo sigue en 9 vistas.

Sobre la base de turnos no se ejecuta nada: solo se la nombra en el
SELECT de la vista, como en 0c294cd98c3a.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

from app.core.config import config

revision: str = "2555bc00750e"
down_revision: Union[str, Sequence[str], None] = "b7c4d2e8f1a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Idénticos carácter por carácter a los comment de UsuarioSistema en
# app/modelos/usuarios.py (mismo corte de línea para compararlos a ojo).
COMENTARIO_USUARIO_TURNOS_ID = (
    "users.id del padron al que esta vinculada la cuenta, sin FK. "
    "NULL = cuenta sin vinculo, creada a mano."
)
COMENTARIO_NOMBRE = "Nombre a mano, solo para las cuentas sin vinculo."
COMENTARIO_CREADA_POR = (
    "usuarios_sistema.id de la cuenta root que la creo. FK interna: "
    "las cuentas se dan de baja, no se borran."
)

# La definición anterior EXACTA de 0c294cd98c3a: el downgrade la restaura
# tal cual, sin la columna login.
VISTA_ANTERIOR = """
SELECT
    u.`id`                                                AS `usuario_id`,
    REGEXP_REPLACE(TRIM(p.`nombre_completo`), '[[:space:]]+', ' ')
                                                          AS `nombre_completo`,
    p.`carnet_identidad`                                  AS `carnet_identidad`,
    p.`tipo_trabajador`                                   AS `tipo_trabajador`,
    p.`numero_tipo_salario`                               AS `numero_item`,
    u.`categoria_id`                                      AS `categoria_id`,
    c.`nombre`                                            AS `categoria`,
    c.`nivel`                                             AS `categoria_nivel`,
    (p.`id` IS NOT NULL)                                  AS `tiene_ficha`
FROM {t}.`users` u
LEFT JOIN (
    SELECT `user_id`, MIN(`id`) AS `persona_id`
    FROM {t}.`personas`
    GROUP BY `user_id`
) fp ON fp.`user_id` = u.`id`
LEFT JOIN {t}.`personas`   p ON p.`id` = fp.`persona_id`
LEFT JOIN {t}.`categorias` c ON c.`id` = u.`categoria_id`
"""

# Igual que la anterior, mas `login` = users.name. Es un login de acceso,
# nunca un secreto: password, email, remember_token y email_verified_at
# siguen sin exponerse.
VISTA_NUEVA = """
SELECT
    u.`id`                                                AS `usuario_id`,
    u.`name`                                              AS `login`,
    REGEXP_REPLACE(TRIM(p.`nombre_completo`), '[[:space:]]+', ' ')
                                                          AS `nombre_completo`,
    p.`carnet_identidad`                                  AS `carnet_identidad`,
    p.`tipo_trabajador`                                   AS `tipo_trabajador`,
    p.`numero_tipo_salario`                               AS `numero_item`,
    u.`categoria_id`                                      AS `categoria_id`,
    c.`nombre`                                            AS `categoria`,
    c.`nivel`                                             AS `categoria_nivel`,
    (p.`id` IS NOT NULL)                                  AS `tiene_ficha`
FROM {t}.`users` u
LEFT JOIN (
    SELECT `user_id`, MIN(`id`) AS `persona_id`
    FROM {t}.`personas`
    GROUP BY `user_id`
) fp ON fp.`user_id` = u.`id`
LEFT JOIN {t}.`personas`   p ON p.`id` = fp.`persona_id`
LEFT JOIN {t}.`categorias` c ON c.`id` = u.`categoria_id`
"""


def _base_turnos() -> str:
    nombre = config.db_name_turnos
    if not nombre or "`" in nombre:
        raise ValueError(f"DB_NAME_TURNOS inválido: {nombre!r}")
    return f"`{nombre}`"


def _crear_vista(cuerpo: str) -> None:
    sql = (
        "CREATE OR REPLACE SQL SECURITY INVOKER VIEW `v_comensales` AS "
        + cuerpo.format(t=_base_turnos())
    )
    # text() leería `[[:space:]]` como un parámetro `:spac...`. La vista no
    # lleva parámetros, así que todo ':' se escapa como literal.
    op.execute(sa.text(sql.replace(":", r"\:")))


def upgrade() -> None:
    op.add_column(
        "usuarios_sistema",
        sa.Column(
            "usuario_turnos_id",
            mysql.BIGINT(unsigned=True),
            nullable=True,
            comment=COMENTARIO_USUARIO_TURNOS_ID,
        ),
    )
    op.create_unique_constraint(
        op.f("uq_usuarios_sistema_usuario_turnos_id"),
        "usuarios_sistema",
        ["usuario_turnos_id"],
    )
    op.add_column(
        "usuarios_sistema",
        sa.Column(
            "nombre",
            sa.String(length=100),
            nullable=True,
            comment=COMENTARIO_NOMBRE,
        ),
    )
    op.add_column(
        "usuarios_sistema",
        sa.Column(
            "creada_por_cuenta",
            mysql.BIGINT(unsigned=True),
            nullable=True,
            comment=COMENTARIO_CREADA_POR,
        ),
    )
    op.create_foreign_key(
        op.f("fk_usuarios_sistema_creada_por_cuenta"),
        "usuarios_sistema",
        "usuarios_sistema",
        ["creada_por_cuenta"],
        ["id"],
        ondelete="RESTRICT",
    )
    _crear_vista(VISTA_NUEVA)


def downgrade() -> None:
    _crear_vista(VISTA_ANTERIOR)
    op.drop_constraint(
        op.f("fk_usuarios_sistema_creada_por_cuenta"),
        "usuarios_sistema",
        type_="foreignkey",
    )
    op.drop_column("usuarios_sistema", "creada_por_cuenta")
    op.drop_column("usuarios_sistema", "nombre")
    op.drop_constraint(
        op.f("uq_usuarios_sistema_usuario_turnos_id"),
        "usuarios_sistema",
        type_="unique",
    )
    op.drop_column("usuarios_sistema", "usuario_turnos_id")
