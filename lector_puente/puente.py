"""Puente entre el lector biométrico y la API del comedor.

Corre en la PC de cocina. Lee lo que entrega el lector (el identificador con
que enroló la huella), lo manda a POST /lector/lecturas con la clave del
lector y muestra el resultado a la cocinera.

Si la API o la red fallan, reintenta el MISMO envío (misma Idempotency-Key)
durante `reintentar_segundos`. Pasado ese tiempo no lo descarta en silencio:
lo anota en `pendientes.csv` y avisa en pantalla para que la jefatura registre
la ración a mano con su hora real. La API pone siempre la hora del servidor,
así que reenviar horas después registraría una hora falsa.

Solo librería estándar de Python 3.10+. Uso:

    python puente.py                 (lee puente.ini junto a este archivo)
    python puente.py --config otra.ini
"""

import argparse
import configparser
import csv
import json
import logging
import queue
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib import error, request

import adaptadores

CARPETA = Path(__file__).resolve().parent
registro = logging.getLogger("puente")

MOTIVOS = {
    "duplicado": "Ya recibió esta comida",
    "sin_derecho": "Sin derecho a esta comida",
    "fuera_horario": "Fuera del horario de comida",
    "no_identificado": "Huella no reconocida: identificar en la pantalla de cocina",
}


@dataclass
class Configuracion:
    url: str
    clave: str
    adaptador: str = "teclado"
    reintentar_segundos: float = 120.0
    espera_inicial: float = 1.0
    pendientes: Path = field(default_factory=lambda: CARPETA / "pendientes.csv")

    @classmethod
    def leer(cls, ruta: Path) -> "Configuracion":
        if not ruta.exists():
            raise SystemExit(f"Falta {ruta.name}. Copia puente.ini.ejemplo a {ruta.name} y complétalo.")
        ini = configparser.ConfigParser()
        ini.read(ruta, encoding="utf-8")
        url = ini.get("api", "url", fallback="").strip().rstrip("/")
        clave = ini.get("api", "clave", fallback="").strip()
        if not url or len(clave) < 32:
            raise SystemExit(f"{ruta.name}: falta [api] url o la clave del lector (32+ caracteres).")
        pendientes = Path(ini.get("puente", "pendientes", fallback="pendientes.csv"))
        return cls(
            url=url,
            clave=clave,
            adaptador=ini.get("lector", "adaptador", fallback="teclado").strip(),
            reintentar_segundos=ini.getfloat("puente", "reintentar_segundos", fallback=120.0),
            pendientes=pendientes if pendientes.is_absolute() else ruta.parent / pendientes,
        )


class ClaveRechazada(Exception):
    """401: la clave del lector no vale. No tiene sentido reintentar."""


class Rechazo(Exception):
    """4xx definitivo (409, 422): reintentar daría lo mismo."""


class Api:
    def __init__(self, config: Configuracion):
        self.config = config

    def _pedir(self, metodo: str, ruta: str, cuerpo: dict | None = None, clave_envio: str | None = None):
        cabeceras = {"X-Lector-Token": self.config.clave, "Content-Type": "application/json"}
        if clave_envio:
            cabeceras["Idempotency-Key"] = clave_envio
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        peticion = request.Request(self.config.url + ruta, data=datos, headers=cabeceras, method=metodo)
        try:
            with request.urlopen(peticion, timeout=10) as respuesta:
                return json.loads(respuesta.read() or b"null")
        except error.HTTPError as fallo:
            detalle = fallo.read().decode("utf-8", "replace")[:300]
            if fallo.code == 401:
                raise ClaveRechazada(detalle) from None
            if 400 <= fallo.code < 500:
                raise Rechazo(f"HTTP {fallo.code}: {detalle}") from None
            raise  # 5xx: se reintenta

    def salud(self) -> dict:
        return self._pedir("GET", "/lector/salud")

    def plantillas(self) -> list[dict]:
        return self._pedir("GET", "/lector/plantillas")

    def leer(self, identificador: str | None, clave_envio: str) -> dict:
        return self._pedir("POST", "/lector/lecturas", {"identificador": identificador}, clave_envio)


@dataclass
class Toque:
    identificador: str | None
    capturado: datetime = field(default_factory=datetime.now)
    clave: str = field(default_factory=lambda: str(uuid.uuid4()))


def anotar_pendiente(config: Configuracion, toque: Toque, motivo: str) -> None:
    nuevo = not config.pendientes.exists()
    with config.pendientes.open("a", newline="", encoding="utf-8") as archivo:
        escritor = csv.writer(archivo)
        if nuevo:
            escritor.writerow(["momento_captura", "identificador", "clave_envio", "motivo"])
        escritor.writerow([toque.capturado.isoformat(timespec="seconds"),
                           toque.identificador or "(no reconocida)", toque.clave, motivo])


def enviar(api: Api, config: Configuracion, toque: Toque, dormir=time.sleep, reloj=time.monotonic) -> dict | None:
    """Manda el toque, reintentando con la misma clave hasta el plazo.
    Devuelve la respuesta, o None si quedó anotado como pendiente."""
    limite = reloj() + config.reintentar_segundos
    espera = config.espera_inicial
    while True:
        try:
            return api.leer(toque.identificador, toque.clave)
        except (ClaveRechazada, Rechazo):
            raise
        except (error.URLError, OSError, TimeoutError, ValueError) as fallo:
            ultimo = str(getattr(fallo, "reason", fallo))
            registro.warning("Sin respuesta de la API (%s); reintento en %.0f s", ultimo, espera)
        if reloj() + espera > limite:
            anotar_pendiente(config, toque, f"sin conexion: {ultimo}")
            return None
        dormir(espera)
        espera = min(espera * 2, 15)


def mostrar(texto: str, exito: bool | None = None) -> None:
    print(texto, flush=True)
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_OK if exito else winsound.MB_ICONHAND)
    except (ImportError, RuntimeError):
        pass


def describir(respuesta: dict) -> tuple[str, bool]:
    hora = datetime.now().strftime("%H:%M:%S")
    nombre = respuesta.get("nombre") or "Persona sin identificar"
    if respuesta.get("valido"):
        return f"[{hora}]  OK  {respuesta.get('comida') or ''}: {nombre}", True
    motivo = MOTIVOS.get(respuesta.get("motivo"), respuesta.get("detalle") or "Rechazada")
    return f"[{hora}]  NO  {nombre}: {motivo}", False


def trabajador(api: Api, config: Configuracion, cola: "queue.Queue[Toque | None]") -> None:
    while (toque := cola.get()) is not None:
        try:
            respuesta = enviar(api, config, toque)
        except ClaveRechazada:
            mostrar("!! La API rechazó la clave del lector. Revisa [api] clave en puente.ini y LECTORES en el .env.", False)
            anotar_pendiente(config, toque, "clave del lector rechazada")
            continue
        except Rechazo as fallo:
            mostrar(f"!! Lectura no aceptada por la API: {fallo}", False)
            anotar_pendiente(config, toque, str(fallo))
            continue
        if respuesta is None:
            mostrar("!! SIN CONEXIÓN: lectura NO registrada. Quedó en pendientes.csv para registro manual.", False)
        else:
            mostrar(*describir(respuesta))


def comprobar(api: Api) -> bool:
    try:
        datos = api.salud()
    except ClaveRechazada:
        mostrar("!! Clave del lector rechazada: no coincide con LECTORES en el .env de la API.", False)
        return False
    except Exception as fallo:  # noqa: BLE001 - se muestra y se sigue intentando
        mostrar(f"!! No se pudo conectar con la API ({fallo}). Se sigue intentando con cada lectura.", False)
        return True
    comida = datos.get("comida_en_curso") or "fuera de horario"
    mostrar(f"Conectado como {datos['dispositivo']} · hora del servidor {datos['momento'][11:19]} · "
            f"{comida} · {datos['vinculos_activos']} huellas vinculadas.", True)
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=CARPETA / "puente.ini")
    args = parser.parse_args(argv)
    logging.basicConfig(filename=CARPETA / "puente.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    config = Configuracion.leer(args.config)
    api = Api(config)
    if not comprobar(api):
        return 2
    lector = adaptadores.crear(config.adaptador, api)
    cola: "queue.Queue[Toque | None]" = queue.Queue()
    hilo = threading.Thread(target=trabajador, args=(api, config, cola), daemon=True)
    hilo.start()
    mostrar(lector.instrucciones)
    try:
        for identificador in lector.lecturas():
            cola.put(Toque(identificador))
    except KeyboardInterrupt:
        pass
    mostrar("Cerrando: se terminan de enviar las lecturas en curso…")
    cola.put(None)
    hilo.join()
    return 0


if __name__ == "__main__":
    sys.exit(main())
