"""Carga los horarios de comida iniciales.

NO va en una migración, a diferencia de las columnas del formulario. Estos
horarios son una decisión del hospital, no un dato fijo: los valores de abajo
son PROVISIONALES, tomados del prototipo, y hay que confirmarlos con la jefa
de nutrición antes de usar el sistema en serio.

Una franja queda deliberadamente sin cubrir:

    10:00 - 11:00   sería Sobrealimentación

Ese tiempo de comida todavía no existe en la tabla `comidas`, que es del
módulo heredado y necesita autorización para tocarse. Mientras no esté, una
marcación en esas horas se rechaza por `fuera_horario`, que es la respuesta
honesta: el sistema no puede saber a qué fila del informe sumar esa ración.

Ejecutar con:  python -m app.semillas.horarios
"""

from datetime import date, time

from sqlalchemy import select

from app.core.db import SesionLocal
from app.modelos.comedor import HorarioComida
from app.modelos.heredados import Comida

VIGENTE_DESDE = date(2026, 1, 1)

HORARIOS = [
    ("desayuno", time(5, 30), time(10, 0)),
    ("almuerzo", time(11, 0), time(15, 0)),
    ("te", time(15, 0), time(17, 0)),
    ("cena", time(17, 0), time(23, 59, 59)),
]


def sembrar() -> None:
    sesion = SesionLocal()
    creados = 0
    try:
        for codigo, inicio, fin in HORARIOS:
            comida_id = sesion.execute(
                select(Comida.id).where(Comida.codigo == codigo)
            ).scalar_one_or_none()
            if comida_id is None:
                print(f"  falta la comida '{codigo}' en la tabla comidas — se omite")
                continue

            ya_existe = sesion.execute(
                select(HorarioComida.id).where(
                    HorarioComida.comida_id == comida_id,
                    HorarioComida.vigente_desde == VIGENTE_DESDE,
                )
            ).scalar_one_or_none()
            if ya_existe:
                print(f"  {codigo}: ya tenía horario para {VIGENTE_DESDE}")
                continue

            sesion.add(
                HorarioComida(
                    comida_id=comida_id,
                    hora_inicio=inicio,
                    hora_fin=fin,
                    vigente_desde=VIGENTE_DESDE,
                    activo=True,
                )
            )
            creados += 1
            print(f"  {codigo}: {inicio} a {fin}")
        sesion.commit()
        print(f"Horarios creados: {creados}")
    finally:
        sesion.close()


if __name__ == "__main__":
    sembrar()
