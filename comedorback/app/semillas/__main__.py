"""Corre todas las semillas, en orden. Cada una es idempotente.

Ejecutar con:  python -m app.semillas

Requiere la base migrada (`alembic upgrade head`): las semillas leen las
vistas v_* para resolver ids de la base de turnos y escriben SOLO en tablas
propias de bd_nutricion.
"""

from app.semillas import coeficientes, cuentas_iniciales, horarios, mapeo_categorias

SEMILLAS = [
    ("horarios de comida", horarios),
    ("coeficientes de ración", coeficientes),
    ("mapeo de categorías", mapeo_categorias),
    ("cuentas iniciales (root, jefa, cocinera)", cuentas_iniciales),
]


def main() -> None:
    for nombre, modulo in SEMILLAS:
        print(f"-- {nombre}")
        modulo.sembrar()


if __name__ == "__main__":
    main()
