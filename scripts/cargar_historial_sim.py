"""Carga el historial de la semana simulada POR LA API, como lo dejaría el uso real.

    comedorback/.venv/Scripts/python scripts/cargar_historial_sim.py
    ... --porcentaje 80 --desde 2026-09-21 --hasta 2026-09-23 --solo-programados
    ... --api http://127.0.0.1:8100 --usuario jefa

Requiere haber corrido scripts/preparar_simulacion.py y una API levantada
contra la simulación (DB_NAME=bd_nutricion_sim, DB_NAME_TURNOS=bd_turnos_demo):
se verifica con /salud antes de marcar nada. La cuenta tiene que ser de
jefatura (la marcación manual es solo suya) y ya tener la clave temporal
cambiada: un 428 aborta. La clave se lee de CARGA_HISTORIAL_CLAVE o se pide
por consola; ni ella ni el token se imprimen o se guardan.

Cada ración es un POST /asistencias {usuario_id, metodo: manual, momento}, lo
mismo que registra la jefatura a mano: la API aplica las reglas de siempre
(horario, duplicado, derecho). Las bases solo se LEEN, para elegir candidatos
y verificar; no se escribe una sola fila por SQL.

Pasos:

  0. CHECKSUM TABLE del original (`--original`) y guardas: el rango no puede
     tocar la demo en vivo (24-27/09) y no puede tener raciones ya cargadas.
  1. Candidatos: `v_comidas_por_turno` con las reglas de derecho de la API
     (`aplicar_reglas`, app/consultas/derecho.py), uno por (persona, comida,
     fecha) como la clave única de `asistencias`; queda la asignación más
     antigua, la misma que elige `buscar_derecho`. Su `estado` (programado,
     bloqueado...) sale de `v_turnos_asignados`. Las reglas actuales NO miran
     el estado; --solo-programados descarta el resto antes de elegir.
  2. Selección determinista, por fecha_comida: se ordena por
     sha256('fecha|comida_id|usuario_id') y se toman round(n * porcentaje/100)
     (redondeo hacia arriba en .5). Misma base, mismos parámetros: mismas filas.
  3. Momento determinista: franja vigente de `horarios_comida` para esa comida
     y fecha; minuto = sha256('momento|fecha|comida_id|usuario_id') módulo los
     minutos enteros de la franja, contado desde hora_inicio. hora_fin queda
     fuera, igual que en la API.
  4. Ingreso por /auth/login, un POST por ración, conteo de aceptadas y de
     rechazadas por motivo.
  5. Verificación en solo lectura: raciones por fecha en `--sim`, ninguna en la
     demo en vivo; CHECKSUM otra vez sobre el original.
"""

import argparse
import getpass
import hashlib
import os
from collections import Counter
from datetime import date, datetime, time, timedelta

parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("--api", default="http://127.0.0.1:8100", help="API contra la simulación")
parser.add_argument("--usuario", default="jefa", help="cuenta de jefatura (clave: CARGA_HISTORIAL_CLAVE)")
parser.add_argument("--porcentaje", type=int, default=80, help="del total de candidatos de cada día")
parser.add_argument("--desde", type=date.fromisoformat, default=date(2026, 9, 21), help="fecha_comida inicial")
parser.add_argument("--hasta", type=date.fromisoformat, default=date(2026, 9, 23), help="fecha_comida final")
estados = parser.add_mutually_exclusive_group()
estados.add_argument(
    "--incluir-bloqueados",
    dest="solo_programados",
    action="store_false",
    help="candidatos según las reglas actuales, sin mirar el estado (por defecto)",
)
estados.add_argument(
    "--solo-programados",
    dest="solo_programados",
    action="store_true",
    help="solo asignaciones en estado 'programado'",
)
# Explícito: con dos acciones sobre el mismo dest, argparse toma el default
# del store_false (True) y el modo por defecto quedaría invertido.
parser.set_defaults(solo_programados=False)
parser.add_argument("--sim", default="bd_nutricion_sim")
parser.add_argument("--demo", default="bd_turnos_demo")
parser.add_argument("--original", default="bd_proyecto_backend")
args = parser.parse_args()

# Antes de importar la app: la configuración se lee una sola vez al importar.
# Este proceso no sirve la API, solo lee las bases de simulación.
os.environ.update(ENTORNO="desarrollo", DB_NAME=args.sim, DB_NAME_TURNOS=args.demo)

from preparar_simulacion import _abortar, _checksums, _huella, _salida_utf8  # noqa: E402

import httpx  # noqa: E402
from sqlalchemy import create_engine, or_, select, text  # noqa: E402

from app.consultas.derecho import aplicar_reglas  # noqa: E402
from app.core.config import config  # noqa: E402
from app.core.db import SesionLocal  # noqa: E402
from app.modelos.comedor import HorarioComida  # noqa: E402
from app.modelos.heredados import ComidaPorTurno, TurnoAsignado  # noqa: E402

# Días que se marcan en vivo durante la demo: este script no los toca nunca.
DEMO_EN_VIVO = (date(2026, 9, 24), date(2026, 9, 27))


def _sha(texto: str) -> int:
    return int(hashlib.sha256(texto.encode()).hexdigest()[:16], 16)


def _desde_medianoche(valor) -> timedelta:
    # MySQL TIME puede llegar como time o como timedelta según el driver.
    if isinstance(valor, time):
        return timedelta(hours=valor.hour, minutes=valor.minute, seconds=valor.second)
    return valor


def _guardas() -> None:
    if not (args.sim.endswith("_sim") and args.demo.endswith("_demo")):
        _abortar("--sim tiene que terminar en '_sim' y --demo en '_demo'; nunca las bases reales.")
    if args.hasta < args.desde:
        _abortar("--hasta es anterior a --desde.")
    if args.desde <= DEMO_EN_VIVO[1] and args.hasta >= DEMO_EN_VIVO[0]:
        _abortar(f"el rango toca la demo en vivo ({DEMO_EN_VIVO[0]} a {DEMO_EN_VIVO[1]}).")
    if not 0 < args.porcentaje <= 100:
        _abortar("--porcentaje tiene que estar entre 1 y 100.")


def _candidatos(sesion) -> list[dict]:
    consulta = (
        aplicar_reglas(
            select(
                ComidaPorTurno.fecha_comida,
                ComidaPorTurno.comida_id,
                ComidaPorTurno.comida,
                ComidaPorTurno.usuario_id,
                ComidaPorTurno.turno_asignado_id,
                TurnoAsignado.estado,
            )
            .select_from(ComidaPorTurno)
            .join(TurnoAsignado, TurnoAsignado.id == ComidaPorTurno.turno_asignado_id)
        )
        .where(ComidaPorTurno.fecha_comida.between(args.desde, args.hasta))
        .order_by(
            ComidaPorTurno.fecha_comida,
            ComidaPorTurno.comida_id,
            ComidaPorTurno.usuario_id,
            ComidaPorTurno.turno_asignado_id,
        )
    )
    unicos: dict[tuple, dict] = {}
    for fila in sesion.execute(consulta).mappings():
        unicos.setdefault((fila["usuario_id"], fila["comida_id"], fila["fecha_comida"]), dict(fila))
    return list(unicos.values())


def _seleccionar(candidatos: list[dict]) -> list[dict]:
    por_dia: dict[date, list[dict]] = {}
    for c in candidatos:
        por_dia.setdefault(c["fecha_comida"], []).append(c)
    elegidos = []
    for fecha in sorted(por_dia):
        grupo = sorted(
            por_dia[fecha], key=lambda c: _sha(f"{fecha}|{c['comida_id']}|{c['usuario_id']}")
        )
        cuantos = (len(grupo) * args.porcentaje * 2 + 100) // 200
        elegidos.extend(grupo[:cuantos])
    return sorted(elegidos, key=lambda c: (c["fecha_comida"], c["comida_id"], c["usuario_id"]))


def _franja(sesion, comida_id: int, fecha: date) -> tuple[timedelta, timedelta]:
    """La misma franja que usaría resolver_comida_en_curso ese día."""
    fila = sesion.execute(
        select(HorarioComida.hora_inicio, HorarioComida.hora_fin)
        .where(HorarioComida.comida_id == comida_id)
        .where(HorarioComida.activo == 1)
        .where(HorarioComida.vigente_desde <= fecha)
        .where(or_(HorarioComida.vigente_hasta.is_(None), HorarioComida.vigente_hasta >= fecha))
        .order_by(HorarioComida.vigente_desde.desc())
        .limit(1)
    ).first()
    if fila is None:
        _abortar(f"sin horario vigente para la comida {comida_id} el {fecha}.")
    return _desde_medianoche(fila[0]), _desde_medianoche(fila[1])


def _momento(sesion, c: dict) -> datetime:
    inicio, fin = _franja(sesion, c["comida_id"], c["fecha_comida"])
    duracion = (fin - inicio) % timedelta(days=1)  # franjas que cruzan la medianoche
    minutos = int(duracion.total_seconds() // 60)
    if minutos <= 0:
        _abortar(f"franja vacía para la comida {c['comida_id']}.")
    desfase = _sha(f"momento|{c['fecha_comida']}|{c['comida_id']}|{c['usuario_id']}") % minutos
    return datetime.combine(c["fecha_comida"], time()) + inicio + timedelta(minutes=desfase)


def _ingresar(cliente: httpx.Client) -> dict:
    salud = cliente.get("/salud")
    datos = salud.json() if salud.status_code == 200 else {}
    if (datos.get("base_datos"), datos.get("base_turnos")) != (args.sim, args.demo):
        _abortar(
            f"la API en {args.api} no apunta a {args.sim}/{args.demo} "
            f"(/salud {salud.status_code}: {datos.get('base_datos')}/{datos.get('base_turnos')})."
        )
    clave = os.environ.get("CARGA_HISTORIAL_CLAVE") or getpass.getpass(f"Clave de '{args.usuario}': ")
    r = cliente.post("/auth/login", json={"username": args.usuario, "password": clave})
    del clave
    if r.status_code == 428:
        # El cuerpo trae el token temporal: no se imprime.
        _abortar(f"'{args.usuario}' tiene la clave temporal pendiente: cambiarla primero en el front.")
    if r.status_code != 200:
        _abortar(f"no se pudo ingresar como '{args.usuario}': {r.status_code} {r.json().get('motivo')}")
    if r.json()["rol"] != "jefa":
        _abortar(f"'{args.usuario}' no es de jefatura: la marcación manual es solo suya.")
    return {"Authorization": f"Bearer {r.json()['access']}"}


def _raciones_por_fecha(conexion) -> dict[date, int]:
    filas = conexion.execute(
        text(f"SELECT fecha_comida, COUNT(*) FROM `{args.sim}`.`asistencias` GROUP BY fecha_comida")
    ).all()
    return dict(filas)


def main() -> None:
    _salida_utf8()
    _guardas()
    servidor = create_engine(config.url_servidor, future=True, isolation_level="AUTOCOMMIT")
    try:
        with servidor.connect() as conexion:
            antes = _checksums(conexion, args.original)
            previas = _raciones_por_fecha(conexion)
        print(f"[0/5] CHECKSUM '{args.original}' antes: {_huella(antes)} ({len(antes)} tablas).")
        ya = {f: n for f, n in previas.items() if args.desde <= f <= args.hasta}
        if ya:
            _abortar(f"{args.sim} ya tiene raciones en el rango: {ya}. Regenerar con preparar_simulacion.py.")

        with SesionLocal() as sesion:
            candidatos = _candidatos(sesion)
            usados = [c for c in candidatos if c["estado"] == "programado"] if args.solo_programados else candidatos
            elegidos = _seleccionar(usados)
            for c in elegidos:
                c["momento"] = _momento(sesion, c)

        modo = "solo programados" if args.solo_programados else "incluye bloqueados (reglas actuales)"
        print(
            f"[1/5] {len(candidatos)} candidatos con derecho entre {args.desde} y {args.hasta}; "
            f"estado: {dict(Counter(c['estado'] for c in candidatos))}. Modo: {modo} -> {len(usados)}."
        )
        print(f"      Por día: {dict(Counter(str(c['fecha_comida']) for c in usados))}")
        print(
            f"[2/5] {len(elegidos)} elegidos ({args.porcentaje}% por día, orden sha256); "
            f"estado: {dict(Counter(c['estado'] for c in elegidos))}."
        )
        print("[3/5] Momento: hora_inicio + sha256 % minutos de la franja vigente.")

        resultados: Counter = Counter()
        por_dia: Counter = Counter()
        with httpx.Client(base_url=args.api, timeout=30) as cliente:
            cabecera = _ingresar(cliente)
            print(f"[4/5] Ingreso como '{args.usuario}' (jefa). POST /asistencias manual:")
            for c in elegidos:
                r = cliente.post(
                    "/asistencias",
                    json={"usuario_id": c["usuario_id"], "metodo": "manual", "momento": c["momento"].isoformat()},
                    headers=cabecera,
                )
                cuerpo = r.json()
                if r.status_code != 200:
                    motivo = f"http_{r.status_code}"
                elif not cuerpo["valido"]:
                    motivo = cuerpo["motivo"]
                elif (cuerpo["comida_id"], cuerpo["fecha_comida"]) != (c["comida_id"], str(c["fecha_comida"])):
                    motivo = "otra_comida"  # aceptada, pero no la que se buscaba
                else:
                    motivo = "aceptada"
                    por_dia[str(c["fecha_comida"])] += 1
                resultados[motivo] += 1
                print(
                    f"        {c['fecha_comida']} {c['comida']:<9} usuario {c['usuario_id']:>5} "
                    f"{c['estado']:<10} {c['momento']:%H:%M} -> {motivo}"
                )
        print(f"      Resultado: {dict(resultados)}; aceptadas por día: {dict(por_dia)}")

        with servidor.connect() as conexion:
            finales = _raciones_por_fecha(conexion)
            despues = _checksums(conexion, args.original)
        en_vivo = {f: n for f, n in finales.items() if DEMO_EN_VIVO[0] <= f <= DEMO_EN_VIVO[1]}
        print(f"[5/5] {args.sim}.asistencias por fecha_comida: {{{', '.join(f'{f}: {n}' for f, n in sorted(finales.items()))}}}")
        print(f"      Demo en vivo ({DEMO_EN_VIVO[0]} a {DEMO_EN_VIVO[1]}): {sum(en_vivo.values())} raciones.")
        cambiadas = sorted(t for t in antes if antes[t] != despues.get(t))
        print(f"      CHECKSUM '{args.original}' después: {_huella(despues)} ({len(despues)} tablas).")
        if cambiadas or set(antes) != set(despues):
            _abortar(f"'{args.original}' cambió durante la carga: {cambiadas}")
        if en_vivo:
            _abortar(f"hay raciones en la demo en vivo: {en_vivo}")
        print(f"      Idéntico: '{args.original}' no se modificó.")
    finally:
        servidor.dispose()


if __name__ == "__main__":
    main()
