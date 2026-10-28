"""Carga los horarios de comida iniciales.

NO va en una migración, a diferencia de las columnas del formulario. Estos
horarios son una decisión del hospital, no un dato fijo: después se cambian
desde «Reglas del sistema», con vigencia.

Los valores de abajo son el horario observado en el comedor (27/10/2026),
en hora de Tarija, con 30 minutos de margen a cada lado para que nadie
quede fuera por llegar unos minutos antes o después:

    Desayuno   08:00 - 09:00   →  07:30 - 09:30
    Almuerzo   12:00 - 14:00   →  11:30 - 14:30
    Té         16:00 - 17:00   →  15:30 - 17:30
    Cena       18:00 - 18:45   →  17:30 - 19:15

Fuera de esas franjas no hay comida en curso: la marcación se rechaza por
`fuera_horario` y el checklist de cocina no muestra lista.

La semilla es un punto de partida, nunca una corrección de lo configurado:

  · No inserta nada sobre una comida que ya tiene CUALQUIER versión de
    horario (activa, cerrada o inactiva): esa configuración es de root.
  · No inserta una franja que se superponga con la de otra comida que rija
    en el período que la semilla cubriría (desde VIGENTE_DESDE en adelante);
    avisa y la omite.
  · Toma el mismo cerrojo que el guardado por API (tabla `cerrojos`), como
    primera sentencia de su transacción: no corre en paralelo con un cambio.

Ejecutar con:  python -m app.semillas.horarios
"""

from datetime import date, datetime, time

from sqlalchemy import select

from app.core.db import SesionLocal
from app.logica.reglas import franjas_se_solapan
from app.modelos.comedor import CERROJO_HORARIOS, Cerrojo, HorarioComida
from app.modelos.heredados import Comida

VIGENTE_DESDE = date(2026, 1, 1)

HORARIOS = [
    ("desayuno", time(7, 30), time(9, 30)),
    ("almuerzo", time(11, 30), time(14, 30)),
    ("te", time(15, 30), time(17, 30)),
    ("cena", time(17, 30), time(19, 15)),
]


def sembrar() -> None:
    sesion = SesionLocal()
    creados = 0
    try:
        cerrojo = sesion.execute(
            select(Cerrojo.nombre)
            .where(Cerrojo.nombre == CERROJO_HORARIOS)
            .with_for_update()
        ).scalar_one_or_none()
        if cerrojo is None:
            raise RuntimeError("Falta el cerrojo de horarios: aplique las migraciones.")

        desde = datetime.combine(VIGENTE_DESDE, time.min)
        existentes = list(
            sesion.execute(
                select(HorarioComida)
                .order_by(HorarioComida.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            .scalars()
            .all()
        )
        for codigo, inicio, fin in HORARIOS:
            comida_id = sesion.execute(
                select(Comida.id).where(Comida.codigo == codigo)
            ).scalar_one_or_none()
            if comida_id is None:
                print(f"  falta la comida '{codigo}' en v_comidas — se omite")
                continue

            if any(h.comida_id == comida_id for h in existentes):
                print(f"  {codigo}: ya tiene horarios configurados — no se toca")
                continue

            choque = next(
                (
                    h
                    for h in existentes
                    if h.activo
                    and h.comida_id != comida_id
                    and (h.vigente_hasta is None or h.vigente_hasta > desde)
                    and franjas_se_solapan(inicio, fin, h.hora_inicio, h.hora_fin)
                ),
                None,
            )
            if choque is not None:
                print(
                    f"  {codigo}: {inicio} a {fin} se superpone con otra comida "
                    f"(comida_id={choque.comida_id}) — se omite"
                )
                continue

            nuevo = HorarioComida(
                comida_id=comida_id,
                hora_inicio=inicio,
                hora_fin=fin,
                vigente_desde=desde,
                activo=True,
            )
            sesion.add(nuevo)
            existentes.append(nuevo)
            creados += 1
            print(f"  {codigo}: {inicio} a {fin}")
        sesion.commit()
        print(f"Horarios creados: {creados}")
    finally:
        sesion.close()


if __name__ == "__main__":
    sembrar()
