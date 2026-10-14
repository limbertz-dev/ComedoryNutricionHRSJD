"""La próxima franja de comida, para saltar el reloj de simulación a ella.

Lee solo `horarios_comida` (propia) y `v_comidas`. Una franja empieza cuando
empieza una VENTANA EFECTIVA (app/consultas/horarios.py): la intersección entre
la ocurrencia de la franja y la vigencia de su versión. Por eso una versión
guardada a las 16:00 con horario 11:00-20:00 ofrece una franja que empieza a
las 16:00, no a las 11:00 nominales, y una versión que todavía no rige en el
instante candidato no cuenta.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.consultas.horarios import ventanas_de


@dataclass(frozen=True)
class Franja:
    comida_id: int
    comida: str
    inicio: datetime


def proxima_franja(sesion: Session, momento: datetime) -> Franja | None:
    """El inicio de la próxima ventana estrictamente después de `momento`.

    Se miran las ventanas de las `fecha_comida` de ayer, hoy y mañana: ayer,
    porque una franja que cruza la medianoche puede abrirse después de
    `momento` si su versión empezó a regir recién entonces. Si no queda
    ninguna, None.
    """
    hoy = momento.date()
    un_dia = timedelta(days=1)
    candidatas = [
        (ventana.inicio, comida.comida_id, comida.comida)
        for comidas in ventanas_de(sesion, hoy - un_dia, hoy + un_dia).values()
        for comida in comidas
        for ventana in comida.ventanas
        if ventana.inicio > momento
    ]
    if not candidatas:
        return None
    inicio, comida_id, nombre = min(candidatas)
    return Franja(comida_id, nombre, inicio)
