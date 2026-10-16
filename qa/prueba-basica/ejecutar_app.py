"""Lanzador QA de semilla/API: guardas, auditor y configuración sin dotenv."""
import argparse
import os
import runpy
import sys

import comun as c


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
    permitidas = c.permisos((c.SIM, 'usuarios_sistema', 'UPDATE'))
    if args.modo == 'api':
        permitidas |= c.permisos(*((c.SIM, t, 'INSERT') for t in (
            'intentos_login', 'intervenciones_lectura', 'asistencias')))
    with c.entorno_seguro(permitidas) as (_, huella, servidor), c.app_sin_dotenv():
        datos = c.leer_corrida(servidor)
        c.comprobar_base(datos, huella)
        if datos['estado'] not in ('refechada', 'lectura_creada'):
            raise c.Abortado("Refechar antes de habilitar cuentas/arrancar API")
        if args.modo == 'admin':
            if (c.CARPETA / 'api.activa').exists():
                raise c.Abortado("Detener API antes de resetear cuentas")
            with c.bloqueo_corrida():
                sys.argv = ['app.semillas.admin', '--username', args.username, '--rol', 'cocinera', '--resetear']
                runpy.run_module('app.semillas.admin', run_name='__main__')
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
