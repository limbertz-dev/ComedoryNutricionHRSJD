"""Historial nominal: quién recibió qué, persona por persona.

Es la vista que la jefatura usa para revisar caso por caso, distinta de los
informes —que son cifras agregadas—. Aquí importa el nombre.

Los cuatro estados NO se guardan en ninguna tabla: se derivan cruzando tres
cosas en el momento de consultar.

    no_aplica     el turno de esa persona no incluye esa comida ese día
    recibida      hay una ración registrada
    no_recibida   le correspondía, la ventana horaria ya cerró y no marcó
    pendiente     le corresponde y la ventana todavía no cierra

El orden de esas cuatro reglas importa: alguien puede tener una ración sin
derecho, si la jefatura se la autorizó a mano. En ese caso vale la ración, no
la ausencia de derecho, y el estado es `recibida`.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from sqlalchemy import Select, and_, func, or_, select, union
from sqlalchemy.orm import Session

from app.consultas.derecho import aplicar_reglas
from app.modelos.comedor import Asistencia, HorarioComida
from app.modelos.heredados import (
    Comensal,
    Comida,
    ComidaPorTurno,
    Servicio,
    UsuarioServicio,
)

RECIBIDA = "recibida"
NO_RECIBIDA = "no_recibida"
PENDIENTE = "pendiente"
NO_APLICA = "no_aplica"

MESES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


@dataclass
class ComidaDelDia:
    comida_id: int
    nombre: str
    estado: str
    hora: time | None = None


@dataclass
class ComensalDelDia:
    usuario_id: int
    nombre_completo: str | None
    carnet_identidad: str | None
    categoria: str | None
    servicio: str | None
    turno: str | None
    comidas: list[ComidaDelDia] = field(default_factory=list)


@dataclass
class TotalesComida:
    comida_id: int
    nombre: str
    asignadas: int
    recibidas: int
    no_recibidas: int
    pendientes: int


@dataclass
class ComensalDelMes:
    usuario_id: int
    nombre_completo: str | None
    carnet_identidad: str | None
    categoria: str | None
    total_asignadas: int
    total_recibidas: int
    total_no_recibidas: int
    total_pendientes: int
    servicio: str | None = None
    totales: list[TotalesComida] = field(default_factory=list)


@dataclass
class ComidaListada:
    comida_id: int
    codigo: str
    nombre: str


def _comidas(sesion: Session) -> list[ComidaListada]:
    filas = sesion.execute(
        select(Comida.id, Comida.codigo, Comida.nombre)
        .where(Comida.estado == 1)
        .order_by(Comida.id)
    ).all()
    return [ComidaListada(comida_id=i, codigo=c, nombre=n) for i, c, n in filas]


def _fin_de_ventana(sesion: Session, fecha: date) -> dict[int, datetime]:
    """Cuándo cierra la ventana de cada comida, para esa fecha.

    Si la franja cruza la medianoche, cierra al día siguiente. Una comida sin
    horario vigente no tiene cierre: sus raciones quedan pendientes en vez de
    contarse como no recibidas, porque no hay forma de saber si ya pasó.
    """
    filas = sesion.execute(
        select(HorarioComida.comida_id, HorarioComida.hora_inicio, HorarioComida.hora_fin)
        .where(HorarioComida.activo == 1)
        .where(HorarioComida.vigente_desde <= fecha)
        .where(
            or_(
                HorarioComida.vigente_hasta.is_(None),
                HorarioComida.vigente_hasta >= fecha,
            )
        )
        .order_by(HorarioComida.vigente_desde)
    ).all()

    fines: dict[int, datetime] = {}
    for comida_id, inicio, fin in filas:
        cierre = datetime.combine(fecha, fin)
        if fin < inicio:
            cierre += timedelta(days=1)
        fines[comida_id] = cierre
    return fines


def _pagina_de_usuarios(
    sesion: Session,
    con_derecho: Select,
    con_racion: Select,
    limite: int,
    desplazamiento: int,
) -> tuple[int, list[int]]:
    """Los usuarios de la página, ordenados por nombre.

    El conjunto es la unión de quienes tenían derecho y quienes recibieron una
    ración. Los segundos no siempre están entre los primeros: una autorización
    excepcional produce una ración sin derecho, y esa persona tiene que
    aparecer en el historial igual.
    """
    universo = union(con_derecho, con_racion).subquery("universo")
    columna = universo.c[0]

    total = sesion.execute(
        select(func.count()).select_from(universo)
    ).scalar_one()

    pagina = sesion.execute(
        select(columna)
        .select_from(universo)
        .outerjoin(Comensal, Comensal.usuario_id == columna)
        .order_by(
            Comensal.nombre_completo.is_(None), Comensal.nombre_completo, columna
        )
        .limit(limite)
        .offset(desplazamiento)
    ).scalars().all()
    return total, list(pagina)


def _datos_de_comensales(sesion: Session, usuarios: list[int]) -> dict[int, dict]:
    """Nombre, carnet, categoría y sala de cada usuario de la página."""
    if not usuarios:
        return {}

    sala = (
        select(
            UsuarioServicio.usuario_id.label("usuario_id"),
            func.max(UsuarioServicio.id).label("asignacion_id"),
        )
        .where(UsuarioServicio.estado == 1)
        .group_by(UsuarioServicio.usuario_id)
        .subquery("sala")
    )
    filas = sesion.execute(
        select(
            Comensal.usuario_id.label("id"),
            Comensal.nombre_completo,
            Comensal.carnet_identidad,
            Comensal.categoria,
            Servicio.nombre.label("servicio"),
        )
        .select_from(Comensal)
        .outerjoin(sala, sala.c.usuario_id == Comensal.usuario_id)
        .outerjoin(UsuarioServicio, UsuarioServicio.id == sala.c.asignacion_id)
        .outerjoin(Servicio, Servicio.id == UsuarioServicio.servicio_id)
        .where(Comensal.usuario_id.in_(usuarios))
    ).mappings().all()
    return {fila["id"]: dict(fila) for fila in filas}


# ----------------------------------------------------------------- diario


def historial_diario(
    sesion: Session,
    fecha: date,
    limite: int = 50,
    desplazamiento: int = 0,
    momento: datetime | None = None,
) -> tuple[int, list[ComidaListada], list[ComensalDelDia]]:
    momento = momento or datetime.now()

    con_derecho = aplicar_reglas(
        select(ComidaPorTurno.usuario_id.label("usuario_id"))
        .select_from(ComidaPorTurno)
        .where(ComidaPorTurno.fecha_comida == fecha)
    )
    con_racion = select(Asistencia.usuario_id.label("usuario_id")).where(
        Asistencia.fecha_comida == fecha
    )
    total, usuarios = _pagina_de_usuarios(
        sesion, con_derecho, con_racion, limite, desplazamiento
    )

    comidas = _comidas(sesion)
    if not usuarios:
        return total, comidas, []

    fines = _fin_de_ventana(sesion, fecha)
    datos = _datos_de_comensales(sesion, usuarios)

    derechos = sesion.execute(
        aplicar_reglas(
            select(
                ComidaPorTurno.usuario_id,
                ComidaPorTurno.comida_id,
                ComidaPorTurno.turno,
                ComidaPorTurno.turno_asignado_id,
            )
            .select_from(ComidaPorTurno)
            .where(ComidaPorTurno.fecha_comida == fecha)
            .where(ComidaPorTurno.usuario_id.in_(usuarios))
        ).order_by(ComidaPorTurno.turno_asignado_id)
    ).all()

    aplica: dict[int, set[int]] = {u: set() for u in usuarios}
    turno_de: dict[int, str] = {}
    for usuario, comida_id, nombre_turno, _asignacion in derechos:
        aplica[usuario].add(comida_id)
        # Se conserva el turno de la asignación más antigua: en guardias
        # encadenadas puede haber más de una el mismo día.
        turno_de.setdefault(usuario, nombre_turno)

    raciones = {
        (u, c): hora
        for u, c, hora in sesion.execute(
            select(Asistencia.usuario_id, Asistencia.comida_id, Asistencia.fecha_hora)
            .where(Asistencia.fecha_comida == fecha)
            .where(Asistencia.usuario_id.in_(usuarios))
        ).all()
    }

    comensales = []
    for usuario in usuarios:
        info = datos.get(usuario, {})
        del_dia = []
        for comida in comidas:
            servida = raciones.get((usuario, comida.comida_id))
            le_toca = comida.comida_id in aplica.get(usuario, set())
            del_dia.append(
                ComidaDelDia(
                    comida_id=comida.comida_id,
                    nombre=comida.nombre,
                    estado=_estado(
                        le_toca, servida, fines.get(comida.comida_id), momento
                    ),
                    hora=servida.time() if servida else None,
                )
            )
        comensales.append(
            ComensalDelDia(
                usuario_id=usuario,
                nombre_completo=info.get("nombre_completo"),
                carnet_identidad=info.get("carnet_identidad"),
                categoria=info.get("categoria"),
                servicio=info.get("servicio"),
                turno=turno_de.get(usuario),
                comidas=del_dia,
            )
        )
    return total, comidas, comensales


def _estado(
    le_toca: bool,
    servida: datetime | None,
    fin_ventana: datetime | None,
    momento: datetime,
) -> str:
    # La ración manda sobre el derecho: una autorización excepcional produce
    # una ración sin turno que la respalde, y sigue siendo una ración recibida.
    if servida is not None:
        return RECIBIDA
    if not le_toca:
        return NO_APLICA
    if fin_ventana is None:
        # Sin horario vigente no hay forma de saber si la ventana pasó.
        return PENDIENTE
    return NO_RECIBIDA if momento >= fin_ventana else PENDIENTE


# ----------------------------------------------------------------- mensual


def historial_mensual(
    sesion: Session,
    gestion: int,
    mes: int,
    limite: int = 50,
    desplazamiento: int = 0,
    momento: datetime | None = None,
) -> tuple[int, list[ComidaListada], list[ComensalDelMes]]:
    momento = momento or datetime.now()
    desde = date(gestion, mes, 1)
    hasta = (
        date(gestion + 1, 1, 1) if mes == 12 else date(gestion, mes + 1, 1)
    ) - timedelta(days=1)

    con_derecho = aplicar_reglas(
        select(ComidaPorTurno.usuario_id.label("usuario_id"))
        .select_from(ComidaPorTurno)
        .where(ComidaPorTurno.fecha_comida.between(desde, hasta))
    )
    con_racion = select(Asistencia.usuario_id.label("usuario_id")).where(
        Asistencia.fecha_comida.between(desde, hasta)
    )
    total, usuarios = _pagina_de_usuarios(
        sesion, con_derecho, con_racion, limite, desplazamiento
    )

    comidas = _comidas(sesion)
    if not usuarios:
        return total, comidas, []

    datos = _datos_de_comensales(sesion, usuarios)
    hoy = momento.date()
    fines_hoy = _fin_de_ventana(sesion, hoy)

    # Un día del mes puede estar justificado por varias asignaciones; interesa
    # el día, no cuántos turnos lo respaldan, así que se cuenta distinto.
    derechos = (
        aplicar_reglas(
            select(
                ComidaPorTurno.usuario_id,
                ComidaPorTurno.comida_id,
                ComidaPorTurno.fecha_comida,
            )
            .select_from(ComidaPorTurno)
            .where(ComidaPorTurno.fecha_comida.between(desde, hasta))
            .where(ComidaPorTurno.usuario_id.in_(usuarios))
        )
        .distinct()
        .subquery("derechos")
    )

    filas = sesion.execute(
        select(
            derechos.c.usuario_id,
            derechos.c.comida_id,
            func.count().label("asignadas"),
            func.sum(func.if_(Asistencia.id.is_not(None), 1, 0)).label("recibidas"),
            func.sum(
                func.if_(
                    and_(Asistencia.id.is_(None), derechos.c.fecha_comida < hoy), 1, 0
                )
            ).label("no_recibidas_pasadas"),
            func.sum(
                func.if_(
                    and_(Asistencia.id.is_(None), derechos.c.fecha_comida == hoy), 1, 0
                )
            ).label("hoy_sin_racion"),
            func.sum(
                func.if_(
                    and_(Asistencia.id.is_(None), derechos.c.fecha_comida > hoy), 1, 0
                )
            ).label("futuras"),
        )
        .select_from(derechos)
        .outerjoin(
            Asistencia,
            and_(
                Asistencia.usuario_id == derechos.c.usuario_id,
                Asistencia.comida_id == derechos.c.comida_id,
                Asistencia.fecha_comida == derechos.c.fecha_comida,
            ),
        )
        .group_by(derechos.c.usuario_id, derechos.c.comida_id)
    ).all()

    # Raciones sin derecho que las respalde: autorizaciones excepcionales. No
    # están en el cruce de arriba, pero se sirvieron y tienen que contarse.
    sueltas = sesion.execute(
        select(Asistencia.usuario_id, Asistencia.comida_id, func.count())
        .outerjoin(
            derechos,
            and_(
                derechos.c.usuario_id == Asistencia.usuario_id,
                derechos.c.comida_id == Asistencia.comida_id,
                derechos.c.fecha_comida == Asistencia.fecha_comida,
            ),
        )
        .where(Asistencia.fecha_comida.between(desde, hasta))
        .where(Asistencia.usuario_id.in_(usuarios))
        .where(derechos.c.usuario_id.is_(None))
        .group_by(Asistencia.usuario_id, Asistencia.comida_id)
    ).all()

    acumulado: dict[tuple[int, int], dict[str, int]] = {}
    for usuario, comida_id, asignadas, recibidas, pasadas, hoy_sin, futuras in filas:
        # Lo de hoy sin ración: si la ventana ya cerró es una ausencia, si no
        # todavía puede venir a comer.
        cerro = (
            fines_hoy.get(comida_id) is not None
            and momento >= fines_hoy[comida_id]
        )
        acumulado[(usuario, comida_id)] = {
            "asignadas": int(asignadas),
            "recibidas": int(recibidas or 0),
            "no_recibidas": int(pasadas or 0) + (int(hoy_sin or 0) if cerro else 0),
            "pendientes": int(futuras or 0) + (0 if cerro else int(hoy_sin or 0)),
        }

    for usuario, comida_id, cantidad in sueltas:
        casilla = acumulado.setdefault(
            (usuario, comida_id),
            {"asignadas": 0, "recibidas": 0, "no_recibidas": 0, "pendientes": 0},
        )
        casilla["recibidas"] += int(cantidad)

    comensales = []
    for usuario in usuarios:
        info = datos.get(usuario, {})
        totales = []
        for comida in comidas:
            casilla = acumulado.get(
                (usuario, comida.comida_id),
                {"asignadas": 0, "recibidas": 0, "no_recibidas": 0, "pendientes": 0},
            )
            totales.append(
                TotalesComida(
                    comida_id=comida.comida_id, nombre=comida.nombre, **casilla
                )
            )
        comensales.append(
            ComensalDelMes(
                usuario_id=usuario,
                nombre_completo=info.get("nombre_completo"),
                carnet_identidad=info.get("carnet_identidad"),
                categoria=info.get("categoria"),
                servicio=info.get("servicio"),
                total_asignadas=sum(t.asignadas for t in totales),
                total_recibidas=sum(t.recibidas for t in totales),
                total_no_recibidas=sum(t.no_recibidas for t in totales),
                total_pendientes=sum(t.pendientes for t in totales),
                totales=totales,
            )
        )
    return total, comidas, comensales
