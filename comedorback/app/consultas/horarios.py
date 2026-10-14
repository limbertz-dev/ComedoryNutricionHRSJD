"""Los horarios de comida en el tiempo: punto único de resolución.

Una versión de `horarios_comida` rige en el intervalo `[vigente_desde,
vigente_hasta)`, en instantes (DATETIME(6)), no en días. Hay dos preguntas
distintas y cada consumidor hace la suya:

  · POR INSTANTE: qué versión rige cuando ocurrió algo (una marcación, una
    lectura, la hora actual, el inicio de una franja). `rige_en`.

  · POR DÍA: en qué ventanas estuvo abierta una comida cuya `fecha_comida`
    es ese día (historial, supervisión, cierres, pendientes, no recibidas).
    `ventanas_del_dia`. Una ventana es la INTERSECCIÓN entre la ocurrencia
    de la franja y la vigencia de la versión:

        ocurrencia(v, d) = [d + hora_inicio, d + hora_fin)   (+1 día si cruza)
        ventana(v, d)    = ocurrencia(v, d) ∩ [vigente_desde, vigente_hasta)

    Las vacías se descartan y las contiguas se unen. El día `d` es la
    `fecha_comida`: la madrugada de una franja que cruza la medianoche
    pertenece al día que empezó, igual que en `resolver_comida_en_curso`.

Ejemplo: almuerzo 11:00-15:00 abierto desde enero. El día D a las 16:00 se
guarda 12:00-13:00. Las ventanas de D son solo [11:00, 15:00): la versión
nueva da `[12:00, 13:00) ∩ [16:00, ∞) = ∅`. Si en cambio se guardara
11:00-20:00 darían [11:00, 15:00) y [16:00, 20:00): la ventana nueva empieza
a las 16:00, no a las 11:00 nominales, y la anterior no se reescribe.

Por qué no basta conservar `comida_id` en la asistencia: el `comida_id` dice
qué se sirvió, pero los cierres, los pendientes y las raciones no recibidas
dependen de CUÁNDO estuvo abierta la ventana ese día.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.modelos.comedor import HorarioComida
from app.modelos.heredados import Comida


def rige_en(horario, momento):
    """Predicado SQL: el horario está activo y rige en `momento`.

    `horario` es la clase `HorarioComida`, un alias de la tabla o su `.c`;
    `momento` es un datetime o una expresión (la `fecha_hora` de una lectura).
    """
    return and_(
        horario.activo == 1,
        horario.vigente_desde <= momento,
        or_(horario.vigente_hasta.is_(None), horario.vigente_hasta > momento),
    )


def version_rige_en(version: HorarioComida, momento: datetime) -> bool:
    """El mismo predicado, sobre una fila ya cargada."""
    return (
        bool(version.activo)
        and version.vigente_desde <= momento
        and (version.vigente_hasta is None or version.vigente_hasta > momento)
    )


@dataclass(frozen=True)
class Ventana:
    inicio: datetime
    fin: datetime
    # La franja configurada de la versión que origina la ventana.
    hora_inicio: time
    hora_fin: time


@dataclass(frozen=True)
class ComidaConVentanas:
    comida_id: int
    comida: str
    ventanas: tuple[Ventana, ...]

    @property
    def ultima(self) -> Ventana:
        return self.ventanas[-1]


def ocurrencia(dia: date, hora_inicio: time, hora_fin: time) -> tuple[datetime, datetime]:
    """La franja de una versión, anclada en `dia`. Si cruza la medianoche
    (hora_fin < hora_inicio) termina al día siguiente."""
    inicio = datetime.combine(dia, hora_inicio)
    fin = datetime.combine(dia, hora_fin)
    if hora_fin < hora_inicio:
        fin += timedelta(days=1)
    return inicio, fin


def interseccion(
    dia: date,
    hora_inicio: time,
    hora_fin: time,
    vigente_desde: datetime,
    vigente_hasta: datetime | None,
) -> tuple[datetime, datetime] | None:
    """Ocurrencia ∩ vigencia, o None si no se tocan."""
    inicio, fin = ocurrencia(dia, hora_inicio, hora_fin)
    inicio = max(inicio, vigente_desde)
    if vigente_hasta is not None:
        fin = min(fin, vigente_hasta)
    return (inicio, fin) if inicio < fin else None


def _unir(ventanas: list[Ventana]) -> list[Ventana]:
    """Une las que se tocan o se superponen. La unión conserva la franja de
    la última: es la que rige al final del tramo."""
    unidas: list[Ventana] = []
    for ventana in sorted(ventanas, key=lambda v: v.inicio):
        if unidas and ventana.inicio <= unidas[-1].fin:
            previa = unidas[-1]
            unidas[-1] = Ventana(
                previa.inicio,
                max(previa.fin, ventana.fin),
                ventana.hora_inicio,
                ventana.hora_fin,
            )
        else:
            unidas.append(ventana)
    return unidas


def _versiones(sesion: Session, desde: datetime, hasta: datetime):
    """Versiones activas cuya vigencia toca `[desde, hasta)`."""
    return sesion.execute(
        select(
            HorarioComida.comida_id,
            Comida.nombre,
            HorarioComida.hora_inicio,
            HorarioComida.hora_fin,
            HorarioComida.vigente_desde,
            HorarioComida.vigente_hasta,
        )
        .join(Comida, Comida.id == HorarioComida.comida_id)
        .where(HorarioComida.activo == 1)
        .where(HorarioComida.vigente_desde < hasta)
        .where(
            or_(
                HorarioComida.vigente_hasta.is_(None),
                HorarioComida.vigente_hasta > desde,
            )
        )
        .order_by(
            HorarioComida.comida_id, HorarioComida.vigente_desde, HorarioComida.id
        )
    ).all()


def _ventanas(versiones, dia: date) -> list[ComidaConVentanas]:
    """Ventanas efectivas de cada comida para la `fecha_comida` `dia`, en
    orden cronológico por la franja de su última ventana."""
    por_comida: dict[int, tuple[str, list[Ventana]]] = {}
    for comida_id, nombre, hora_inicio, hora_fin, desde, hasta in versiones:
        cruce = interseccion(dia, hora_inicio, hora_fin, desde, hasta)
        if cruce is None:
            continue
        por_comida.setdefault(comida_id, (nombre, []))[1].append(
            Ventana(cruce[0], cruce[1], hora_inicio, hora_fin)
        )
    comidas = [
        ComidaConVentanas(comida_id, nombre, tuple(_unir(ventanas)))
        for comida_id, (nombre, ventanas) in por_comida.items()
    ]
    return sorted(comidas, key=lambda c: (c.ultima.hora_inicio, c.comida_id))


def ventanas_de(
    sesion: Session, primero: date, ultimo: date
) -> dict[date, list[ComidaConVentanas]]:
    """Las ventanas de cada `fecha_comida` de `primero` a `ultimo`, con una
    sola consulta. Una franja anclada en `d` termina antes de `d + 2 días`."""
    versiones = _versiones(
        sesion,
        datetime.combine(primero, time.min),
        datetime.combine(ultimo + timedelta(days=2), time.min),
    )
    dias = (ultimo - primero).days + 1
    return {
        dia: _ventanas(versiones, dia)
        for dia in (primero + timedelta(days=n) for n in range(dias))
    }


def ventanas_del_dia(sesion: Session, dia: date) -> list[ComidaConVentanas]:
    return ventanas_de(sesion, dia, dia)[dia]


def fines_de_ventana(sesion: Session, dia: date) -> dict[int, datetime]:
    """Cuándo cierra la última ventana de cada comida de `dia`.

    Una comida sin ventana ese día no aparece: sus raciones quedan pendientes
    en vez de contarse como no recibidas, porque no hay forma de saber si la
    ventana ya pasó.
    """
    return {c.comida_id: c.ultima.fin for c in ventanas_del_dia(sesion, dia)}


def estado_en(ventanas: tuple[Ventana, ...], ahora: datetime) -> str:
    """Dónde está la comida respecto a `ahora`: en_curso si `ahora` cae en una
    ventana; si no, pendiente si alguna empieza después; si no, cerrada."""
    if any(v.inicio <= ahora < v.fin for v in ventanas):
        return "en_curso"
    if any(v.inicio > ahora for v in ventanas):
        return "pendiente"
    return "cerrada"
