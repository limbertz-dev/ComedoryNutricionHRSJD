"""El lector biométrico real: lecturas del aparato y vínculos de sus huellas.

Dos routers con puertas distintas:

  · `router` (/lector/salud, /lector/lecturas): lo llama el PUENTE de la PC
    de cocina, con la clave del lector en `X-Lector-Token` (LECTORES en .env).
    No acepta el token de una persona: una sesión humana nunca declara una
    marcación biométrica (ver app/core/permisos.py).
  · `vinculos` (/lector/vinculos): jefatura, con su sesión. Traduce el
    identificador que entrega el lector a una persona del padrón.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, status
from fastapi.responses import JSONResponse

from app.core.autorizacion import ErrorAuth, UsuarioActual, no_autenticado
from app.core.db import SesionDep
from app.esquemas.lector import (
    Plantilla,
    RespuestaLectura,
    SaludLector,
    SolicitudLectura,
    SolicitudVinculo,
    Vinculo,
)
from app.logica import intervencion, lector

router = APIRouter(prefix="/lector", tags=["lector"])
vinculos = APIRouter(prefix="/lector/vinculos", tags=["lector"])


def lector_autorizado(
    x_lector_token: Annotated[
        str | None,
        Header(alias="X-Lector-Token", description="Clave del lector, de LECTORES en .env."),
    ] = None,
) -> str:
    """El nombre del lector dueño de la clave. 401 sin clave o con una desconocida."""
    if not x_lector_token:
        raise no_autenticado("falta_token", "Falta la clave del lector (X-Lector-Token).")
    dispositivo = lector.dispositivo_de(x_lector_token)
    if dispositivo is None:
        raise no_autenticado("lector_no_autorizado", "La clave del lector no es válida.")
    return dispositivo


LectorAutorizado = Annotated[str, Depends(lector_autorizado)]


@router.get("/salud", response_model=SaludLector, summary="Comprobar la conexión del lector")
def salud(sesion: SesionDep, dispositivo: LectorAutorizado) -> SaludLector:
    """Para el arranque del puente: confirma la clave, la hora del servidor y
    cuántas huellas hay vinculadas. No escribe nada."""
    return SaludLector(**lector.salud(sesion, dispositivo))


@router.get("/plantillas", response_model=list[Plantilla], summary="Plantillas para el SDK del lector")
def plantillas(sesion: SesionDep, _dispositivo: LectorAutorizado) -> list[Plantilla]:
    """Solo con la clave del lector: las huellas enroladas con un lector USB
    (ZK9500/ZK4500), para que el puente compare en la PC. Nunca salen por
    /lector/vinculos ni con la sesión de una persona."""
    return [Plantilla(**p) for p in lector.plantillas(sesion)]


@router.post(
    "/lecturas",
    response_model=RespuestaLectura,
    summary="Registrar un toque de dedo",
    responses={409: {"description": "Idempotency-Key reutilizada con otro contenido"}},
)
def registrar_lectura(
    sesion: SesionDep,
    solicitud: SolicitudLectura,
    dispositivo: LectorAutorizado,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", description="UUID v4 por toque de dedo; se repite solo al reintentar ese toque."),
    ] = None,
):
    """Registra la lectura con las reglas de siempre y la hora del servidor.

    200 tanto si la ración se habilita como si se rechaza (`valido` lo dice):
    el puente muestra el resultado a la cocinera. Un reintento con la misma
    Idempotency-Key devuelve lo guardado (`reintento=true`) sin escribir otra
    lectura.
    """
    clave = intervencion.normalizar_clave(idempotency_key)
    if clave is None:
        raise ErrorAuth(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "clave_idempotencia_invalida",
            "Falta la cabecera Idempotency-Key o no es un UUID v4.",
        )
    try:
        resultado = lector.registrar_lectura(
            sesion, dispositivo=dispositivo, clave=clave, identificador=solicitud.identificador
        )
    except lector.ConflictoLector as error:
        return JSONResponse(status_code=409, content={"detail": error.detalle, "motivo": error.motivo})
    return RespuestaLectura(**resultado.cuerpo)


@vinculos.get("", response_model=list[Vinculo], summary="Huellas vinculadas")
def listar(
    sesion: SesionDep,
    activos: Annotated[bool, Query(description="Solo los vínculos vigentes.")] = True,
) -> list[Vinculo]:
    return [Vinculo(**v) for v in lector.listar_vinculos(sesion, solo_activos=activos)]


@vinculos.post("", response_model=Vinculo, status_code=201, summary="Vincular una huella a una persona")
def vincular(sesion: SesionDep, solicitud: SolicitudVinculo, usuario: UsuarioActual):
    """El identificador es el que muestra el lector al enrolar la huella. Uno
    dado de baja se puede volver a vincular, también a otra persona."""
    cuenta_id = usuario.id
    try:
        return Vinculo(**lector.vincular(
            sesion, identificador=solicitud.identificador,
            usuario_id=solicitud.usuario_id, cuenta_id=cuenta_id,
            plantilla=solicitud.plantilla, tipo=solicitud.tipo,
            nombre=solicitud.nombre, documento=solicitud.documento,
        ))
    except LookupError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except lector.ConflictoLector as error:
        return JSONResponse(status_code=409, content={"detail": error.detalle, "motivo": error.motivo})


@vinculos.delete("/{vinculo_id}", response_model=Vinculo, summary="Dar de baja un vínculo")
def dar_de_baja(
    sesion: SesionDep,
    vinculo_id: Annotated[int, Path(gt=0)],
) -> Vinculo:
    """Baja lógica: el identificador deja de reconocer a la persona y sus
    lecturas pasadas se conservan."""
    try:
        return Vinculo(**lector.dar_de_baja(sesion, vinculo_id))
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
