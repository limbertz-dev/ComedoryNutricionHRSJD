"""El derecho a comer.

No existe ninguna tabla que lo guarde: sale de cruzar `turnos_asignados` con
`turno_comida`. Es la misma consulta que ya hace la vista
`vw_personal_comidas_externo` del módulo heredado.

La pieza clave es `fecha_comida`:

    fecha_comida = turnos_asignados.fecha + turno_comida.dia_relativo

Sale del derecho, nunca del reloj. Es lo que permite que una guardia de 32
horas reciba DOS desayunos —en fechas distintas— sin chocar con la clave única
de la ración, y a la vez que dos intentos de la misma comida sí choquen.

Para que una asignación dé derecho tiene que cumplir DOS condiciones, además
de estar mapeada en turno_comida:

  1. El turno dura 12 horas o más. Es la política del hospital: un turno corto
     no genera derecho a comida.
  2. No hay una novedad que lo anule (permiso, baja, vacación, licencia).
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modelos.heredados import (
    Categoria,
    Comida,
    NovedadLaboral,
    TurnoAsignado,
    TurnoComida,
    Turno,
    Usuario,
)

# Un permiso, una baja, una vacación o una licencia anulan el derecho de esa
# asignación. `devolucion_turno` NO está en la lista: es un cambio entre
# compañeros, no una ausencia.
#
# PENDIENTE: cuando hay reemplazo (novedades_laborales.usuario_reemplazo_id),
# el derecho debería pasar al que cubre el turno. No está implementado porque
# primero hay que confirmar con el hospital cómo usan esa columna en la
# práctica; hoy solo hay 5 filas en la tabla.
NOVEDADES_QUE_ANULAN = ("permiso", "baja_medica", "vacacion", "licencia")

# Un turno corto no da derecho a comida: es política del hospital.
#
# El umbral filtra 49 de los 76 turnos cargados. Se compara contra
# `turnos.duracion_horas`, que es el dato que declara el hospital, y NO contra
# hora_inicio/hora_fin: en los turnos largos esas dos columnas no reflejan la
# duración real (el turno 90 dura 30 horas y figura como 6:00-12:00).
DURACION_MINIMA_HORAS = 12
PATRON_CATEGORIA_ENFERMERIA = "%enfermer%"

_FECHA_COMIDA = func.adddate(TurnoAsignado.fecha, TurnoComida.dia_relativo)


def no_es_enfermeria():
    return ~Categoria.nombre.ilike(PATRON_CATEGORIA_ENFERMERIA)


def sin_novedad():
    """Que no haya un permiso, baja, vacación o licencia sobre la asignación."""
    return ~select(NovedadLaboral.id).where(
        NovedadLaboral.asignacion_id == TurnoAsignado.id,
        NovedadLaboral.tipo_novedad.in_(NOVEDADES_QUE_ANULAN),
    ).exists()


def aplicar_reglas(consulta):
    """Une `turnos` y aplica las condiciones que dan derecho a comer.

    Punto único: cualquier consulta que derive el derecho —la marcación, el
    historial diario, el mensual— pasa por aquí. Si la política cambia, se
    cambia en un solo lugar y las tres quedan alineadas.

    La consulta que se recibe ya debe partir de `turnos_asignados`.
    """
    return (
        consulta.join(Turno, Turno.id == TurnoAsignado.turno_id)
        .join(Usuario, Usuario.id == TurnoAsignado.usuario_id)
        .join(Categoria, Categoria.id == Usuario.categoria_id)
        .where(Turno.duracion_horas >= DURACION_MINIMA_HORAS)
        .where(no_es_enfermeria())
        .where(sin_novedad())
    )


@dataclass(frozen=True)
class Derecho:
    """Una comida a la que una persona tiene derecho en una fecha concreta."""

    comida_id: int
    comida: str
    fecha_comida: date
    turno_asignado_id: int
    servicio_id: int
    turno: str
    fecha_turno: date
    dia_relativo: int


def _consulta_base():
    return aplicar_reglas(
        select(
            Comida.id.label("comida_id"),
            Comida.nombre.label("comida"),
            _FECHA_COMIDA.label("fecha_comida"),
            TurnoAsignado.id.label("turno_asignado_id"),
            TurnoAsignado.servicio_id,
            TurnoAsignado.fecha.label("fecha_turno"),
            Turno.nombre_turno.label("turno"),
            TurnoComida.dia_relativo,
        )
        .select_from(TurnoAsignado)
        .join(TurnoComida, TurnoComida.turno_id == TurnoAsignado.turno_id)
        .join(Comida, Comida.id == TurnoComida.comida_id)
    )


def contar_personas_con_derecho(
    sesion: Session, comida_id: int, fecha_comida: date
) -> int:
    """Cuenta personas distintas con derecho a una comida en una fecha.

    Una persona puede tener más de una asignación que justifique la misma
    comida; para el cupo previsto cuenta una sola ración. Parte de
    ``_consulta_base`` para conservar la política de duración, mapeo de
    turno a comida, fecha relativa y novedades anulatorias.
    """
    consulta = (
        _consulta_base()
        .with_only_columns(
            func.count(func.distinct(TurnoAsignado.usuario_id)),
            maintain_column_froms=True,
        )
        .where(Comida.id == comida_id)
        .where(_FECHA_COMIDA == fecha_comida)
    )
    return sesion.execute(consulta).scalar_one()


def derechos_del_dia(
    sesion: Session, usuario_id: int, fecha_comida: date
) -> list[Derecho]:
    """Las comidas que le corresponden a alguien en una fecha, sin repetir.

    Una misma comida puede estar justificada por más de una asignación: pasa
    de verdad en la base, con guardias en días consecutivos. Por ejemplo, el
    desayuno del 2 de agosto lo justifican tanto la guardia de 30 horas que
    empezó el 1 (dia_relativo = 1) como la que empieza el 2 (dia_relativo = 0).

    El derecho es a UN desayuno ese día, no a dos —la clave única de
    `asistencias` lo impone—, así que se devuelve una fila por comida. Se
    conserva la asignación más antigua, que es la que empezó primero.
    """
    consulta = (
        _consulta_base()
        .where(TurnoAsignado.usuario_id == usuario_id)
        .where(_FECHA_COMIDA == fecha_comida)
        .order_by(Comida.id, TurnoAsignado.id)
    )
    vistas: dict[int, Derecho] = {}
    for fila in sesion.execute(consulta).mappings().all():
        derecho = Derecho(**fila)
        vistas.setdefault(derecho.comida_id, derecho)
    return list(vistas.values())


def buscar_derecho(
    sesion: Session, usuario_id: int, comida_id: int, fecha_comida: date
) -> Derecho | None:
    """El derecho concreto que habilita una ración, si existe.

    Puede haber más de una asignación que lo justifique (un cambio de turno,
    por ejemplo). Basta con una: se devuelve la primera.
    """
    consulta = (
        _consulta_base()
        .where(TurnoAsignado.usuario_id == usuario_id)
        .where(Comida.id == comida_id)
        .where(_FECHA_COMIDA == fecha_comida)
        .order_by(TurnoAsignado.id)
        .limit(1)
    )
    fila = sesion.execute(consulta).mappings().first()
    return Derecho(**fila) if fila else None
