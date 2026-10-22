"""Consulta del padrón de comensales.

Dos decisiones que no son obvias y conviene no deshacer:

1. Se parte de `v_comensales`, cuyo eje es `users.id` y no `personas.id`.
   Es el eje de identidad de todo el sistema, porque es lo que ya usan
   turnos_asignados, usuario_servicios y las asistencias.

2. Los JOIN son LEFT, a propósito (dentro de la vista y acá). Un usuario sin
   ficha en `personas` aparece igual, marcado con `tiene_ficha = False`, en
   vez de desaparecer en silencio. En un padrón de comedor, una persona que
   falta es peor que una fila incompleta: nadie se entera de que falta.

La vista ya resuelve la ficha principal (la de menor id, por si algún día
`personas.user_id` trae duplicados) y limpia los espacios del nombre.
"""

from dataclasses import dataclass

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.consultas.derecho import excluye_enfermeria_hoy, no_es_enfermeria
from app.consultas.perfiles import categoria_permitida_sql
from app.modelos.comedor import CategoriaReporte, CategoriaReporteMap
from app.modelos.heredados import Comensal, Servicio, UsuarioServicio


@dataclass(frozen=True)
class FiltrosPadron:
    busqueda: str | None = None
    categoria_id: int | None = None
    servicio_id: int | None = None
    solo_con_ficha: bool = False


# La asignación de sala vigente: la más reciente de las activas.
_sala_vigente = (
    select(
        UsuarioServicio.usuario_id.label("usuario_id"),
        func.max(UsuarioServicio.id).label("asignacion_id"),
    )
    .where(UsuarioServicio.estado == 1)
    .group_by(UsuarioServicio.usuario_id)
    .subquery("sala_vigente")
)


def _base(sesion: Session) -> Select:
    consulta = (
        select(
            Comensal.usuario_id,
            Comensal.nombre_completo,
            Comensal.carnet_identidad,
            Comensal.numero_item,
            Comensal.tipo_trabajador,
            Comensal.categoria,
            CategoriaReporte.nombre.label("categoria_reporte"),
            Servicio.nombre.label("servicio"),
            Comensal.tiene_ficha,
        )
        .select_from(Comensal)
        .outerjoin(
            CategoriaReporteMap,
            CategoriaReporteMap.categoria_id == Comensal.categoria_id,
        )
        .outerjoin(
            CategoriaReporte,
            CategoriaReporte.id == CategoriaReporteMap.categoria_reporte_id,
        )
        .outerjoin(_sala_vigente, _sala_vigente.c.usuario_id == Comensal.usuario_id)
        .outerjoin(UsuarioServicio, UsuarioServicio.id == _sala_vigente.c.asignacion_id)
        .outerjoin(Servicio, Servicio.id == UsuarioServicio.servicio_id)
        .where(categoria_permitida_sql(Comensal.categoria))
    )
    if excluye_enfermeria_hoy(sesion):
        consulta = consulta.where(no_es_enfermeria(Comensal.categoria))
    return consulta


def _aplicar_filtros(consulta: Select, filtros: FiltrosPadron) -> Select:
    if filtros.busqueda:
        patron = f"%{filtros.busqueda.strip()}%"
        consulta = consulta.where(
            or_(
                Comensal.nombre_completo.like(patron),
                Comensal.carnet_identidad.like(patron),
                Comensal.numero_item.like(patron),
            )
        )
    if filtros.categoria_id is not None:
        consulta = consulta.where(Comensal.categoria_id == filtros.categoria_id)
    if filtros.servicio_id is not None:
        consulta = consulta.where(UsuarioServicio.servicio_id == filtros.servicio_id)
    if filtros.solo_con_ficha:
        consulta = consulta.where(Comensal.tiene_ficha == 1)
    return consulta


def contar_comensales(sesion: Session, filtros: FiltrosPadron) -> int:
    consulta = _aplicar_filtros(_base(sesion), filtros).subquery()
    return sesion.execute(select(func.count()).select_from(consulta)).scalar_one()


def listar_comensales(
    sesion: Session,
    filtros: FiltrosPadron,
    limite: int = 50,
    desplazamiento: int = 0,
) -> list[dict]:
    consulta = _aplicar_filtros(_base(sesion), filtros)
    # Los usuarios sin ficha van al final: MySQL ordena los NULL primero y no
    # queremos que las filas incompletas encabecen el padrón.
    consulta = (
        consulta.order_by(
            Comensal.nombre_completo.is_(None),
            Comensal.nombre_completo,
            Comensal.usuario_id,
        )
        .limit(limite)
        .offset(desplazamiento)
    )
    filas = sesion.execute(consulta).mappings().all()
    return [{**fila, "tiene_ficha": bool(fila["tiene_ficha"])} for fila in filas]


def obtener_comensal(sesion: Session, usuario_id: int) -> dict | None:
    consulta = _base(sesion).where(Comensal.usuario_id == usuario_id)
    fila = sesion.execute(consulta).mappings().first()
    if fila is None:
        return None
    return {**fila, "tiene_ficha": bool(fila["tiene_ficha"])}
