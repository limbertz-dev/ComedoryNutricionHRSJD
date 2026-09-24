"""Las 5 tablas del Módulo Pacientes / Dietas.

Espejo exacto de `sql/modulo_pacientes.sql` y del DDL vivo de `bd_nutricion`.
Si una cambia, cambian las dos.

Control de Dietas (cambio DECIDIDO):
Control de Dietas deja de registrar la dieta por cama y paciente. Ahora se
registra, por día, cuántas raciones de cada tipo de dieta recibe cada
servicio: una matriz servicios × tipos de dieta en `raciones_servicio_dia`,
igual a la planilla "INFORME MENSUAL DE RACIONES SERVIDAS A PACIENTES".

Las tablas históricas (`dietas_cama`, `servicios_nutricion`, `tipos_dieta` y
`columnas_informe_dieta`) se preservan intactas con todo su historial.

Lo que este módulo NO guarda, a propósito: pacientes, camas, salas y
servicios del hospital. Todo eso ya vive en `bdestadistica` (SQL Server) y se
lee con un usuario de solo lectura. Acá solo se guarda la decisión de
nutrición, que es lo único que el hospital no tiene sistematizado en ningún
lado.

Las dos reglas que el esquema hace cumplir por sí mismo:

  · Una fila = UN HECHO                    ->  nunca se actualiza, se inserta.
  · Solo INSERT en hechos (dietas_cama,    ->  la última por momento manda.
    raciones_servicio_dia)
"""

from datetime import date, datetime

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text as sql,
)
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.modelos.comedor import ID, opciones
from app.modelos.heredados import ESQUEMA_TURNOS

MODOS_SERVICIO = ("censo", "cantidad")
VIAS = ("oral", "sng", "gastrostomia", "yeyunostomia", "parenteral")


class ColumnaInformeDieta(Base):
    """Las columnas del Informe Mensual de Raciones Servidas a Pacientes.

    `agrupa_en_id` existe porque los dos papeles del hospital no coinciden: la
    Planilla de Distribución Diaria lleva SONDAS y LÍQUIDAS en columnas
    separadas, y el informe mensual las suma en una sola. Las hijas apuntan a
    la madre y cada vista usa el nivel que le toca.

    Es autorreferencial y no una jerarquía de dos tablas porque el hospital
    cambia qué se agrupa con qué de una gestión a otra: siendo un dato, eso se
    corrige desde la pantalla y no con una migración.
    """

    __tablename__ = "columnas_informe_dieta"
    __table_args__ = opciones("Columnas del informe mensual de raciones a pacientes.")

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(60), unique=True)
    codigo: Mapped[str] = mapped_column(String(40), unique=True)
    agrupa_en_id: Mapped[int | None] = mapped_column(
        ID,
        ForeignKey("columnas_informe_dieta.id", ondelete="RESTRICT"),
        comment="NULL = columna del informe mensual. Con valor = se suma a esa.",
    )
    orden: Mapped[int] = mapped_column(Integer)
    activo: Mapped[bool] = mapped_column(TINYINT(1), default=1, server_default=sql("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class TipoDieta(Base):
    """El vocabulario de nutrición, más fino que el del informe.

    `cuenta_racion = 0` para NPO: la fila queda registrada —hace falta saber
    que a esa cama se la vio y se decidió no darle comida— y NO suma al total
    del servicio. Es la única razón de que la columna exista. Lo mismo vale
    para `dietas_cama.suspendida`, pero por cama y no por tipo de dieta.
    """

    __tablename__ = "tipos_dieta"
    __table_args__ = opciones("Tipos de dieta que prescribe nutricion.")

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(80), unique=True)
    codigo: Mapped[str] = mapped_column(String(40), unique=True)
    columna_informe_id: Mapped[int] = mapped_column(
        ID, ForeignKey("columnas_informe_dieta.id", ondelete="RESTRICT"), index=True
    )
    cuenta_racion: Mapped[bool] = mapped_column(
        TINYINT(1), default=1, server_default=sql("1")
    )
    orden: Mapped[int] = mapped_column(Integer)
    activo: Mapped[bool] = mapped_column(TINYINT(1), default=1, server_default=sql("1"))
    # Borrado lógico. `activo = 0` es "no disponible" y la dieta sigue listada;
    # `visible = 0` es "eliminada": desaparece del catálogo y de la captura,
    # pero la fila queda porque los hechos de `dietas_cama` la siguen citando.
    visible: Mapped[bool] = mapped_column(TINYINT(1), default=1, server_default=sql("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ServicioNutricion(Base):
    """Traduce el SIH al informe. Es la tabla que evita migraciones.

    Regla de resolución, y es la clave de todo el módulo: una fila con
    `sa_codigo` GANA sobre la fila con `sa_codigo IS NULL`. Así Infectología
    —que no existe como servicio del SIH, son las salas 38 y 39 dentro de
    Coloproctología (208)— se separa sin una sola excepción escrita en el
    código.

    `codigo_sih` admite NULL porque no todo lo que come sale del censo:
    Hemodiálisis no existe como servicio del SIH y se carga por cantidad
    (`modo = 'cantidad'`). La unicidad real la garantiza `codigo`.

    `hoja_informe` y `grupo_informe` son TEXTO y no claves foráneas a
    propósito: el hospital reordena sus agrupaciones de una gestión a otra, y
    un mes ya firmado tiene que poder mostrar el nombre con el que se firmó.
    """

    __tablename__ = "servicios_nutricion"
    __table_args__ = opciones(
        "Mapeo SIH -> hoja y grupo del informe. Sala gana sobre servicio.",
        # Una sola fila por par (servicio, sala). Con `sa_codigo` NULL es la
        # fila que cubre el servicio entero; con valor, la excepción por sala.
        UniqueConstraint(
            "codigo_sih", "sa_codigo", name="uq_servicios_nutricion_sih_sala"
        ),
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    codigo: Mapped[str] = mapped_column(
        String(40), unique=True, comment="Identificador estable para semillas y seeds."
    )
    codigo_sih: Mapped[int | None] = mapped_column(
        Integer,
        comment="VGRUCODIGO del servicio de la CAMA, no el de internacion.",
    )
    sa_codigo: Mapped[int | None] = mapped_column(
        Integer,
        comment="SE_SALA.SA_CODIGO. Con valor, esta fila gana sobre la del servicio.",
    )
    nombre_sih: Mapped[str] = mapped_column(String(120))
    hoja_informe: Mapped[str | None] = mapped_column(
        String(60), comment="NULL = todavia sin mapear: cae en Sin clasificar."
    )
    grupo_informe: Mapped[str | None] = mapped_column(
        String(60),
        comment="Fila del resumen mensual. Cambia de mes a mes: por eso es dato.",
    )
    orden: Mapped[int] = mapped_column(Integer, default=0, server_default=sql("0"))
    modo: Mapped[str] = mapped_column(
        SAEnum(*MODOS_SERVICIO, name="modo_servicio_nutricion"),
        default="censo",
        server_default=sql("'censo'"),
    )
    servicio_id: Mapped[int | None] = mapped_column(
        ID,
        ForeignKey(f"{ESQUEMA_TURNOS}.servicios.id", ondelete="RESTRICT"),
        index=True,
        comment="Servicio del modulo de turnos. Opcional: son vocabularios distintos.",
    )
    activo: Mapped[bool] = mapped_column(TINYINT(1), default=1, server_default=sql("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class DietasCama(Base):
    """El registro. Una fila = UN HECHO.

    A esta cama, este día, a esta hora, se le asignó esta dieta.

    **Un cambio NO actualiza la fila anterior: inserta una nueva.** Si a las
    08:00 la cama 12 tenía Corriente y a las 09:40 pasó a Hiposograsa, quedan
    las dos filas. Para el conteo del día manda la última de cada cama; para
    auditar están todas. Es la única forma de responder después por qué un mes
    cerrado no coincide con lo que se vio en el momento.

    NINGUNA columna del SIH es clave foránea, y no es un olvido: son copias
    congeladas. El SIH es de otro sistema y de otro motor —una FK ni siquiera
    sería posible— pero aunque lo fuera, tampoco la querríamos.

    Lo que NO suma al libro aunque quede registrado: las filas con
    `suspendida = 1` y las de un tipo de dieta con `cuenta_racion = 0` (NPO).
    Las camas con `servicio_nutricion_id` NULL SÍ suman, en una fila
    "Sin clasificar" visible: el hueco se muestra, no se esconde.
    """

    __tablename__ = "dietas_cama"
    __table_args__ = opciones(
        "Una fila = un hecho: a esta cama, este dia, a esta hora, esta dieta.",
        Index("ix_dietas_cama_fecha_servicio", "fecha", "servicio_nutricion_id"),
        # El índice que sostiene todo el conteo: resuelve la ÚLTIMA dieta de
        # cada cama en un día sin recorrer la tabla. Los tres informes y el
        # libro final salen de esa misma consulta.
        Index("ix_dietas_cama_ultima", "fecha", "cam_codigo", "momento"),
        Index("ix_dietas_cama_historia", "nro_historia"),
        # La traduccion de `HCL_SEXO` (1/2) a M/F la hace la aplicacion, en
        # `censo.py`. Este CHECK es el ultimo guardian: si alguna vez se
        # inserta por fuera de la aplicacion, la BD rechaza el codigo crudo
        # en vez de dejar un '1' que despues nadie sabe leer.
        CheckConstraint("`sexo` IS NULL OR `sexo` IN ('M','F')", name="sexo"),
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True)

    fecha: Mapped[date] = mapped_column(
        Date, comment="Dia al que corresponde la racion."
    )
    momento: Mapped[datetime] = mapped_column(
        DateTime,
        comment="Hora del hecho. Ordena los cambios: la ultima del dia manda.",
    )

    # --- copias congeladas del SIH · sin FK a propósito ---
    cam_codigo: Mapped[int | None] = mapped_column(
        Integer, comment="SE_CAMA.CAM_CODIGO"
    )
    sa_codigo: Mapped[int | None] = mapped_column(Integer, comment="SE_SALA.SA_CODIGO")
    nro_historia: Mapped[int | None] = mapped_column(ID)
    nombre_paciente: Mapped[str | None] = mapped_column(String(160))
    sexo: Mapped[str | None] = mapped_column(
        CHAR(1),
        comment=(
            "Solo M o F, ya traducidos por la aplicacion. NUNCA el codigo "
            "crudo de SE_HC.HCL_SEXO: si el hospital cambia su codificacion, "
            "se arregla en un solo lugar y el historico no se toca."
        ),
    )
    sala_texto: Mapped[str | None] = mapped_column(String(120))
    pieza_texto: Mapped[str | None] = mapped_column(
        String(60), comment="La columna PIEZA del parte de papel."
    )
    cama_texto: Mapped[str | None] = mapped_column(String(60))

    # --- la decisión de nutrición ---
    servicio_nutricion_id: Mapped[int | None] = mapped_column(
        ID,
        ForeignKey("servicios_nutricion.id", ondelete="RESTRICT"),
        comment=(
            "Resuelto al momento del hecho. NULL = sala sin mapeo: cae en "
            "Sin clasificar."
        ),
    )
    tipo_dieta_id: Mapped[int] = mapped_column(
        ID, ForeignKey("tipos_dieta.id", ondelete="RESTRICT")
    )
    prescripcion_texto: Mapped[str | None] = mapped_column(
        Text,
        comment=(
            "Texto libre, tal cual lo escribe la licenciada. CUALQUIER dieta "
            'puede llevarlo: en las hojitas hay una corriente "a tolerancia '
            'asistido semisentado".'
        ),
    )

    # --- extracción del texto anterior · opcional, nunca lo reemplaza ---
    # Se intenta leer estos campos de `prescripcion_texto`, pero el texto
    # original manda siempre: si la extracción falla quedan en NULL y no se
    # pierde nada de lo que escribió la licenciada.
    volumen_ml: Mapped[int | None] = mapped_column(Integer)
    kcal: Mapped[int | None] = mapped_column(Integer)
    proteina_g: Mapped[int | None] = mapped_column(Integer)
    tomas: Mapped[int | None] = mapped_column(TINYINT)
    via: Mapped[str | None] = mapped_column(SAEnum(*VIAS, name="via_alimentacion"))

    suspendida: Mapped[bool] = mapped_column(
        TINYINT(1),
        default=0,
        server_default=sql("0"),
        comment="La cama deja de recibir comida (cirugia, alta). No suma al libro.",
    )
    motivo: Mapped[str | None] = mapped_column(
        String(200),
        comment=(
            "NULLable a proposito: la PRIMERA dieta del dia no tiene motivo. "
            "La aplicacion lo exige en todo cambio y en toda suspension; la "
            "BD no, porque la carga inicial y una eventual importacion masiva "
            "no lo tienen."
        ),
    )

    registrado_por: Mapped[int | None] = mapped_column(
        ID, ForeignKey(f"{ESQUEMA_TURNOS}.users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RacionServicioDia(Base):
    """Una celda de la planilla de distribución diaria. Una fila = UN HECHO.

    Registra: el día `fecha`, para el servicio / fila `fila_informe` (el código de
    `FILAS_DISTRIBUCION`, p. ej. 'pediatria_gral'), se asignan `cantidad` raciones
    de la columna `columna_informe_id`.

    **Solo INSERT, igual que `dietas_cama`:**
    Corregir o actualizar una celda NO ejecuta UPDATE ni DELETE: se inserta una
    nueva fila con su `momento`. La celda vigente para un día, fila y columna es
    la última registrada (por `momento`, y a igual momento por `id`).

    Una cantidad de 0 es válida y representa explícitamente que no se sirven
    raciones en esa celda (o la corrección a cero de una celda cargada por error).
    """

    __tablename__ = "raciones_servicio_dia"
    __table_args__ = opciones(
        "Una fila = un hecho: el dia F, el servicio S tiene N raciones de la columna C. Celda vigente = ultima por momento.",
        Index(
            "ix_raciones_servicio_dia_ultima",
            "fecha",
            "fila_informe",
            "columna_informe_id",
            "momento",
        ),
        CheckConstraint("`cantidad` >= 0", name="cantidad"),
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    fecha: Mapped[date] = mapped_column(
        Date, comment="Dia al que corresponde la racion."
    )
    fila_informe: Mapped[str] = mapped_column(
        String(40),
        comment="Codigo de fila de FILAS_DISTRIBUCION (ej: 'pediatria_gral').",
    )
    columna_informe_id: Mapped[int] = mapped_column(
        ID,
        ForeignKey("columnas_informe_dieta.id", ondelete="RESTRICT"),
        comment="Columna del informe mensual a la que suma.",
    )
    cantidad: Mapped[int] = mapped_column(
        Integer, comment="Numero de raciones servidas (>= 0)."
    )
    momento: Mapped[datetime] = mapped_column(
        DateTime,
        comment="Hora del hecho. Ordena los cambios: la ultima por celda manda.",
    )
    registrado_por: Mapped[int | None] = mapped_column(
        ID,
        ForeignKey(f"{ESQUEMA_TURNOS}.users.id", ondelete="SET NULL"),
        comment="Usuario que registro o modifico la celda.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

