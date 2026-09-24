"""Motor, sesión y bases declarativas de SQLAlchemy.

Un solo motor, contra `bd_nutricion`. La base de turnos no tiene motor
propio: se lee a través de las vistas v_* que viven en `bd_nutricion` (ver
app/core/tablas_heredadas.py). Así una misma consulta puede cruzar
`asistencias` con el padrón en un JOIN y en una sola transacción, cosa que
dos motores con `bind` separados no permiten.
"""

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends
from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import config

# Nombres predecibles para índices y restricciones. Alembic los necesita para
# poder deshacer una migración sin adivinar cómo se llama cada objeto.
CONVENCION_NOMBRES = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s",
    "pk": "pk_%(table_name)s",
}

motor = create_engine(config.url_base_datos, pool_pre_ping=True, future=True)

SesionLocal = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Tablas propias del comedor. Es la metadata que compara alembic."""

    metadata = MetaData(naming_convention=CONVENCION_NOMBRES)


class BaseContrato(DeclarativeBase):
    """Vistas v_* del contrato con la base de turnos. SOLO LECTURA.

    Metadata aparte a propósito: si compartieran `Base.metadata`, el
    autogenerate de alembic propondría un CREATE TABLE por cada vista y un
    `create_all` las crearía como tablas vacías.
    """

    metadata = MetaData()


def obtener_sesion() -> Generator[Session, None, None]:
    """Dependencia de FastAPI: una sesión por petición, siempre cerrada."""
    sesion = SesionLocal()
    try:
        yield sesion
    finally:
        sesion.close()


# Atajo para las firmas de los endpoints: `sesion: SesionDep`.
SesionDep = Annotated[Session, Depends(obtener_sesion)]
