"""Consulta del padrón de comensales.

Dos decisiones que no son obvias y conviene no deshacer:

1. Se parte de `users`, no de `personas`. El eje de identidad de todo el
   sistema es `users.id`, porque es lo que ya usan turnos_asignados,
   usuario_servicios y las asistencias.

2. Los JOIN son LEFT, a propósito. Un usuario sin ficha en `personas` aparece
   igual, marcado con `tiene_ficha = False`, en vez de desaparecer en silencio.
   En un padrón de comedor, una persona que falta es peor que una fila
   incompleta: nadie se entera de que falta.
"""

from dataclasses import dataclass

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.consultas.derecho import no_es_enfermeria
from app.modelos.comedor import CategoriaReporte, CategoriaReporteMap
from app.modelos.heredados import (
    Categoria,
    Persona,
    Servicio,
    Usuario,
    UsuarioServicio,
)


# El padrón viene con basura de espacios: "    JEREZ    DURAN    ALVARO".
# Se limpia al leer, no en la tabla: los datos son del módulo heredado y no nos
# corresponde editarlos. Sin esto, el nombre se imprime así en el informe
# firmado y además los espacios iniciales desordenan el listado alfabético.
_NOMBRE = func.regexp_replace(func.trim(Persona.nombre_completo), "[[:space:]]+", " ")


@dataclass(frozen=True)
class FiltrosPadron:
    busqueda: str | None = None
    categoria_id: int | None = None
    servicio_id: int | None = None
    solo_con_ficha: bool = False


# Una sola ficha por usuario, la de menor id.
#
# `personas.user_id` NO tiene índice único: se decidió no agregarlo para no
# tocar una tabla del módulo heredado, porque el índice haría fallar SU
# importación, no la nuestra. Hoy no hay duplicados (1.074 filas, 1.074
# user_id distintos), pero si algún día aparece uno, esta subconsulta hace que
# la persona se cuente una vez en vez de duplicar la ración en los informes.
_ficha_principal = (
    select(
        Persona.user_id.label("user_id"),
        func.min(Persona.id).label("persona_id"),
    )
    .group_by(Persona.user_id)
    .subquery("ficha_principal")
)

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


def _base() -> Select:
    return (
        select(
            Usuario.id.label("usuario_id"),
            _NOMBRE.label("nombre_completo"),
            Persona.carnet_identidad,
            Persona.numero_tipo_salario.label("numero_item"),
            Persona.tipo_trabajador,
            Categoria.nombre.label("categoria"),
            CategoriaReporte.nombre.label("categoria_reporte"),
            Servicio.nombre.label("servicio"),
        )
        .select_from(Usuario)
        .outerjoin(_ficha_principal, _ficha_principal.c.user_id == Usuario.id)
        .outerjoin(Persona, Persona.id == _ficha_principal.c.persona_id)
        .outerjoin(Categoria, Categoria.id == Usuario.categoria_id)
        .outerjoin(CategoriaReporteMap, CategoriaReporteMap.categoria_id == Categoria.id)
        .outerjoin(
            CategoriaReporte,
            CategoriaReporte.id == CategoriaReporteMap.categoria_reporte_id,
        )
        .outerjoin(_sala_vigente, _sala_vigente.c.usuario_id == Usuario.id)
        .outerjoin(UsuarioServicio, UsuarioServicio.id == _sala_vigente.c.asignacion_id)
        .outerjoin(Servicio, Servicio.id == UsuarioServicio.servicio_id)
        .where(no_es_enfermeria())
    )


def _aplicar_filtros(consulta: Select, filtros: FiltrosPadron) -> Select:
    if filtros.busqueda:
        patron = f"%{filtros.busqueda.strip()}%"
        consulta = consulta.where(
            or_(
                _NOMBRE.like(patron),
                Persona.carnet_identidad.like(patron),
                Persona.numero_tipo_salario.like(patron),
            )
        )
    if filtros.categoria_id is not None:
        consulta = consulta.where(Usuario.categoria_id == filtros.categoria_id)
    if filtros.servicio_id is not None:
        consulta = consulta.where(UsuarioServicio.servicio_id == filtros.servicio_id)
    if filtros.solo_con_ficha:
        consulta = consulta.where(Persona.id.is_not(None))
    return consulta


def contar_comensales(sesion: Session, filtros: FiltrosPadron) -> int:
    consulta = _aplicar_filtros(_base(), filtros).subquery()
    return sesion.execute(select(func.count()).select_from(consulta)).scalar_one()


def listar_comensales(
    sesion: Session,
    filtros: FiltrosPadron,
    limite: int = 50,
    desplazamiento: int = 0,
) -> list[dict]:
    consulta = _aplicar_filtros(_base(), filtros)
    # Los usuarios sin ficha van al final: MySQL ordena los NULL primero y no
    # queremos que las filas incompletas encabecen el padrón.
    consulta = (
        consulta.order_by(
            Persona.nombre_completo.is_(None),
            _NOMBRE,
            Usuario.id,
        )
        .limit(limite)
        .offset(desplazamiento)
    )
    filas = sesion.execute(consulta).mappings().all()
    return [
        {**fila, "tiene_ficha": fila["nombre_completo"] is not None} for fila in filas
    ]


def obtener_comensal(sesion: Session, usuario_id: int) -> dict | None:
    consulta = _base().where(Usuario.id == usuario_id)
    fila = sesion.execute(consulta).mappings().first()
    if fila is None:
        return None
    return {**fila, "tiene_ficha": fila["nombre_completo"] is not None}
