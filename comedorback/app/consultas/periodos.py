"""Qué períodos puede consultar la pantalla de informes.

Las gestiones salen de la tabla `gestiones` del módulo heredado, que es el
calendario propio del hospital: si mañana habilitan 2027, aparece sola aquí sin
tocar código. Se ofrecen solo las marcadas como activas.

Los meses son los doce del calendario, siempre. No se leen de la tabla `meses`
a propósito: un informe se puede consultar aunque nadie haya creado la fila
del mes.

Cada mes trae su conteo de raciones para que el front pueda mostrar en blanco
los que no tienen registro, como las hojas sin llenar del cuaderno.
"""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session

from app.modelos.comedor import Asistencia
from app.modelos.heredados import Gestion

MESES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


@dataclass
class MesDisponible:
    mes: int
    nombre: str
    situacion: str
    cerrado: bool
    raciones: int


@dataclass
class GestionDisponible:
    gestion: int
    activo: bool
    situacion: str
    raciones: int
    meses: list[MesDisponible] = field(default_factory=list)


def _situacion(gestion: int, mes: int | None, hoy: date) -> str:
    """'cerrado' = ya pasó, 'curso' = es el actual, 'futuro' = no llegó.

    Es la situación del CALENDARIO, distinta de que la jefatura haya dado el
    visto bueno: eso lo dice `cerrado`.
    """
    if mes is None:
        if gestion < hoy.year:
            return "cerrado"
        return "curso" if gestion == hoy.year else "futuro"
    pedido = gestion * 12 + mes
    actual = hoy.year * 12 + hoy.month
    if pedido < actual:
        return "cerrado"
    return "curso" if pedido == actual else "futuro"


def _raciones_por_mes(sesion: Session) -> dict[tuple[int, int], int]:
    """Raciones servidas, agrupadas por (año, mes)."""
    filas = sesion.execute(
        select(
            extract("year", Asistencia.fecha_comida).label("anio"),
            extract("month", Asistencia.fecha_comida).label("mes"),
            func.count(),
        ).group_by("anio", "mes")
    ).all()
    return {(int(anio), int(mes)): int(total) for anio, mes, total in filas}


def periodos_disponibles(
    sesion: Session, hoy: date | None = None
) -> list[GestionDisponible]:
    hoy = hoy or date.today()
    raciones = _raciones_por_mes(sesion)

    gestiones = sesion.execute(
        select(Gestion.anio, Gestion.activo)
        .where(Gestion.activo == 1)
        .order_by(Gestion.anio)
    ).all()

    disponibles = []
    for anio, activo in gestiones:
        anio = int(anio)
        total_gestion = sum(
            v for (a, _m), v in raciones.items() if a == anio
        )
        # La tabla del hospital marca como activas gestiones anteriores a este
        # sistema (2023, 2024, 2025), que nunca van a tener una sola ración.
        # Ofrecerlas solo llena el selector de años vacíos. Se muestran las que
        # tienen registro y las que todavía pueden tenerlo.
        if total_gestion == 0 and anio < hoy.year:
            continue

        meses = [
            MesDisponible(
                mes=numero,
                nombre=nombre,
                situacion=_situacion(anio, numero, hoy),
                cerrado=_situacion(anio, numero, hoy) == "cerrado",
                raciones=raciones.get((anio, numero), 0),
            )
            for numero, nombre in enumerate(MESES, start=1)
        ]
        disponibles.append(
            GestionDisponible(
                gestion=anio,
                activo=bool(activo),
                situacion=_situacion(anio, None, hoy),
                raciones=total_gestion,
                meses=meses,
            )
        )
    return disponibles
