"""Adaptador ZKTeco y enrolamiento contra un SDK falso con la misma interfaz
que SdkZK (el aparato real no está en las pruebas)."""

import itertools

import pytest

import adaptadores
import enrolar
from zkteco import ZKTeco


class SdkFalso:
    """Plantillas = textos; identifica por igualdad con las cargadas."""

    def __init__(self, capturas):
        self.capturas = list(capturas)  # None = sin dedo
        self.cargadas: dict[int, str] = {}
        self.luces = []
        self.abierto = self.cerrado = False
        self.cargas = 0

    def abrir(self):
        self.abierto = True

    def cerrar(self):
        self.cerrado = True

    def luz(self, color):
        self.luces.append(color)

    def capturar(self):
        return self.capturas.pop(0) if self.capturas else None

    def cargar(self, plantillas):
        self.cargas += 1
        self.cargadas = {p["id"]: p["plantilla"] for p in plantillas}
        return len(self.cargadas)

    def identificar(self, plantilla):
        return next((fid for fid, t in self.cargadas.items() if t == plantilla), None)

    def coinciden(self, a, b):
        return a == b

    def unir(self, t1, t2, t3):
        return f"unida:{t1}"


class ApiFalsa:
    def __init__(self, plantillas, falla=False):
        self.lista = plantillas
        self.falla = falla
        self.pedidas = 0

    def plantillas(self):
        self.pedidas += 1
        if self.falla:
            raise OSError("sin red")
        return self.lista


PLANTILLAS = [{"id": 7, "identificador": "zk-ana", "plantilla": "ANA"},
              {"id": 9, "identificador": "zk-pol", "plantilla": "POL"}]


def _adaptador(sdk, api, **extra):
    reloj = itertools.count()
    return ZKTeco(api, sdk=sdk, dormir=lambda _s: None, reloj=lambda: next(reloj),
                  avisar=lambda *_: None, **extra)


def test_reconoce_conocidas_y_no_reconocidas():
    sdk = SdkFalso([None, "ANA", None, "XXX", "POL"])
    lector = _adaptador(sdk, ApiFalsa(PLANTILLAS), recarga_segundos=1000)
    lecturas = lector.lecturas()
    assert [next(lecturas) for _ in range(3)] == ["zk-ana", None, "zk-pol"]
    assert sdk.abierto and sdk.luces[-3:] == ["green", "red", "green"]
    lecturas.close()
    assert sdk.cerrado


def test_recarga_las_plantillas_periodicamente():
    sdk = SdkFalso(["ANA"] * 5)
    api = ApiFalsa(PLANTILLAS)
    lecturas = _adaptador(sdk, api, recarga_segundos=2).lecturas()
    for _ in range(4):
        next(lecturas)
    assert api.pedidas >= 2


def test_sin_api_sigue_con_las_ya_cargadas():
    sdk = SdkFalso(["ANA"])
    lector = _adaptador(sdk, ApiFalsa(PLANTILLAS), recarga_segundos=1000)
    lector._cargar = lector._cargar  # primera carga normal
    lecturas = lector.lecturas()
    assert next(lecturas) == "zk-ana"
    lector.api.falla = True
    lector._cargar()
    assert lector.mapa == {7: "zk-ana", 9: "zk-pol"}


def test_adaptador_zkteco_se_elige_por_nombre():
    lector = adaptadores.crear("zkteco", api=ApiFalsa([]))
    assert isinstance(lector, ZKTeco)


# --- enrolamiento ----------------------------------------------------------------


def _enrolar(capturas, actuales=(), respuestas=()):
    sdk = SdkFalso(capturas)
    pedidas = iter(respuestas)
    return enrolar.enrolar(sdk, list(actuales), avisar=lambda *_: None,
                           pedir=lambda _p: next(pedidas), dormir=lambda _s: None), sdk


def test_tres_capturas_del_mismo_dedo_dan_una_plantilla():
    # Cada captura va seguida de "sin dedo" (el dedo se retira).
    plantilla, _ = _enrolar(["NUEVA", None, "NUEVA", None, "NUEVA", None])
    assert plantilla == "unida:NUEVA"


def test_dedo_ya_enrolado_no_se_duplica():
    plantilla, sdk = _enrolar(["ANA", None], actuales=PLANTILLAS)
    assert plantilla is None and sdk.luces[-1] == "red"


def test_dedo_distinto_reinicia_o_cancela():
    plantilla, _ = _enrolar(["A", None, "B", None], respuestas=["n"])
    assert plantilla is None
    plantilla, _ = _enrolar(["A", None, "B", None, "C", None, "C", None, "C", None], respuestas=["s"])
    assert plantilla == "unida:C"


@pytest.mark.parametrize("nombre", ["teclado", "prueba"])
def test_adaptadores_de_teclado_no_necesitan_sdk(nombre):
    assert adaptadores.crear(nombre).lecturas
