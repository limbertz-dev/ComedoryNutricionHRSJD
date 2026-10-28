"""Checklist de cocina: la lista de la comida en curso, mientras no esté el lector.

La cocinera ve a quienes les corresponde la comida que está abierta y marca a
cada uno al entregarle su ración. La lista es el derecho de siempre
(`aplicar_reglas`: turno de 12 h o más, categorías permitidas, sin novedad
que lo anule) y la marca pasa por `registrar_marcacion`, con el mismo orden de
validación que la huella: la pantalla nunca decide si alguien come.

Desmarcar es la única excepción a «una ración no se borra»: solo la misma
cuenta que marcó y mientras esa comida siga abierta; al cerrar la comida, la
corrección pasa a la jefa. La copia queda en `anulaciones_checklist`.

Los policías no están en el padrón: la jefatura da de alta Policía 1, 2, ...
(tabla `policias`) y la cocinera los marca como al personal. La ración va a
`raciones_policia` sin huella, solo con una comida en curso y una por policía
en cada comida; Deshacer lo devuelve a pendientes.
"""

from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from sqlalchemy.orm import Session

from app.consultas.derecho import _consulta_base
from app.core import reloj
from app.logica import policia
from app.logica.marcacion import Resultado, registrar_marcacion, resolver_comida_en_curso
from app.modelos.comedor import AnulacionChecklist, Asistencia, CategoriaReporte
from app.modelos.heredados import ComidaPorTurno, Comensal, Servicio
from app.modelos.lector import Policia, RacionPolicia, VinculoLector

DISPOSITIVO_CHECKLIST = "checklist-cocina"


@dataclass(frozen=True)
class PersonaChecklist:
    usuario_id: int
    nombre: str | None
    categoria: str | None
    servicio: str | None
    turno: str
    servida: bool
    metodo: str | None = None
    asistencia_id: int | None = None
    fecha_hora: datetime | None = None
    anulable: bool = False


@dataclass(frozen=True)
class PoliciaChecklist:
    """Un policía por número (servido o pendiente) o una ración de policía sin
    número de la comida (por huella o por nombre, siempre servida)."""

    nombre: str
    servida: bool
    policia_id: int | None = None
    numero: int | None = None
    racion_id: int | None = None
    fecha_hora: datetime | None = None
    origen: str | None = None  # 'checklist' | 'huella'
    anulable: bool = False


@dataclass(frozen=True)
class Checklist:
    momento: datetime
    fuera_de_horario: bool
    comida_id: int | None = None
    comida: str | None = None
    fecha_comida: date | None = None
    personas: list[PersonaChecklist] = field(default_factory=list)
    policias: list[PoliciaChecklist] = field(default_factory=list)


class ErrorChecklist(Exception):
    def __init__(self, status: int, motivo: str, detalle: str):
        super().__init__(detalle)
        self.status = status
        self.motivo = motivo
        self.detalle = detalle


def listar(sesion: Session, cuenta_id: int) -> Checklist:
    """Quiénes tienen derecho a la comida en curso y si ya la recibieron.

    `anulable` solo es true en las marcas del checklist de ESTA cuenta (la
    lista ya es de la comida abierta); las de otra cocinera, la huella o la
    jefa nunca.
    """
    ahora = reloj.ahora()
    comida = resolver_comida_en_curso(sesion, ahora)
    if comida is None:
        return Checklist(momento=ahora, fuera_de_horario=True)

    con_derecho = (
        _consulta_base()
        .with_only_columns(
            ComidaPorTurno.usuario_id,
            func.min(ComidaPorTurno.turno).label("turno"),
            func.min(ComidaPorTurno.servicio_id).label("servicio_id"),
            maintain_column_froms=True,
        )
        .where(ComidaPorTurno.comida_id == comida.comida_id)
        .where(ComidaPorTurno.fecha_comida == comida.fecha_comida)
        .group_by(ComidaPorTurno.usuario_id)
        .subquery("con_derecho")
    )
    filas = sesion.execute(
        select(
            con_derecho.c.usuario_id,
            con_derecho.c.turno,
            Comensal.nombre_completo,
            Comensal.categoria,
            Servicio.nombre.label("servicio"),
        )
        .select_from(con_derecho)
        .outerjoin(Comensal, Comensal.usuario_id == con_derecho.c.usuario_id)
        .outerjoin(Servicio, Servicio.id == con_derecho.c.servicio_id)
    ).all()

    servidas = {
        a.usuario_id: a
        for a in sesion.execute(
            select(Asistencia).where(
                Asistencia.comida_id == comida.comida_id,
                Asistencia.fecha_comida == comida.fecha_comida,
            )
        ).scalars()
    }

    personas = []
    for fila in filas:
        asistencia = servidas.get(fila.usuario_id)
        anulable = (
            asistencia is not None
            and asistencia.metodo == "checklist"
            and asistencia.registrado_por_cuenta == cuenta_id
        )
        personas.append(
            PersonaChecklist(
                usuario_id=fila.usuario_id,
                nombre=fila.nombre_completo,
                categoria=fila.categoria,
                servicio=fila.servicio,
                turno=fila.turno,
                servida=asistencia is not None,
                metodo=asistencia.metodo if asistencia else None,
                asistencia_id=asistencia.id if asistencia else None,
                fecha_hora=asistencia.fecha_hora if asistencia else None,
                anulable=anulable,
            )
        )
    personas.sort(key=lambda p: ((p.nombre or "").casefold(), p.usuario_id))
    return Checklist(
        momento=ahora,
        fuera_de_horario=False,
        comida_id=comida.comida_id,
        comida=comida.comida,
        fecha_comida=comida.fecha_comida,
        personas=personas,
        policias=_policias_de(sesion, comida, cuenta_id),
    )


def _policias_de(sesion: Session, comida, cuenta_id: int) -> list[PoliciaChecklist]:
    """Los policías activos por número, servidos o pendientes, y las demás
    raciones de policía de la comida (huella o nombre)."""
    vinculo = aliased(VinculoLector)
    raciones = sesion.execute(
        select(
            RacionPolicia.id,
            RacionPolicia.policia_id,
            func.coalesce(RacionPolicia.nombre, vinculo.nombre, policia.NOMBRE).label("nombre"),
            RacionPolicia.fecha_hora,
            RacionPolicia.dispositivo,
            RacionPolicia.registrado_por_cuenta,
        )
        .outerjoin(vinculo, vinculo.id == RacionPolicia.vinculo_id)
        .where(
            RacionPolicia.comida_id == comida.comida_id,
            RacionPolicia.fecha_comida == comida.fecha_comida,
        )
        .order_by(RacionPolicia.fecha_hora, RacionPolicia.id)
    ).all()

    def servida(f, **extra) -> PoliciaChecklist:
        return PoliciaChecklist(
            nombre=f.nombre, servida=True, racion_id=f.id, fecha_hora=f.fecha_hora,
            origen="checklist" if f.dispositivo == DISPOSITIVO_CHECKLIST else "huella",
            anulable=f.dispositivo == DISPOSITIVO_CHECKLIST and f.registrado_por_cuenta == cuenta_id,
            **extra,
        )

    por_policia = {f.policia_id: f for f in raciones if f.policia_id is not None}
    numerados = sesion.execute(
        select(Policia)
        .where((Policia.activo == 1) | Policia.id.in_(list(por_policia) or [0]))
        .order_by(Policia.numero)
    ).scalars()
    lista = []
    for p in numerados:
        f = por_policia.get(p.id)
        if f is None:
            lista.append(PoliciaChecklist(nombre=policia.etiqueta(p.numero), servida=False,
                                          policia_id=p.id, numero=p.numero))
        else:
            lista.append(servida(f, policia_id=p.id, numero=p.numero))
    return lista + [servida(f) for f in raciones if f.policia_id is None]


def marcar_policia(sesion: Session, cuenta_id: int, policia_id: int) -> dict:
    """Ración del policía por número: solo con una comida en curso y una por
    comida. Un rechazo (fuera de horario, ya recibió, columna Policías
    inactiva) es 200 con `valido=false`, como en el lector."""
    numerado = sesion.get(Policia, policia_id)
    if numerado is None or not numerado.activo:
        raise ErrorChecklist(404, "policia_inexistente", "Ese policía no existe o fue dado de baja.")
    nombre = policia.etiqueta(numerado.numero)
    base = {"policia_id": policia_id, "nombre": nombre, "racion_id": None}
    ahora = reloj.ahora()
    comida = resolver_comida_en_curso(sesion, ahora)
    if comida is None:
        return {**base, "valido": False, "motivo": "fuera_horario",
                "detalle": "No hay un tiempo de comida vigente a esta hora",
                "comida": None, "fecha_comida": None}
    en_comida = {**base, "comida": comida.comida, "fecha_comida": comida.fecha_comida}
    columna = sesion.execute(
        select(CategoriaReporte.id).where(
            CategoriaReporte.codigo == policia.CODIGO_POLICIAS, CategoriaReporte.activo == 1
        )
    ).scalar_one_or_none()
    if columna is None:
        return {**en_comida, "valido": False, "motivo": "sin_columna_policias",
                "detalle": "La columna Policías no está activa en el catálogo de reportes."}
    duplicado = {**en_comida, "valido": False, "motivo": "duplicado",
                 "detalle": f"{nombre} ya recibió esta comida."}
    if sesion.execute(
        select(RacionPolicia.id).where(
            RacionPolicia.policia_id == policia_id,
            RacionPolicia.fecha_comida == comida.fecha_comida,
            RacionPolicia.comida_id == comida.comida_id,
        )
    ).first():
        return duplicado
    racion = RacionPolicia(
        fecha_comida=comida.fecha_comida, comida_id=comida.comida_id,
        categoria_reporte_id=columna, fecha_hora=ahora, dispositivo=DISPOSITIVO_CHECKLIST,
        vinculo_id=None, nombre=nombre, policia_id=policia_id, registrado_por_cuenta=cuenta_id,
    )
    sesion.add(racion)
    try:
        sesion.commit()
    except IntegrityError:  # otra cocinera lo marcó a la vez
        sesion.rollback()
        return duplicado
    return {**en_comida, "valido": True, "motivo": None,
            "detalle": "Ración de policía registrada", "racion_id": racion.id}


def anular_policia(sesion: Session, cuenta_id: int, racion_id: int) -> AnulacionChecklist:
    """Deshace una ración de policía propia del checklist, con la comida abierta."""
    ahora = reloj.ahora()
    racion = sesion.execute(
        select(RacionPolicia).where(RacionPolicia.id == racion_id).with_for_update()
    ).scalar_one_or_none()
    if racion is None:
        raise ErrorChecklist(404, "no_existe", "Esa ración no existe o ya se anuló.")
    if racion.dispositivo != DISPOSITIVO_CHECKLIST:
        raise ErrorChecklist(
            409, "no_es_checklist", "Solo se desmarcan raciones marcadas en el checklist."
        )
    if racion.registrado_por_cuenta != cuenta_id:
        raise ErrorChecklist(403, "otra_cuenta", "Solo puede desmarcar quien marcó la ración.")
    comida = resolver_comida_en_curso(sesion, ahora)
    if (
        comida is None
        or comida.comida_id != racion.comida_id
        or comida.fecha_comida != racion.fecha_comida
    ):
        raise ErrorChecklist(
            409, "comida_cerrada", "Esa comida ya cerró: pida la corrección a la jefa."
        )
    anulacion = AnulacionChecklist(
        racion_policia_id=racion.id,
        nombre=racion.nombre,
        fecha_comida=racion.fecha_comida,
        comida_id=racion.comida_id,
        marcada_en=racion.fecha_hora,
        cuenta_id=cuenta_id,
        anulada_en=ahora,
    )
    sesion.add(anulacion)
    sesion.delete(racion)
    sesion.commit()
    return anulacion


def marcar(sesion: Session, cuenta_id: int, usuario_id: int) -> Resultado:
    """Registra la ración con las reglas de la huella; el rechazo no es error."""
    return registrar_marcacion(
        sesion,
        usuario_id=usuario_id,
        dispositivo=DISPOSITIVO_CHECKLIST,
        metodo="checklist",
        registrado_por_cuenta=cuenta_id,
    )


def anular(sesion: Session, cuenta_id: int, asistencia_id: int) -> AnulacionChecklist:
    """Deshace una marca propia de la comida que sigue abierta."""
    ahora = reloj.ahora()
    asistencia = sesion.execute(
        select(Asistencia).where(Asistencia.id == asistencia_id).with_for_update()
    ).scalar_one_or_none()
    if asistencia is None:
        raise ErrorChecklist(404, "no_existe", "Esa ración no existe o ya se anuló.")
    if asistencia.metodo != "checklist":
        raise ErrorChecklist(
            409, "no_es_checklist", "Solo se desmarcan raciones marcadas en el checklist."
        )
    if asistencia.registrado_por_cuenta != cuenta_id:
        raise ErrorChecklist(
            403, "otra_cuenta", "Solo puede desmarcar quien marcó la ración."
        )
    comida = resolver_comida_en_curso(sesion, ahora)
    if (
        comida is None
        or comida.comida_id != asistencia.comida_id
        or comida.fecha_comida != asistencia.fecha_comida
    ):
        raise ErrorChecklist(
            409, "comida_cerrada", "Esa comida ya cerró: pida la corrección a la jefa."
        )

    anulacion = AnulacionChecklist(
        asistencia_id=asistencia.id,
        usuario_id=asistencia.usuario_id,
        fecha_comida=asistencia.fecha_comida,
        comida_id=asistencia.comida_id,
        marcada_en=asistencia.fecha_hora,
        cuenta_id=cuenta_id,
        anulada_en=ahora,
    )
    sesion.add(anulacion)
    sesion.delete(asistencia)
    sesion.commit()
    return anulacion
