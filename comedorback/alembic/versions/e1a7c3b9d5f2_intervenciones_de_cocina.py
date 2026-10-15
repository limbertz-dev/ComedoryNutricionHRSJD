"""intervenciones de cocina: auditoria de la identificacion manual y una racion por lectura

Revision ID: e1a7c3b9d5f2
Revises: ca83b39b791c
Create Date: 2026-10-14

La cocinera puede identificar a mano una lectura `no_identificado` y confirmar
la entrega. Para que eso deje rastro y no pueda dar dos raciones:

  · tabla nueva `intervenciones_lectura`: un intento por fila (registrado o
    rechazado), solo inserciones. Guarda la clave de idempotencia del intento
    y una copia de lo necesario para responder un reintento sin tocar la
    lectura, el padron ni los horarios. La lectura original no se modifica.
  · UNIQUE(asistencias.lectura_id): una lectura da, como mucho, una racion.
    Varias filas con lectura_id NULL (registros manuales) siguen valiendo.

ANTES DEL PRIMER DDL (solo SELECT) se comprueba, y la migracion se detiene sin
modificar nada si:

  1. `asistencias` ya tiene algun `lectura_id` repetido: el UNIQUE no se puede
     crear. Se listan los ofensores. Se resuelve a mano, mirando cada caso,
     ANTES de volver a correr. La migracion no borra ni reescribe raciones.
  2. quedo un estado parcial de un intento anterior (la tabla nueva o el
     UNIQUE ya existen).

DDL EN MYSQL. Cada sentencia DDL se confirma sola: si algo falla DESPUES de los
prechecks, la base puede quedar parcialmente migrada y alembic no la revierte.
El intento siguiente detecta el estado parcial y se detiene con un mensaje.
Hacer respaldo antes de migrar una base real y detener la API durante la
migracion.

DOWNGRADE. Se niega a perder auditoria: si `intervenciones_lectura` tiene
filas, se detiene sin modificar nada. Vacia, deshace los pasos de forma
idempotente (cada uno solo si hace falta), asi que un downgrade interrumpido
se puede reintentar. El UNIQUE de lectura_id es el unico indice que sostiene la
FK hacia lecturas_biometricas, y MySQL no deja soltarlo sin otro: por eso se
crea antes un indice comun.

Los prechecks necesitan una conexion viva: esta revision no admite `--sql`
(modo offline).

Solo toca bd_nutricion. Sobre bd_proyecto_backend no se ejecuta nada.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "e1a7c3b9d5f2"
down_revision: Union[str, Sequence[str], None] = "ca83b39b791c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "intervenciones_lectura"
UQ_LECTURA = "uq_asistencias_lectura_id"
IX_LECTURA = "ix_asistencias_lectura_id"

# Identicos caracter por caracter a los de app/modelos/comedor.py.
COMENTARIO_TABLA = (
    "Auditoria de la identificacion manual de una lectura no reconocida. "
    "Solo inserciones: cada fila es un intento de la cocinera, registrado o "
    "rechazado. La lectura original no se modifica."
)
COMENTARIO_CLAVE = (
    "Idempotency-Key del intento, por cuenta. Con la misma huella devuelve "
    "lo guardado en vez de repetir."
)
COMENTARIO_HUELLA = (
    "SHA-256 de {lectura_id, usuario_id}. La misma clave con otra huella es "
    "un conflicto."
)
COMENTARIO_SERVICIO = (
    "Servicio que el sistema uso. Se RECONSTRUYE por horario a partir de "
    "lecturas_biometricas.fecha_hora, que no guarda comida ni fecha_comida: "
    "no es un dato historico de la lectura."
)
COMENTARIO_COPIAS = (
    "Copia del momento del intento, para responder un reintento sin depender "
    "del padron ni de los horarios."
)

MOTIVOS_RECHAZO = (
    "sin_derecho",
    "duplicado",
    "lectura_ya_resuelta",
    "lectura_no_resoluble",
    "servicio_distinto",
    "servicio_no_determinable",
    "reloj_inconsistente",
)
CAUSA = "identificacion_manual_por_no_identificado"


def _detener(titulo: str, detalle: str) -> None:
    raise RuntimeError(
        f"Migración e1a7c3b9d5f2 detenida ANTES de modificar nada: {titulo}\n"
        f"{detalle}"
    )


def _verificar_upgrade(conexion) -> None:
    inspector = sa.inspect(conexion)

    parcial = []
    if inspector.has_table(TABLA):
        parcial.append(f"la tabla {TABLA} ya existe")
    if any(u["name"] == UQ_LECTURA for u in inspector.get_unique_constraints("asistencias")):
        parcial.append(f"el UNIQUE {UQ_LECTURA} ya existe")
    if parcial:
        _detener(
            "estado parcial de un intento anterior.",
            "      · " + "\n      · ".join(parcial) + "\n"
            "    Revise a mano que objetos de esta revision existen y complete o\n"
            "    deshaga lo que falte; esta migracion no repite pasos por su cuenta.",
        )

    repetidas = conexion.execute(
        sa.text(
            "SELECT lectura_id, COUNT(*) FROM asistencias "
            "WHERE lectura_id IS NOT NULL "
            "GROUP BY lectura_id HAVING COUNT(*) > 1 "
            "ORDER BY lectura_id LIMIT 20"
        )
    ).all()
    if repetidas:
        lista = "\n".join(
            f"      · lectura_id {lectura}: {cuantas} asistencias" for lectura, cuantas in repetidas
        )
        _detener(
            "hay lecturas con mas de una asistencia, y el UNIQUE no se puede crear.",
            f"{lista}\n"
            "    Revise cada caso a mano (esta migracion no borra ni reescribe\n"
            "    raciones) y vuelva a correr.",
        )


def upgrade() -> None:
    conexion = op.get_bind()
    _verificar_upgrade(conexion)

    op.create_table(
        TABLA,
        sa.Column("id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column(
            "lectura_id",
            mysql.BIGINT(unsigned=True),
            nullable=False,
            comment="La lectura intervenida. RESTRICT: la auditoria no se queda sin ella.",
        ),
        sa.Column(
            "usuario_id",
            mysql.BIGINT(unsigned=True),
            nullable=False,
            comment="users.id de la persona propuesta por la cocinera, sin FK entre bases.",
        ),
        sa.Column(
            "cuenta_id",
            mysql.BIGINT(unsigned=True),
            nullable=False,
            comment=(
                "usuarios_sistema.id de la cocinera, tomado del token. FK interna: "
                "las cuentas se dan de baja, no se borran."
            ),
        ),
        sa.Column("clave_idempotencia", sa.CHAR(length=36), nullable=False, comment=COMENTARIO_CLAVE),
        sa.Column("huella_solicitud", sa.CHAR(length=64), nullable=False, comment=COMENTARIO_HUELLA),
        sa.Column(
            "resultado",
            sa.Enum("registrada", "rechazada", name="resultado_intervencion"),
            nullable=False,
            comment="registrada = hubo entrega y racion. rechazada = no la hubo.",
        ),
        sa.Column(
            "motivo_rechazo",
            sa.Enum(*MOTIVOS_RECHAZO, name="motivo_rechazo_intervencion"),
            nullable=True,
        ),
        sa.Column(
            "causa",
            sa.Enum(CAUSA, name="causa_intervencion"),
            nullable=False,
            comment="La fija el servidor. La usuaria no escribe motivo ni nota.",
        ),
        sa.Column(
            "comida_id", mysql.BIGINT(unsigned=True), nullable=True, comment=COMENTARIO_SERVICIO
        ),
        sa.Column("fecha_comida", sa.Date(), nullable=True),
        sa.Column("ventana_inicio", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("ventana_fin", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column(
            "origen_servicio",
            sa.Enum("reconstruido_por_horario", name="origen_servicio"),
            nullable=True,
        ),
        sa.Column("nombre_comensal", sa.String(length=100), nullable=True, comment=COMENTARIO_COPIAS),
        sa.Column("nombre_comida", sa.String(length=80), nullable=True),
        sa.Column("servicio_id", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column(
            "asistencia_id",
            mysql.BIGINT(unsigned=True),
            nullable=True,
            comment="La racion de una intervencion registrada. NULL en las rechazadas.",
        ),
        sa.Column(
            "momento",
            mysql.DATETIME(fsp=6),
            nullable=False,
            comment="Instante del reloj del servidor en que se resolvio el intento.",
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(resultado = 'registrada' AND motivo_rechazo IS NULL) OR "
            "(resultado = 'rechazada' AND motivo_rechazo IS NOT NULL)",
            name=op.f("ck_intervenciones_lectura_motivo_coherente"),
        ),
        sa.ForeignKeyConstraint(
            ["asistencia_id"],
            ["asistencias.id"],
            name=op.f("fk_intervenciones_lectura_asistencia_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["cuenta_id"],
            ["usuarios_sistema.id"],
            name=op.f("fk_intervenciones_lectura_cuenta_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lectura_id"],
            ["lecturas_biometricas.id"],
            name=op.f("fk_intervenciones_lectura_lectura_id"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_intervenciones_lectura")),
        sa.UniqueConstraint("asistencia_id", name="uq_intervenciones_lectura_asistencia_id"),
        sa.UniqueConstraint(
            "cuenta_id", "clave_idempotencia", name="uq_intervenciones_lectura_cuenta_clave"
        ),
        comment=COMENTARIO_TABLA,
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("idx_intervenciones_momento", TABLA, ["momento"], unique=False)
    op.create_index("idx_intervenciones_lectura", TABLA, ["lectura_id"], unique=False)
    op.create_index(
        "idx_intervenciones_cuenta_momento", TABLA, ["cuenta_id", "momento"], unique=False
    )

    op.create_unique_constraint(UQ_LECTURA, "asistencias", ["lectura_id"])
    # Un downgrade anterior pudo dejar un indice comun sobre la misma columna.
    # Con el UNIQUE sobra, y `alembic check` lo veria como diferencia.
    indices = sa.inspect(op.get_bind()).get_indexes("asistencias")
    if any(i["name"] == IX_LECTURA for i in indices):
        op.drop_index(IX_LECTURA, table_name="asistencias")


def downgrade() -> None:
    conexion = op.get_bind()
    inspector = sa.inspect(conexion)

    if inspector.has_table(TABLA):
        filas = conexion.execute(sa.text(f"SELECT COUNT(*) FROM {TABLA}")).scalar_one()
        if filas:
            raise RuntimeError(
                "Reversión de e1a7c3b9d5f2 detenida ANTES de modificar nada: "
                f"{TABLA} tiene {filas} filas de auditoría y bajar las perdería.\n"
                "    Respalde esa tabla y vaciela a mano si de verdad quiere bajar."
            )

    # Cada paso solo si hace falta: un downgrade interrumpido se puede repetir.
    indices = inspector.get_indexes("asistencias")
    if not any(i["name"] == IX_LECTURA for i in indices):
        op.create_index(IX_LECTURA, "asistencias", ["lectura_id"], unique=False)
    if any(u["name"] == UQ_LECTURA for u in inspector.get_unique_constraints("asistencias")):
        op.drop_constraint(UQ_LECTURA, "asistencias", type_="unique")
    if inspector.has_table(TABLA):
        op.drop_table(TABLA)
