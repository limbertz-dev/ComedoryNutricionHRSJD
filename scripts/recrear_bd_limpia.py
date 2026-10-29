"""Recrea `bd_nutricion` desde cero: DROP + alembic + vistas + semilla.

    comedorback/.venv/Scripts/python scripts/recrear_bd_limpia.py        (pide confirmación)
    comedorback/.venv/Scripts/python scripts/recrear_bd_limpia.py --si   (sin preguntar)

Pasos, todos contra la base de DB_NAME (comedorback/.env):

  1. Guardas: DB_NAME no puede ser DB_NAME_TURNOS ni una base del sistema,
     y la base de turnos tiene que existir (las vistas la leen).
  2. DROP DATABASE IF EXISTS + CREATE DATABASE (utf8mb4_unicode_ci, la
     collation de las tablas del módulo de turnos).
  3. alembic upgrade head: las 16 tablas propias, las columnas del
     formulario y las 9 vistas v_*.
  4. Verificación: están las 16 tablas y las 9 vistas, y cada vista responde.
  5. Semilla: python -m app.semillas (horarios, coeficientes, mapeo y las
     cuentas iniciales root, jefa y cocinera, con clave nombre+2026 que se
     cambia en el primer ingreso).

Idempotente: correrlo dos veces deja la base igual. DESTRUCTIVO para
DB_NAME: borra todo lo que tenga, incluidas las asistencias y las cuentas de
usuarios_sistema. Sobre la base de
turnos NO emite nada más que los SELECT de las vistas: ni DROP, ni ALTER, ni
CREATE, ni INSERT. El nombre de la base de turnos nunca aparece en un DROP.
"""

import argparse
import os
import sys
from pathlib import Path

RAIZ_BACK = Path(__file__).resolve().parents[1] / "comedorback"

# La configuración lee `.env` y alembic lee `alembic.ini` desde el directorio
# de trabajo: todo se resuelve como si se corriera dentro de comedorback/.
os.chdir(RAIZ_BACK)
sys.path.insert(0, str(RAIZ_BACK))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.core.config import config  # noqa: E402

BASES_DEL_SISTEMA = {"mysql", "sys", "information_schema", "performance_schema"}


def _salida_utf8() -> None:
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def _abortar(mensaje: str) -> None:
    print(f"ABORTADO: {mensaje}", file=sys.stderr)
    sys.exit(1)


def _guardas(servidor) -> None:
    propia = config.db_name.strip()
    turnos = config.db_name_turnos.strip()
    # Config ya rechaza DB_NAME == DB_NAME_TURNOS al cargar; se repite acá
    # porque este script es el único que hace DROP y no cuesta nada.
    if not propia or "`" in propia:
        _abortar(f"DB_NAME inválido: {propia!r}")
    if propia.lower() in {turnos.lower(), "bd_proyecto_backend"} | BASES_DEL_SISTEMA:
        _abortar(f"'{propia}' está protegida: este script nunca la borra.")

    with servidor.connect() as conexion:
        existe_turnos = conexion.execute(
            text("SELECT 1 FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = :b"),
            {"b": turnos},
        ).first()
    if existe_turnos is None:
        _abortar(
            f"no existe la base de turnos '{turnos}' (DB_NAME_TURNOS). "
            "Sin ella las vistas no se pueden crear; no se borró nada."
        )


def _describir_actual(servidor) -> None:
    with servidor.connect() as conexion:
        objetos = conexion.execute(
            text(
                "SELECT TABLE_TYPE, COUNT(*) FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = :b GROUP BY TABLE_TYPE"
            ),
            {"b": config.db_name},
        ).all()
        raciones = None
        if objetos:
            tiene = conexion.execute(
                text(
                    "SELECT 1 FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA = :b AND TABLE_NAME = 'asistencias'"
                ),
                {"b": config.db_name},
            ).first()
            if tiene:
                raciones = conexion.execute(
                    text(f"SELECT COUNT(*) FROM `{config.db_name}`.`asistencias`")
                ).scalar_one()
    if not objetos:
        print(f"'{config.db_name}' no existe o está vacía.")
        return
    resumen = ", ".join(f"{n} {tipo.lower()}" for tipo, n in objetos)
    print(f"'{config.db_name}' hoy tiene: {resumen}.")
    if raciones:
        print(f"  ¡ATENCIÓN! {raciones} raciones en asistencias se van a perder.")


def _confirmar(forzar: bool) -> None:
    if forzar:
        return
    print(
        f"\nSe va a BORRAR y recrear '{config.db_name}' en "
        f"{config.db_host}:{config.db_port}. '{config.db_name_turnos}' no se toca."
    )
    respuesta = input("Escriba el nombre de la base para confirmar: ").strip()
    if respuesta != config.db_name:
        _abortar("la confirmación no coincide; no se borró nada.")


def _recrear(servidor) -> None:
    nombre = config.db_name
    with servidor.connect() as conexion:
        conexion.execute(text(f"DROP DATABASE IF EXISTS `{nombre}`"))
        conexion.execute(
            text(
                f"CREATE DATABASE `{nombre}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        )
    print(f"[1/4] '{nombre}' borrada y creada vacía.")


def _migrar() -> None:
    command.upgrade(Config(str(RAIZ_BACK / "alembic.ini")), "head")
    print("[2/4] alembic upgrade head: tablas, columnas del formulario y vistas.")


def _verificar() -> None:
    import app.modelos  # noqa: F401  registra las tablas propias
    from app.core.db import Base, motor
    from app.core.tablas_heredadas import VISTAS_CONTRATO

    with motor.connect() as conexion:
        objetos = conexion.execute(
            text(
                "SELECT TABLE_NAME, TABLE_TYPE FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE()"
            )
        ).all()
        tablas = {n for n, t in objetos if t == "BASE TABLE"} - {"alembic_version"}
        vistas = {n for n, t in objetos if t == "VIEW"}
        esperadas = set(Base.metadata.tables)
        if tablas != esperadas or vistas != set(VISTAS_CONTRATO):
            _abortar(
                f"esquema inesperado. Tablas: {sorted(tablas ^ esperadas)} / "
                f"vistas: {sorted(vistas ^ set(VISTAS_CONTRATO))}"
            )
        conteos = {
            v: conexion.execute(text(f"SELECT COUNT(*) FROM `{v}`")).scalar_one()
            for v in VISTAS_CONTRATO
        }
    print(f"[3/4] {len(tablas)} tablas + {len(vistas)} vistas. Filas por vista:")
    for vista, n in conteos.items():
        print(f"        {vista:<24} {n}")


def _sembrar() -> None:
    from app.semillas.__main__ import main as sembrar

    print("[4/4] semilla:")
    sembrar()


def main() -> None:
    _salida_utf8()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--si", action="store_true", help="no pedir confirmación")
    args = parser.parse_args()

    servidor = create_engine(config.url_servidor, future=True, isolation_level="AUTOCOMMIT")
    try:
        _guardas(servidor)
        _describir_actual(servidor)
        _confirmar(args.si)
        _recrear(servidor)
    finally:
        servidor.dispose()
    _migrar()
    _verificar()
    _sembrar()
    print(f"\nListo: '{config.db_name}' recreada desde cero.")


if __name__ == "__main__":
    main()
