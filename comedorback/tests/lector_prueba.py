"""Lector biométrico de prueba.

POST /asistencias rechaza el biométrico que declara una sesión (403
`biometrico_solo_lector`): solo un lector autorizado registra lecturas. Las
pruebas que necesitan lecturas las registran como lo haría ese lector, con
la misma lógica de marcación (app/logica/marcacion.py), y reciben el mismo
cuerpo que devuelve la API.
"""

from app.core.db import SesionLocal
from app.esquemas.marcacion import RespuestaMarcacion
from app.logica import marcacion

DISPOSITIVO = "lector-de-prueba"


class LectorDePrueba:
    def leer(self, usuario_id: int | None = None, dispositivo: str = DISPOSITIVO) -> dict:
        """Una lectura con la hora de `reloj.ahora()`; `usuario_id=None` es una
        huella que el lector no reconoce."""
        with SesionLocal() as sesion:
            resultado = marcacion.registrar_marcacion(
                sesion,
                usuario_id=usuario_id,
                dispositivo=dispositivo,
                metodo="biometrico",
            )
        return RespuestaMarcacion(**vars(resultado)).model_dump(mode="json")
