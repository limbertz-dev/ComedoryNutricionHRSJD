"""El puente contra una API falsa: envío, reintento con la misma clave,
pendientes.csv cuando no hay conexión y errores que no se reintentan."""

import csv
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import adaptadores
import puente

CLAVE = "c" * 40


class ApiFalsa:
    def __init__(self, respuestas):
        self.respuestas = list(respuestas)  # (código, cuerpo) por petición
        self.recibidas = []
        api = self

        class Manejador(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def _responder(self):
                largo = int(self.headers.get("Content-Length") or 0)
                api.recibidas.append({
                    "metodo": self.command, "ruta": self.path,
                    "clave": self.headers.get("X-Lector-Token"),
                    "idempotencia": self.headers.get("Idempotency-Key"),
                    "cuerpo": json.loads(self.rfile.read(largo) or b"null"),
                })
                codigo, cuerpo = api.respuestas.pop(0) if api.respuestas else (500, {})
                datos = json.dumps(cuerpo).encode()
                self.send_response(codigo)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(datos)))
                self.end_headers()
                self.wfile.write(datos)

            do_GET = do_POST = _responder

        self.servidor = ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.servidor.server_port}"

    def cerrar(self):
        self.servidor.shutdown()
        self.servidor.server_close()


@pytest.fixture
def config(tmp_path):
    def crear(url, segundos=5.0):
        return puente.Configuracion(url=url, clave=CLAVE, reintentar_segundos=segundos,
                                    espera_inicial=0.01, pendientes=tmp_path / "pendientes.csv")
    return crear


ACEPTADA = {"valido": True, "motivo": None, "nombre": "ANA QUISPE", "comida": "Almuerzo",
            "dispositivo": "cocina-01", "vinculado": True, "reintento": False}


def test_envia_identificador_con_clave_e_idempotencia(config):
    falsa = ApiFalsa([(200, ACEPTADA)])
    try:
        respuesta = puente.enviar(puente.Api(config(falsa.url)), config(falsa.url), puente.Toque("17"))
    finally:
        falsa.cerrar()
    assert respuesta == ACEPTADA
    (envio,) = falsa.recibidas
    assert (envio["metodo"], envio["ruta"], envio["clave"]) == ("POST", "/lector/lecturas", CLAVE)
    assert envio["cuerpo"] == {"identificador": "17"}
    assert len(envio["idempotencia"]) == 36


def test_reintenta_un_503_con_la_misma_clave(config):
    falsa = ApiFalsa([(503, {}), (503, {}), (200, ACEPTADA)])
    try:
        respuesta = puente.enviar(puente.Api(config(falsa.url)), config(falsa.url), puente.Toque("17"))
    finally:
        falsa.cerrar()
    assert respuesta == ACEPTADA
    assert len({r["idempotencia"] for r in falsa.recibidas}) == 1
    assert len(falsa.recibidas) == 3


def test_sin_conexion_queda_en_pendientes_y_no_se_pierde(config, tmp_path):
    cfg = config("http://127.0.0.1:9", segundos=0.05)  # puerto sin servidor
    toque = puente.Toque(None)
    assert puente.enviar(puente.Api(cfg), cfg, toque) is None
    filas = list(csv.DictReader(cfg.pendientes.open(encoding="utf-8")))
    assert len(filas) == 1
    assert filas[0]["identificador"] == "(no reconocida)"
    assert filas[0]["clave_envio"] == toque.clave
    assert filas[0]["motivo"].startswith("sin conexion")


@pytest.mark.parametrize("codigo,error", [(401, puente.ClaveRechazada), (409, puente.Rechazo), (422, puente.Rechazo)])
def test_errores_definitivos_no_se_reintentan(config, codigo, error):
    falsa = ApiFalsa([(codigo, {"motivo": "x"}), (200, ACEPTADA)])
    try:
        with pytest.raises(error):
            puente.enviar(puente.Api(config(falsa.url)), config(falsa.url), puente.Toque("17"))
    finally:
        falsa.cerrar()
    assert len(falsa.recibidas) == 1


def test_describir_resultados():
    assert puente.describir(ACEPTADA) == (puente.describir(ACEPTADA)[0], True)
    assert "OK" in puente.describir(ACEPTADA)[0] and "ANA QUISPE" in puente.describir(ACEPTADA)[0]
    texto, exito = puente.describir({"valido": False, "motivo": "duplicado", "nombre": "ANA"})
    assert not exito and "Ya recibió" in texto


def test_adaptador_teclado_ignora_vacias_y_traduce_no_reconocida():
    lector = adaptadores.Teclado(io.StringIO("17\n\n  42 \n-\n"))
    assert list(lector.lecturas()) == ["17", "42", None]


def test_adaptador_desconocido_corta_con_mensaje():
    with pytest.raises(SystemExit, match="Opciones"):
        adaptadores.crear("zkteco")


def test_configuracion_exige_url_y_clave(tmp_path):
    ini = tmp_path / "puente.ini"
    ini.write_text("[api]\nurl = http://x\nclave = corta\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="clave"):
        puente.Configuracion.leer(ini)
    ini.write_text(f"[api]\nurl = http://x/\nclave = {CLAVE}\n[lector]\nadaptador = prueba\n", encoding="utf-8")
    cfg = puente.Configuracion.leer(ini)
    assert (cfg.url, cfg.adaptador, cfg.pendientes) == ("http://x", "prueba", tmp_path / "pendientes.csv")
