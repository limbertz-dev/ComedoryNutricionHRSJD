"""Entorno de Alembic.

Regla no negociable de este proyecto: las migraciones corren SOLO contra
`bd_nutricion` (DB_NAME) y administran ÚNICAMENTE lo propio del comedor: las
6 tablas y las 9 vistas v_* del contrato de lectura. La base de turnos
(DB_NAME_TURNOS) nunca es destino de una migración: las vistas la leen, nada
la escribe.

Filtros del autogenerate (ver app/core/tablas_heredadas.py):

  · Las 36 tablas heredadas y la vista vw_* del módulo de turnos quedan
    fuera. Ya no existen en bd_nutricion, pero si alguien apunta alembic a
    una copia vieja que las tenga, sin el filtro el autogenerate emitiría un
    DROP TABLE por cada tabla del otro ingeniero.
  · Las vistas v_* también quedan fuera: se administran a mano en su propia
    migración (0c294cd98c3a), porque el autogenerate no entiende vistas.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import app.modelos  # noqa: F401  registra las tablas en Base.metadata
from app.core.config import config as config_app
from app.core.db import Base
from app.core.tablas_heredadas import (
    TABLAS_HEREDADAS,
    VISTAS_CONTRATO,
    VISTAS_HEREDADAS,
)

config = context.config
config.set_main_option("sqlalchemy.url", config_app.url_base_datos)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _es_heredada(tabla) -> bool:
    if tabla is None:
        return False
    if (
        tabla.name in TABLAS_HEREDADAS
        or tabla.name in VISTAS_HEREDADAS
        or tabla.name in VISTAS_CONTRATO
    ):
        return True
    return bool(tabla.info.get("heredada"))


def incluir_objeto(objeto, nombre, tipo, reflejado, comparar_con) -> bool:
    """Deja fuera del autogenerate todo lo que no pertenezca al comedor.

    El filtro va a nivel de tabla Y de columna: si una tabla queda excluida,
    sus columnas, índices y FKs también, o reaparecerían sueltos en la
    migración siguiente.
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
