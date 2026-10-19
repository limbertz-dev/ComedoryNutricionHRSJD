"""Lanzador QA de semilla/API: guardas, auditor y configuración sin dotenv."""
import argparse
import os

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


def sembrar_cuentas_qa(motor, cuentas=None, exigir_clave=True):
    objetivo = tuple(c.CUENTAS if cuentas is None else cuentas)
    roles = {cuenta: c.rol_cuenta(cuenta) for cuenta in objetivo}
    with motor.connect() as conn:
        for cuenta in objetivo:
            c.validar_cuenta_admin(conn, cuenta)
    from app.semillas import admin as semilla_admin
    temporales = {}
    for cuenta in objetivo:
        clave = semilla_admin.sembrar(cuenta, rol=roles[cuenta], resetear=True)
        if exigir_clave and (not isinstance(clave, str) or not clave):
            raise c.Abortado(f"La semilla no generó clave temporal para {cuenta}")
        temporales[cuenta] = clave
    return temporales


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='modo', required=True)
    preparar = sub.add_parser('preparar')
    preparar.add_argument('--port', type=int, default=8001)
    admin = sub.add_parser('admin')
    admin.add_argument('--username', choices=c.CUENTAS, required=True)
    api = sub.add_parser('api')
    api.add_argument('--port', type=int, default=8001)
    args = parser.parse_args(argv)
    if os.environ.get('ENTORNO') != 'desarrollo':
        raise c.Abortado('ENTORNO')
    if args.modo == 'preparar':
        import cuentas
        cuentas.ejecutar_preparacion(port=args.port)
        return
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
            c.rol_cuenta(args.username)
            with c.bloqueo_corrida():
                sembrar_cuentas_qa(motor, (args.username,), exigir_clave=False)
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
