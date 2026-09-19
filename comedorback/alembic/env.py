"""Entorno de Alembic.

Regla no negociable de este proyecto: las migraciones administran ÚNICAMENTE
las tablas nuevas del comedor. Las 36 tablas heredadas del módulo de turnos
quedan fuera de la comparación (ver app/core/tablas_heredadas.py).

Sin ese filtro, el primer `revision --autogenerate` emitiría un DROP TABLE por
cada tabla del otro ingeniero, porque no están declaradas en nuestros modelos.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import app.modelos  # noqa: F401  registra las tablas en Base.metadata
from app.core.config import config as config_app
from app.core.db import Base
from app.core.tablas_heredadas import TABLAS_HEREDADAS, VISTAS_HEREDADAS

config = context.config
config.set_main_option("sqlalchemy.url", config_app.url_base_datos)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _es_heredada(tabla) -> bool:
    if tabla is None:
        return False
    if tabla.name in TABLAS_HEREDADAS or tabla.name in VISTAS_HEREDADAS:
        return True
    return bool(tabla.info.get("heredada"))


def incluir_objeto(objeto, nombre, tipo, reflejado, comparar_con) -> bool:
    """Deja fuera del autogenerate todo lo que no pertenezca al comedor.

    El filtro va a nivel de tabla Y de columna: sin lo segundo, las dos columnas
    que este sistema agrega a `comidas` volverían a aparecer en cada migración,
    porque están declaradas en el modelo pero su tabla está excluida.
    """
    if tipo == "table":
        return not _es_heredada(objeto)
    if tipo in ("column", "index", "unique_constraint", "foreign_key_constraint"):
        return not _es_heredada(getattr(objeto, "table", None))
    return True


def ejecutar_migraciones_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=incluir_objeto,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def ejecutar_migraciones_online() -> None:
    conectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with conectable.connect() as conexion:
        context.configure(
            connection=conexion,
            target_metadata=target_metadata,
            include_object=incluir_objeto,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    ejecutar_migraciones_offline()
else:
    ejecutar_migraciones_online()
