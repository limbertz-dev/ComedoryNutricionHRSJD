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
    CHAR,
    CheckConstraint,
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
from sqlalchemy.dialects.mysql import BIGINT, DATETIME, TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# Las claves de bd_turnos son BIGINT UNSIGNED: toda FK que las apunte debe
# usar el mismo tipo o MySQL rechaza la restricción.
ID = BIGINT(unsigned=True)

# Instantes con microsegundos. Los horarios cambian en el instante en que se
# guardan y la lectura se compara contra ese instante: si cualquiera de los
# dos perdiera precisión, un toque de dedo pegado al corte caería en la
# versión vecina. Las columnas existentes conservan sus valores (.000000).
INSTANTE = DATETIME(fsp=6)

# Idénticos carácter por carácter a los de la migración ca83b39b791c.
COMENTARIO_VIGENTE_DESDE = (
    "Primer instante en que rige esta versión, inclusive. Con microsegundos: "
    "puede haber varios cambios el mismo día."
)
COMENTARIO_VIGENTE_HASTA = (
    "Instante en que deja de regir, EXCLUSIVO. NULL = versión abierta: la que "
    "rige desde su vigente_desde en adelante."
)
COMENTARIO_MOTIVO_HORARIO = (
    "Solo las filas de R2 lo traen. Desde que los horarios rigen al guardar, "
    "el sistema no pide motivo y queda NULL."
)


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


# 'checklist': la cocinera marca en la lista de la comida en curso mientras
# no esté el lector. Pasa por las mismas reglas que la huella.
METODOS_ASISTENCIA = ("biometrico", "manual", "checklist")

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
    """Qué franja horaria corresponde a cada tiempo de comida, con vigencia.

    Cada fila es una versión con vigencia `[vigente_desde, vigente_hasta)` en
    instantes, no en días. Guardar un horario cierra la versión abierta
    (`vigente_hasta` NULL) en el instante del servidor y abre otra desde ese
    mismo instante; nunca se programa a futuro ni se reescribe el pasado. La
    resolución vive en app/consultas/horarios.py.
    """

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
    vigente_desde: Mapped[datetime] = mapped_column(
        INSTANTE, comment=COMENTARIO_VIGENTE_DESDE
    )
    vigente_hasta: Mapped[datetime | None] = mapped_column(
        INSTANTE, comment=COMENTARIO_VIGENTE_HASTA
    )
    activo: Mapped[bool] = mapped_column(TINYINT(1), default=1)
    motivo: Mapped[str | None] = mapped_column(
        String(500), comment=COMENTARIO_MOTIVO_HORARIO
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
    fecha_hora: Mapped[datetime] = mapped_column(INSTANTE)
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
        # Una lectura da, como mucho, una ración. Varias filas con lectura_id
        # NULL (registros manuales) siguen siendo posibles.
        UniqueConstraint("lectura_id", name="uq_asistencias_lectura_id"),
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
        SAEnum(*METODOS_ASISTENCIA, name="metodo_asistencia")
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


# Idénticos carácter por carácter a los de la migración b3e5f7a9c1d4.
COMENTARIO_TABLA_ANULACIONES = (
    "Raciones del checklist que la misma cocinera desmarco a los pocos "
    "minutos. Solo inserciones: la asistencia se borra y aqui queda su copia."
)
COMENTARIO_ANULACION_ASISTENCIA = (
    "asistencias.id que se borro. Sin FK: la fila ya no existe."
)


class AnulacionChecklist(Base):
    """Una ración del checklist que se deshizo por error de la cocinera.

    La ración es un hecho histórico y no se borra... salvo esta excepción
    acotada: la marcó la misma cuenta hace pocos minutos y la comida sigue
    abierta (app/logica/checklist.py). Para que la excepción no deje huecos,
    la copia de la ración y quién la anuló quedan aquí.
    """

    __tablename__ = "anulaciones_checklist"
    __table_args__ = opciones(
        COMENTARIO_TABLA_ANULACIONES,
        Index("idx_anulaciones_checklist_fecha_comida", "fecha_comida", "comida_id"),
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    asistencia_id: Mapped[int] = mapped_column(ID, comment=COMENTARIO_ANULACION_ASISTENCIA)
    usuario_id: Mapped[int] = mapped_column(
        ID, comment="users.id del comensal desmarcado, sin FK entre bases."
    )
    fecha_comida: Mapped[date] = mapped_column(Date)
    comida_id: Mapped[int] = mapped_column(ID)
    marcada_en: Mapped[datetime] = mapped_column(
        DateTime, comment="asistencias.fecha_hora de la racion anulada."
    )
    cuenta_id: Mapped[int] = mapped_column(
        ID,
        ForeignKey("usuarios_sistema.id", ondelete="RESTRICT"),
        comment="La cocinera que marco y anulo (la misma cuenta, por regla).",
    )
    anulada_en: Mapped[datetime] = mapped_column(
        DateTime, comment="Instante del reloj del servidor al anular."
    )


CAUSA_IDENTIFICACION = "identificacion_manual_por_no_identificado"
RESULTADOS_INTERVENCION = ("registrada", "rechazada")
MOTIVOS_RECHAZO_INTERVENCION = (
    "sin_derecho",
    "duplicado",
    "lectura_ya_resuelta",
    "lectura_no_resoluble",
    "servicio_distinto",
    "servicio_no_determinable",
    "reloj_inconsistente",
)
ORIGEN_SERVICIO = "reconstruido_por_horario"

# Idénticos carácter por carácter a los de la migración e1a7c3b9d5f2.
COMENTARIO_TABLA_INTERVENCIONES = (
    "Auditoria de la identificacion manual de una lectura no reconocida. "
    "Solo inserciones: cada fila es un intento de la cocinera, registrado o "
    "rechazado. La lectura original no se modifica."
)
COMENTARIO_INTERVENCION_CLAVE = (
    "Idempotency-Key del intento, por cuenta. Con la misma huella devuelve "
    "lo guardado en vez de repetir."
)
COMENTARIO_INTERVENCION_HUELLA = (
    "SHA-256 de {lectura_id, usuario_id}. La misma clave con otra huella es "
    "un conflicto."
)
COMENTARIO_INTERVENCION_SERVICIO = (
    "Servicio que el sistema uso. Se RECONSTRUYE por horario a partir de "
    "lecturas_biometricas.fecha_hora, que no guarda comida ni fecha_comida: "
    "no es un dato historico de la lectura."
)
COMENTARIO_INTERVENCION_COPIAS = (
    "Copia del momento del intento, para responder un reintento sin depender "
    "del padron ni de los horarios."
)


class IntervencionLectura(Base):
    """Un intento de identificar a mano una lectura `no_identificado`.

    Solo se inserta: ninguna fila se actualiza ni se borra, y por eso el
    conjunto de filas visibles para un rol solo crece (la `revision` de la
    pantalla se apoya en eso). `registrada` es la única que tiene ración;
    `rechazada` es un intento que no la tuvo y nunca es una entrega.

    Esa relación (`registrada` ⇔ `asistencia_id` no nulo) NO la protege ningún
    CHECK de la base: el CHECK de la tabla solo cubre `motivo_rechazo`, y no se
    verificó si MySQL admite uno sobre una columna con FK RESTRICT. La sostiene
    el único camino de inserción (app/logica/intervencion.py), que escribe la
    ración y la fila en una sola transacción, y la comprueban las pruebas
    sobre lo que queda en la base tras carreras y fallos.
    """

    __tablename__ = "intervenciones_lectura"
    __table_args__ = opciones(
        COMENTARIO_TABLA_INTERVENCIONES,
        UniqueConstraint(
            "cuenta_id",
            "clave_idempotencia",
            name="uq_intervenciones_lectura_cuenta_clave",
        ),
        UniqueConstraint("asistencia_id", name="uq_intervenciones_lectura_asistencia_id"),
        CheckConstraint(
            "(resultado = 'registrada' AND motivo_rechazo IS NULL) OR "
            "(resultado = 'rechazada' AND motivo_rechazo IS NOT NULL)",
            name="motivo_coherente",
        ),
        Index("idx_intervenciones_momento", "momento"),
        Index("idx_intervenciones_lectura", "lectura_id"),
        Index("idx_intervenciones_cuenta_momento", "cuenta_id", "momento"),
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    lectura_id: Mapped[int] = mapped_column(
        ID,
        ForeignKey("lecturas_biometricas.id", ondelete="RESTRICT"),
        comment="La lectura intervenida. RESTRICT: la auditoria no se queda sin ella.",
    )
    usuario_id: Mapped[int] = mapped_column(
        ID,
        comment="users.id de la persona propuesta por la cocinera, sin FK entre bases.",
    )
    cuenta_id: Mapped[int] = mapped_column(
        ID,
        ForeignKey("usuarios_sistema.id", ondelete="RESTRICT"),
        comment=(
            "usuarios_sistema.id de la cocinera, tomado del token. FK interna: "
            "las cuentas se dan de baja, no se borran."
        ),
    )
    clave_idempotencia: Mapped[str] = mapped_column(
        CHAR(36), comment=COMENTARIO_INTERVENCION_CLAVE
    )
    huella_solicitud: Mapped[str] = mapped_column(
        CHAR(64), comment=COMENTARIO_INTERVENCION_HUELLA
    )
    resultado: Mapped[str] = mapped_column(
        SAEnum(*RESULTADOS_INTERVENCION, name="resultado_intervencion"),
        comment="registrada = hubo entrega y racion. rechazada = no la hubo.",
    )
    motivo_rechazo: Mapped[str | None] = mapped_column(
        SAEnum(*MOTIVOS_RECHAZO_INTERVENCION, name="motivo_rechazo_intervencion")
    )
    causa: Mapped[str] = mapped_column(
        SAEnum(CAUSA_IDENTIFICACION, name="causa_intervencion"),
        comment="La fija el servidor. La usuaria no escribe motivo ni nota.",
    )
    comida_id: Mapped[int | None] = mapped_column(
        ID, comment=COMENTARIO_INTERVENCION_SERVICIO
    )
    fecha_comida: Mapped[date | None] = mapped_column(Date)
    ventana_inicio: Mapped[datetime | None] = mapped_column(INSTANTE)
    ventana_fin: Mapped[datetime | None] = mapped_column(INSTANTE)
    origen_servicio: Mapped[str | None] = mapped_column(
        SAEnum(ORIGEN_SERVICIO, name="origen_servicio")
    )
    nombre_comensal: Mapped[str | None] = mapped_column(
        String(100), comment=COMENTARIO_INTERVENCION_COPIAS
    )
    nombre_comida: Mapped[str | None] = mapped_column(String(80))
    servicio_id: Mapped[int | None] = mapped_column(ID)
    asistencia_id: Mapped[int | None] = mapped_column(
        ID,
        ForeignKey("asistencias.id", ondelete="RESTRICT"),
        comment="La racion de una intervencion registrada. NULL en las rechazadas.",
    )
    momento: Mapped[datetime] = mapped_column(
        INSTANTE, comment="Instante del reloj del servidor en que se resolvio el intento."
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# Idénticos carácter por carácter a los de la migración ca83b39b791c.
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


class Cerrojo(Base):
    """Un mutex persistente dentro de `bd_nutricion`.

    `SELECT ... FOR UPDATE` sobre una tabla vacía solo toma el gap-lock del
    supremum, que no choca con el de otra transacción: dos altas simultáneas
    pasan las dos o terminan en deadlock, y en READ COMMITTED ni siquiera hay
    gap-lock. Una fila que existe siempre sí: el bloqueo de registro es
    exclusivo en cualquier aislamiento, se libera con COMMIT o ROLLBACK y lo
    suelta el servidor si la conexión muere. No hay GET_LOCK, que pertenece a
    la conexión y no a la transacción.
    """

    __tablename__ = "cerrojos"
    __table_args__ = opciones(COMENTARIO_TABLA_CERROJOS)

    nombre: Mapped[str] = mapped_column(
        String(40), primary_key=True, comment=COMENTARIO_CERROJO_NOMBRE
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
