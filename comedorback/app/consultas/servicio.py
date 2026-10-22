"""El servicio: qué comida, de qué fecha_comida y en qué ventana efectiva.

Una lectura `no_identificado` solo se puede resolver dentro del MISMO servicio
en el que se leyó. Comparar solo `comida_id` no alcanza: el almuerzo de ayer y
el de hoy tienen la misma comida y son servicios distintos, y un almuerzo
cortado por un cambio de horario son dos ventanas del mismo día.

Un servicio es la terna `(comida_id, fecha_comida, ventana)`, con la ventana
tal como la define app/consultas/horarios.py: la intersección entre la
ocurrencia de la franja y la vigencia de cada versión ACTIVA, con las
contiguas unidas. La misma `Ventana` tiene que contener el instante de la
lectura y el de ahora; un solo cómputo decide los dos, así no se comparan
estructuras calculadas en momentos distintos.

`lecturas_biometricas` NO guarda comida ni fecha_comida (modelos/comedor.py).
El servicio de una lectura es entonces una RECONSTRUCCIÓN por horario con las
versiones almacenadas hoy; no es un dato histórico de la lectura. Por eso todo
lo que no se puede afirmar falla cerrado:

    reloj_inconsistente        ahora < lectura.fecha_hora (reloj retrocedido)
    servicio_no_determinable   ninguna ventana contiene la lectura, o más de
                               una (franjas superpuestas heredadas, una
                               versión pasada a activo=0), o las dos formas
                               de resolver la comida en curso discrepan
    servicio_distinto          ahora cae fuera de esa ventana: otra comida,
                               otra fecha_comida, otra ventana, o cerrado

Medianoche: la madrugada de una franja que cruza pertenece a la fecha_comida
que empezó, así que para un instante `t` se miran las fecha_comida `t.date()
- 1` y `t.date()`.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.consultas.horarios import ComidaConVentanas, ventanas_del_dia, interseccion
from app.logica.marcacion import ComidaEnCurso, resolver_comida_en_curso
from app.modelos.comedor import HorarioComida
from app.modelos.heredados import Comida

RELOJ_INCONSISTENTE = "reloj_inconsistente"
SERVICIO_NO_DETERMINABLE = "servicio_no_determinable"
SERVICIO_DISTINTO = "servicio_distinto"


def comida_de_referencia(sesion: Session, momento: datetime) -> ComidaEnCurso | None:
    """Comida vigente o ultima ventana cerrada. Solo contexto, nunca permiso."""
    vigente = resolver_comida_en_curso(sesion, momento)
    if vigente is not None:
        return vigente
    versiones = sesion.execute(select(HorarioComida, Comida.nombre).join(
        Comida, Comida.id == HorarioComida.comida_id).where(
        HorarioComida.activo == 1, Comida.estado == 1, HorarioComida.vigente_desde <= momento)).all()
    cerradas = []
    for horario, nombre in versiones:
        limite = min(momento, horario.vigente_hasta) if horario.vigente_hasta else momento
        for dia in (limite.date(), limite.date() - timedelta(days=1)):
            ventana = interseccion(dia, horario.hora_inicio, horario.hora_fin,
                                   horario.vigente_desde, horario.vigente_hasta)
            if ventana is not None and ventana[1] <= momento:
                cerradas.append((ventana[1], ventana[0], horario.comida_id, nombre, dia))
    if not cerradas:
        return None
    _, _, comida_id, nombre, dia = max(cerradas)
    return ComidaEnCurso(comida_id=comida_id, comida=nombre, fecha_comida=dia)


@dataclass(frozen=True)
class Servicio:
    comida_id: int
    comida: str
    fecha_comida: date
    inicio: datetime
    fin: datetime


@dataclass(frozen=True)
class EvaluacionServicio:
    """`servicio` es el de la lectura cuando se pudo determinar, aunque el
    motivo sea `servicio_distinto`: la auditoría guarda qué servicio usó el
    sistema. `motivo` es None si la lectura es resoluble ahora."""

    servicio: Servicio | None
    motivo: str | None


class VentanasDelDia:
    """Las ventanas de cada fecha_comida, con una consulta por día y no más.

    Una instancia vive lo que dura una petición. Solo lee `horarios_comida`
    (tabla propia) y el catálogo de comidas, sin ningún bloqueo.
    """

    def __init__(self, sesion: Session):
        self._sesion = sesion
        self._por_dia: dict[date, list[ComidaConVentanas]] = {}

    def del_dia(self, dia: date) -> list[ComidaConVentanas]:
        if dia not in self._por_dia:
            self._por_dia[dia] = ventanas_del_dia(self._sesion, dia)
        return self._por_dia[dia]

    def servicios_en(self, instante: datetime) -> list[Servicio]:
        """Todos los servicios cuya ventana contiene `instante`."""
        encontrados: list[Servicio] = []
        for dia in (instante.date() - timedelta(days=1), instante.date()):
            for comida in self.del_dia(dia):
                for ventana in comida.ventanas:
                    if ventana.inicio <= instante < ventana.fin:
                        encontrados.append(
                            Servicio(
                                comida_id=comida.comida_id,
                                comida=comida.comida,
                                fecha_comida=dia,
                                inicio=ventana.inicio,
                                fin=ventana.fin,
                            )
                        )
        return encontrados


def evaluar_servicio(
    sesion: Session,
    ventanas: VentanasDelDia,
    momento_lectura: datetime,
    ahora: datetime,
) -> EvaluacionServicio:
    """¿La lectura de `momento_lectura` pertenece al servicio de `ahora`?"""
    if ahora < momento_lectura:
        return EvaluacionServicio(None, RELOJ_INCONSISTENTE)

    de_la_lectura = ventanas.servicios_en(momento_lectura)
    if len(de_la_lectura) != 1:
        return EvaluacionServicio(None, SERVICIO_NO_DETERMINABLE)
    servicio = de_la_lectura[0]

    de_ahora = ventanas.servicios_en(ahora)
    if not de_ahora:
        return EvaluacionServicio(servicio, SERVICIO_DISTINTO)
    if len(de_ahora) != 1:
        return EvaluacionServicio(servicio, SERVICIO_NO_DETERMINABLE)
    if de_ahora[0] != servicio:
        return EvaluacionServicio(servicio, SERVICIO_DISTINTO)

    # La ración nace con la comida y la fecha que da `resolver_comida_en_curso`
    # (marcacion.py). Si las dos formas de resolverla discrepan, no se afirma.
    en_curso = resolver_comida_en_curso(sesion, ahora)
    if (
        en_curso is None
        or en_curso.comida_id != servicio.comida_id
        or en_curso.fecha_comida != servicio.fecha_comida
    ):
        return EvaluacionServicio(servicio, SERVICIO_NO_DETERMINABLE)
    return EvaluacionServicio(servicio, None)
