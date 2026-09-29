"""Las 6 tablas propias del Módulo Personal / Comensales, en `bd_nutricion`.

Reglas del modelo que el esquema hace cumplir por sí mismo:

  · Una ración por persona, comida y día  ->  UNIQUE en asistencias.
  · Reclasificar o trasladar no altera informes de fechas anteriores  ->  copias congeladas
    de categoria_reporte_id y servicio_id dentro de la ración.

Sin FK hacia la base de turnos. Las columnas que guardan un id de
`bd_proyecto_backend` (usuario_id, comida_id, categoria_id, servicio_id,
turno_asignado_id, registrado_por) son referencias LÓGICAS, validadas por la
aplicación contra las vistas v_*: una FK entre bases le impediría al otro
ingeniero borrar un usuario o migrar su propio esquema, y eso es tocar su
base aunque no se le emita un ALTER. Por eso ya no hay RESTRICT al borrar un
usuario: una ración servida sigue siendo un hecho histórico, pero se protege
no borrando asistencias, no bloqueando la base ajena. Las FK internas
(asistencias -> categorias_reporte, lecturas_biometricas) se mantienen.

Los COMMENT no son decorativos: viajan con el esquema, salen en SHOW CREATE
TABLE y son lo que impide que alguien "normalice" las copias congeladas sin
saber para qué están.
"""

from datetime import date, datetime, time

from sqlalchemy import (
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import BIGINT, TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# Las claves de bd_turnos son BIGINT UNSIGNED: toda FK que las apunte debe
# usar el mismo tipo o MySQL rechaza la restricción.
ID = BIGINT(unsigned=True)


def opciones(comentario: str, *restricciones):
    """Opciones de tabla para todo lo que cree este sistema.

    La collation NO es un detalle cosmético. Las tablas del módulo de turnos
    usan `utf8mb4_unicode_ci` (la convención de Laravel), pero la base tiene
    `utf8mb4_0900_ai_ci` por defecto. Si nuestras tablas toman el default,
    cualquier JOIN por texto contra una tabla del otro ingeniero revienta con
    "Illegal mix of collations". Hoy ningún JOIN del sistema compara texto
    entre tablas (todos van por id), pero basta con que alguien agregue uno
    para que reaparezca.

    Toda tabla nueva debe crearse con esto. Es la razón de que esta función
    exista en vez de repetir el diccionario once veces.
    """
    config = {
        "comment": comentario,
        "mysql_charset": "utf8mb4",
        "mysql_collate": "utf8mb4_unicode_ci",
    }
    return (*restricciones, config) if restricciones else config


MOTIVOS_RECHAZO = (
    "duplicado",
    "sin_derecho",
    "fuera_horario",
    "no_identificado",
)


class CategoriaReporte(Base):
    """Las 6 columnas del formulario del Servicio de Estadística."""

    __tablename__ = "categorias_reporte"
    __table_args__ = opciones("Columnas del formulario de Estadistica.")

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(80), unique=True)
    codigo: Mapped[str] = mapped_column(String(40), unique=True)
    orden: Mapped[int] = mapped_column(Integer)
    activo: Mapped[bool] = mapped_column(TINYINT(1), default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class CategoriaReporteMap(Base):
    """Mapea cada categoría real del hospital a su columna del formulario.

    Existe como tabla aparte, en vez de una columna dentro de `categorias`,
    para no alterar la estructura de una tabla del módulo de turnos.
    """

    __tablename__ = "categoria_reporte_map"
    __table_args__ = opciones(
        "Categoria del hospital -> columna del formulario. Tabla puente "
        "para no alterar la tabla heredada categorias."
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    categoria_id: Mapped[int] = mapped_column(
        ID,
        unique=True,
        comment=(
            "categorias.id de la base de turnos (v_categorias), sin FK. Una "
            "categoria mapea a una sola columna del informe."
        ),
    )
    categoria_reporte_id: Mapped[int] = mapped_column(
        ID, ForeignKey("categorias_reporte.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class HorarioComida(Base):
    """Qué franja horaria corresponde a cada tiempo de comida, con vigencia."""

    __tablename__ = "horarios_comida"
    __table_args__ = opciones(
        "Franja horaria de cada comida. Dos comidas NO pueden solaparse "
        "en la misma fecha: eso decide a que fila del informe suma la racion.",
        UniqueConstraint(
            "comida_id", "vigente_desde", name="uq_horarios_comida_vigencia"
        ),
        Index(
            "ix_horarios_comida_comida_id_vigente_desde",
            "comida_id",
            "vigente_desde",
        ),
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    comida_id: Mapped[int] = mapped_column(
        ID, comment="comidas.id de la base de turnos (v_comidas), sin FK."
    )
    hora_inicio: Mapped[time] = mapped_column(Time)
    hora_fin: Mapped[time] = mapped_column(
        Time,
        comment="Si es menor que hora_inicio, la franja cruza la medianoche.",
    )
    vigente_desde: Mapped[date] = mapped_column(Date)
    vigente_hasta: Mapped[date | None] = mapped_column(Date)
    activo: Mapped[bool] = mapped_column(TINYINT(1), default=1)
    motivo: Mapped[str | None] = mapped_column(
        String(500),
        comment=(
            "Por qué se creó esta versión del horario. NULL en las filas "
            "anteriores a R2, que no lo tenían."
        ),
    )
    creada_por_cuenta: Mapped[int | None] = mapped_column(
        ID,
        ForeignKey("usuarios_sistema.id", ondelete="RESTRICT"),
        comment=(
            "usuarios_sistema.id de la cuenta root que creó esta versión del "
            "horario. FK interna: las cuentas se dan de baja, no se borran."
        ),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class CoeficienteRacion(Base):
    """Coeficientes que reducen cada tiempo de comida a ración completa."""

    __tablename__ = "coeficientes_racion"
    __table_args__ = opciones(
        "Cada fila es una VERSION del coeficiente de una comida. Se "
        "resuelve por (comida_id, fecha), nunca por una FK desde comidas "
        "a una version concreta: cambiar un coeficiente no debe alterar "
        "los informes ya firmados.",
        UniqueConstraint(
            "comida_id", "vigente_desde", name="uq_coeficientes_racion_vigencia"
        ),
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    comida_id: Mapped[int] = mapped_column(
        ID, comment="comidas.id de la base de turnos (v_comidas), sin FK."
    )
    coeficiente: Mapped[float] = mapped_column(Numeric(4, 3))
    vigente_desde: Mapped[date] = mapped_column(Date)
    vigente_hasta: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class LecturaBiometrica(Base):
    """El hardware: cada toque de dedo, identifique o no a alguien."""

    __tablename__ = "lecturas_biometricas"
    __table_args__ = opciones(
        "Bitacora del lector. Un rechazo vive aqui, no en asistencias: se "
        "evita la racion, nunca el registro del intento.",
        Index("idx_lecturas_fecha_hora", "fecha_hora"),
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    usuario_id: Mapped[int | None] = mapped_column(
        ID,
        comment=(
            "users.id de la base de turnos (v_comensales), sin FK. NULL "
            "cuando el lector no reconoce la huella."
        ),
    )
    dispositivo: Mapped[str] = mapped_column(String(50))
    fecha_hora: Mapped[datetime] = mapped_column(DateTime)
    resultado: Mapped[str] = mapped_column(
        SAEnum("aceptada", "rechazada", name="resultado_lectura")
    )
    motivo: Mapped[str | None] = mapped_column(
        SAEnum(*MOTIVOS_RECHAZO, name="motivo_rechazo")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Asistencia(Base):
    """Una fila = una ración servida. Única fuente de los tres informes."""

    __tablename__ = "asistencias"
    __table_args__ = opciones(
        "Una racion por persona, comida y dia. El derecho a comer NO se "
        "guarda: sale de turnos_asignados cruzado con turno_comida.",
        UniqueConstraint(
            "usuario_id", "fecha_comida", "comida_id", name="uq_asistencias_racion"
        ),
        Index("idx_asistencias_fecha_comida", "fecha_comida", "comida_id"),
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(
        ID,
        comment=(
            "users.id de la base de turnos (v_comensales), sin FK entre bases. "
            "Una racion servida es un hecho historico: no se borra."
        ),
    )
    fecha_comida: Mapped[date] = mapped_column(
        Date,
        comment=(
            "Fecha a la que corresponde la racion: turnos_asignados.fecha + "
            "turno_comida.dia_relativo. Sale del derecho, NUNCA de DATE(fecha_hora)."
        ),
    )
    comida_id: Mapped[int] = mapped_column(
        ID, comment="comidas.id de la base de turnos (v_comidas), sin FK."
    )
    categoria_reporte_id: Mapped[int] = mapped_column(
        ID,
        ForeignKey("categorias_reporte.id", ondelete="RESTRICT"),
        comment=(
            "Copia deliberada, NO normalizar: congela la columna del informe al "
            "momento de servir, para que reclasificar no cambie la historia."
        ),
    )
    servicio_id: Mapped[int | None] = mapped_column(
        ID,
        comment=(
            "Copia deliberada (ver categoria_reporte_id). Sala del hospital, NO "
            "la categoria 'Servicio' del formulario de Estadistica."
        ),
    )
    turno_asignado_id: Mapped[int | None] = mapped_column(
        ID, comment="turnos_asignados.id que justifico la racion, sin FK."
    )
    metodo: Mapped[str] = mapped_column(
        SAEnum("biometrico", "manual", name="metodo_asistencia")
    )
    lectura_id: Mapped[int | None] = mapped_column(
        ID,
        ForeignKey("lecturas_biometricas.id", ondelete="SET NULL"),
        comment="NULL si la racion se registro a mano porque el lector fallo.",
    )
    fecha_hora: Mapped[datetime] = mapped_column(
        DateTime, comment="Instante del reloj en que se marco."
    )
    registrado_por: Mapped[int | None] = mapped_column(
        ID,
        comment=(
            "LEGACY: users.id de quien la registro a mano, sin FK. Desde "
            "registrado_por_cuenta queda en NULL para las filas nuevas."
        ),
    )
    registrado_por_cuenta: Mapped[int | None] = mapped_column(
        ID,
        ForeignKey("usuarios_sistema.id", ondelete="RESTRICT"),
        comment=(
            "usuarios_sistema.id de quien la registro a mano, tomado del "
            "token. FK interna: las cuentas se dan de baja, no se borran."
        ),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
