"""Lanzador QA de semilla/API: guardas, auditor y configuración sin dotenv."""
import argparse
import os
import sys
import threading

import comun as c


def permisos_modo(modo, laboratorio=False):
    if modo == 'admin':
        return c.permisos(
            (c.SIM, 'usuarios_sistema', 'INSERT'),
            (c.SIM, 'usuarios_sistema', 'UPDATE'),
        )
    if modo == 'api':
        return c.permisos(
            (c.SIM, 'usuarios_sistema', 'INSERT'),
            (c.SIM, 'usuarios_sistema', 'UPDATE'),
            *((c.SIM, t, 'INSERT') for t in (
                'intentos_login', 'intervenciones_lectura', 'asistencias')),
            *(((c.SIM, 'lecturas_biometricas', 'INSERT'),) if laboratorio else ()),
        )
    raise c.Abortado("Modo inválido")


def instalar_errores_auditor(app):
    """El bloqueo conserva el auditor y responde HTTP sin parecer un corte de red."""
    from starlette.responses import JSONResponse

    async def bloqueado(_peticion, _error):
        return JSONResponse({
            'motivo': 'operacion_bloqueada_qa',
            'detail': 'El auditor del laboratorio bloqueó esta operación. No se confirmó ningún cambio.',
        }, status_code=500)

    app.add_exception_handler(c.Abortado, bloqueado)


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
    api.add_argument('--laboratorio', action='store_true', help='Control local por stdin y reloj interactivo')
    args = parser.parse_args(argv)
    if os.environ.get('ENTORNO') != 'desarrollo':
        raise c.Abortado('ENTORNO')
    if args.modo == 'preparar':
        import cuentas
        cuentas.ejecutar_preparacion(port=args.port)
        return
    permitidas = permisos_modo(args.modo, laboratorio=getattr(args, 'laboratorio', False))
    with c.entorno_seguro(permitidas) as (motor, huella, servidor):
        datos = c.leer_corrida(servidor)
        c.comprobar_base(datos, huella)
        iniciar(args, datos, motor)


def iniciar(args, datos, motor):
    reloj_controlado = (c.reloj_laboratorio(datos, interactivo=True)
                        if getattr(args, 'laboratorio', False) else c.reloj_laboratorio(datos))
    with c.app_sin_dotenv(), reloj_controlado as reloj:
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
                instalar_errores_auditor(app)
                # Sin reload/workers: cada proceso nuevo perdería los listeners.
                if getattr(args, 'laboratorio', False):
                    import enrolamiento
                    enrolamiento.instalar(app, motor, datos['servidor'], datos['huella_base'])
                    import concurrencia
                    concurrencia.instalar(app, motor, datos['servidor'], datos['huella_base'])
                    servidor = uvicorn.Server(uvicorn.Config(
                        app, host='127.0.0.1', port=args.port, access_log=False,
                    ))

                    def esperar_cierre():
                        # El padre posee esta tubería. EOF también cierra una API huérfana.
                        sys.stdin.readline()
                        servidor.should_exit = True

                    threading.Thread(target=esperar_cierre, daemon=True).start()
                    servidor.run()
                else:
                    uvicorn.run(app, host='127.0.0.1', port=args.port, access_log=False)
            finally:
                marca.unlink()


if __name__ == '__main__':
    c.ejecutar(main)
