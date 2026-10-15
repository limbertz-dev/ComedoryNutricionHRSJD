"""Habilita cocinera2 y cocinera3 en el escenario sintético. SOLO en
bd_nutricion_escenario_sim / bd_turnos_escenario_demo, a través de la API del
escenario en http://127.0.0.1:8765.

Lo corre el OPERADOR en su consola privada, desde comedorback:

    .venv\\Scripts\\python ..\\qa\\habilitar_cocineras_escenario.py
    (--solo-comprobar: solo verifica destino, API, cuentas y manifiesto; no escribe)

Por cada cuenta:
  1. Comprueba que existe en la base del escenario con rol cocinera y sin
     vínculo con el padrón. No crea cuentas.
  2. La resetea con app.semillas.admin. La clave temporal NO se muestra: el
     script la usa una sola vez para el primer ingreso (428).
  3. Pide la contraseña definitiva sin eco (dos veces) y la fija con
     POST /auth/cambio-password usando el token temporal.
  4. Verifica por HTTP: login 200, rol cocinera, debe_cambiar=false,
     GET /auth/yo y GET /personal/900001/derecho?fecha=2026-10-15.

Ninguna contraseña ni token se imprime, se guarda ni se escribe en un log.
No registra raciones, no identifica lecturas y no cambia reglas.
"""

import contextlib
import getpass
import io
import json
import os
import sys
import urllib.error
import urllib.request

API = "http://127.0.0.1:8765"
SIM, DEMO, REVISION = "bd_nutricion_escenario_sim", "bd_turnos_escenario_demo", "e1a7c3b9d5f2"
CUENTAS = ("cocinera2", "cocinera3")
FECHA, PRINCIPAL, ALMUERZO = "2026-10-15", 900001, 2
MANIFIESTO = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "manifiesto_escenario_2026-10-15.json")

# Las bases del escenario, ANTES de importar la configuración del backend.
os.environ.update({"ENTORNO": "simulacion", "DB_NAME": SIM, "DB_NAME_TURNOS": DEMO})
sys.path.insert(0, os.getcwd())


def abortar(mensaje: str) -> None:
    print(f"ABORTADO: {mensaje}")
    sys.exit(1)


def http(metodo, ruta, cuerpo=None, token=None):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    peticion = urllib.request.Request(API + ruta, data=datos, method=metodo)
    peticion.add_header("Content-Type", "application/json")
    if token:
        peticion.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(peticion, timeout=30) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except ValueError:
            return e.code, None
    except urllib.error.URLError as e:
        abortar(f"la API del escenario no responde en {API}: {e.reason}")


def main() -> None:
    if not os.path.isfile(os.path.join(os.getcwd(), "app", "semillas", "admin.py")):
        abortar("corra el script desde comedorback.")
    from sqlalchemy import select

    from app.core.config import config
    from app.core.db import SesionLocal
    from app.modelos.usuarios import UsuarioSistema
    from app.semillas import admin

    if (config.entorno, config.db_name, config.db_name_turnos) != ("simulacion", SIM, DEMO):
        abortar(f"destino inesperado: {config.entorno} {config.db_name}/{config.db_name_turnos}")
    estado, salud = http("GET", "/salud")
    if not (estado == 200 and salud.get("entorno") == "simulacion" and salud.get("base_datos") == SIM
            and salud.get("base_turnos") == DEMO and salud.get("revision_alembic") == REVISION):
        abortar(f"la API de {API} no es la del escenario: HTTP {estado} {salud}")
    print(f"Destino verificado: {SIM} / {DEMO}, API {API} en {REVISION}.")

    with SesionLocal() as sesion:
        filas = {u.username: u for u in sesion.execute(
            select(UsuarioSistema).where(UsuarioSistema.username.in_(CUENTAS))).scalars()}
        for nombre in CUENTAS:
            u = filas.get(nombre)
            if u is None or u.rol != "cocinera" or u.usuario_turnos_id is not None:
                abortar(f"'{nombre}' no existe en {SIM} como cocinera sin vínculo: no se crea ni se toca.")

    with open(MANIFIESTO, encoding="utf-8") as f:
        manifiesto = json.load(f)
    esperado = manifiesto["derecho_principal"]
    if "--solo-comprobar" in sys.argv:
        print("--solo-comprobar: destino, API, cuentas y manifiesto en orden. No se tocó nada.")
        return

    claves: dict[str, str] = {}
    for nombre in CUENTAS:
        print(f"\n--- {nombre} ---")
        nueva = getpass.getpass(f"Contraseña definitiva para {nombre} (mín. 8, no se muestra): ")
        if getpass.getpass("Repítala: ") != nueva:
            abortar(f"las contraseñas de {nombre} no coinciden. No se cambió nada de {nombre}.")
        if nueva in claves.values():
            abortar("cada cuenta es independiente: use contraseñas distintas.")
        # El reseteo imprime la temporal: se descarta esa salida.
        with contextlib.redirect_stdout(io.StringIO()):
            temporal = admin.sembrar(nombre, "cocinera", resetear=True)
        if not temporal:
            abortar(f"no se pudo resetear {nombre}.")
        estado, cuerpo = http("POST", "/auth/login", {"username": nombre, "password": temporal})
        if estado != 428 or not (cuerpo or {}).get("temporal"):
            abortar(f"{nombre}: el primer ingreso respondió HTTP {estado}, se esperaba 428.")
        estado, cuerpo = http("POST", "/auth/cambio-password", {"password_nueva": nueva},
                              token=cuerpo["temporal"])
        temporal = None
        if estado != 200:
            abortar(f"{nombre}: cambio de contraseña HTTP {estado}: {(cuerpo or {}).get('detail')}")
        claves[nombre] = nueva
        print(f"{nombre}: contraseña definitiva fijada.")

    print("\n=== Verificación por HTTP (sin credenciales en pantalla) ===")
    ok = True
    for nombre in CUENTAS:
        estado, cuerpo = http("POST", "/auth/login", {"username": nombre, "password": claves[nombre]})
        cuerpo = cuerpo or {}
        login_ok = estado == 200 and cuerpo.get("rol") == "cocinera" and cuerpo.get("debe_cambiar") is False
        est_yo, yo = http("GET", "/auth/yo", token=cuerpo.get("access"))
        yo = yo or {}
        yo_ok = est_yo == 200 and yo.get("username") == nombre and yo.get("rol") == "cocinera" \
            and yo.get("debe_cambiar") is False
        est_d, derechos = http("GET", f"/personal/{PRINCIPAL}/derecho?fecha={FECHA}", token=cuerpo.get("access"))
        almuerzo = [d for d in (derechos if isinstance(derechos, list) else [])
                    if d.get("comida_id") == ALMUERZO and d.get("fecha_comida") == FECHA]
        derecho_ok = (est_d == 200 and bool(almuerzo) == esperado["obtenido"]
                      and [d["comida_id"] for d in derechos] == esperado["derechos_del_dia"]
                      and (not almuerzo or almuerzo[0]["turno_asignado_id"]
                           == esperado["turno_asignado_que_lo_justifica"]))
        print(f"{nombre}: login HTTP {estado}, rol {cuerpo.get('rol')}, debe_cambiar "
              f"{cuerpo.get('debe_cambiar')} -> {'VERDE' if login_ok else 'ROJO'}")
        print(f"{nombre}: /auth/yo HTTP {est_yo}, {yo.get('username')}, rol {yo.get('rol')}, "
              f"debe_cambiar {yo.get('debe_cambiar')} -> {'VERDE' if yo_ok else 'ROJO'}")
        print(f"{nombre}: derecho de {PRINCIPAL} el {FECHA}: HTTP {est_d}, comidas "
              f"{[d.get('comida_id') for d in derechos] if isinstance(derechos, list) else derechos}, "
              f"turno {almuerzo[0]['turno_asignado_id'] if almuerzo else None}; manifiesto: "
              f"{esperado['derechos_del_dia']}, turno {esperado['turno_asignado_que_lo_justifica']}"
              f" -> {'VERDE' if derecho_ok else 'ROJO'}")
        ok = ok and login_ok and yo_ok and derecho_ok
    claves.clear()
    print("\nRESULTADO:", "VERDE: ambas cuentas habilitadas" if ok else "ROJO: revisar las filas de arriba")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
