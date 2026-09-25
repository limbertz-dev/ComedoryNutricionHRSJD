"""Escenario demo del modo simulación: fija el reloj y marca una ración real.

    comedorback/.venv/Scripts/python scripts/demo_reloj.py
    ... --usuario 2040 --momento 2026-09-24T12:30 --conservar

Requiere haber corrido scripts/preparar_simulacion.py. Corre la API EN
PROCESO (TestClient) con ENTORNO=simulacion contra `--sim` / `--demo`: la
configuración no deja arrancar la simulación contra las bases reales.

Pasos:

  0. CHECKSUM TABLE de la base de turnos original (`--original`).
  1. Cuenta temporal de rol sistemas en `--sim` e ingreso por /auth/login.
  2. PUT /simulacion/reloj en `--momento`; /salud tiene que decir simulado.
  3. POST /asistencias biométrico de `--usuario`, SIN hora: la pone el
     reloj. Tiene que ser válida y dejar su fila en `asistencias`.
  4. POST /simulacion/reloj/proxima-franja y DELETE /simulacion/reloj.
  5. Limpieza (salvo --conservar): la ración, su lectura y la cuenta
     temporal. Así el historial que carga la fase 3 no arrastra la demo.
  6. CHECKSUM otra vez sobre el original; si algo cambió, aborta.

Por defecto, el candidato verificado del 24/09: usuario 2040, asignación
7467, TARDE/32, estado 'programado' (también en el original) y sin novedades.
"""

import argparse
import os
import secrets
import sys
from datetime import datetime

parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("--usuario", type=int, default=2040)
parser.add_argument("--momento", type=datetime.fromisoformat, default=datetime(2026, 9, 24, 12, 30))
parser.add_argument("--sim", default="bd_nutricion_sim")
parser.add_argument("--demo", default="bd_turnos_demo")
parser.add_argument("--original", default="bd_proyecto_backend")
parser.add_argument("--conservar", action="store_true", help="no borrar lo que crea la demo")
args = parser.parse_args()

# Antes de importar la app: la configuración se lee una sola vez al importar,
# y las variables de entorno le ganan al .env. El secreto JWT es de este
# proceso: los tokens no salen de acá.
os.environ.update(ENTORNO="simulacion", DB_NAME=args.sim, DB_NAME_TURNOS=args.demo)
os.environ.setdefault("AUTH_JWT_SECRETO", secrets.token_urlsafe(48))

from preparar_simulacion import _abortar, _checksums, _huella, _salida_utf8  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.core import seguridad  # noqa: E402
from app.core.config import config  # noqa: E402
from app.core.db import SesionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.modelos.usuarios import UsuarioSistema  # noqa: E402


def _cuenta_temporal() -> tuple[str, str]:
    username = f"demo_reloj_{secrets.token_hex(3)}"
    clave = secrets.token_urlsafe(16)
    with SesionLocal() as sesion:
        sesion.add(
            UsuarioSistema(
                username=username,
                password_hash=seguridad.hashear_clave(clave),
                rol="sistemas",
                debe_cambiar=False,
                activo=True,
                version_token=0,
            )
        )
        sesion.commit()
    return username, clave


def _limpiar(username: str, marcacion: dict | None) -> None:
    with SesionLocal() as sesion:
        if marcacion and marcacion.get("asistencia_id"):
            sesion.execute(text("DELETE FROM asistencias WHERE id = :i"), {"i": marcacion["asistencia_id"]})
        if marcacion and marcacion.get("lectura_id"):
            sesion.execute(
                text("DELETE FROM lecturas_biometricas WHERE id = :i"), {"i": marcacion["lectura_id"]}
            )
        sesion.execute(text("DELETE FROM intentos_login WHERE username = :u"), {"u": username})
        sesion.execute(text("DELETE FROM usuarios_sistema WHERE username = :u"), {"u": username})
        sesion.commit()


def _escenario(cliente: TestClient, username: str, clave: str) -> dict:
    ingreso = cliente.post("/auth/login", json={"username": username, "password": clave})
    if ingreso.status_code != 200:
        _abortar(f"no se pudo ingresar con la cuenta temporal: {ingreso.text}")
    jefatura = {"Authorization": f"Bearer {ingreso.json()['access']}"}

    r = cliente.put("/simulacion/reloj", json={"momento": args.momento.isoformat()}, headers=jefatura)
    print(f"[2/6] PUT /simulacion/reloj -> {r.status_code} {r.json()}")
    salud = cliente.get("/salud").json()
    print(f"      /salud: entorno={salud['entorno']} reloj={salud['reloj']}")
    if r.status_code != 200 or not salud["reloj"]["simulado"]:
        _abortar("el reloj no quedó fijado")

    r = cliente.post(
        "/asistencias", json={"usuario_id": args.usuario, "metodo": "biometrico"}, headers=jefatura
    )
    marcacion = r.json()
    print(f"[3/6] POST /asistencias -> {r.status_code} {marcacion}")
    if r.status_code != 200 or not marcacion.get("valido"):
        _abortar("la marcación no fue válida")
    with SesionLocal() as sesion:
        fila = sesion.execute(
            text(
                "SELECT id, usuario_id, fecha_comida, comida_id, turno_asignado_id, "
                "metodo, fecha_hora FROM asistencias WHERE id = :i"
            ),
            {"i": marcacion["asistencia_id"]},
        ).mappings().one()
    print(f"      fila en {config.db_name}.asistencias: {dict(fila)}")

    r = cliente.post("/simulacion/reloj/proxima-franja", headers=jefatura)
    print(f"[4/6] POST /simulacion/reloj/proxima-franja -> {r.status_code} {r.json()}")
    r = cliente.delete("/simulacion/reloj", headers=jefatura)
    print(f"      DELETE /simulacion/reloj -> {r.status_code} simulado={r.json()['simulado']}")
    return marcacion


def main() -> None:
    _salida_utf8()
    servidor = create_engine(config.url_servidor, future=True, isolation_level="AUTOCOMMIT")
    try:
        with servidor.connect() as conexion:
            antes = _checksums(conexion, args.original)
        print(f"[0/6] CHECKSUM '{args.original}' antes: {_huella(antes)} ({len(antes)} tablas).")
        print(f"      API en proceso: entorno={config.entorno} base={config.db_name} turnos={config.db_name_turnos}")

        username, clave = _cuenta_temporal()
        print(f"[1/6] cuenta temporal '{username}' (sistemas) en '{config.db_name}'.")
        marcacion = None
        try:
            marcacion = _escenario(TestClient(app), username, clave)
        finally:
            if args.conservar:
                print(f"[5/6] --conservar: quedan la ración y la cuenta '{username}'.")
            else:
                _limpiar(username, marcacion)
                print("[5/6] limpieza: ración, lectura y cuenta temporal borradas.")

        with servidor.connect() as conexion:
            despues = _checksums(conexion, args.original)
        cambiadas = sorted(t for t in antes if antes[t] != despues.get(t))
        print(f"[6/6] CHECKSUM '{args.original}' después: {_huella(despues)} ({len(despues)} tablas).")
        if cambiadas or set(antes) != set(despues):
            _abortar(f"'{args.original}' cambió durante la demo: {cambiadas}")
        print(f"      Idéntico: '{args.original}' no se modificó.")
    finally:
        servidor.dispose()


if __name__ == "__main__":
    main()
