"""Qué períodos puede consultar la pantalla de informes.

Las gestiones salen de los propios datos del comedor: el año en curso más
todo año que tenga al menos una ración registrada. No se lee la tabla
`gestiones` del módulo de turnos: no forma parte del contrato de vistas v_*.
Con los datos actuales el resultado es el mismo que daba el filtro viejo
(gestiones activas, descartando las pasadas sin raciones): las futuras
figuran inactivas. La única diferencia es que un año que el hospital
habilite por adelantado ya no aparece antes de empezar: aparece solo el 1 de
enero, sin tocar código.

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

    # Años sin ninguna ración anteriores al actual no se ofrecen: solo
    # llenarían el selector de años vacíos.
    gestiones = sorted({anio for anio, _mes in raciones} | {hoy.year})

    disponibles = []
    for anio in gestiones:
        total_gestion = sum(
            v for (a, _m), v in raciones.items() if a == anio
        )

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
                activo=True,
                situacion=_situacion(anio, None, hoy),
                raciones=total_gestion,
                meses=meses,
            )
        )
    return disponibles
