"""Prepara un entorno de simulación: una copia de la base de turnos y una bd_nutricion paralela.

    comedorback/.venv/Scripts/python scripts/preparar_simulacion.py        (pide confirmación)
    comedorback/.venv/Scripts/python scripts/preparar_simulacion.py --si   (sin preguntar)
    ... --semana-origen 2026-08-24 --dias 28 --demo bd_turnos_demo --sim bd_nutricion_sim

Pasos:

  0. Guardas y CHECKSUM TABLE de todas las tablas de la base de turnos
     (DB_NAME_TURNOS de comedorback/.env).
  1. Clona la base de turnos -> `bd_turnos_demo`: DDL con SHOW CREATE,
     datos con INSERT ... SELECT, vistas reescritas para leer la copia. Sobre
     el original solo se ejecutan SHOW y SELECT. La copia se verifica con
     CHECKSUM tabla por tabla.
  2. Desplaza la semana de origen (lunes a domingo) `--dias` días hacia
     adelante, SOLO en la copia. En `turnos_asignados` y
     `novedades_laborales` se desplazan las columnas DATE que el esquema real
     declare (se leen de information_schema, no están escritas acá), y solo
     los valores que caen en la semana. `semana_id` y `mes_id` quedan como
     están: la semana destino no existe en `semanas` y crearla sería
     inventar datos. Las vistas del comedor no exponen esas columnas.
  3. Crea `bd_nutricion_sim`: alembic upgrade head + semilla, en un proceso
     aparte con DB_NAME / DB_NAME_TURNOS apuntando a la simulación. Verifica
     que las 9 vistas v_* lean la copia y no el original: si la migración de
     vistas tuviera el nombre fijo, este paso lo detecta y aborta.
  4. Historial: NO se genera. En la fase 3 se carga por la API. Este paso
     solo cuenta, en solo lectura, los candidatos crudos de la semana destino
     según `v_comidas_por_turno`.
  5. CHECKSUM TABLE otra vez sobre el original; si algo cambió, aborta.

Idempotente: cada corrida borra y recrea las dos bases de simulación desde
el original, así que dos corridas dejan exactamente lo mismo. DESTRUCTIVO
solo para `--demo` y `--sim`, que tienen que terminar en `_demo` y `_sim`.
"""

import argparse
import hashlib
import os
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

RAIZ_BACK = Path(__file__).resolve().parents[1] / "comedorback"

os.chdir(RAIZ_BACK)
sys.path.insert(0, str(RAIZ_BACK))

from sqlalchemy import create_engine, text  # noqa: E402

from app.core.config import config  # noqa: E402
from app.core.tablas_heredadas import VISTAS_CONTRATO  # noqa: E402

BASES_DEL_SISTEMA = {"mysql", "sys", "information_schema", "performance_schema"}
TABLAS_A_DESPLAZAR = ("turnos_asignados", "novedades_laborales")
IDENTIFICADOR = re.compile(r"^[A-Za-z0-9_]+$")


def _salida_utf8() -> None:
    for flujo in (sys.stdout, sys.stderr):
        try:
            # line_buffering: si no, la salida de alembic y la semilla (proceso
            # hijo) aparece antes que los pasos previos de este script.
            flujo.reconfigure(encoding="utf-8", line_buffering=True)
        except (AttributeError, ValueError):
            pass


def _abortar(mensaje: str) -> None:
    print(f"ABORTADO: {mensaje}", file=sys.stderr)
    sys.exit(1)


def _existe(conexion, base: str) -> bool:
    return (
        conexion.execute(
            text("SELECT 1 FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = :b"),
            {"b": base},
        ).first()
        is not None
    )


def _tablas(conexion, base: str) -> list[str]:
    return list(
        conexion.execute(
            text(
                "SELECT TABLE_NAME FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = :b AND TABLE_TYPE = 'BASE TABLE' "
                "ORDER BY TABLE_NAME"
            ),
            {"b": base},
        ).scalars()
    )


def _guardas(servidor, origen: str, demo: str, sim: str) -> None:
    for nombre in (origen, demo, sim):
        if not IDENTIFICADOR.match(nombre):
            _abortar(f"nombre de base inválido: {nombre!r}")
    if not demo.endswith("_demo") or not sim.endswith("_sim"):
        _abortar("--demo tiene que terminar en '_demo' y --sim en '_sim'.")
    protegidas = {origen.lower(), config.db_name.lower(), "bd_proyecto_backend"}
    protegidas |= BASES_DEL_SISTEMA
    for nombre in (demo, sim):
        if nombre.lower() in protegidas:
            _abortar(f"'{nombre}' está protegida: este script nunca la borra.")
    if demo.lower() == sim.lower():
        _abortar("--demo y --sim no pueden ser la misma base.")

    with servidor.connect() as conexion:
        if not _existe(conexion, origen):
            _abortar(f"no existe la base de turnos '{origen}' (DB_NAME_TURNOS).")
        extras = conexion.execute(
            text(
                "SELECT 'trigger', TRIGGER_NAME FROM information_schema.TRIGGERS "
                "WHERE TRIGGER_SCHEMA = :b "
                "UNION ALL SELECT ROUTINE_TYPE, ROUTINE_NAME "
                "FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = :b "
                "UNION ALL SELECT 'event', EVENT_NAME "
                "FROM information_schema.EVENTS WHERE EVENT_SCHEMA = :b"
            ),
            {"b": origen},
        ).all()
    if extras:
        # El clon solo copia tablas y vistas. Si el módulo de turnos empieza a
        # usar triggers o rutinas, la copia quedaría incompleta sin avisar.
        _abortar(f"'{origen}' tiene objetos que este script no clona: {extras}")


def _checksums(conexion, base: str) -> dict[str, int | None]:
    tablas = _tablas(conexion, base)
    lista = ", ".join(f"`{base}`.`{t}`" for t in tablas)
    filas = conexion.execute(text(f"CHECKSUM TABLE {lista}")).all()
    return {nombre.split(".", 1)[1]: suma for nombre, suma in filas}


def _huella(sumas: dict[str, int | None]) -> str:
    """Un solo valor para comparar a ojo: sha256 de 'tabla:checksum' ordenado."""
    cuerpo = "\n".join(f"{t}:{s}" for t, s in sorted(sumas.items()))
    return hashlib.sha256(cuerpo.encode()).hexdigest()[:16]


def _describir_actual(servidor, demo: str, sim: str) -> None:
    with servidor.connect() as conexion:
        for base in (demo, sim):
            if not _existe(conexion, base):
                print(f"'{base}' no existe todavía.")
                continue
            print(f"'{base}' existe y se va a borrar ({len(_tablas(conexion, base))} tablas).")
        if _existe(conexion, sim) and "asistencias" in _tablas(conexion, sim):
            raciones = conexion.execute(
                text(f"SELECT COUNT(*) FROM `{sim}`.`asistencias`")
            ).scalar_one()
            if raciones:
                print(f"  ¡ATENCIÓN! {raciones} raciones en {sim}.asistencias se van a perder.")


def _confirmar(forzar: bool, origen: str, demo: str, sim: str) -> None:
    if forzar:
        return
    print(
        f"\nSe van a BORRAR y recrear '{demo}' y '{sim}' en "
        f"{config.db_host}:{config.db_port}. '{origen}' solo se lee."
    )
    if input("Escriba SIMULAR para confirmar: ").strip() != "SIMULAR":
        _abortar("la confirmación no coincide; no se tocó nada.")


def _clonar(servidor, origen: str, demo: str) -> dict[str, int]:
    filas_por_tabla: dict[str, int] = {}
    with servidor.connect() as conexion:
        # Lo que hace mysqldump: FKs apagadas para cargar en cualquier orden y
        # NO_AUTO_VALUE_ON_ZERO para que un id 0 no se convierta en otro. READ
        # COMMITTED evita que el INSERT ... SELECT deje locks compartidos
        # sobre las filas del original.
        conexion.execute(text("SET SESSION foreign_key_checks = 0"))
        conexion.execute(text("SET SESSION sql_mode = 'NO_AUTO_VALUE_ON_ZERO'"))
        conexion.execute(text("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED"))

        juego, cotejamiento = conexion.execute(
            text(
                "SELECT DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME "
                "FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = :b"
            ),
            {"b": origen},
        ).one()
        conexion.execute(text(f"DROP DATABASE IF EXISTS `{demo}`"))
        conexion.execute(
            text(f"CREATE DATABASE `{demo}` CHARACTER SET {juego} COLLATE {cotejamiento}")
        )
        conexion.execute(text(f"USE `{demo}`"))

        for tabla in _tablas(conexion, origen):
            # SHOW CREATE TABLE nombra la tabla y sus FKs sin base: bajo
            # `USE demo` todo queda dentro de la copia. exec_driver_sql para
            # que ni SQLAlchemy ni el driver interpreten ':' o '%' del DDL.
            ddl = conexion.execute(text(f"SHOW CREATE TABLE `{origen}`.`{tabla}`")).one()[1]
            conexion.exec_driver_sql(ddl)
            columnas = ", ".join(
                f"`{c}`"
                for c in conexion.execute(
                    text(
                        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                        "WHERE TABLE_SCHEMA = :b AND TABLE_NAME = :t "
                        "AND EXTRA NOT LIKE '%GENERATED%' ORDER BY ORDINAL_POSITION"
                    ),
                    {"b": origen, "t": tabla},
                ).scalars()
            )
            resultado = conexion.execute(
                text(
                    f"INSERT INTO `{demo}`.`{tabla}` ({columnas}) "
                    f"SELECT {columnas} FROM `{origen}`.`{tabla}`"
                )
            )
            filas_por_tabla[tabla] = resultado.rowcount

        vistas = conexion.execute(
            text(
                "SELECT TABLE_NAME FROM information_schema.VIEWS "
                "WHERE TABLE_SCHEMA = :b ORDER BY TABLE_NAME"
            ),
            {"b": origen},
        ).scalars().all()
        for vista in vistas:
            ddl = conexion.execute(text(f"SHOW CREATE VIEW `{origen}`.`{vista}`")).one()[1]
            ddl = re.sub(r"DEFINER=`[^`]*`@`[^`]*`\s*", "", ddl)
            ddl = ddl.replace(f"`{origen}`.", f"`{demo}`.")
            if f"`{origen}`" in ddl:
                _abortar(f"la vista {vista} sigue nombrando '{origen}' tras reescribirla.")
            conexion.exec_driver_sql(ddl)

        conexion.execute(text("SET SESSION foreign_key_checks = 1"))

    print(
        f"[1/5] '{demo}' clonada: {len(filas_por_tabla)} tablas, "
        f"{sum(filas_por_tabla.values())} filas, {len(vistas)} vista(s)."
    )
    return filas_por_tabla


def _verificar_clon(servidor, origen: str, demo: str) -> None:
    with servidor.connect() as conexion:
        original = _checksums(conexion, origen)
        copia = _checksums(conexion, demo)
    distintas = sorted(t for t in original if original[t] != copia.get(t))
    if distintas or set(original) != set(copia):
        _abortar(f"la copia no coincide con el original en: {distintas}")
    print(f"      CHECKSUM de la copia idéntico al original en las {len(copia)} tablas.")


def _desplazar(motor, demo: str, inicio: date, dias: int) -> dict[str, dict]:
    fin = inicio + timedelta(days=6)
    destino_ini, destino_fin = inicio + timedelta(days=dias), fin + timedelta(days=dias)
    rango = {"ini": inicio, "fin": fin}
    reporte: dict[str, dict] = {}

    with motor.begin() as conexion:
        for tabla in TABLAS_A_DESPLAZAR:
            columnas = conexion.execute(
                text(
                    "SELECT COLUMN_NAME, DATA_TYPE, EXTRA FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = :b AND TABLE_NAME = :t ORDER BY ORDINAL_POSITION"
                ),
                {"b": demo, "t": tabla},
            ).all()
            if not columnas:
                _abortar(f"'{demo}' no tiene la tabla {tabla}.")
            fechas = [c for c, tipo, _ in columnas if tipo == "date"]
            if not fechas:
                _abortar(f"{tabla} no tiene columnas DATE que desplazar.")
            # Un ON UPDATE CURRENT_TIMESTAMP pisaría la marca de tiempo real;
            # asignarla a sí misma lo impide.
            congeladas = [c for c, _, extra in columnas if "on update" in extra.lower()]

            por_columna = {}
            for c in fechas:
                n_origen, n_destino = conexion.execute(
                    text(
                        f"SELECT SUM(`{c}` BETWEEN :ini AND :fin), "
                        f"SUM(`{c}` BETWEEN :dini AND :dfin) FROM `{demo}`.`{tabla}`"
                    ),
                    {**rango, "dini": destino_ini, "dfin": destino_fin},
                ).one()
                if n_destino:
                    _abortar(
                        f"{tabla}.{c} ya tiene {n_destino} filas entre {destino_ini} y "
                        f"{destino_fin}: el desplazamiento las mezclaría. No se tocó nada."
                    )
                por_columna[c] = int(n_origen or 0)

            filas = 0
            if any(por_columna.values()):
                asignaciones = [
                    f"`{c}` = IF(`{c}` BETWEEN :ini AND :fin, `{c}` + INTERVAL :dias DAY, `{c}`)"
                    for c in fechas
                ] + [f"`{c}` = `{c}`" for c in congeladas]
                condicion = " OR ".join(f"`{c}` BETWEEN :ini AND :fin" for c in fechas)
                filas = conexion.execute(
                    text(
                        f"UPDATE `{demo}`.`{tabla}` SET {', '.join(asignaciones)} "
                        f"WHERE {condicion}"
                    ),
                    {**rango, "dias": dias},
                ).rowcount
            reporte[tabla] = {"filas": filas, "por_columna": por_columna}

    print(f"[2/5] Semana {inicio}..{fin} desplazada {dias} días -> {destino_ini}..{destino_fin}:")
    for tabla, datos in reporte.items():
        detalle = ", ".join(f"{c}={n}" for c, n in datos["por_columna"].items())
        print(f"        {tabla:<22} {datos['filas']} filas  ({detalle})")
    return reporte


def _crear_sim(servidor, demo: str, sim: str) -> None:
    with servidor.connect() as conexion:
        conexion.execute(text(f"DROP DATABASE IF EXISTS `{sim}`"))
        conexion.execute(
            text(f"CREATE DATABASE `{sim}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        )
    # Proceso aparte: la configuración se cachea al importarse, y las variables
    # de entorno le ganan al .env. Así alembic y la semilla ven la simulación
    # sin tocar comedorback/.env.
    entorno = {
        **os.environ,
        "DB_NAME": sim,
        "DB_NAME_TURNOS": demo,
        "PYTHONIOENCODING": "utf-8",
    }
    for paso in (["-m", "alembic", "upgrade", "head"], ["-m", "app.semillas"]):
        if subprocess.run([sys.executable, *paso], cwd=RAIZ_BACK, env=entorno).returncode:
            _abortar(f"falló '{' '.join(paso[1:])}' contra '{sim}'.")
    print(f"[3/5] '{sim}' creada: alembic upgrade head + semilla.")


def _verificar_vistas(servidor, origen: str, demo: str, sim: str) -> None:
    with servidor.connect() as conexion:
        definiciones = dict(
            conexion.execute(
                text(
                    "SELECT TABLE_NAME, VIEW_DEFINITION FROM information_schema.VIEWS "
                    "WHERE TABLE_SCHEMA = :b"
                ),
                {"b": sim},
            ).all()
        )
        if set(definiciones) != set(VISTAS_CONTRATO):
            _abortar(f"vistas inesperadas en '{sim}': {sorted(definiciones)}")
        mal = [
            v for v, d in definiciones.items() if f"`{origen}`" in d or f"`{demo}`" not in d
        ]
        if mal:
            _abortar(
                f"estas vistas de '{sim}' no leen '{demo}': {mal}. "
                "¿La migración de vistas tiene el nombre de la base fijo?"
            )
        for vista in VISTAS_CONTRATO:
            conexion.execute(text(f"SELECT 1 FROM `{sim}`.`{vista}` LIMIT 1")).all()
    print(f"      Las {len(definiciones)} vistas leen '{demo}' (DB_NAME_TURNOS), ninguna '{origen}'.")


def _historial_pendiente(servidor, sim: str, inicio: date, dias: int) -> None:
    """Fase 3 carga el historial por la API; acá no se escribe una sola ración.
    Solo se cuenta el insumo crudo, sin reglas de derecho, para saber qué va a
    encontrar la API en la semana destino."""
    destino_ini = inicio + timedelta(days=dias)
    destino_fin = destino_ini + timedelta(days=6)
    with servidor.connect() as conexion:
        filas = conexion.execute(
            text(
                f"SELECT fecha_comida, comida, COUNT(*) FROM `{sim}`.`v_comidas_por_turno` "
                "WHERE fecha_turno BETWEEN :i AND :f "
                "GROUP BY fecha_comida, comida_id, comida ORDER BY fecha_comida, comida_id"
            ),
            {"i": destino_ini, "f": destino_fin},
        ).all()
    print("[4/5] Historial NO generado (fase 3, vía API). Candidatos crudos en v_comidas_por_turno:")
    for fecha, comida, n in filas:
        print(f"        {fecha} {fecha:%a}  {comida:<12} {n}")
    if not filas:
        print("        (ninguno)")


def main() -> None:
    _salida_utf8()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--si", action="store_true", help="no pedir confirmación")
    parser.add_argument("--demo", default="bd_turnos_demo", help="copia de la base de turnos")
    parser.add_argument("--sim", default="bd_nutricion_sim", help="bd_nutricion de simulación")
    parser.add_argument(
        "--semana-origen",
        type=date.fromisoformat,
        default=date(2026, 8, 24),
        help="primer día (lunes) de la semana real a desplazar",
    )
    parser.add_argument("--dias", type=int, default=28, help="días hacia adelante")
    args = parser.parse_args()

    if args.dias <= 0 or args.dias % 7:
        _abortar("--dias tiene que ser un múltiplo positivo de 7 (mismo día de la semana).")

    origen = config.db_name_turnos.strip()
    servidor = create_engine(config.url_servidor, future=True, isolation_level="AUTOCOMMIT")
    transaccional = create_engine(config.url_servidor, future=True)
    try:
        _guardas(servidor, origen, args.demo, args.sim)
        with servidor.connect() as conexion:
            antes = _checksums(conexion, origen)
        print(f"[0/5] CHECKSUM '{origen}' antes: {_huella(antes)} ({len(antes)} tablas).")
        _describir_actual(servidor, args.demo, args.sim)
        _confirmar(args.si, origen, args.demo, args.sim)

        _clonar(servidor, origen, args.demo)
        _verificar_clon(servidor, origen, args.demo)
        _desplazar(transaccional, args.demo, args.semana_origen, args.dias)
        _crear_sim(servidor, args.demo, args.sim)
        _verificar_vistas(servidor, origen, args.demo, args.sim)
        _historial_pendiente(servidor, args.sim, args.semana_origen, args.dias)

        with servidor.connect() as conexion:
            despues = _checksums(conexion, origen)
        cambiadas = sorted(t for t in antes if antes[t] != despues.get(t))
        print(f"[5/5] CHECKSUM '{origen}' después: {_huella(despues)} ({len(despues)} tablas).")
        if cambiadas or set(antes) != set(despues):
            _abortar(f"'{origen}' cambió durante la corrida: {cambiadas}")
        print(f"      Idéntico: '{origen}' no se modificó.")
    finally:
        servidor.dispose()
        transaccional.dispose()
    print(f"\nListo: '{args.demo}' + '{args.sim}' preparadas para la simulación.")


if __name__ == "__main__":
    main()
