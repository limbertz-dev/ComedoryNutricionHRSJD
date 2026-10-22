"""Ventana local de simulación QA. No forma parte de los routers de la aplicación."""
import argparse
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time
from urllib.request import urlopen

from sqlalchemy import text

import comun as c
import verificar_casos as verificar


ACTIVOS = Path(__file__).resolve().parent / 'laboratorio'


def validar_horario(cuerpo):
    try:
        momento = c.argumento_reloj(cuerpo['momento'])
    except (KeyError, TypeError, argparse.ArgumentTypeError):
        raise c.Abortado('Elige una fecha y hora válidas.') from None
    modo = cuerpo.get('modo', 'fijo')
    if modo not in ('fijo', 'continuo'):
        raise c.Abortado('Elige reloj pausado o en marcha.')
    return momento, modo


def puerto_ocupado(puerto):
    with socket.socket() as conexion:
        conexion.settimeout(.5)
        return conexion.connect_ex(('127.0.0.1', puerto)) == 0


def validar_comida(cuerpo, predeterminada=2):
    comida = cuerpo.get('comida_id', predeterminada)
    if type(comida) is not int or comida not in c.COMIDAS_LABORATORIO:
        raise c.Abortado('Elige Desayuno, Almuerzo, Té o Cena.')
    return comida


class Laboratorio:
    def __init__(self, motor, servidor, huella):
        self.motor = motor
        self.servidor = servidor
        self.huella = huella
        self.cerrojo = threading.RLock()
        self.api = None
        self.token = secrets.token_urlsafe(32)
        self.entorno = dict(os.environ)
        # Solo en memoria y compartido por los reinicios de esta sesión del laboratorio.
        self.entorno.setdefault('AUTH_JWT_SECRETO', secrets.token_urlsafe(48))
        self.entorno['PYTHONDONTWRITEBYTECODE'] = '1'
        self.ultima_accion = 'Elige un caso para empezar. Ningún caso se aprueba automáticamente.'

    def diario(self):
        datos = c.leer_corrida(self.servidor)
        c.comprobar_base(datos, self.huella)
        if not c.es_corrida_multi(datos):
            raise c.Abortado('El laboratorio necesita la corrida de tres comensales QA.')
        if not datos.get('parte_a', {}).get('completa'):
            raise c.Abortado('Falta la verificación de cuentas de la Parte A.')
        return datos

    def ejecutar_script(self, archivo, *argumentos):
        permitidos = {'huella.py', 'limpiar.py', 'limpiar_fallido.py', 'comun.py', 'refechar.py', 'preparar_servicios.py', 'preparar_perfiles.py'}
        if archivo not in permitidos:
            raise c.Abortado('Operación de laboratorio no permitida.')
        resultado = subprocess.run(
            [sys.executable, '-B', str(c.CARPETA / archivo), *argumentos],
            cwd=c.RAIZ, env=self.entorno, capture_output=True,
            text=True, encoding='utf-8', errors='replace', timeout=90,
        )
        if resultado.returncode:
            # El motivo va a la consola del laboratorio; c.ejecutar ya lo deja sin SQL ni parámetros.
            motivo = resultado.stderr.strip().splitlines()[-1:] or ['sin mensaje']
            print(f'{archivo} falló: {motivo[0]}', file=sys.stderr, flush=True)
            # No enviar a HTTP SQL, parámetros o salida arbitraria de otro proceso.
            raise c.Abortado(
                f'No se pudo completar {archivo}. Se conserva el diario; '
                'revisa el estado antes de repetir la operación.'
            )

    def iniciar_api(self):
        if self.api is not None and self.api.poll() is None:
            return
        if puerto_ocupado(8001) or (c.CARPETA / 'api.activa').exists():
            raise c.Abortado('Hay otra API QA activa. Ciérrala desde su consola antes de abrir el laboratorio.')
        self.api = subprocess.Popen(
            [sys.executable, '-B', str(c.CARPETA / 'ejecutar_app.py'), 'api',
             '--port', '8001', '--laboratorio'],
            cwd=c.RAIZ, env=self.entorno, stdin=subprocess.PIPE, text=True,
        )
        limite = time.monotonic() + 25
        while time.monotonic() < limite:
            if self.api.poll() is not None:
                raise c.Abortado('La API QA no pudo iniciar. El diario se conserva.')
            try:
                with urlopen('http://127.0.0.1:8001/salud', timeout=1) as respuesta:
                    salud = json.load(respuesta)
                if (salud.get('estado') == 'ok' and salud.get('entorno') == 'desarrollo'
                        and salud.get('base_datos') == c.SIM
                        and salud.get('base_turnos') == c.DEMO
                        and salud.get('revision_alembic') == '8d4a2b7c9f10'):
                    return
                raise c.Abortado('La API no corresponde al escenario QA esperado.')
            except (OSError, TimeoutError):
                time.sleep(.15)
        raise c.Abortado('La API QA no respondió a tiempo. El diario se conserva.')

    def detener_api(self):
        proceso = self.api
        if proceso is None:
            return
        if proceso.poll() is None:
            try:
                proceso.stdin.write('detener\n')
                proceso.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            try:
                proceso.wait(timeout=20)
            except subprocess.TimeoutExpired:
                raise c.Abortado('La API no terminó limpiamente; se conserva su marca y la corrida.') from None
        if proceso.returncode != 0 or (c.CARPETA / 'api.activa').exists():
            raise c.Abortado('La API cerró con error. No se inicia la limpieza ni se retira su marca.')
        self.api = None

    def cambiar_horario(self, cuerpo):
        momento, modo = validar_horario(cuerpo)
        with c.bloqueo_corrida():
            datos = self.diario()
            fecha = datos.get('fecha_destino') or datos['fecha_original']
            if momento.date().isoformat() != fecha:
                raise c.Abortado('Para cambiar de fecha, usa «Nuevo ensayo»; se conservará la evidencia anterior.')
            anterior = datos['reloj']
            datos['reloj'] = {**c.crear_ancla_reloj(momento), 'modo': modo}
            if 'comida_id' in cuerpo:
                comida_id = validar_comida(cuerpo)
            else:
                with c.app_sin_dotenv():
                    from app.consultas.servicio import comida_de_referencia
                    from sqlalchemy.orm import Session
                    with Session(self.motor) as sesion:
                        referencia = comida_de_referencia(sesion, momento)
                    comida_id = referencia.comida_id if referencia else c.comida_corrida(datos)
            c.seleccionar_servicio(datos, comida_id)
            cambios = datos.setdefault('cambios_horario', [])
            cambios.append({'anterior': anterior, 'nuevo': datos['reloj']})
            c.guardar_corrida(datos)
        self.ultima_accion = 'Horario aplicado. Las marcaciones existentes se conservan.'

    def nuevo_ensayo(self, cuerpo):
        momento, modo = validar_horario(cuerpo)
        comida_id = validar_comida(cuerpo)
        if cuerpo.get('confirmar') is not True:
            raise c.Abortado('Confirma la limpieza de las marcaciones de este ensayo.')
        datos_previos = self.diario()
        estado_previo = self.estado()
        self.detener_api()
        cierre = ('limpiar_fallido.py' if any(
            revision.get('resultado') == 'rechazado'
            for revision in datos_previos.get('revision_operador', {}).values()
        ) or estado_previo['casos']['qa02']['estado'] == 'Revisar inconsistencia' else 'limpiar.py')
        self.ejecutar_script(cierre)
        self.ejecutar_script(cierre, '--aplicar')
        self.ejecutar_script('comun.py', '--huella-final')
        archivo = c.CARPETA / 'evidencias' / (
            datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '-ensayo-laboratorio.json'
        )
        archivo.parent.mkdir(exist_ok=True)
        c.CORRIDA.rename(archivo)
        self.ejecutar_script(
            'comun.py', '--huella-base', '--reloj', momento.isoformat(),
            '--conservar-cuentas-de', str(archivo),
        )
        datos = self.diario()
        if momento.date().isoformat() != datos['fecha_original']:
            self.ejecutar_script('refechar.py', '--fecha', momento.date().isoformat())
        self.ejecutar_script('preparar_servicios.py')
        with c.bloqueo_corrida():
            datos = self.diario()
            datos['comida_ensayo'] = comida_id
            datos['casos'] = c.casos_iniciales_diario(comida_id)
            c.guardar_corrida(datos)
        self.cambiar_horario({'momento': momento.isoformat(), 'modo': modo})
        self.iniciar_api()
        comida = c.COMIDAS_LABORATORIO[comida_id]['nombre']
        self.ultima_accion = f'Ensayo de {comida} listo. Las cuentas y contraseñas se conservaron; puedes simular ambos casos.'

    def simular(self, cuerpo):
        caso = cuerpo.get('caso')
        if caso not in ('qa01', 'qa02'):
            raise c.Abortado('Elige QA 01 o QA 02. QA 03 está en reserva.')
        import enrolamiento
        registro = enrolamiento.registro_de(c.COMENSALES_QA[caso]['usuario_id'])
        if registro is None:
            spec = c.COMENSALES_QA[caso]
            raise c.Abortado(f"Falta la huella de {spec['nombre']} ({spec['legajo']}). Usa «Registrar huella» en ese caso y vuelve al simulador.")
        if cuerpo.get('reiniciar') is True:
            self.nuevo_ensayo({**cuerpo, 'confirmar': True})
        datos = self.diario()
        estado = self.estado()
        comida_actual = estado.get('comida_id')
        if comida_actual is not None and comida_actual != c.comida_corrida(datos):
            with c.bloqueo_corrida():
                datos = self.diario()
                c.seleccionar_servicio(datos, comida_actual)
                c.guardar_corrida(datos)
        if not datos.get('turno_laboratorio'):
            raise c.Abortado('Prepara el servicio elegido para habilitar las cuatro comidas de los comensales QA.')
        if datos['casos'][caso].get('lectura_id') is not None:
            raise c.Abortado('Este caso ya tiene una lectura. Usa «Nuevo ensayo» para repetirlo sin duplicarla.')
        if not estado['servicio_elegido_vigente']:
            raise c.Abortado('La hora no corresponde al servicio elegido. Aplica el horario sugerido o ajusta la hora.')
        self.ejecutar_script('huella.py', '--caso', caso, '--referencia', registro['referencia'])
        comida = c.COMIDAS_LABORATORIO[c.comida_corrida(datos)]['nombre']
        self.ultima_accion = (f'QA 01 registrado en {comida}. Cierra el modal y comprueba la fila del mismo servicio.'
                              if caso == 'qa01' else
                              'Huella no reconocida creada. En cocina, elige QA 02 IDENTIFICACION y confirma la entrega.')

    def revisar(self, cuerpo):
        caso = cuerpo.get('caso')
        resultado = cuerpo.get('resultado')
        if caso not in ('qa01', 'qa02') or resultado not in ('aprobado', 'rechazado'):
            raise c.Abortado('Revisión no válida.')
        estado = self.estado()
        if resultado == 'aprobado' and not estado['casos'][caso]['comprobado']:
            raise c.Abortado('Todavía falta completar este caso antes de aprobarlo.')
        if cuerpo.get('revisado') is not True:
            raise c.Abortado('Marca que revisaste el resultado en la aplicación.')
        with c.bloqueo_corrida():
            datos = self.diario()
            if estado.get('comida_id') is not None and estado['comida_id'] != c.comida_corrida(datos):
                c.seleccionar_servicio(datos, estado['comida_id'])
            datos.setdefault('revision_operador', {})[caso] = {
                'resultado': resultado, 'momento_real': datetime.now().isoformat(),
                'origen': 'operador_local',
            }
            c.guardar_corrida(datos)
        self.ultima_accion = f'Tu revisión de {caso.upper()} quedó registrada: {resultado}.'

    def estado(self):
        import enrolamiento
        registros = enrolamiento.leer_registro()['registros']
        datos = self.diario()
        momento = c.momento_laboratorio(datos)
        fecha = date.fromisoformat(datos.get('fecha_destino') or datos['fecha_original'])
        salida = {
            'momento': momento.isoformat(timespec='seconds'),
            'modo': datos['reloj'].get('modo', 'continuo'),
            'api_activa': self.api is not None and self.api.poll() is None,
            'ultima_accion': self.ultima_accion,
            'casos': {}, 'revision': datos.get('revision_operador', {}),
            'comida_id': c.comida_corrida(datos),
            'comidas': list(c.COMIDAS_LABORATORIO.values()),
            'preparado_cuatro_comidas': bool(datos.get('turno_laboratorio')),
            'advertencias': [],
        }
        with c.app_sin_dotenv():
            from app.logica.marcacion import resolver_comida_en_curso
            from app.consultas.servicio import comida_de_referencia
            from sqlalchemy.orm import Session
            with Session(self.motor) as sesion:
                comida = resolver_comida_en_curso(sesion, momento)
                referencia = comida or comida_de_referencia(sesion, momento)
                salida['almuerzo_vigente'] = comida is not None and comida.comida_id == c.COMIDA
                salida['servicio_elegido_vigente'] = comida is not None
                salida['fuera_de_horario'] = comida is None
                salida['servicio'] = referencia.comida if referencia else 'Sin servicio'
                if referencia is not None:
                    salida['comida_id'] = referencia.comida_id
                    anterior = c.comida_corrida(datos)
                    vistas = list(c.vistas_servicios(datos))
                    vista = next((v for v in vistas if c.comida_corrida(v) == referencia.comida_id), None)
                    datos = vista or {**datos, 'comida_ensayo': referencia.comida_id,
                                      'casos': c.casos_iniciales_diario(referencia.comida_id)}
                    datos['casos_por_comida'] = {str(c.comida_corrida(v)): v['casos'] for v in vistas}
                    datos['casos_por_comida'][str(referencia.comida_id)] = datos['casos']
                    salida['revision'] = datos.get('revisiones_por_comida', {}).get(str(referencia.comida_id),
                        datos.get('revision_operador', {}) if anterior == referencia.comida_id else {})
        with self.motor.connect() as conn:
            cuentas = conn.execute(text(
                "SELECT id, username, rol, usuario_turnos_id FROM usuarios_sistema "
                "WHERE username IN ('cocinera1','cocinera2','cocinera3','jefa')"
            )).mappings().all()
            actuales = c.validar_cuentas_limpieza(cuentas, datos['cuentas'])
            for caso in ('qa01', 'qa02'):
                info = datos['casos'][caso]
                lid = info.get('lectura_id')
                spec = c.COMENSALES_QA[caso]
                item = {'lectura_id': lid, 'comprobado': False, 'estado': 'Sin simular', 'detalle': '',
                        'usuario_id': spec['usuario_id'], 'nombre': spec['nombre'], 'legajo': spec['legajo'],
                        'huella_registrada': str(spec['usuario_id']) in registros,
                        'referencia_huella': registros.get(str(spec['usuario_id']), {}).get('referencia')}
                if lid is not None:
                    try:
                        if caso == 'qa01':
                            verificar.verificar_caso_normal(conn, datos, fecha)
                            item.update(comprobado=True, estado='Registro normal comprobado',
                                        detalle='Una lectura aceptada, una ración biométrica y ninguna intervención.')
                        else:
                            n = conn.execute(text('SELECT COUNT(*) FROM asistencias WHERE lectura_id=:lid'), {'lid': lid}).scalar_one()
                            if n == 0:
                                intervenciones = conn.execute(text(
                                    'SELECT COUNT(*) FROM intervenciones_lectura WHERE lectura_id=:lid'
                                ), {'lid': lid}).scalar_one()
                                if intervenciones:
                                    raise c.Abortado('Existe una intervención sin asistencia; revisa la corrida.')
                                lectura = conn.execute(text(
                                    'SELECT usuario_id, resultado, motivo FROM lecturas_biometricas WHERE id=:lid'
                                ), {'lid': lid}).mappings().one()
                                if (lectura['usuario_id'] is not None or lectura['resultado'] != 'rechazada'
                                        or lectura['motivo'] != 'no_identificado'):
                                    raise c.Abortado('La lectura original no corresponde al caso QA 02.')
                                item.update(estado='Por identificar en cocina', detalle='La identidad es desconocida. Todavía no se entregó la ración.')
                            else:
                                verificar.verificar_caso_identificacion(conn, datos, fecha, actuales)
                                verificar.verificar_consulta_jefa(conn, datos, fecha, actuales)
                                item.update(comprobado=True, estado='Corrección registrada por cocinera2',
                                            detalle='Una ración manual y una intervención vinculadas. La decisión original se conserva. Falta tu revisión visual como jefa.')
                    except c.Abortado as error:
                        item.update(estado='Revisar inconsistencia', detalle=str(error))
                salida['casos'][caso] = item
            # Un resultado incorrecto es un fallo del caso, no una caída de red.
            # No modifica ni da por válidas sus filas; la limpieza mantiene sus guardas.
            try:
                salida['reserva'] = verificar.verificar_reserva_qa03(conn, datos)
            except c.Abortado:
                salida['reserva'] = {'resultado': 'REVISAR'}
                salida['advertencias'].append(
                    'QA 03 tiene registros: revisa a qué persona se confirmó la entrega. '
                    'El ensayo se conserva. Para repetir desde cero, usa «Nuevo ensayo».'
                )
        return salida


def crear_handler(control):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def enviar(self, codigo, contenido, tipo='application/json; charset=utf-8'):
            cuerpo = (json.dumps(contenido, ensure_ascii=False).encode('utf-8')
                      if not isinstance(contenido, bytes) else contenido)
            self.send_response(codigo)
            self.send_header('Content-Type', tipo)
            self.send_header('Content-Length', str(len(cuerpo)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors http://127.0.0.1:5173 http://localhost:5173; base-uri 'none'")
            self.end_headers()
            self.wfile.write(cuerpo)

        def local(self):
            puerto = self.server.server_port
            hosts = {f'127.0.0.1:{puerto}', f'localhost:{puerto}'}
            origen = self.headers.get('Origin')
            return (self.headers.get('Host') in hosts
                    and (origen is None or origen in {f'http://{h}' for h in hosts}))

        def do_GET(self):
            if not self.local():
                self.enviar(403, {'error': 'El laboratorio solo admite acceso local.'})
                return
            if self.path == '/salud':
                self.enviar(200, {'estado': 'ok', 'servicio': 'laboratorio-qa', 'version_panel': 2})
                return
            rutas = {
                '/': (ACTIVOS / 'index.html', 'text/html; charset=utf-8'),
                '/panel.js': (ACTIVOS / 'panel.js', 'text/javascript; charset=utf-8'),
                '/panel.css': (ACTIVOS / 'panel.css', 'text/css; charset=utf-8'),
                '/tokens.css': (c.RAIZ / 'comedorfront/src/styles/tokens.css', 'text/css; charset=utf-8'),
            }
            if self.path in rutas:
                ruta, tipo = rutas[self.path]
                contenido = ruta.read_bytes()
                if self.path == '/':
                    contenido = contenido.replace(b'__TOKEN_QA__', control.token.encode('ascii'))
                self.enviar(200, contenido, tipo)
                return
            if self.path == '/estado' and secrets.compare_digest(self.headers.get('X-QA-Control', ''), control.token):
                try:
                    with control.cerrojo:
                        self.enviar(200, control.estado())
                except c.Abortado as error:
                    self.enviar(409, {'error': str(error)})
                except Exception:
                    self.enviar(503, {'error': 'El laboratorio está abierto, pero no pudo consultar la base QA. Comprueba MySQL en Laragon. El ensayo se conserva.'})
                return
            self.enviar(404, {'error': 'Ruta no disponible.'})

        def do_POST(self):
            if not self.local() or not secrets.compare_digest(self.headers.get('X-QA-Control', ''), control.token):
                self.enviar(403, {'error': 'Acceso de control no válido. Recarga el laboratorio.'})
                return
            if self.path == '/detener':
                if not control.cerrojo.acquire(blocking=False):
                    self.enviar(409, {'error': 'Espera a que termine la operación en curso.'})
                    return
                try:
                    control.detener_api()
                    self.enviar(200, {'mensaje': 'API QA detenida con cierre normal.'})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                except c.Abortado as error:
                    self.enviar(409, {'error': str(error)})
                finally:
                    control.cerrojo.release()
                return
            acciones = {'/simular': control.simular, '/horario': control.cambiar_horario,
                        '/nuevo': control.nuevo_ensayo, '/revision': control.revisar}
            if self.path not in acciones:
                self.enviar(404, {'error': 'Operación no disponible.'})
                return
            if not control.cerrojo.acquire(blocking=False):
                self.enviar(409, {'error': 'Hay una operación en curso. Espera a que termine.'})
                return
            try:
                longitud = int(self.headers.get('Content-Length', '0'))
                if not 0 < longitud <= 4096:
                    raise ValueError
                cuerpo = json.loads(self.rfile.read(longitud))
                if not isinstance(cuerpo, dict):
                    raise ValueError
                acciones[self.path](cuerpo)
                self.enviar(200, control.estado())
            except (ValueError, json.JSONDecodeError):
                self.enviar(400, {'error': 'Revisa los datos de la operación.'})
            except c.Abortado as error:
                self.enviar(409, {'error': str(error)})
            except Exception:
                self.enviar(500, {'error': 'La operación no pudo confirmarse. Se conserva la evidencia; actualiza el estado antes de repetir.'})
            finally:
                control.cerrojo.release()

    return Handler


def main():
    rama = subprocess.check_output(['git', '-C', str(c.RAIZ), 'branch', '--show-current'], text=True).strip()
    if rama != 'qa' or os.environ.get('ENTORNO') != 'desarrollo':
        raise c.Abortado('El laboratorio requiere la rama qa y ENTORNO=desarrollo.')
    if puerto_ocupado(8002):
        raise c.Abortado('El laboratorio ya está abierto en http://127.0.0.1:8002.')
    c.retirar_marca_api_huerfana()
    with c.entorno_seguro() as (motor, huella, servidor), c.app_sin_dotenv():
        control = Laboratorio(motor, servidor, huella)
        control.diario()
        control.ejecutar_script('preparar_perfiles.py')
        http = ThreadingHTTPServer(('127.0.0.1', 8002), crear_handler(control))
        try:
            control.iniciar_api()
            print('Laboratorio QA: http://127.0.0.1:8002', flush=True)
            http.serve_forever(poll_interval=.25)
        except KeyboardInterrupt:
            pass
        finally:
            http.server_close()
            control.detener_api()


if __name__ == '__main__':
    c.ejecutar(main)
