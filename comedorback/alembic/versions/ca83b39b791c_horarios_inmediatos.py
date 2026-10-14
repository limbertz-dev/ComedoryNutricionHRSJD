"""horarios inmediatos: instantes con microsegundos y cerrojo de escritura

Revision ID: ca83b39b791c
Revises: f13dd53094ae
Create Date: 2026-10-14

Los horarios de comida dejan de programarse por fecha: se guardan con efecto
inmediato, en el instante del servidor, y puede haber varios cambios el mismo
día. Para eso:

  · horarios_comida.vigente_desde / vigente_hasta pasan de DATE a DATETIME(6).
    Las filas existentes quedan a las 00:00:00.000000 de su fecha, que es lo
    que significaban. `vigente_hasta` pasa de INCLUSIVO (último día) a
    EXCLUSIVO (primer instante fuera): se le suma un día.
  · lecturas_biometricas.fecha_hora pasa de DATETIME a DATETIME(6): la lectura
    se compara contra el instante del cambio y no puede perder microsegundos.
    No se inventa precisión: lo ya guardado queda con .000000.
  · tabla nueva `cerrojos` con la fila 'horarios_comida': el mutex persistente
    que serializa los guardados, también con `horarios_comida` vacía.
  · se ajusta el comentario de horarios_comida.motivo: ya no se pide.

El derecho no se toca: ni DDL ni UPDATE sobre reglas_derecho.

ANTES DEL PRIMER DDL (solo SELECT) se comprueba, y la migración se detiene sin
modificar nada si:

  1. hay versiones FUTURAS de horario activas (vigente_desde > hoy),
  2. hay versiones FUTURAS de reglas_derecho,
  3. alguna comida tiene más de una versión de horario abierta,
  4. quedó un estado parcial de un intento anterior (ver abajo).

La migración NO cancela, desactiva, reabre ni reescribe programaciones. Cada
caso se resuelve a mano, con la API vigente, ANTES de desplegar el código nuevo
(que ya no permite gestionar versiones futuras): borrar la programación, o
esperar a que entre en vigor, y volver a correr.

DDL EN MYSQL. Cada sentencia DDL se confirma sola: si algo falla DESPUÉS de los
prechecks, la base puede quedar parcialmente migrada y alembic no la revierte
ni sella la revisión. No hay rollback automático. El intento siguiente
detecta el estado parcial (cerrojos creada, o columnas ya DATETIME) y se
detiene con un mensaje en vez de repetir pasos, en particular el +1 día de
`vigente_hasta`, que aplicado dos veces corrompe los cierres. Hacer respaldo
antes de migrar una base real y detener la API durante la migración.

DOWNGRADE. Solo si no pierde nada y solo desde el estado exacto de esta
revisión. Antes de modificar nada comprueba, y se detiene con instrucciones de
recuperación (sin reintentar ni adivinar) si:

  1. la base no está en el estado de la revisión: falta la tabla cerrojos o
     alguna de las tres columnas no es DATETIME(6). Es lo que deja un downgrade
     interrumpido, y un reintento restaría OTRO día a `vigente_hasta`;
  2. alguna `vigente_desde` o `vigente_hasta` tiene hora distinta de 00:00:00
     (el primer cambio intradía lo bloquea);
  3. alguna `lecturas_biometricas.fecha_hora` tiene microsegundos.

Con todo a medianoche exacta y sin microsegundos la reversión es exacta: DATE
otra vez y `vigente_hasta` menos un día, que es el último paso.

Los prechecks necesitan una conexión viva: esta revisión no admite `--sql`
(modo offline).

Solo toca bd_nutricion. Sobre bd_proyecto_backend no se ejecuta nada.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "ca83b39b791c"
down_revision: Union[str, Sequence[str], None] = "f13dd53094ae"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Idénticos carácter por carácter a los de app/modelos/comedor.py.
COMENTARIO_VIGENTE_DESDE = (
    "Primer instante en que rige esta versión, inclusive. Con microsegundos: "
    "puede haber varios cambios el mismo día."
)
COMENTARIO_VIGENTE_HASTA = (
    "Instante en que deja de regir, EXCLUSIVO. NULL = versión abierta: la que "
    "rige desde su vigente_desde en adelante."
)
COMENTARIO_MOTIVO_NUEVO = (
    "Solo las filas de R2 lo traen. Desde que los horarios rigen al guardar, "
    "el sistema no pide motivo y queda NULL."
)
# El de f13dd53094ae, para el downgrade.
COMENTARIO_MOTIVO_ANTERIOR = (
    "Por qué se creó esta versión del horario. NULL en las filas "
    "anteriores a R2, que no lo tenían."
)
COMENTARIO_TABLA_CERROJOS = (
    "Cerrojos de escritura. Quien bloquea la fila de un recurso con SELECT ... "
    "FOR UPDATE serializa a todos los que escriban ese recurso, incluso con "
    "sus tablas de datos vacias."
)
COMENTARIO_CERROJO_NOMBRE = (
    "Recurso que protege. Lo siembra la migracion: la aplicacion no crea ni "
    "borra filas, solo las bloquea dentro de su transaccion."
)

CERROJO_HORARIOS = "horarios_comida"


def _literal(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("'", "''")


def _lista(filas, formato) -> str:
    return "\n".join(f"      · {formato(f)}" for f in filas)


def _detener(titulo: str, detalle: str) -> None:
    raise RuntimeError(
        f"Migración ca83b39b791c detenida ANTES de modificar nada: {titulo}\n"
        f"{detalle}"
    )


def _verificar_upgrade(conexion) -> None:
    inspector = sa.inspect(conexion)

    parcial = []
    if inspector.has_table("cerrojos"):
        parcial.append("la tabla cerrojos ya existe")
    columnas = {c["name"]: c["type"] for c in inspector.get_columns("horarios_comida")}
    for nombre in ("vigente_desde", "vigente_hasta"):
        if isinstance(columnas[nombre], sa.DateTime):
            parcial.append(f"horarios_comida.{nombre} ya es DATETIME")
    lecturas = {c["name"]: c["type"] for c in inspector.get_columns("lecturas_biometricas")}
    if getattr(lecturas["fecha_hora"], "fsp", None) == 6:
        parcial.append("lecturas_biometricas.fecha_hora ya es DATETIME(6)")
    if parcial:
        _detener(
            "estado parcial de un intento anterior.",
            "    " + "; ".join(parcial) + ".\n"
            "    No se repite ningún paso: revise a mano qué se aplicó (en especial si\n"
            "    horarios_comida.vigente_hasta ya recibió el +1 día) y complete lo que\n"
            "    falte, o restaure el respaldo, antes de reintentar.",
        )

    futuras = conexion.execute(
        sa.text(
            "SELECT id, comida_id, vigente_desde FROM horarios_comida "
            "WHERE activo = 1 AND vigente_desde > CURDATE() "
            "ORDER BY vigente_desde, id"
        )
    ).all()
    derecho = conexion.execute(
        sa.text(
            "SELECT id, vigente_desde FROM reglas_derecho "
            "WHERE vigente_desde > CURDATE() ORDER BY vigente_desde, id"
        )
    ).all()
    abiertas = conexion.execute(
        sa.text(
            "SELECT comida_id, COUNT(*) FROM horarios_comida "
            "WHERE activo = 1 AND vigente_hasta IS NULL "
            "GROUP BY comida_id HAVING COUNT(*) > 1 ORDER BY comida_id"
        )
    ).all()

    problemas = []
    if futuras:
        problemas.append(
            "  · Versiones de horario programadas a futuro (horarios_comida):\n"
            + _lista(futuras, lambda f: f"id={f[0]} comida_id={f[1]} desde {f[2]}")
        )
    if derecho:
        problemas.append(
            "  · Versiones de derecho programadas a futuro (reglas_derecho):\n"
            + _lista(derecho, lambda f: f"id={f[0]} desde {f[1]}")
        )
    if abiertas:
        problemas.append(
            "  · Comidas con más de una versión de horario abierta (vigente_hasta NULL):\n"
            + _lista(abiertas, lambda f: f"comida_id={f[0]} con {f[1]} abiertas")
        )
    if problemas:
        _detener(
            "hay programaciones o datos ambiguos que no se resuelven solos.",
            "\n".join(problemas)
            + "\n\n  Esta migración no cancela, desactiva ni reabre nada. Resuélvalos\n"
            "  explícitamente con la API vigente (borrar la programación o esperar a\n"
            "  que entre en vigor) y vuelva a correr. Después de migrar, el código\n"
            "  nuevo ya no permite gestionar versiones futuras.",
        )


def upgrade() -> None:
    conexion = op.get_bind()
    _verificar_upgrade(conexion)

    op.create_table(
        "cerrojos",
        sa.Column(
            "nombre",
            sa.String(length=40),
            nullable=False,
            comment=COMENTARIO_CERROJO_NOMBRE,
        ),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("nombre", name=op.f("pk_cerrojos")),
        comment=COMENTARIO_TABLA_CERROJOS,
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    conexion.execute(
        sa.text("INSERT INTO cerrojos (nombre) VALUES (:nombre)"),
        {"nombre": CERROJO_HORARIOS},
    )

    op.alter_column(
        "lecturas_biometricas",
        "fecha_hora",
        existing_type=sa.DateTime(),
        type_=mysql.DATETIME(fsp=6),
        existing_nullable=False,
    )

    # Una sola sentencia: el cambio de tipo de la tabla es atómico.
    conexion.exec_driver_sql(
        "ALTER TABLE horarios_comida "
        f"MODIFY vigente_desde DATETIME(6) NOT NULL COMMENT '{_literal(COMENTARIO_VIGENTE_DESDE)}', "
        f"MODIFY vigente_hasta DATETIME(6) NULL COMMENT '{_literal(COMENTARIO_VIGENTE_HASTA)}', "
        f"MODIFY motivo VARCHAR(500) NULL COMMENT '{_literal(COMENTARIO_MOTIVO_NUEVO)}'"
    )
    # Inclusivo -> exclusivo. Va DESPUÉS del ALTER y una sola vez: el estado
    # parcial se detecta arriba para que un reintento no la repita.
    conexion.execute(
        sa.text(
            "UPDATE horarios_comida "
            "SET vigente_hasta = DATE_ADD(vigente_hasta, INTERVAL 1 DAY) "
            "WHERE vigente_hasta IS NOT NULL"
        )
    )


COLUMNAS_INSTANTE = (
    ("horarios_comida", "vigente_desde"),
    ("horarios_comida", "vigente_hasta"),
    ("lecturas_biometricas", "fecha_hora"),
)

RECUPERACION = (
    "  No se intenta adivinar qué pasos se aplicaron. Un reintento NO es seguro: el\n"
    "  último paso del downgrade resta un día a horarios_comida.vigente_hasta y,\n"
    "  aplicado dos veces, corrompe los cierres.\n"
    "\n"
    "  Recuperación, a mano y con el respaldo previo a migrar a mano:\n"
    "    1. Lo más simple: restaure el respaldo y reintente con la base intacta.\n"
    "    2. O complete SOLO lo que falte, en este orden:\n"
    "         a) lecturas_biometricas.fecha_hora -> DATETIME NOT NULL;\n"
    "         b) DROP TABLE cerrojos;\n"
    "         c) horarios_comida: vigente_desde DATE NOT NULL, vigente_hasta DATE NULL,\n"
    "            motivo VARCHAR(500) NULL con el comentario anterior (ver este archivo);\n"
    "         d) UPDATE horarios_comida SET vigente_hasta = DATE_SUB(vigente_hasta,\n"
    "            INTERVAL 1 DAY) WHERE vigente_hasta IS NOT NULL -- SOLO si todavía no se\n"
    "            aplicó: si en un cierre vigente_hasta es IGUAL a la vigente_desde de su\n"
    "            sucesor (exclusivo), falta; si es un día ANTES (inclusivo), ya se aplicó.\n"
    "    3. Con el esquema de f13dd53094ae completo: `alembic stamp f13dd53094ae`.\n"
    "       Si todo estaba aplicado y solo falta el sello, es lo único que hay que hacer.\n"
    "    Para volver al estado de esta revisión: restaure el respaldo o deshaga a mano\n"
    "    los pasos aplicados y `alembic stamp ca83b39b791c`."
)


def _verificar_estado_de_la_revision(conexion) -> None:
    """El downgrade solo arranca desde el estado EXACTO de esta revisión: la
    tabla cerrojos y las tres columnas en DATETIME(6). Cualquier otra cosa es
    un downgrade interrumpido (o un esquema tocado a mano): no se continúa,
    porque no se puede saber si el -1 día ya se aplicó."""
    inspector = sa.inspect(conexion)
    anomalias = []
    if not inspector.has_table("cerrojos"):
        anomalias.append("falta la tabla cerrojos")
    for tabla, columna in COLUMNAS_INSTANTE:
        tipos = {c["name"]: c["type"] for c in inspector.get_columns(tabla)}
        tipo = tipos.get(columna)
        if not (isinstance(tipo, sa.DateTime) and getattr(tipo, "fsp", None) == 6):
            anomalias.append(
                f"{tabla}.{columna} es {type(tipo).__name__ if tipo is not None else 'inexistente'}, "
                "no DATETIME(6)"
            )
    if anomalias:
        raise RuntimeError(
            "Reversión de ca83b39b791c detenida ANTES de modificar nada: la base no "
            "está en el estado exacto de esta revisión (¿un downgrade interrumpido?).\n"
            + "\n".join(f"  · {a}" for a in anomalias)
            + "\n"
            + RECUPERACION
        )


def _tiene_hora(columna: str) -> str:
    """Predicado SQL: `columna` tiene alguna hora, minuto, segundo o microsegundo
    distinto de cero. Componentes numéricos contra cero: no depende de cómo
    MySQL formatee un TIME con fracción. NULL no cuenta (HOUR(NULL) es NULL)."""
    return (
        f"({columna} IS NOT NULL AND (HOUR({columna}) <> 0 OR MINUTE({columna}) <> 0 "
        f"OR SECOND({columna}) <> 0 OR MICROSECOND({columna}) <> 0))"
    )


def _verificar_downgrade(conexion) -> None:
    con_hora = conexion.execute(
        sa.text(
            "SELECT id, comida_id, vigente_desde, vigente_hasta FROM horarios_comida "
            f"WHERE {_tiene_hora('vigente_desde')} OR {_tiene_hora('vigente_hasta')} "
            "ORDER BY id"
        )
    ).all()
    con_micro = conexion.execute(
        sa.text(
            "SELECT COUNT(*), MIN(id) FROM lecturas_biometricas "
            "WHERE MICROSECOND(fecha_hora) <> 0"
        )
    ).one()
    problemas = []
    if con_hora:
        problemas.append(
            "  · Versiones de horario con hora (la reversión a DATE las perdería):\n"
            + _lista(
                con_hora,
                lambda f: f"id={f[0]} comida_id={f[1]} desde {f[2]} hasta {f[3]}",
            )
        )
    if con_micro[0]:
        problemas.append(
            f"  · {con_micro[0]} lecturas_biometricas con microsegundos "
            f"(la primera, id={con_micro[1]}): DATETIME(0) los perdería."
        )
    if problemas:
        raise RuntimeError(
            "Reversión de ca83b39b791c bloqueada ANTES de modificar nada: "
            "perdería datos o precisión.\n"
            + "\n".join(problemas)
            + "\n  Solo se revierte sin pérdida con todo a medianoche exacta y sin "
            "microsegundos. Resuélvalo explícitamente antes de reintentar."
        )


def downgrade() -> None:
    conexion = op.get_bind()
    # Primero el estado exacto (detecta un downgrade interrumpido), después los
    # datos que se perderían. Ambos antes de la primera modificación.
    _verificar_estado_de_la_revision(conexion)
    _verificar_downgrade(conexion)

    # Lo que no toca `vigente_hasta` va primero y lo que sí, al final: el
    # -1 día es el último paso. Si algo se interrumpe, el reintento NO
    # continúa (el estado ya no es el de la revisión): se detiene arriba con
    # instrucciones de recuperación, y el -1 día nunca se aplica dos veces.
    op.alter_column(
        "lecturas_biometricas",
        "fecha_hora",
        existing_type=mysql.DATETIME(fsp=6),
        type_=sa.DateTime(),
        existing_nullable=False,
    )
    if sa.inspect(conexion).has_table("cerrojos"):
        op.drop_table("cerrojos")
    # El tipo primero (los valores ya son medianoche exacta), después el -1 día
    # sobre DATE.
    conexion.exec_driver_sql(
        "ALTER TABLE horarios_comida "
        "MODIFY vigente_desde DATE NOT NULL COMMENT '', "
        "MODIFY vigente_hasta DATE NULL COMMENT '', "
        f"MODIFY motivo VARCHAR(500) NULL COMMENT '{_literal(COMENTARIO_MOTIVO_ANTERIOR)}'"
    )
    conexion.execute(
        sa.text(
            "UPDATE horarios_comida "
            "SET vigente_hasta = DATE_SUB(vigente_hasta, INTERVAL 1 DAY) "
            "WHERE vigente_hasta IS NOT NULL"
        )
    )
