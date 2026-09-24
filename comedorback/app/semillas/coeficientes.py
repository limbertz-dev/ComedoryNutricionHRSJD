"""Carga los coeficientes que reducen cada tiempo de comida a ración completa.

Son los impresos en el formulario del Servicio de Estadística. No van en una
migración, a diferencia de las columnas del formulario, porque se guardan por
`comida_id` y ese id es de la base de turnos: la migración no puede depender
de datos de otra base. Acá se resuelven por `codigo` a través de v_comidas.

Cada fila es la PRIMERA versión del coeficiente de su comida. Si la jefatura
lo cambia, no se edita esta fila: se cierra con `vigente_hasta` y se inserta
otra, para que los informes ya firmados sigan dando el mismo número.

Idempotente: una comida que ya tiene coeficiente para VIGENTE_DESDE se omite.

Ejecutar con:  python -m app.semillas.coeficientes
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.core.db import SesionLocal
from app.modelos.comedor import CoeficienteRacion
from app.modelos.heredados import Comida

VIGENTE_DESDE = date(2026, 1, 1)

COEFICIENTES = [
    ("desayuno", Decimal("0.150")),
    ("almuerzo", Decimal("0.500")),
    ("te", Decimal("0.050")),
    ("cena", Decimal("0.300")),
]


def sembrar() -> None:
    sesion = SesionLocal()
    creados = 0
    try:
        for codigo, coeficiente in COEFICIENTES:
            comida_id = sesion.execute(
                select(Comida.id).where(Comida.codigo == codigo)
            ).scalar_one_or_none()
            if comida_id is None:
                print(f"  falta la comida '{codigo}' en v_comidas — se omite")
                continue

            ya_existe = sesion.execute(
                select(CoeficienteRacion.id).where(
                    CoeficienteRacion.comida_id == comida_id,
                    CoeficienteRacion.vigente_desde == VIGENTE_DESDE,
                )
            ).scalar_one_or_none()
            if ya_existe:
                print(f"  {codigo}: ya tenía coeficiente para {VIGENTE_DESDE}")
                continue

            sesion.add(
                CoeficienteRacion(
                    comida_id=comida_id,
                    coeficiente=coeficiente,
                    vigente_desde=VIGENTE_DESDE,
                )
            )
            creados += 1
            print(f"  {codigo}: {coeficiente}")
        sesion.commit()
        print(f"Coeficientes creados: {creados}")
    finally:
        sesion.close()


if __name__ == "__main__":
    sembrar()
