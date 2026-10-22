"""Arranque único y reutilizable de QA. No resetea cuentas ni inicia otro ensayo."""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

import comun as c


def obtener(url):
    with urlopen(url, timeout=3) as respuesta:
        return respuesta.read().decode('utf-8-sig')


def salud_api(datos):
    return all(datos.get(k) == v for k, v in {
        'estado': 'ok', 'entorno': 'desarrollo', 'base_datos': c.SIM,
        'base_turnos': c.DEMO, 'revision_alembic': '8d4a2b7c9f10',
    }.items())


def estado_servicio(tipo):
    try:
        if tipo == 'laboratorio':
            datos = json.loads(obtener('http://127.0.0.1:8002/salud'))
            return datos.get('servicio') == 'laboratorio-qa' and datos.get('version_panel') == 2
        if tipo == 'api':
            return salud_api(json.loads(obtener('http://127.0.0.1:8001/salud')))
        html = obtener('http://127.0.0.1:5173/')
        return 'id="qa-abrir"' in html and '/_qa/modal.js' in html
    except (OSError, URLError, HTTPError, ValueError):
        return False


def ocupado(puerto):
    with socket.socket() as conexion:
        conexion.settimeout(.5)
        return conexion.connect_ex(('127.0.0.1', puerto)) == 0


def esperar(tipo, proceso, segundos=35):
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if estado_servicio(tipo):
            return
        if proceso is not None and proceso.poll() is not None:
            raise c.Abortado(f'No inició {tipo}. Revisa el mensaje de su consola. El ensayo se conserva.')
        time.sleep(.25)
    raise c.Abortado(f'{tipo.capitalize()} no respondió a tiempo. El ensayo se conserva.')


def detener_propio(tipo, proceso):
    """Nunca detiene un servicio reutilizado o un PID encontrado por su puerto."""
    if proceso is None or proceso.poll() is not None:
        return
    if tipo == 'laboratorio':
        html = obtener('http://127.0.0.1:8002/')
        token = re.search(r'name="qa-control"\s+content="([^"]+)"', html)
        if not token:
            raise c.Abortado('No se pudo solicitar el cierre del laboratorio. Se conserva el ensayo.')
        solicitud = Request('http://127.0.0.1:8002/detener', data=b'{}',
                            headers={'Content-Type': 'application/json', 'X-QA-Control': token[1]})
        with urlopen(solicitud, timeout=30):
            pass
        proceso.wait(timeout=30)
        if proceso.returncode != 0:
            raise c.Abortado('El laboratorio cerró con error. Revisa la huella final antes de continuar.')
    else:
        proceso.terminate()
        proceso.wait(timeout=10)


def main():
    rama = subprocess.check_output(['git', '-C', str(c.RAIZ), 'branch', '--show-current'], text=True).strip()
    if rama != 'qa' or os.environ.get('ENTORNO') != 'desarrollo':
        raise c.Abortado('El arranque requiere wt-qa, rama qa y entorno desarrollo.')
    if not ocupado(int(os.environ.get('DB_PORT', '3306'))):
        raise c.Abortado('Enciende MySQL en Laragon y vuelve a ejecutar el mismo comando.')
    node = shutil.which('node')
    if node is None:
        raise c.Abortado('No se encontró Node.js para iniciar el frontend QA.')
    propios = []
    try:
        if ocupado(8002):
            if not estado_servicio('laboratorio'):
                raise c.Abortado('Hay un laboratorio anterior u otro servicio en 8002. Ciérralo con Ctrl+C en su consola y repite este comando.')
            print('Laboratorio QA existente: reutilizado. No se reinicia el ensayo.', flush=True)
        else:
            if ocupado(8001) or (c.CARPETA / 'api.activa').exists():
                raise c.Abortado('Hay una API anterior sin laboratorio. Ciérrala con Ctrl+C en su consola y repite este comando.')
            proceso = subprocess.Popen([sys.executable, '-B', str(c.CARPETA / 'laboratorio.py')],
                                       cwd=c.RAIZ, stdin=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0))
            propios.append(('laboratorio', proceso))
            esperar('laboratorio', proceso)
        esperar('api', propios[0][1] if propios else None, segundos=10)
        if ocupado(5173):
            if not estado_servicio('frontend'):
                raise c.Abortado('El puerto 5173 pertenece a otro frontend. Ciérralo desde su consola antes de continuar.')
            print('Frontend QA existente: reutilizado.', flush=True)
        else:
            proceso = subprocess.Popen([node, str(c.RAIZ / 'comedorfront/scripts/iniciar-qa.mjs')],
                                       cwd=c.RAIZ / 'comedorfront', stdin=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0))
            propios.append(('frontend', proceso))
            esperar('frontend', proceso)
        print('\nQA LISTO: http://127.0.0.1:5173\nInicia sesión y pulsa «Simular escenarios QA».', flush=True)
        if propios:
            print('Mantén esta consola abierta. Ctrl+C cierra únicamente los servicios iniciados aquí.', flush=True)
            while True:
                for tipo, proceso in propios:
                    if proceso.poll() is not None:
                        raise c.Abortado(f'Se cerró {tipo}. El ensayo se conserva; revisa su salida.')
                time.sleep(.5)
    except KeyboardInterrupt:
        print('\nCerrando los servicios de esta consola…', flush=True)
    finally:
        fallos = []
        for tipo, proceso in reversed(propios):
            try:
                detener_propio(tipo, proceso)
            except (OSError, URLError, subprocess.TimeoutExpired, c.Abortado):
                fallos.append(tipo)
        if fallos:
            raise c.Abortado('No se confirmó el cierre de: ' + ', '.join(fallos) + '. Se conserva el diario.')


if __name__ == '__main__':
    c.ejecutar(main)
