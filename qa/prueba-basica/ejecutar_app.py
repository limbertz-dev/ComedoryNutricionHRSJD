"""Lanzador QA de semilla/API: guardas, auditor y configuración sin dotenv."""
import argparse
from contextlib import redirect_stdout
import getpass
import io
import os
from unittest.mock import patch

import comun as c


def permisos_modo(modo):
    if modo == 'admin':
        return c.permisos(
            (c.SIM, 'usuarios_sistema', 'INSERT'),
            (c.SIM, 'usuarios_sistema', 'UPDATE'),
        )
    if modo == 'api':
        return c.permisos(
            (c.SIM, 'usuarios_sistema', 'UPDATE'),
            *((c.SIM, t, 'INSERT') for t in (
                'intentos_login', 'intervenciones_lectura', 'asistencias')),
        )
    raise c.Abortado("Modo inválido")


def pedir_clave_temporal(username, lector=None):
    lector = getpass.getpass if lector is None else lector
    clave = lector(f"[{username}] Clave temporal: ")
    confirmacion = lector(f"[{username}] Confirmar clave temporal: ")
    if not clave:
        raise c.Abortado(f"Se requiere clave temporal para {username}")
    if clave != confirmacion:
        raise c.Abortado(f"La confirmación de clave temporal no coincide para {username}")
    return clave


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='modo', required=True)
    admin = sub.add_parser('admin')
    admin.add_argument('--username', choices=c.CUENTAS, required=True)
    api = sub.add_parser('api')
    api.add_argument('--port', type=int, default=8001)
    args = parser.parse_args()
    if os.environ.get('ENTORNO') != 'desarrollo':
        raise c.Abortado('ENTORNO')
    permitidas = permisos_modo(args.modo)
    with c.entorno_seguro(permitidas) as (motor, huella, servidor):
        datos = c.leer_corrida(servidor)
        c.comprobar_base(datos, huella)
        iniciar(args, datos, motor)


def iniciar(args, datos, motor):
    with c.app_sin_dotenv(), c.reloj_laboratorio(datos) as reloj:
        c.fecha_para_operar(datos, reloj.ahora(), permitir_lectura=True)
        if args.modo == 'admin':
            if (c.CARPETA / 'api.activa').exists():
                raise c.Abortado("Detener API antes de resetear cuentas")
            rol = c.rol_cuenta(args.username)
            with c.bloqueo_corrida():
                with motor.connect() as conn:
                    c.validar_cuenta_admin(conn, args.username)
                clave = pedir_clave_temporal(args.username)
                from app.semillas import admin as semilla_admin
                with (
                    patch.object(semilla_admin, 'clave_temporal', lambda *a, **kw: clave),
                    redirect_stdout(io.StringIO()),
                ):
                    semilla_admin.sembrar(args.username, rol=rol, resetear=True)
                print(f"Cuenta '{args.username}' preparada (rol {rol}, cambio de clave pendiente).")
        else:
            marca = c.CARPETA / 'api.activa'
            try:
                fd = os.open(marca, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                raise c.Abortado("api.activa ya existe; revisar GUION") from None
            os.close(fd)
            try:
                import uvicorn
                from app.main import app
                # Sin reload/workers: cada proceso nuevo perdería los listeners.
                uvicorn.run(app, host='127.0.0.1', port=args.port, access_log=False)
            finally:
                marca.unlink()


if __name__ == '__main__':
    c.ejecutar(main)
