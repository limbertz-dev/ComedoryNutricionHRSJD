"""Motor, sesión y base declarativa de SQLAlchemy."""

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
    metadata = MetaData(naming_convention=CONVENCION_NOMBRES)


def obtener_sesion() -> Generator[Session, None, None]:
    """Dependencia de FastAPI: una sesión por petición, siempre cerrada."""
    sesion = SesionLocal()
    try:
        yield sesion
    finally:
        sesion.close()


# Atajo para las firmas de los endpoints: `sesion: SesionDep`.
SesionDep = Annotated[Session, Depends(obtener_sesion)]
