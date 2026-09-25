"""El reloj único del servidor. Toda la aplicación lee la hora de acá.

Dos horas, a propósito distintas:

  · ahora() / hoy()       la hora del NEGOCIO: marcación, pantalla, historial,
                          informes. Es la real salvo que se haya fijado otra
                          desde /simulacion/reloj (solo con ENTORNO=simulacion;
                          ver app/api/simulacion.py).
  · real() / real_utc()   la hora del servidor, siempre. La usan el bloqueo
                          de login y los JWT: si siguieran al reloj simulado,
                          moverlo podría vencer tokens o levantar bloqueos.

Fijar el reloj guarda un DESFASE contra la hora real, así que el reloj sigue
corriendo desde el momento fijado; con `congelar=True` se queda quieto.

El estado vive en la memoria del proceso: al reiniciar la API vuelve solo a
la hora real, y no hace falta ninguna tabla que llegue a producción. Por lo
mismo, en simulación la API corre con UN solo worker de uvicorn: con varios,
cada uno tendría su propio reloj.

Hora local sin zona, como el resto de las tablas.
"""

import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

_candado = threading.Lock()
_desfase: timedelta | None = None
_congelado: datetime | None = None


@dataclass(frozen=True)
class EstadoReloj:
    ahora: datetime
    real: datetime
    simulado: bool
    congelado: bool


def real() -> datetime:
    """La hora del servidor, nunca simulada."""
    return datetime.now()


def real_utc() -> datetime:
    """La hora del servidor con zona UTC, para los JWT."""
    return datetime.now(timezone.utc)


def ahora() -> datetime:
    """La hora del negocio. Sin simulación es exactamente `datetime.now()`."""
    with _candado:
        desfase, congelado = _desfase, _congelado
    if congelado is not None:
        return congelado
    actual = real()
    return actual if desfase is None else actual + desfase


def hoy() -> date:
    return ahora().date()


def _local(momento: datetime) -> datetime:
    """Un momento con zona se pasa a la hora local del servidor, sin zona."""
    if momento.tzinfo is None:
        return momento
    return momento.astimezone().replace(tzinfo=None)


def fijar(momento: datetime, congelar: bool = False) -> None:
    global _desfase, _congelado
    momento = _local(momento)
    with _candado:
        if congelar:
            _congelado, _desfase = momento, None
        else:
            _congelado, _desfase = None, momento - real()


def avanzar(cuanto: timedelta) -> None:
    """Suma `cuanto` al reloj. Sin fijar, empieza a simular desde la real."""
    global _desfase, _congelado
    with _candado:
        if _congelado is not None:
            _congelado += cuanto
        else:
            _desfase = (_desfase or timedelta()) + cuanto


def volver_a_real() -> None:
    global _desfase, _congelado
    with _candado:
        _desfase = _congelado = None


def estado() -> EstadoReloj:
    with _candado:
        simulado = _desfase is not None or _congelado is not None
        congelado = _congelado is not None
    return EstadoReloj(ahora=ahora(), real=real(), simulado=simulado, congelado=congelado)
