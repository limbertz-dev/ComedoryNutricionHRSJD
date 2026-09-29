"""Modelos de datos.

Importar este paquete registra todas las tablas en `Base.metadata`. Alembic
depende de eso: si un modelo no está importado aquí, el autogenerate no lo ve
y la migración sale vacía.
"""

from app.modelos import comedor, heredados, reglas, usuarios  # noqa: F401
