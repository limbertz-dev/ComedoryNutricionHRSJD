"""Migración aditiva exclusiva del escenario QA; conserva cuentas y contraseñas."""
import argparse
import importlib.util

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

import comun as c

ANTERIOR = "e1a7c3b9d5f2"
ACTUAL = "8d4a2b7c9f10"


def actualizar(conn, aplicar=False):
    revision = conn.scalar(text("SELECT version_num FROM alembic_version"))
    columna = conn.execute(text(
        "SELECT DATA_TYPE, IS_NULLABLE FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA=:base AND TABLE_NAME='usuarios_sistema' AND COLUMN_NAME='eliminada_en'"
    ), {"base": c.SIM}).one_or_none()
    if columna is not None and tuple(columna) != ("datetime", "YES"):
        raise c.Abortado("La columna de baja lógica tiene un contrato incompatible")
    if revision == ACTUAL:
        if columna is None:
            raise c.Abortado("La revisión no coincide con el esquema de cuentas")
        print("Esquema de cuentas ya actualizado; no se modifican datos.")
        return
    if revision != ANTERIOR:
        raise c.Abortado("Revisión incompatible para actualizar cuentas")
    if not aplicar:
        print("Simulacro: añadir eliminada_en y actualizar revisión; no se escribe nada.")
        return
    if columna is None:
        ruta = c.RAIZ / "comedorback/alembic/versions/8d4a2b7c9f10_baja_logica_cuentas.py"
        spec = importlib.util.spec_from_file_location("baja_logica_cuentas", ruta)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        with Operations.context(MigrationContext.configure(conn)):
            modulo.upgrade()
    # Si MySQL confirmó el DDL antes de una interrupción, la repetición solo sella la revisión.
    resultado = conn.execute(text(
        "UPDATE alembic_version SET version_num=:actual WHERE version_num=:anterior"
    ), {"actual": ACTUAL, "anterior": ANTERIOR})
    if resultado.rowcount != 1:
        raise c.Abortado("No se pudo confirmar la revisión de cuentas")
    conn.commit()
    print("Baja lógica habilitada. Cuentas, contraseñas e historial conservados.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aplicar", action="store_true")
    args = parser.parse_args()
    permitidas = c.permisos(
        (c.SIM, "usuarios_sistema", "ADD_ELIMINADA_EN"),
        (c.SIM, "alembic_version", "UPDATE"),
    )
    with c.bloqueo_corrida(), c.entorno_seguro(permitidas, revisiones=(ANTERIOR, ACTUAL)) as (motor, _, _):
        with motor.connect() as conn:
            actualizar(conn, args.aplicar)


if __name__ == "__main__":
    c.ejecutar(main)
