"""Validación inmediata del derecho en el escenario sintético de cocina.

NO es «solo lectura»: cada login con una cocinera escribe su auditoría de
acceso (`intentos_login`). Fuera de eso, solo hay SELECT en las bases del
escenario y GET a la API. NO llama a POST /asistencias ni a /identificar, NO
cambia claves y NO escribe reglas. Raciones, lecturas e intervenciones tienen
que seguir en cero.

Lo corre la sesión de A1, que ya tiene la conexión. Las claves se leen de
variables de entorno y nunca se imprimen ni se pasan a otra sesión:

    DB_HOST, DB_PORT, DB_USER, DB_PASSWORD          (obligatorias)
    CLAVE_COCINERA2, CLAVE_COCINERA3                (opcionales: sin ellas, el
                                                     paso autenticado queda PENDIENTE)

    <python del venv de comedorback> qa/validar_derecho_escenario.py \\
        --manifiesto <manifiesto real> --back <ruta a comedorback> [--api http://127.0.0.1:8000]

Fecha y ventana: salen del MANIFIESTO, no de la hora real. El derecho se
consulta con `fecha=` explícita y no depende del reloj.

Estados: VERDE, ROJO o PENDIENTE (no se pudo comprobar en esta corrida o hay
que cotejarlo a mano). Salida: 0 sin ROJO; 1 con algún ROJO o un aborto.
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path

SIM = "bd_nutricion_escenario_sim"
DEMO = "bd_turnos_escenario_demo"
CABEZA_ALEMBIC = "e1a7c3b9d5f2"
ALMUERZO = 2
PRINCIPAL = 900001
CONTRASTE = 900007
NEGATIVOS = {
    900002: "turno de 8 h (control adicional de duración)",
    900003: "categoría Enfermería, turno de 12 h",
    900004: "turno de 12 h sin turno_comida",
    900005: "novedad 'permiso' guardada, turno de 12 h",
    900006: "asignación al día siguiente, turno de 12 h",
}
IDS = [PRINCIPAL, *NEGATIVOS, CONTRASTE]
COCINERAS = (("cocinera2", "CLAVE_COCINERA2"), ("cocinera3", "CLAVE_COCINERA3"))

VERDE, ROJO, PENDIENTE = "VERDE", "ROJO", "PENDIENTE"


# --- paso interno: el derecho con el código del servidor, en las bases del escenario ---

def paso_derecho(fecha: date) -> None:
    """Corre en un subproceso con cwd=comedorback y DB_NAME/DB_NAME_TURNOS del
    escenario. Usa app/consultas/derecho.py, el mismo que usa GET
    /personal/{id}/derecho. Solo SELECT."""
    sys.path.insert(0, os.getcwd())
    from app.consultas import derecho
    from app.core.config import config
    from app.core.db import SesionLocal

    if (config.db_name, config.db_name_turnos) != (SIM, DEMO):
        raise SystemExit(f"destino inesperado: {config.db_name}/{config.db_name_turnos}")
    salida = {"bases": [config.db_name, config.db_name_turnos], "casos": {}}
    with SesionLocal() as sesion:
        for uid in IDS:
            salida["casos"][uid] = derecho.buscar_derecho(sesion, uid, ALMUERZO, fecha) is not None
        sesion.rollback()
    print(json.dumps(salida))


# --- utilidades -----------------------------------------------------------------

def http(metodo, url, token=None, cuerpo=None):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    peticion = urllib.request.Request(url, data=datos, method=metodo)
    peticion.add_header("Content-Type", "application/json")
    if token:
        peticion.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(peticion, timeout=15) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except ValueError:
            return e.code, None
    except urllib.error.URLError as e:
        return None, str(e.reason)


def conteos(conexion, text) -> dict:
    ids = ", ".join(map(str, IDS))
    q = lambda sql: conexion.execute(text(sql)).scalar_one()  # noqa: E731
    return {
        "asistencias": q(f"SELECT COUNT(*) FROM `{SIM}`.asistencias WHERE usuario_id IN ({ids})"),
        "lecturas": q(f"SELECT COUNT(*) FROM `{SIM}`.lecturas_biometricas"),
        "intervenciones": q(f"SELECT COUNT(*) FROM `{SIM}`.intervenciones_lectura"),
        "reglas_derecho": [
            [str(c) for c in f] for f in conexion.execute(text(
                f"SELECT id, vigente_desde, duracion_minima_horas, excluir_enfermeria "
                f"FROM `{SIM}`.reglas_derecho ORDER BY vigente_desde, id")).all()
        ],
        "reglas_derecho_novedad": [
            [str(c) for c in f] for f in conexion.execute(text(
                f"SELECT regla_id, tipo_novedad FROM `{SIM}`.reglas_derecho_novedad "
                f"ORDER BY regla_id, tipo_novedad")).all()
        ],
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--manifiesto", type=Path)
    p.add_argument("--back", type=Path, help="carpeta comedorback del código del escenario")
    p.add_argument("--api", default="http://127.0.0.1:8000")
    p.add_argument("--paso-derecho", type=date.fromisoformat, help=argparse.SUPPRESS)
    a = p.parse_args()

    if a.paso_derecho:
        paso_derecho(a.paso_derecho)
        return 0
    if not a.manifiesto or not a.back:
        print("ABORTA: faltan --manifiesto y --back.")
        return 1

    filas = []

    def anotar(paso, esperado, obtenido, estado):
        filas.append((paso, str(esperado), str(obtenido), estado))

    def si(cond):
        return VERDE if cond else ROJO

    # Como el preparador: DB_PASSWORD puede estar definida y vacía (root de Laragon).
    faltan = [v for v in ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD") if v not in os.environ]
    if faltan:
        print("ABORTA: faltan variables de conexión: " + ", ".join(faltan))
        return 1

    # 1. El manifiesto describe ESTE destino. Fecha y ventana salen de él.
    m = json.loads(a.manifiesto.read_text(encoding="utf-8"))
    bases = m.get("bases", {})
    anotar("M1 manifiesto: bases", f"{SIM} / {DEMO}",
           f"{bases.get('propia')} / {bases.get('turnos_sintetica')}",
           si(bases.get("propia") == SIM and bases.get("turnos_sintetica") == DEMO))
    fecha = date.fromisoformat(m["fecha"])
    ventana = m.get("ventana") or []
    ventana_ok = (len(ventana) == 1
                  and datetime.fromisoformat(ventana[0][0]).date() == fecha
                  and datetime.fromisoformat(ventana[0][0]) < datetime.fromisoformat(ventana[0][1]))
    anotar("M2 manifiesto: fecha y ventana del almuerzo", "una ventana, el día de la fecha",
           f"fecha {fecha}, ventana {ventana}", si(ventana_ok))
    rev = m.get("revision", {})
    anotar("M3 manifiesto: revisión del código", "commit conocido, sin cambios sin commit",
           f"{rev.get('commit')} ({rev.get('rama')}), sin commit: {rev.get('cambios_sin_commit_en_el_codigo')}",
           si(rev.get("commit") not in (None, "desconocido") and not rev.get("cambios_sin_commit_en_el_codigo")))

    # 2. La API consultada apunta al MISMO destino.
    estado, salud = http("GET", f"{a.api}/salud")
    salud = salud if isinstance(salud, dict) else {}
    anotar("A1 API /salud: destino", f"simulacion, {SIM}, {DEMO}, {CABEZA_ALEMBIC}",
           f"HTTP {estado}: {salud.get('entorno')}, {salud.get('base_datos')}, "
           f"{salud.get('base_turnos')}, {salud.get('revision_alembic')}",
           si(estado == 200 and salud.get("entorno") == "simulacion"
              and salud.get("base_datos") == SIM and salud.get("base_turnos") == DEMO
              and salud.get("revision_alembic") == CABEZA_ALEMBIC))
    if estado is None:  # no hay API levantada: no es un fallo del destino, es un paso no hecho
        filas[-1] = (filas[-1][0], filas[-1][1], f"sin API en {a.api}", PENDIENTE)
    api_ok = filas[-1][3] == VERDE

    # 3. Conteos y reglas ANTES.
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import URL

    motor = create_engine(URL.create(
        "mysql+pymysql", username=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"],
        host=os.environ["DB_HOST"], port=int(os.environ["DB_PORT"])))
    with motor.connect() as c:
        antes = conteos(c, text)
    anotar("P1 raciones / lecturas / intervenciones (antes)", "0 / 0 / 0",
           f"{antes['asistencias']} / {antes['lecturas']} / {antes['intervenciones']}",
           si(antes["asistencias"] == antes["lecturas"] == antes["intervenciones"] == 0))
    # Regla vigente para la fecha, comparada campo a campo con el manifiesto.
    rm = m.get("regla_vigente") or {}
    vigentes = [f for f in antes["reglas_derecho"] if date.fromisoformat(f[1][:10]) <= fecha]
    vigente = vigentes[-1] if vigentes else None
    if vigente is None or not rm:
        anotar("P2 regla vigente: base = manifiesto", rm, vigente, PENDIENTE)
    else:
        anulan = sorted(t for rid, t in antes["reglas_derecho_novedad"] if rid == vigente[0])
        base = {"id": int(vigente[0]), "vigente_desde": vigente[1][:10],
                "duracion_minima_horas": int(vigente[2]),
                "excluir_enfermeria": vigente[3] in ("1", "True"), "novedades_que_anulan": anulan}
        esperado = {k: rm.get(k) for k in base}
        esperado["novedades_que_anulan"] = sorted(esperado["novedades_que_anulan"] or [])
        anotar("P2 regla vigente: base = manifiesto", esperado, base, si(base == esperado))

    # 4. Cuentas: estado según el manifiesto.
    for cuenta in m.get("cuentas", []):
        anotar(f"P3 cuenta {cuenta.get('username')} (manifiesto)",
               "rol cocinera, activa, sin vínculo",
               {k: cuenta.get(k) for k in ("id", "rol", "activo", "debe_cambiar", "vinculo_padron")},
               si(cuenta.get("rol") == "cocinera" and cuenta.get("activo")
                  and not cuenta.get("vinculo_padron")))

    # 5. Derecho con el código del servidor sobre las bases del escenario (sin login).
    entorno = {**os.environ, "ENTORNO": "simulacion", "DB_NAME": SIM, "DB_NAME_TURNOS": DEMO,
               "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--paso-derecho", fecha.isoformat()],
                       cwd=a.back, env=entorno, capture_output=True, text=True, encoding="utf-8")
    medido = json.loads(r.stdout.strip().splitlines()[-1])["casos"] if r.returncode == 0 else None
    if medido is None:
        anotar("D0 derecho con app/consultas/derecho.py", "se calcula", r.stderr.strip()[-300:], ROJO)

    manifiesto_obt = {PRINCIPAL: m["derecho_principal"]["obtenido"]}
    for n in m.get("controles_12h_no_bastan", []) + m.get("control_adicional_duracion", []):
        manifiesto_obt[n["usuario_id"]] = n["derecho_obtenido"]
    contraste = m.get("contraste_novedad", {})
    manifiesto_obt[CONTRASTE] = contraste.get("sin_novedad", {}).get("derecho_al_almuerzo")

    for uid in IDS:
        esperado = uid in (PRINCIPAL, CONTRASTE)
        nombre = ("principal (usuariosimulado)" if uid == PRINCIPAL else
                  "contraste, sin novedad persistida" if uid == CONTRASTE else NEGATIVOS[uid])
        txt = "con almuerzo" if esperado else "sin almuerzo"
        if medido is not None:
            obt = medido[str(uid)]
            anotar(f"D {uid} {nombre}: código del servidor", txt,
                   "con almuerzo" if obt else "sin almuerzo", si(obt == esperado))
        anotar(f"D {uid}: manifiesto (derecho obtenido)", txt, manifiesto_obt.get(uid),
               si(manifiesto_obt.get(uid) == esperado))

    # Contraste: el rechazo CON novedad es de la transacción revertida del preparador.
    con = contraste.get("con_novedad", {}).get("derecho_al_almuerzo")
    anotar("D 900007 con novedad 'permiso' (transacción revertida del preparador)",
           "sin almuerzo; la novedad no queda guardada",
           f"con novedad: {con}; persistida: {contraste.get('novedad_persistida_tras_revertir')}",
           si(con is False and contraste.get("novedad_persistida_tras_revertir") is not None
              and not contraste.get("novedad_persistida_tras_revertir")))

    # 6. Comprobación autenticada por HTTP, con cada cocinera.
    for usuario, variable in COCINERAS:
        clave = os.environ.get(variable)
        if not clave:
            anotar(f"H login {usuario}", "200, rol cocinera", "sin clave en esta sesión: cuenta no habilitada", PENDIENTE)
            continue
        if not api_ok:
            anotar(f"H login {usuario}", "200, rol cocinera", "no se intenta: la API no apunta al escenario", PENDIENTE)
            continue
        estado, cuerpo = http("POST", f"{a.api}/auth/login", cuerpo={"username": usuario, "password": clave})
        cuerpo = cuerpo if isinstance(cuerpo, dict) else {}
        if estado == 428:
            anotar(f"H login {usuario}", "200, rol cocinera", "428: cambio de clave pendiente", PENDIENTE)
            continue
        if estado != 200 or cuerpo.get("rol") != "cocinera":
            anotar(f"H login {usuario}", "200, rol cocinera", f"HTTP {estado}, {cuerpo.get('motivo')}", ROJO)
            continue
        anotar(f"H login {usuario}", "200, rol cocinera", "200, rol cocinera", VERDE)
        for uid in IDS:
            esperado = uid in (PRINCIPAL, CONTRASTE)
            est, cuerpo2 = http("GET", f"{a.api}/personal/{uid}/derecho?fecha={fecha}", cuerpo["access"])
            obt = est == 200 and any(d["comida_id"] == ALMUERZO and d["fecha_comida"] == fecha.isoformat()
                                     for d in cuerpo2)
            anotar(f"H {usuario} GET /personal/{uid}/derecho", "con almuerzo" if esperado else "sin almuerzo",
                   f"HTTP {est}, " + ("con almuerzo" if obt else "sin almuerzo"),
                   si(est == 200 and obt == esperado))

    # 7. Conteos y reglas DESPUÉS.
    with motor.connect() as c:
        despues = conteos(c, text)
    anotar("P4 raciones / lecturas / intervenciones (después)", "0 / 0 / 0",
           f"{despues['asistencias']} / {despues['lecturas']} / {despues['intervenciones']}",
           si(despues["asistencias"] == despues["lecturas"] == despues["intervenciones"] == 0))
    anotar("P5 reglas sin cambios (antes = después)", "iguales",
           "iguales" if (antes["reglas_derecho"], antes["reglas_derecho_novedad"]) ==
           (despues["reglas_derecho"], despues["reglas_derecho_novedad"]) else "CAMBIARON",
           si((antes["reglas_derecho"], antes["reglas_derecho_novedad"]) ==
              (despues["reglas_derecho"], despues["reglas_derecho_novedad"])))

    print("| Paso | Esperado | Obtenido | Estado |\n|---|---|---|---|")
    for paso, esp, obt, est in filas:
        print(f"| {paso} | {esp} | {obt} | {est} |")
    print("\nNo comprobado acá: la huella CHECKSUM de las bases protegidas (antes y después).")
    return 1 if any(f[3] == ROJO for f in filas) else 0


if __name__ == "__main__":
    sys.exit(main())
