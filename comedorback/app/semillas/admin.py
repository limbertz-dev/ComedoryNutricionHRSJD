"""Alta (o reseteo) de una cuenta del sistema con clave TEMPORAL.

La clave se genera al azar, se muestra UNA vez en la consola y se guarda solo
como hash. La cuenta queda con `debe_cambiar = 1`: el primer ingreso responde
428 y solo deja cambiar la clave.

No está en `python -m app.semillas` a propósito: esa corre sola dentro de
scripts/recrear_bd_limpia.py, y una clave impresa en medio de esa salida se
pierde o termina copiada en un log.

Ejecutar con (desde comedorback/, con la base migrada):

    python -m app.semillas.admin                          # 'admin', rol sistemas
    python -m app.semillas.admin --username jefa --rol jefa
    python -m app.semillas.admin --username jefa --resetear   # nueva temporal

Idempotente: si la cuenta existe y no se pide --resetear, no la toca.
Resetear también la reactiva y cierra todas sus sesiones abiertas.
"""

import argparse
import secrets
import sys

from sqlalchemy import select

from app.core.db import SesionLocal
from app.core.permisos import ROLES
from app.logica.autenticacion import fijar_clave, normalizar_username
from app.modelos.usuarios import UsuarioSistema

# Sin caracteres que se confunden al dictarla o copiarla a mano (0/O, 1/l/I).
ALFABETO = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def clave_temporal(largo: int = 12) -> str:
    return "".join(secrets.choice(ALFABETO) for _ in range(largo))


def sembrar(username: str = "admin", rol: str = "sistemas", resetear: bool = False) -> str | None:
    """Devuelve la clave temporal, o None si no hubo cambios."""
    username = normalizar_username(username)
    sesion = SesionLocal()
    try:
        usuario = sesion.execute(
            select(UsuarioSistema).where(UsuarioSistema.username == username)
        ).scalar_one_or_none()

        if usuario is not None and not resetear:
            print(f"  '{username}' ya existe (rol {usuario.rol}). Para una clave nueva: --resetear")
            return None

        clave = clave_temporal()
        if usuario is None:
            usuario = UsuarioSistema(username=username, rol=rol, activo=1, version_token=0)
            sesion.add(usuario)
            accion = "creada"
        else:
            usuario.activo = 1
            accion = "reseteada"
        fijar_clave(sesion, usuario, clave, temporal=True)

        print(f"  Cuenta '{username}' {accion} (rol {usuario.rol}).")
        print(f"  Clave temporal: {clave}")
        print("  Se muestra solo esta vez. Se pedirá cambiarla en el primer ingreso.")
        return clave
    finally:
        sesion.close()


def main(argumentos: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--username", default="admin")
    parser.add_argument("--rol", choices=ROLES, default="sistemas")
    parser.add_argument("--resetear", action="store_true")
    args = parser.parse_args(argumentos)
    if not 1 <= len(args.username.strip()) <= 50:
        sys.exit("El username debe tener entre 1 y 50 caracteres.")
    sembrar(args.username, args.rol, args.resetear)


if __name__ == "__main__":
    main()
