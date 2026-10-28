"""Policías por número (Policía 1, 2, ...): alta y baja de la jefatura.

Jefa y sistemas (ACCESO["policias"]). La cocinera los ve y los marca en el
checklist (GET /pantalla/checklist), no los administra.

    GET   /policias                 [{id, numero, nombre, activo}]
    POST  /policias                 da de alta el siguiente número -> 201
    PATCH /policias/{id}  {activo}  baja lógica o reactivación; sus raciones quedan
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, status

from app.core.autorizacion import UsuarioActual
from app.core.db import SesionDep
from app.esquemas.marcacion import PoliciaNumerado, SolicitudEstadoPolicia
from app.logica import policia

router = APIRouter(prefix="/policias", tags=["policias"])


@router.get("", response_model=list[PoliciaNumerado], summary="Policías por número")
def listar(sesion: SesionDep) -> list[PoliciaNumerado]:
    return [PoliciaNumerado(**p) for p in policia.listar_por_numero(sesion)]


@router.post(
    "", response_model=PoliciaNumerado, status_code=status.HTTP_201_CREATED,
    summary="Dar de alta el siguiente policía",
)
def crear(sesion: SesionDep, usuario: UsuarioActual) -> PoliciaNumerado:
    return PoliciaNumerado(**policia.crear_siguiente(sesion, usuario.id))


@router.patch(
    "/{policia_id}", response_model=PoliciaNumerado, summary="Dar de baja o reactivar un policía",
    responses={404: {"description": "No existe"}},
)
def cambiar_estado(
    sesion: SesionDep,
    policia_id: Annotated[int, Path(gt=0, description="policias.id")],
    solicitud: SolicitudEstadoPolicia,
) -> PoliciaNumerado:
    fila = policia.cambiar_activo(sesion, policia_id, solicitud.activo)
    if fila is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ese policía no existe.")
    return PoliciaNumerado(**fila)
