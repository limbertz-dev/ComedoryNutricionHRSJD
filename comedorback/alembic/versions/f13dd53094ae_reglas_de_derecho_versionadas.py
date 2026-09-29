"""reglas de derecho versionadas y motivo en horarios

Revision ID: f13dd53094ae
Revises: 2555bc00750e
Create Date: 2026-09-29

R2: los horarios de comida y los parámetros del derecho se vuelven
configurables por root, con vigencia por fecha y nunca hacia atrás.

  · reglas_derecho + reglas_derecho_novedad   versiones de turno mínimo,
    novedades que anulan y exclusión de enfermería. Cada cambio es una
    fila nueva; solo se borra una programada.
  · horarios_comida suma motivo y creada_por_cuenta (NULL en filas
    viejas) e índice (comida_id, vigente_desde).
  · Inserta la versión BASE con los valores vigentes antes de R2
    (12 h, cuatro novedades, enfermería excluida) desde 2000-01-01,
    para que el comportamiento tras el upgrade sea idéntico.

Solo toca bd_nutricion. Sobre bd_proyecto_backend no se ejecuta nada.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "f13dd53094ae"
down_revision: Union[str, Sequence[str], None] = "2555bc00750e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Idénticos carácter por carácter a los comment de ReglaDerecho,
# ReglaDerechoNovedad y HorarioComida (mismo corte de línea).
COMENTARIO_TABLA_REGLA = (
    "Versiones de los parámetros del derecho a comer. Cada cambio es una "
    "fila nueva vigente desde una fecha; nunca se edita ni se borra el pasado."
)
COMENTARIO_VIGENTE_DESDE = (
    "Desde qué fecha rige esta versión, inclusive. Nunca hacia atrás: "
    "tiene que ser hoy o futuro al crearla."
)
COMENTARIO_DURACION = "Turno mínimo en horas para tener derecho. Política del hospital."
COMENTARIO_EXCLUIR = "1 = enfermería queda fuera del derecho y del padrón; 0 = incluida."
COMENTARIO_MOTIVO_REGLA = "Por qué se creó esta versión. Obligatorio, 10 o más caracteres."
COMENTARIO_CREADA_REGLA = (
    "usuarios_sistema.id de la cuenta root que la creó. FK interna: "
    "las cuentas se dan de baja, no se borran. NULL solo en la versión base."
)
COMENTARIO_TABLA_NOVEDAD = (
    "Novedades que anulan el derecho, por versión de reglas_derecho. "
    "Una fila por (versión, tipo)."
)
COMENTARIO_REGLA_ID = (
    "reglas_derecho.id a la que pertenece. Si se borra una versión "
    "programada, se borran sus novedades."
)
COMENTARIO_TIPO = (
    "Tipo de novedad laboral que anula el derecho en esta versión "
    "(v_novedades_laborales.tipo_novedad)."
)
COMENTARIO_MOTIVO_HORARIO = (
    "Por qué se creó esta versión del horario. NULL en las filas "
    "anteriores a R2, que no lo tenían."
)
COMENTARIO_CREADA_HORARIO = (
    "usuarios_sistema.id de la cuenta root que creó esta versión del "
    "horario. FK interna: las cuentas se dan de baja, no se borran."
)

BASE_DESDE = "2000-01-01"
BASE_MOTIVO = "Versión base anterior a R2: 12 h, cuatro novedades y enfermería excluida."
BASE_NOVEDADES = ("permiso", "baja_medica", "vacacion", "licencia")


def upgrade() -> None:
    op.create_table(
        "reglas_derecho",
        sa.Column("id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "vigente_desde", sa.Date(), nullable=False, comment=COMENTARIO_VIGENTE_DESDE
        ),
        sa.Column(
            "duracion_minima_horas",
            sa.Integer(),
            nullable=False,
            comment=COMENTARIO_DURACION,
        ),
        sa.Column(
            "excluir_enfermeria",
            mysql.TINYINT(display_width=1),
            nullable=False,
            comment=COMENTARIO_EXCLUIR,
        ),
        sa.Column(
            "motivo", sa.String(length=500), nullable=False, comment=COMENTARIO_MOTIVO_REGLA
        ),
        sa.Column(
            "creada_por_cuenta",
            mysql.BIGINT(unsigned=True),
            nullable=True,
            comment=COMENTARIO_CREADA_REGLA,
        ),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["creada_por_cuenta"],
            ["usuarios_sistema.id"],
            name=op.f("fk_reglas_derecho_creada_por_cuenta"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reglas_derecho")),
        sa.UniqueConstraint(
            "vigente_desde", name="uq_reglas_derecho_vigente_desde"
        ),
        comment=COMENTARIO_TABLA_REGLA,
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_table(
        "reglas_derecho_novedad",
        sa.Column("id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "regla_id",
            mysql.BIGINT(unsigned=True),
            nullable=False,
            comment=COMENTARIO_REGLA_ID,
        ),
        sa.Column(
            "tipo_novedad",
            sa.String(length=30),
            nullable=False,
            comment=COMENTARIO_TIPO,
        ),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["regla_id"],
            ["reglas_derecho.id"],
            name=op.f("fk_reglas_derecho_novedad_regla_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reglas_derecho_novedad")),
        sa.UniqueConstraint(
            "regla_id",
            "tipo_novedad",
            name="uq_reglas_derecho_novedad_regla_id_tipo_novedad",
        ),
        comment=COMENTARIO_TABLA_NOVEDAD,
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.add_column(
        "horarios_comida",
        sa.Column(
            "motivo",
            sa.String(length=500),
            nullable=True,
            comment=COMENTARIO_MOTIVO_HORARIO,
        ),
    )
    op.add_column(
        "horarios_comida",
        sa.Column(
            "creada_por_cuenta",
            mysql.BIGINT(unsigned=True),
            nullable=True,
            comment=COMENTARIO_CREADA_HORARIO,
        ),
    )
    op.create_foreign_key(
        op.f("fk_horarios_comida_creada_por_cuenta"),
        "horarios_comida",
        "usuarios_sistema",
        ["creada_por_cuenta"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_horarios_comida_comida_id_vigente_desde",
        "horarios_comida",
        ["comida_id", "vigente_desde"],
        unique=False,
    )
    conexion = op.get_bind()
    resultado = conexion.execute(
        sa.text(
            "INSERT INTO reglas_derecho "
            "(vigente_desde, duracion_minima_horas, excluir_enfermeria, "
            "motivo, creada_por_cuenta) "
            "VALUES (:desde, :duracion, :excluir, :motivo, NULL)"
        ),
        {"desde": BASE_DESDE, "duracion": 12, "excluir": 1, "motivo": BASE_MOTIVO},
    )
    regla_id = resultado.lastrowid
    for tipo in BASE_NOVEDADES:
        conexion.execute(
            sa.text(
                "INSERT INTO reglas_derecho_novedad (regla_id, tipo_novedad) "
                "VALUES (:regla_id, :tipo)"
            ),
            {"regla_id": regla_id, "tipo": tipo},
        )


def downgrade() -> None:
    op.drop_index(
        "ix_horarios_comida_comida_id_vigente_desde", table_name="horarios_comida"
    )
    op.drop_constraint(
        op.f("fk_horarios_comida_creada_por_cuenta"),
        "horarios_comida",
        type_="foreignkey",
    )
    op.drop_column("horarios_comida", "creada_por_cuenta")
    op.drop_column("horarios_comida", "motivo")
    op.drop_table("reglas_derecho_novedad")
    op.drop_table("reglas_derecho")
