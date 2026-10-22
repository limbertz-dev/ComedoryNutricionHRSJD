"""Tablas del lector biométrico real.

El lector no conoce el padrón: entrega el identificador con el que enroló a
la persona (el número de usuario de una terminal, o el id de plantilla que
devuelve el programa de un lector USB). `vinculos_lector` lo traduce a
`users.id`. `solicitudes_lector` guarda cada envío por su Idempotency-Key,
para que un reintento del puente no escriba una segunda lectura.
"""

from datetime import datetime

from sqlalchemy import CHAR, JSON, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.modelos.comedor import ID, opciones

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
        Index("idx_vinculos_lector_usuario", "usuario_id"),
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    identificador: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        comment="Numero de usuario o id de plantilla con que el lector enrolo la huella.",
    )
    usuario_id: Mapped[int] = mapped_column(
        ID, comment="users.id de la base de turnos (v_comensales), sin FK entre bases."
    )
    activo: Mapped[bool] = mapped_column(TINYINT(1), default=1)
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
    lectura_id: Mapped[int] = mapped_column(
        ID, ForeignKey("lecturas_biometricas.id", ondelete="RESTRICT")
    )
    respuesta: Mapped[dict] = mapped_column(
        JSON, comment="Respuesta enviada al lector, para repetirla ante un reintento."
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
