"""El entorno efectivo: el de la app que atiende la petición.

`crear_app(entorno)` (app/main.py) lo valida y lo guarda en `app.state.entorno`
al armar la API. Desde ahí, todo lo que dependa del entorno en una petición
lo lee con `EntornoDep`, nunca de `config.entorno`:

  · `config.entorno` (ENTORNO en .env) es solo el valor por omisión con que
    se arma la app del proceso. Los tests arman apps de los tres entornos en
    un mismo proceso; si una decisión leyera `config`, una app de producción
    podría comportarse como simulación o al revés.
  · Sale del arranque, no de la petición: ningún parámetro, cabecera ni
    cuerpo del cliente lo puede elegir.

Lo usan /salud, /monitoreo/estado y la regla de origen de la marcación
biométrica (app/core/autorizacion.py), así los tres dicen lo mismo.
"""

from typing import Annotated, get_args

from fastapi import Depends, Request

from app.core.config import Entorno

ENTORNOS: tuple[str, ...] = get_args(Entorno)


def validar_entorno(entorno: str) -> str:
    """Corta el arranque con un entorno que no existe, en vez de armar una
    app que no sea ni producción ni simulación."""
    if entorno not in ENTORNOS:
        raise ValueError(f"Entorno desconocido: {entorno!r}. Valores: {', '.join(ENTORNOS)}.")
    return entorno


def entorno_efectivo(request: Request) -> str:
    """El entorno con que se armó la app que atiende esta petición."""
    return request.app.state.entorno


EntornoDep = Annotated[str, Depends(entorno_efectivo)]
