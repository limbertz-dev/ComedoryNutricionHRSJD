"""alinear collation con las tablas heredadas

Revision ID: 69862d9fda41
Revises: 63e8e2d4d7f9
Create Date: 2026-09-09

Corrige un choque de collations que rompía los informes.

Las tablas del módulo de turnos usan `utf8mb4_unicode_ci`, que es la convención
de Laravel. La base, en cambio, tiene `utf8mb4_0900_ai_ci` por defecto. Nuestras
11 tablas se crearon sin especificar nada, así que tomaron el default de la base
y quedaron con una collation distinta a la de las tablas con las que se juntan.

MySQL no compara texto entre collations distintas. El síntoma fue este, al
calcular el equivalente en raciones completas:

    (1267) Illegal mix of collations
    (utf8mb4_0900_ai_ci,IMPLICIT) and (utf8mb4_unicode_ci,IMPLICIT)

El JOIN que falla es `coeficientes_racion.grupo = comidas.grupo_coeficiente`:
la primera es nuestra, la segunda vive en una tabla heredada y hereda SU
collation. Cualquier otro JOIN por texto contra el módulo de turnos habría
fallado igual.

Los modelos ya declaran la collation correcta, así que las tablas que se creen
de aquí en adelante nacen bien. Esta migración arregla las que ya existen.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "69862d9fda41"
down_revision: Union[str, Sequence[str], None] = "63e8e2d4d7f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLAS = [
    "asistencias",
    "autorizaciones_racion",
    "categoria_reporte_map",
    "categorias_reporte",
    "cierres_periodo",
    "coeficientes_racion",
    "cupos_racion",
    "horarios_comida",
    "huellas_biometricas",
    "informes_generados",
    "lecturas_biometricas",
]


def _convertir(collation: str) -> None:
    for tabla in TABLAS:
        op.execute(
            f"ALTER TABLE `{tabla}` CONVERT TO CHARACTER SET utf8mb4 COLLATE {collation}"
        )


def upgrade() -> None:
    _convertir("utf8mb4_unicode_ci")


def downgrade() -> None:
    _convertir("utf8mb4_0900_ai_ci")
