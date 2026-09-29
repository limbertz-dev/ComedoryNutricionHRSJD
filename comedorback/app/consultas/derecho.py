"""El derecho a comer.

No existe ninguna tabla que lo guarde: sale de cruzar `turnos_asignados` con
`turno_comida`. Ese cruce, sin reglas, es la vista `v_comidas_por_turno` de
bd_nutricion (lee la base de turnos); las reglas se aplican acá.

La pieza clave es `fecha_comida`:

    fecha_comida = turnos_asignados.fecha + turno_comida.dia_relativo

Sale del derecho, nunca del reloj. Es lo que permite que una guardia de 32
horas reciba DOS desayunos —en fechas distintas— sin chocar con la clave única
de la ración, y a la vez que dos intentos de la misma comida sí choquen.

Para que una asignación dé derecho tiene que cumplir DOS condiciones, además
de estar mapeada en turno_comida:

  1. El turno dura lo suficiente. Es la política del hospital: un turno corto
     no genera derecho a comida. El umbral sale de la versión vigente.
  2. No hay una novedad que lo anule según la versión vigente.

Los parámetros viven versionados en `reglas_derecho` y se resuelven EN SQL
por `fecha_turno`: la regla califica la asignación, y `dia_relativo`
desplaza la comida. Cada fila usa su propia versión, también en consultas
de varios días, sin bucles en Python.
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core import reloj
from app.modelos.heredados import ComidaPorTurno, NovedadLaboral
from app.modelos.reglas import ReglaDerecho, ReglaDerechoNovedad

# Valores BASE anteriores a R2, idénticos a la versión base de la migración.
# `aplicar_reglas` ya no los usa: resuelve la versión vigente EN SQL.
# Se conservan para documentar el punto de partida y para quien los importe.
#
# Un permiso, una baja, una vacación o una licencia anulan el derecho de esa
# asignación. `devolucion_turno` NO está en la lista: es un cambio entre
# compañeros, no una ausencia.
#
# PENDIENTE: cuando hay reemplazo (novedades_laborales.usuario_reemplazo_id),
# el derecho debería pasar al que cubre el turno. No está implementado porque
# primero hay que confirmar con el hospital cómo usan esa columna en la
# práctica; hoy solo hay 5 filas en la tabla.
NOVEDADES_QUE_ANULAN = ("permiso", "baja_medica", "vacacion", "licencia")

# El umbral base filtra 49 de los 76 turnos cargados. Se compara contra
# `turnos.duracion_horas`, que es el dato que declara el hospital, y NO contra
# hora_inicio/hora_fin: en los turnos largos esas dos columnas no reflejan la
# duración real (el turno 90 dura 30 horas y figura como 6:00-12:00).
DURACION_MINIMA_HORAS = 12
PATRON_CATEGORIA_ENFERMERIA = "%enfermer%"

def no_es_enfermeria(categoria):
    """`categoria` es la columna con el NOMBRE de la categoría del hospital.

    Una categoría NULL (usuario sin categoría) tampoco pasa: `NOT (NULL LIKE
    ...)` es NULL, igual que antes con el INNER JOIN a `categorias`.
    """
    return ~categoria.ilike(PATRON_CATEGORIA_ENFERMERIA)


def _version_id_para(fecha_columna):
    """Id de la versión vigente para una fecha, como subconsulta escalar."""
    return (
        select(ReglaDerecho.id)
        .where(ReglaDerecho.vigente_desde <= fecha_columna)
        .order_by(ReglaDerecho.vigente_desde.desc(), ReglaDerecho.id.desc())
        .limit(1)
        .scalar_subquery()
    )


def _duracion_minima_para(fecha_columna):
    """Turno mínimo vigente para una fecha, como subconsulta escalar."""
    return (
        select(ReglaDerecho.duracion_minima_horas)
        .where(ReglaDerecho.vigente_desde <= fecha_columna)
        .order_by(ReglaDerecho.vigente_desde.desc(), ReglaDerecho.id.desc())
        .limit(1)
        .scalar_subquery()
    )


def _excluir_enfermeria_para(fecha_columna):
    """Si enfermería queda fuera en la versión vigente para una fecha."""
    return (
        select(ReglaDerecho.excluir_enfermeria)
        .where(ReglaDerecho.vigente_desde <= fecha_columna)
        .order_by(ReglaDerecho.vigente_desde.desc(), ReglaDerecho.id.desc())
        .limit(1)
        .scalar_subquery()
    )


def sin_novedad():
    """Que no haya una novedad anulatoria según la versión de `fecha_turno`."""
    version_id = _version_id_para(ComidaPorTurno.fecha_turno)
    return ~select(NovedadLaboral.id).where(
        NovedadLaboral.asignacion_id == ComidaPorTurno.turno_asignado_id,
        NovedadLaboral.tipo_novedad.in_(
            select(ReglaDerechoNovedad.tipo_novedad).where(
                ReglaDerechoNovedad.regla_id == version_id
            )
        ),
    ).exists()


def aplicar_reglas(consulta):
    """Aplica las condiciones que dan derecho a comer.

    Punto único: cualquier consulta que derive el derecho —la marcación, el
    historial diario, el mensual— pasa por aquí. Si la política cambia, se
    cambia en un solo lugar y las tres quedan alineadas.

    La consulta que se recibe ya debe partir de `v_comidas_por_turno`
    (`ComidaPorTurno`), que trae la duración del turno y la categoría.
    La versión se resuelve por `fecha_turno`, fila por fila, en SQL.
    """
    fecha = ComidaPorTurno.fecha_turno
    return (
        consulta.where(
            ComidaPorTurno.duracion_horas >= _duracion_minima_para(fecha)
        )
        .where(
            or_(
                _excluir_enfermeria_para(fecha) == 0,
                no_es_enfermeria(ComidaPorTurno.categoria),
            )
        )
        .where(sin_novedad())
    )


def excluye_enfermeria_hoy(sesion: Session) -> bool:
    """Si la versión vigente HOY deja a enfermería fuera del padrón.

    El padrón y la pantalla lo usan para no quedar en desacuerdo con el
    derecho cuando cambia `excluir_enfermeria`. Sin versión, excluye.
    """
    hoy = reloj.hoy()
    valor = sesion.execute(
        select(ReglaDerecho.excluir_enfermeria)
        .where(ReglaDerecho.vigente_desde <= hoy)
        .order_by(ReglaDerecho.vigente_desde.desc(), ReglaDerecho.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    return bool(valor) if valor is not None else True


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
            ComidaPorTurno.comida_id,
            ComidaPorTurno.comida,
            ComidaPorTurno.fecha_comida,
            ComidaPorTurno.turno_asignado_id,
            ComidaPorTurno.servicio_id,
            ComidaPorTurno.fecha_turno,
            ComidaPorTurno.turno,
            ComidaPorTurno.dia_relativo,
        ).select_from(ComidaPorTurno)
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
            func.count(func.distinct(ComidaPorTurno.usuario_id)),
            maintain_column_froms=True,
        )
        .where(ComidaPorTurno.comida_id == comida_id)
        .where(ComidaPorTurno.fecha_comida == fecha_comida)
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
        .where(ComidaPorTurno.usuario_id == usuario_id)
        .where(ComidaPorTurno.fecha_comida == fecha_comida)
        .order_by(ComidaPorTurno.comida_id, ComidaPorTurno.turno_asignado_id)
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
        .where(ComidaPorTurno.usuario_id == usuario_id)
        .where(ComidaPorTurno.comida_id == comida_id)
        .where(ComidaPorTurno.fecha_comida == fecha_comida)
        .order_by(ComidaPorTurno.turno_asignado_id)
        .limit(1)
    )
    fila = sesion.execute(consulta).mappings().first()
    return Derecho(**fila) if fila else None
