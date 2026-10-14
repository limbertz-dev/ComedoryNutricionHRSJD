"""Reglas para root. Solo rol sistemas (ACCESO["reglas"]).

CONTRATO con el front (no cambiar sin avisar):

    GET    /reglas/derecho                 versión vigente + todas, SOLO LECTURA
    GET    /reglas/horarios?momento=       versión de cada comida que rige en
                                           `momento` (por omisión, ahora);
                                           datetime SIN zona: con Z o desfase, 422
    GET    /reglas/horarios/historial?comida_id=   todas las versiones de esa comida
    POST   /reglas/horarios                201: guarda el horario con efecto
                                           inmediato; cierra la versión abierta

El derecho ya no se edita por API: POST y DELETE de /reglas/derecho y
GET /reglas/derecho/novedades no existen (405/404). Ocultar un botón no
alcanza; el servidor es quien lo impide. Sus versiones, valores y
evaluación histórica no cambian.

Los horarios rigen desde el instante del servidor (reloj.ahora(), día
simulado en simulación). No hay vigencia, programación ni motivo escrito por
el usuario. Los errores traen además `motivo`: horario_invalido,
comida_inexistente, solapa_con_otra_comida, version_desactualizada,
sin_cambios, instante_no_posterior, cambio_en_curso, parametro_retirado,
momento_con_zona.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core import reloj
from app.core.autorizacion import ErrorAuth, UsuarioActual
from app.core.db import SesionDep
from app.esquemas.auth import ErrorConMotivo
from app.esquemas.reglas import CrearHorario, HorarioRegla, ListaDerecho, VersionDerecho
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
    summary="Versión vigente y todas las versiones (solo lectura)",
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
    "/horarios",
    response_model=list[HorarioRegla],
    summary="Horario que rige en un instante, una fila por comida",
    responses={422: {"model": ErrorConMotivo}},
)
def listar_horarios(
    sesion: SesionDep,
    momento: Annotated[
        datetime | None,
        Query(
            description=(
                "Instante a consultar, hora local del servidor y SIN zona: "
                "'2026-09-24T16:00:00.250000'. Con 'Z' o desfase, 422 "
                "momento_con_zona. Por defecto, ahora"
            )
        ),
    ] = None,
    fecha: Annotated[str | None, Query(include_in_schema=False)] = None,
) -> list[HorarioRegla]:
    if fecha is not None:
        raise ErrorAuth(
            422,
            "parametro_retirado",
            "`fecha` ya no existe: use `momento` (datetime) o no mande nada para ahora.",
        )
    if momento is not None and momento.tzinfo is not None:
        # 'Z' o desfase: el reloj del negocio es hora local sin zona, y un
        # instante con zona no se puede comparar con ella sin adivinar.
        raise ErrorAuth(
            422,
            "momento_con_zona",
            "`momento` va sin zona horaria (hora local del servidor): "
            "sin 'Z' ni desfase, por ejemplo 2026-09-24T16:00:00.250000.",
        )
    return [
        HorarioRegla(**d)
        for d in reglas.listar_horarios(sesion, reloj.ahora() if momento is None else momento)
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
    summary="Guardar el horario de una comida, con efecto inmediato",
    responses=CON_MOTIVO,
)
def crear_horario(
    sesion: SesionDep, datos: CrearHorario, usuario: UsuarioActual
) -> HorarioRegla:
    # Valores simples ANTES de la lógica: esta termina la transacción de la
    # autenticación y el rollback expira los objetos ORM de la sesión.
    cuenta_id, autor = usuario.id, usuario.username
    try:
        creado = reglas.guardar_horario(
            sesion,
            datos.comida_id,
            datos.hora_inicio,
            datos.hora_fin,
            datos.base_horario_id,
            cuenta_id,
            autor,
        )
    except ErrorRegla as error:
        raise _traducir(error) from error
    return HorarioRegla(**creado)
