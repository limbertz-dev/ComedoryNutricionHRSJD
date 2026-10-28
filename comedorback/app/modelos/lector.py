"""Tablas del lector biométrico real.

El lector no conoce el padrón: entrega el identificador con el que enroló a
la persona (el número de usuario de una terminal, o el id de plantilla que
devuelve el programa de un lector USB). `vinculos_lector` lo traduce a
`users.id`. `solicitudes_lector` guarda cada envío por su Idempotency-Key,
para que un reintento del puente no escriba una segunda lectura.

Un vínculo es de `personal` (una persona del padrón) o de `policia`: los
policías no están en la base de turnos, así que su huella no apunta a nadie y
cada lectura suya es una ración en `raciones_policia`, aparte del personal, que
solo cuenta en la columna Policías (app/logica/policia.py).
"""

from datetime import date, datetime

from sqlalchemy import CHAR, JSON, CheckConstraint, Date, DateTime, Enum as SAEnum, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.mysql import SMALLINT, TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.modelos.comedor import ID, INSTANTE, opciones

TIPOS_VINCULO = ("personal", "policia")

# Idénticos carácter por carácter a los de la migración a9d3c5e7f1b2.
COMENTARIO_TABLA_VINCULOS = (
    "Traduce el identificador que entrega el lector a la persona del padron. "
    "Baja logica: un vinculo se desactiva, no se borra."
)
COMENTARIO_TABLA_SOLICITUDES = (
    "Cada envio de un lector autorizado, por su Idempotency-Key: un reintento "
    "devuelve lo guardado en vez de escribir otra lectura."
)


class VinculoLector(Base):
    """Identificador del lector -> persona del padrón."""

    __tablename__ = "vinculos_lector"
    __table_args__ = opciones(
        COMENTARIO_TABLA_VINCULOS,
        CheckConstraint(
            "(tipo = 'personal' AND usuario_id IS NOT NULL) OR "
            "(tipo = 'policia' AND usuario_id IS NULL)",
            name="tipo_coherente",
        ),
        Index("idx_vinculos_lector_usuario", "usuario_id"),
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    identificador: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        comment="Numero de usuario o id de plantilla con que el lector enrolo la huella.",
    )
    tipo: Mapped[str] = mapped_column(
        SAEnum(*TIPOS_VINCULO, name="tipo_vinculo"), default="personal",
        comment="personal = persona del padron. policia = racion directa en la columna Policias.",
    )
    usuario_id: Mapped[int | None] = mapped_column(
        ID, comment="users.id de la base de turnos (v_comensales), sin FK. NULL en policias."
    )
    nombre: Mapped[str | None] = mapped_column(
        String(100), comment="Solo policias: nombre completo, escrito al registrar la huella."
    )
    documento: Mapped[str | None] = mapped_column(
        String(30), comment="Solo policias, opcional: CI o numero de placa."
    )
    activo: Mapped[bool] = mapped_column(TINYINT(1), default=1)
    plantilla: Mapped[str | None] = mapped_column(
        Text, deferred=True,
        comment=(
            "Plantilla ZKFinger en base64, si la huella se enrolo con un lector USB. "
            "Solo la lee el puente con la clave del lector; nunca sale en /lector/vinculos."
        ),
    )
    creado_por_cuenta: Mapped[int | None] = mapped_column(
        ID,
        ForeignKey("usuarios_sistema.id", ondelete="RESTRICT"),
        comment="Cuenta de jefatura que creo o reasigno el vinculo.",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class SolicitudLector(Base):
    """Un envío del lector, identificado por su Idempotency-Key."""

    __tablename__ = "solicitudes_lector"
    __table_args__ = opciones(
        COMENTARIO_TABLA_SOLICITUDES,
        Index("idx_solicitudes_lector_lectura", "lectura_id"),
    )

    clave: Mapped[str] = mapped_column(
        CHAR(36), primary_key=True, comment="Idempotency-Key (UUID v4) del envio."
    )
    dispositivo: Mapped[str] = mapped_column(
        String(50), comment="Nombre del lector, fijado por su clave en LECTORES."
    )
    identificador: Mapped[str | None] = mapped_column(
        String(64), comment="Lo que entrego el lector. NULL = huella no reconocida."
    )
    lectura_id: Mapped[int | None] = mapped_column(
        ID, ForeignKey("lecturas_biometricas.id", ondelete="RESTRICT"),
        comment="NULL cuando el envio fue de un policia: su racion va a raciones_policia.",
    )
    respuesta: Mapped[dict] = mapped_column(
        JSON, comment="Respuesta enviada al lector, para repetirla ante un reintento."
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


COMENTARIO_TABLA_POLICIAS = (
    "Policias que comen en el comedor, por numero (Policia 1, 2, ...): no estan en "
    "la base de turnos. Los da de alta la jefatura. Baja logica: se desactiva, no se borra."
)


class Policia(Base):
    """Un policía por número, sin nombre: lo que ve la cocinera en el checklist."""

    __tablename__ = "policias"
    __table_args__ = opciones(COMENTARIO_TABLA_POLICIAS)

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    numero: Mapped[int] = mapped_column(
        SMALLINT(unsigned=True), unique=True, comment="Policia 1, 2, ...: el siguiente libre al crearlo."
    )
    activo: Mapped[bool] = mapped_column(TINYINT(1), default=1)
    creado_por_cuenta: Mapped[int | None] = mapped_column(
        ID,
        ForeignKey("usuarios_sistema.id", ondelete="RESTRICT"),
        comment="Cuenta de jefatura que lo dio de alta.",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


COMENTARIO_TABLA_POLICIA = (
    "Raciones de policias, registradas por el lector sin identidad: no estan en "
    "la base de turnos. Solo cuentan como racion en la columna Policias."
)


class RacionPolicia(Base):
    """Una ración servida a un policía. Sin persona: no aparece en historiales."""

    __tablename__ = "raciones_policia"
    __table_args__ = opciones(
        COMENTARIO_TABLA_POLICIA,
        Index("idx_raciones_policia_fecha_comida", "fecha_comida", "comida_id"),
        # Un policía por número recibe una ración por comida y día.
        UniqueConstraint("policia_id", "fecha_comida", "comida_id", name="uq_raciones_policia_policia_comida"),
        # Con huella (lector) o con nombre (checklist de cocina): nunca anónima.
        CheckConstraint("vinculo_id IS NOT NULL OR nombre IS NOT NULL", name="huella_o_nombre"),
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    fecha_comida: Mapped[date] = mapped_column(Date)
    comida_id: Mapped[int] = mapped_column(ID, comment="comidas.id de la base de turnos, sin FK.")
    categoria_reporte_id: Mapped[int] = mapped_column(
        ID,
        ForeignKey("categorias_reporte.id", ondelete="RESTRICT"),
        comment="Snapshot de la columna Policias al servir: un cambio de catalogo no reescribe meses.",
    )
    fecha_hora: Mapped[datetime] = mapped_column(INSTANTE)
    dispositivo: Mapped[str] = mapped_column(String(50), comment="El lector que la registro.")
    vinculo_id: Mapped[int | None] = mapped_column(
        ID, ForeignKey("vinculos_lector.id", ondelete="RESTRICT"),
        comment="La huella de policia que se leyo. NULL si cocina lo registro por nombre en el checklist.",
    )
    nombre: Mapped[str | None] = mapped_column(
        String(100), comment="Solo checklist: nombre del policia escrito por cocina (sin huella)."
    )
    policia_id: Mapped[int | None] = mapped_column(
        ID, ForeignKey("policias.id", ondelete="RESTRICT"),
        comment="El policia por numero marcado en el checklist. NULL en las raciones por huella o por nombre.",
    )
    lectura_id: Mapped[int | None] = mapped_column(
        ID, ForeignKey("lecturas_biometricas.id", ondelete="RESTRICT"), unique=True,
        comment=(
            "Solo si cocina identifico como policia una huella no reconocida: esa "
            "lectura. UNIQUE: una lectura da, como mucho, una racion."
        ),
    )
    registrado_por_cuenta: Mapped[int | None] = mapped_column(
        ID, ForeignKey("usuarios_sistema.id", ondelete="RESTRICT"),
        comment="La cocinera que identifico al policia. NULL si la leyo el lector.",
    )
    clave_idempotencia: Mapped[str | None] = mapped_column(
        CHAR(36), unique=True,
        comment="Idempotency-Key de la identificacion por cocina: un reintento no da dos raciones.",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
