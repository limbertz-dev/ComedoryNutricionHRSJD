"""Versiones de los parámetros del derecho a comer, en `bd_nutricion`.

Cada cambio es una fila nueva con `vigente_desde` hoy o futuro; nunca se
edita ni se borra una versión ya vigente o pasada, para que informes e
historial de días pasados no cambien. Solo se puede borrar una versión
programada (`vigente_desde` mayor a hoy).

La versión vigente para una fecha es la de `vigente_desde` máximo menor o
igual a esa fecha. El derecho la resuelve EN SQL por `fecha_turno` (ver
`aplicar_reglas` en app/consultas/derecho.py), fila por fila, sin bucles.
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.modelos.comedor import ID, opciones


class ReglaDerecho(Base):
    """Una versión de los parámetros del derecho: turno mínimo, novedades y enfermería."""

    __tablename__ = "reglas_derecho"
    __table_args__ = opciones(
        "Versiones de los parámetros del derecho a comer. Cada cambio es una "
        "fila nueva vigente desde una fecha; nunca se edita ni se borra el pasado.",
        UniqueConstraint(
            "vigente_desde", name="uq_reglas_derecho_vigente_desde"
        ),
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    vigente_desde: Mapped[date] = mapped_column(
        Date,
        comment=(
            "Desde qué fecha rige esta versión, inclusive. Nunca hacia atrás: "
            "tiene que ser hoy o futuro al crearla."
        ),
    )
    duracion_minima_horas: Mapped[int] = mapped_column(
        Integer,
        comment="Turno mínimo en horas para tener derecho. Política del hospital.",
    )
    excluir_enfermeria: Mapped[bool] = mapped_column(
        TINYINT(1),
        comment=(
            "1 = enfermería queda fuera del derecho y del padrón; 0 = incluida."
        ),
    )
    motivo: Mapped[str] = mapped_column(
        String(500),
        comment="Por qué se creó esta versión. Obligatorio, 10 o más caracteres.",
    )
    creada_por_cuenta: Mapped[int | None] = mapped_column(
        ID,
        ForeignKey("usuarios_sistema.id", ondelete="RESTRICT"),
        comment=(
            "usuarios_sistema.id de la cuenta root que la creó. FK interna: "
            "las cuentas se dan de baja, no se borran. NULL solo en la versión base."
        ),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ReglaDerechoNovedad(Base):
    """Qué novedades anulan el derecho en una versión de `reglas_derecho`."""

    __tablename__ = "reglas_derecho_novedad"
    __table_args__ = opciones(
        "Novedades que anulan el derecho, por versión de reglas_derecho. "
        "Una fila por (versión, tipo).",
        UniqueConstraint(
            "regla_id",
            "tipo_novedad",
            name="uq_reglas_derecho_novedad_regla_id_tipo_novedad",
        ),
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    regla_id: Mapped[int] = mapped_column(
        ID,
        ForeignKey("reglas_derecho.id", ondelete="CASCADE"),
        comment=(
            "reglas_derecho.id a la que pertenece. Si se borra una versión "
            "programada, se borran sus novedades."
        ),
    )
    tipo_novedad: Mapped[str] = mapped_column(
        String(30),
        comment=(
            "Tipo de novedad laboral que anula el derecho en esta versión "
            "(v_novedades_laborales.tipo_novedad)."
        ),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
