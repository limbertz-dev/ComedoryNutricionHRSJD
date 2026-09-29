"""Reglas versionadas para root. Solo rol sistemas (ACCESO["reglas"]).

CONTRATO con el front (no cambiar sin avisar):

    GET    /reglas/derecho                 vigente de hoy + todas, nueva a vieja
    GET    /reglas/derecho/novedades       tipos reales para la UI
    POST   /reglas/derecho                 201 Version
    DELETE /reglas/derecho/{id}            204, solo programada
    GET    /reglas/horarios?fecha=         vigente de cada comida en esa fecha
    GET    /reglas/horarios/historial?comida_id=  todas las de esa comida
    POST   /reglas/horarios                201, cierra la anterior
    DELETE /reglas/horarios/{horario_id}   204, solo programado, reabre anterior

La vigente se calcula con reloj.hoy(), día simulado en simulación.
Los errores traen además `motivo`: vigencia_en_el_pasado,
horario_invalido, solapa_con_otra_comida, version_en_esa_fecha,
comida_inexistente, version_inexistente, version_ya_vigente,
motivo_obligatorio.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from app.core import reloj
from app.core.autorizacion import ErrorAuth, UsuarioActual
from app.core.db import SesionDep
from app.esquemas.auth import ErrorConMotivo
from app.esquemas.reglas import (
    CrearHorario,
    CrearVersionDerecho,
    HorarioRegla,
    ListaDerecho,
    VersionDerecho,
)
from app.logica import reglas
from app.logica.reglas import ErrorRegla

router = APIRouter(prefix="/reglas", tags=["reglas"])

CON_MOTIVO = {
    404: {"model": ErrorConMotivo},
    409: {"model": ErrorConMotivo},
    422: {"model": ErrorConMotivo},
}


def _traducir(error: ErrorRegla) -> ErrorAuth:
    return ErrorAuth(error.status_code, error.motivo, error.detail)


@router.get(
    "/derecho",
    response_model=ListaDerecho,
    summary="Versión vigente y todas las versiones",
)
def listar_derecho(sesion: SesionDep) -> ListaDerecho:
    try:
        datos = reglas.listar_derecho(sesion)
    except ErrorRegla as error:
        raise _traducir(error) from error
    return ListaDerecho(
        vigente=VersionDerecho(**datos["vigente"]),
        versiones=[VersionDerecho(**v) for v in datos["versiones"]],
    )


@router.get(
    "/derecho/novedades",
    response_model=list[str],
    summary="Tipos de novedad reales para la UI",
)
def listar_novedades(sesion: SesionDep) -> list[str]:
    return reglas.listar_novedades(sesion)


@router.post(
    "/derecho",
    response_model=VersionDerecho,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una versión de parámetros",
    responses=CON_MOTIVO,
)
def crear_derecho(
    sesion: SesionDep, datos: CrearVersionDerecho, usuario: UsuarioActual
) -> VersionDerecho:
    try:
        creada = reglas.crear_derecho(
            sesion,
            datos.vigente_desde,
            datos.duracion_minima_horas,
            datos.novedades_que_anulan,
            datos.excluir_enfermeria,
            datos.motivo,
            usuario,
        )
    except ErrorRegla as error:
        raise _traducir(error) from error
    return VersionDerecho(**creada)


@router.delete(
    "/derecho/{version_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borrar una versión programada",
    responses=CON_MOTIVO,
)
def eliminar_derecho(
    sesion: SesionDep, version_id: Annotated[int, Path(gt=0)]
) -> None:
    try:
        reglas.eliminar_derecho(sesion, version_id)
    except ErrorRegla as error:
        raise _traducir(error) from error


@router.get(
    "/horarios",
    response_model=list[HorarioRegla],
    summary="Horario vigente de cada comida en una fecha",
)
def listar_horarios(
    sesion: SesionDep,
    fecha: Annotated[date | None, Query(description="Por defecto, hoy")] = None,
) -> list[HorarioRegla]:
    return [
        HorarioRegla(**d)
        for d in reglas.listar_horarios(sesion, fecha or reloj.hoy())
    ]


@router.get(
    "/horarios/historial",
    response_model=list[HorarioRegla],
    summary="Todas las versiones de una comida",
    responses=CON_MOTIVO,
)
def historial_horarios(
    sesion: SesionDep,
    comida_id: Annotated[int, Query(gt=0, description="comidas.id")],
) -> list[HorarioRegla]:
    try:
        filas = reglas.historial_horarios(sesion, comida_id)
    except ErrorRegla as error:
        raise _traducir(error) from error
    return [HorarioRegla(**d) for d in filas]


@router.post(
    "/horarios",
    response_model=HorarioRegla,
    status_code=status.HTTP_201_CREATED,
    summary="Programar un horario nuevo",
    responses=CON_MOTIVO,
)
def crear_horario(
    sesion: SesionDep, datos: CrearHorario, usuario: UsuarioActual
) -> HorarioRegla:
    try:
        creado = reglas.crear_horario(
            sesion,
            datos.comida_id,
            datos.hora_inicio,
            datos.hora_fin,
            datos.vigente_desde,
            datos.motivo,
            usuario,
        )
    except ErrorRegla as error:
        raise _traducir(error) from error
    return HorarioRegla(**creado)


@router.delete(
    "/horarios/{horario_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borrar un horario programado",
    responses=CON_MOTIVO,
)
def eliminar_horario(
    sesion: SesionDep, horario_id: Annotated[int, Path(gt=0)]
) -> None:
    try:
        reglas.eliminar_horario(sesion, horario_id)
    except ErrorRegla as error:
        raise _traducir(error) from error
