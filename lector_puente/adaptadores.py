"""Cómo se lee cada tipo de lector.

Un adaptador entrega, por cada toque de dedo, el identificador con que el
lector enroló la huella, o None si el lector no la reconoció. Para un modelo
que no escribe como teclado (SDK, red), se agrega aquí una clase con el mismo
método `lecturas()` y se elige con `[lector] adaptador` en puente.ini.
"""

import sys
from collections.abc import Iterator

NO_RECONOCIDA = "-"


class Teclado:
    """Lectores que escriben el número de usuario como un teclado y Enter
    (muchos USB y terminales en modo «keyboard wedge»). La ventana del puente
    tiene que tener el foco."""

    instrucciones = ("Listo. Mantén esta ventana activa: cada huella llega como un número. "
                     "Ctrl+C para cerrar.")

    def __init__(self, entrada=None):
        self.entrada = entrada or sys.stdin

    def lecturas(self) -> Iterator[str | None]:
        for linea in self.entrada:
            valor = linea.strip()
            if not valor:
                continue
            yield None if valor == NO_RECONOCIDA else valor


class Prueba(Teclado):
    """Para probar la cadena entera sin el aparato: se escribe a mano."""

    instrucciones = ("MODO PRUEBA. Escribe un identificador y Enter; «-» simula una huella "
                     "no reconocida. Ctrl+C para cerrar.")


ADAPTADORES = {"teclado": Teclado, "prueba": Prueba}


def crear(nombre: str):
    try:
        return ADAPTADORES[nombre]()
    except KeyError:
        raise SystemExit(
            f"Adaptador '{nombre}' desconocido. Opciones: {', '.join(ADAPTADORES)}."
        ) from None
