"""Cuentas propias del sistema y bitácora de intentos de ingreso.

Son tablas de `bd_nutricion`, no de la base de turnos: las cuentas del
comedor (jefa, cocinera, sistemas) no son los `users` del otro ingeniero y no
se les escribe nada allá. Si algún día el ingreso se valida contra otro sistema del hospital o
contra `users`, lo que cambia es `verificar_credenciales()` en
app/logica/autenticacion.py; estas tablas siguen guardando el rol y la
bitácora.
"""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.permisos import ROLES
from app.modelos.comedor import ID, opciones

RESULTADOS_LOGIN = ("exitoso", "fallido", "bloqueado")


class UsuarioSistema(Base):
    """Una cuenta que puede ingresar al sistema del comedor."""

    __tablename__ = "usuarios_sistema"
    __table_args__ = opciones(
        "Cuentas propias del comedor. NO son los users de la base de turnos. "
        "La clave se guarda solo como hash bcrypt.",
        UniqueConstraint(
            "usuario_turnos_id", name="uq_usuarios_sistema_usuario_turnos_id"
        ),
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    username: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        comment="Siempre en minusculas y sin espacios en los extremos.",
    )
    password_hash: Mapped[str] = mapped_column(String(255))
    rol: Mapped[str] = mapped_column(SAEnum(*ROLES, name="rol_sistema"))
    debe_cambiar: Mapped[bool] = mapped_column(
        TINYINT(1),
        default=1,
        comment="1 = clave temporal: el ingreso solo habilita el cambio de clave.",
    )
    activo: Mapped[bool] = mapped_column(TINYINT(1), default=1)
    eliminada_en: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, deferred=True,
        comment="Baja lógica: oculta la cuenta sin borrar su identidad ni registros. UTC.",
    )
    version_token: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment=(
            "Va dentro de cada token. Cambiar la clave la incrementa y "
            "anula todas las sesiones abiertas."
        ),
    )
    usuario_turnos_id: Mapped[int | None] = mapped_column(
        ID,
        comment=(
            "users.id del padron al que esta vinculada la cuenta, sin FK. "
            "NULL = cuenta sin vinculo, creada a mano."
        ),
    )
    nombre: Mapped[str | None] = mapped_column(
        String(100),
        comment="Nombre a mano, solo para las cuentas sin vinculo.",
    )
    creada_por_cuenta: Mapped[int | None] = mapped_column(
        ID,
        ForeignKey("usuarios_sistema.id", ondelete="RESTRICT"),
        comment=(
            "usuarios_sistema.id de la cuenta root que la creo. FK interna: "
            "las cuentas se dan de baja, no se borran."
        ),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class IntentoLogin(Base):
    """Cada intento de ingreso, exista o no el usuario.

    El bloqueo no se guarda como un estado en la cuenta: se deriva de esta
    bitácora (ver `bloqueado_hasta()`). Un contador en la cuenta habría que
    resetearlo a mano y no dejaría rastro de quién lo intentó ni cuándo.
    """

    __tablename__ = "intentos_login"
    __table_args__ = opciones(
        "Bitacora de ingresos. El bloqueo por intentos fallidos se deriva de "
        "aqui; se registra tambien el username que no existe.",
        Index("idx_intentos_login_username_fecha", "username", "fecha_hora"),
    )

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    username: Mapped[str] = mapped_column(
        String(50), comment="Lo que se tipeo, normalizado. Puede no existir."
    )
    resultado: Mapped[str] = mapped_column(
        SAEnum(*RESULTADOS_LOGIN, name="resultado_login"),
        comment="bloqueado = llego con la cuenta bloqueada; no se verifico la clave.",
    )
    ip: Mapped[str | None] = mapped_column(String(45))
    fecha_hora: Mapped[datetime] = mapped_column(DateTime)
