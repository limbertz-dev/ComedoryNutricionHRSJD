"""Reloj fijo para las pruebas.

La aplicación lee la hora con `reloj.ahora()` / `reloj.hoy()`
(app/core/reloj.py). Las pruebas que dependen de un instante exacto lo fijan
acá; el fixture `reloj_real` de conftest.py lo devuelve a la hora real
después de cada prueba. `reloj.real()` (login y JWT) no se toca.
"""

from datetime import datetime

from app.core import reloj

_ahora_real = reloj.ahora


def fijar(momento: datetime, corriendo: bool = False) -> None:
    """Desde ahora `reloj.ahora()` devuelve `momento`: quieto, o avanzando
    desde ahí al ritmo real con `corriendo=True`."""
    if momento.tzinfo is not None:
        momento = momento.astimezone().replace(tzinfo=None)
    if not corriendo:
        reloj.ahora = lambda: momento
        return
    desfase = momento - reloj.real()
    reloj.ahora = lambda: reloj.real() + desfase


def liberar() -> None:
    """Vuelve a la hora real."""
    reloj.ahora = _ahora_real
