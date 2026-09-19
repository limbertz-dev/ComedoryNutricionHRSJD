"""Retirar tablas y atributos obsoletos del comedor.

Revision ID: d4e5f6a7b8c9
Revises: 69862d9fda41
Create Date: 2026-09-11

La operacion borra datos de cupos manuales, autorizaciones digitales,
enrolamientos biometricos, cierres e informes archivados. La jefatura
confirmo que esas funciones no forman parte del flujo real del comedor.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "69862d9fda41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Las FK se retiran antes de las columnas y sus tablas destino.
    op.drop_constraint(
        "fk_asistencias_autorizacion_id", "asistencias", type_="foreignkey"
    )
    op.drop_column("asistencias", "autorizacion_id")
    op.drop_column("asistencias", "observacion")

    op.drop_constraint(
        "fk_lecturas_biometricas_huella_id",
        "lecturas_biometricas",
        type_="foreignkey",
    )
    op.drop_column("lecturas_biometricas", "huella_id")
    op.drop_column("lecturas_biometricas", "calidad")

    op.drop_constraint(
        "fk_coeficientes_racion_definido_por",
        "coeficientes_racion",
        type_="foreignkey",
    )
    op.drop_column("coeficientes_racion", "respaldo")
    op.drop_column("coeficientes_racion", "definido_por")

    op.alter_column(
        "lecturas_biometricas",
        "motivo",
        existing_type=sa.Enum(
            "duplicado",
            "sin_derecho",
            "fuera_horario",
            "sin_cupo",
            "no_identificado",
            name="motivo_rechazo",
        ),
        type_=sa.Enum(
            "duplicado",
            "sin_derecho",
            "fuera_horario",
            "no_identificado",
            name="motivo_rechazo",
        ),
        existing_nullable=True,
    )

    op.drop_table("cupos_racion")
    op.drop_table("autorizaciones_racion")
    op.drop_table("huellas_biometricas")
    op.drop_table("cierres_periodo")
    op.drop_table("informes_generados")


def downgrade() -> None:
    raise NotImplementedError(
        "Esta migracion elimina datos y tablas obsoletos de forma irreversible."
    )
