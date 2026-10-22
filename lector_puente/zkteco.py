"""Lectores USB ZKTeco ZK9500 / ZK4500 con el SDK ZKFinger.

Estos lectores solo CAPTURAN la huella: no la reconocen ni escriben un número.
La comparación 1:N la hace el SDK en la PC, contra las plantillas que el
puente carga de la API (GET /lector/plantillas). El `fid` de cada plantilla en
el SDK es el id de su vínculo; con él se obtiene el identificador que se manda
a POST /lector/lecturas, como con cualquier otro lector.

Requisitos en la PC de cocina (solo para este adaptador):
  1. Driver y SDK «ZKFinger SDK for Windows» de ZKTeco instalados.
  2. `pip install pyzkfp` (usa pythonnet y la libzkfpcsharp.dll del SDK).

`SdkZK` es la ÚNICA clase que habla con el aparato. Si el modelo se comporta
distinto de lo esperado, se ajusta acá; el resto del puente no cambia.
"""

import base64
import time
from collections.abc import Iterator


class LectorNoDisponible(SystemExit):
    """El SDK o el aparato no responden: se corta con un mensaje claro."""


class SdkZK:
    """Envoltura mínima de pyzkfp.ZKFP2."""

    def __init__(self):
        try:
            from pyzkfp import ZKFP2
        except Exception as error:  # noqa: BLE001 - ImportError o falta de la DLL / .NET
            raise LectorNoDisponible(
                "No se pudo cargar el SDK ZKFinger. Instala el «ZKFinger SDK for Windows» "
                f"de ZKTeco y luego `pip install pyzkfp`. Detalle: {error}"
            ) from None
        self._ZKFP2 = ZKFP2
        self.zk = ZKFP2()

    def abrir(self) -> None:
        try:
            self.zk.Init()
        except Exception as error:  # noqa: BLE001 - .NET lanza DllNotFoundException, no ImportError
            if "libzkfp" in str(error):
                raise LectorNoDisponible(
                    "Falta libzkfp.dll: instala el «ZKFinger SDK for Windows» de ZKTeco "
                    "(trae el driver del ZK9500/ZK4500) y vuelve a abrir el puente."
                ) from None
            raise LectorNoDisponible(f"El SDK ZKFinger no pudo iniciar: {error}") from None
        if self.zk.GetDeviceCount() < 1:
            raise LectorNoDisponible(
                "No se detecta ningún lector ZKTeco. Revisa el cable USB y que el driver esté instalado."
            )
        self.zk.OpenDevice(0)
        self.luz("green")

    def cerrar(self) -> None:
        try:
            self.zk.CloseDevice()
            self.zk.Terminate()
        except Exception:  # noqa: BLE001 - al cerrar no hay nada que hacer con el error
            pass

    def luz(self, color: str) -> None:
        try:
            self.zk.Light(color)
        except Exception:  # noqa: BLE001 - la luz es cosmética; algunos modelos no la tienen
            pass

    def capturar(self):
        """La plantilla del dedo apoyado, o None si no hay dedo."""
        captura = self.zk.AcquireFingerprint()
        return captura[0] if captura else None

    def cargar(self, plantillas: list[dict]) -> int:
        self.zk.DBClear()
        cargadas = 0
        for p in plantillas:
            self.zk.DBAdd(p["id"], self.zk.Base64String2Blob(p["plantilla"]))
            cargadas += 1
        return cargadas

    def identificar(self, plantilla) -> int | None:
        fid, _puntaje = self.zk.DBIdentify(plantilla)
        return fid if fid and fid > 0 else None

    def coinciden(self, a, b) -> bool:
        return self.zk.DBMatch(a, b) > 0

    def unir(self, t1, t2, t3) -> str:
        """Las tres capturas del enrolamiento en una plantilla, en base64."""
        regtemp, largo = self.zk.DBMerge(t1, t2, t3)
        return base64.b64encode(bytes(regtemp)[:largo]).decode("ascii")


class ZKTeco:
    """Adaptador del puente: entrega el identificador de cada huella reconocida
    o None si no coincide con ninguna enrolada."""

    instrucciones = ("Listo. Lector ZKTeco conectado: apoyar el dedo y retirarlo. "
                     "Ctrl+C para cerrar.")

    def __init__(self, api, sdk=None, recarga_segundos=60.0, pausa=1.5,
                 dormir=time.sleep, reloj=time.monotonic, avisar=print):
        self.api = api
        self.sdk = sdk
        self.recarga = recarga_segundos
        self.pausa = pausa
        self.dormir = dormir
        self.reloj = reloj
        self.avisar = avisar
        self.mapa: dict[int, str] = {}
        self._cargado = None

    def _cargar(self) -> None:
        try:
            plantillas = self.api.plantillas()
        except Exception as error:  # noqa: BLE001 - sin API se sigue con las que ya están
            self.avisar(f"!! No se pudieron actualizar las huellas ({error}). Se usan las cargadas.")
            self._cargado = self.reloj()
            return
        self.sdk.cargar(plantillas)
        self.mapa = {p["id"]: p["identificador"] for p in plantillas}
        if self._cargado is None:
            self.avisar(f"{len(self.mapa)} huellas cargadas en el lector.")
        self._cargado = self.reloj()

    def lecturas(self) -> Iterator[str | None]:
        if self.sdk is None:
            self.sdk = SdkZK()
        self.sdk.abrir()
        try:
            self._cargar()
            while True:
                if self.reloj() - self._cargado >= self.recarga:
                    self._cargar()
                plantilla = self.sdk.capturar()
                if plantilla is None:
                    self.dormir(0.15)
                    continue
                identificador = self.mapa.get(self.sdk.identificar(plantilla))
                self.sdk.luz("green" if identificador else "red")
                yield identificador
                # Un dedo que se queda apoyado no debe contar dos veces.
                self.dormir(self.pausa)
        finally:
            self.sdk.cerrar()
