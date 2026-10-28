"""Las tres cuentas con que se entrega el sistema: root, jefa y cocinera.

La clave inicial de cada una es su nombre + 2026 (root2026, jefa2026,
cocinera2026) y es TEMPORAL: en el primer ingreso el sistema pide cambiarla
(responde 428 y solo deja cambiar la clave), así que una clave conocida no
queda en uso. Cumple la política de claves: 8+ caracteres y distinta del
usuario.

Idempotente: una cuenta que ya existe no se toca (ni su clave ni su rol).
Para resetear una clave: python -m app.semillas.admin --username jefa --resetear

Ejecutar con:  python -m app.semillas.cuentas_iniciales
"""

from sqlalchemy import select

from app.core.db import SesionLocal
from app.logica.autenticacion import fijar_clave
from app.modelos.usuarios import UsuarioSistema

CUENTAS = [
    ("root", "sistemas", "Sistemas"),
    ("jefa", "jefa", "Jefa de nutrición"),
    ("cocinera", "cocinera", "Cocinera"),
]
SUFIJO_CLAVE = "2026"


def clave_inicial(username: str) -> str:
    return f"{username}{SUFIJO_CLAVE}"


def sembrar() -> None:
    sesion = SesionLocal()
    creadas = 0
    try:
        for username, rol, nombre in CUENTAS:
            existe = sesion.execute(
                select(UsuarioSistema.id).where(UsuarioSistema.username == username)
            ).scalar_one_or_none()
            if existe is not None:
                print(f"  '{username}' ya existe: no se toca")
                continue
            cuenta = UsuarioSistema(username=username, rol=rol, nombre=nombre, activo=1, version_token=0)
            sesion.add(cuenta)
            fijar_clave(sesion, cuenta, clave_inicial(username), temporal=True)
            print(f"  '{username}' ({rol}) creada: clave inicial {username}{SUFIJO_CLAVE}, se cambia al primer ingreso")
            creadas += 1
        print(f"Cuentas creadas: {creadas}")
    finally:
        sesion.close()


if __name__ == "__main__":
    sembrar()
