"""La próxima franja de comida, para saltar el reloj de simulación a ella.

Lee solo `horarios_comida` (propia) y `v_comidas`. Aplica la misma vigencia
que `resolver_comida_en_curso` (app/logica/marcacion.py): horario activo,
vigente ese día y, si una comida tiene más de un horario vigente, el de
`vigente_desde` más reciente.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.modelos.comedor import HorarioComida
from app.modelos.heredados import Comida


@dataclass(frozen=True)
class Franja:
    comida_id: int
    comida: str
    inicio: datetime


def _inicios_del_dia(sesion: Session, dia: date) -> list[tuple[time, int, str]]:
    """(hora_inicio, comida_id, nombre) de cada comida que rige ese día."""
    filas = sesion.execute(
        select(HorarioComida.comida_id, Comida.nombre, HorarioComida.hora_inicio)
        .join(Comida, Comida.id == HorarioComida.comida_id)
        .where(HorarioComida.activo == 1)
        .where(HorarioComida.vigente_desde <= dia)
        .where(
            or_(
                HorarioComida.vigente_hasta.is_(None),
                HorarioComida.vigente_hasta >= dia,
            )
        )
        .order_by(HorarioComida.vigente_desde.desc())
    ).all()
    vigentes: dict[int, tuple[time, int, str]] = {}
    for comida_id, nombre, inicio in filas:
        vigentes.setdefault(comida_id, (inicio, comida_id, nombre))
    return sorted(vigentes.values())


def proxima_franja(sesion: Session, momento: datetime) -> Franja | None:
    """El inicio de la próxima franja estrictamente después de `momento`.

    Si hoy no queda ninguna, la primera de mañana. None si mañana tampoco
    rige ningún horario.
    """
    hoy = momento.date()
    for inicio, comida_id, nombre in _inicios_del_dia(sesion, hoy):
        if inicio > momento.time():
            return Franja(comida_id, nombre, datetime.combine(hoy, inicio))

    manana = hoy + timedelta(days=1)
    inicios = _inicios_del_dia(sesion, manana)
    if not inicios:
        return None
    inicio, comida_id, nombre = inicios[0]
    return Franja(comida_id, nombre, datetime.combine(manana, inicio))
