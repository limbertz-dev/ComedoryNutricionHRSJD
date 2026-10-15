"""Endpoint de marcación: registrar una ración servida."""

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Path, status
from fastapi.responses import JSONResponse

from app.core.autorizacion import (
    ErrorAuth,
    UsuarioActual,
    UsuarioIdentificador,
    exigir_metodo_marcacion,
    exigir_origen_biometrico,
)
from app.core.db import SesionDep
from app.esquemas.intervenciones import (
    ErrorIntervencionCuerpo,
    RespuestaIdentificacion,
    SolicitudIdentificacion,
)
from app.esquemas.marcacion import RespuestaMarcacion, SolicitudMarcacion
from app.logica import intervencion, marcacion

router = APIRouter(prefix="/asistencias", tags=["asistencias"])

# Toda marcación de esta ruta llega con el token de una persona, desde el
# navegador, y es manual. El dispositivo lo fija el servidor: el texto del
# cliente no distingue nada y en la bitácora parecería un lector que no existe.
DISPOSITIVO_NAVEGADOR = "registro-manual"


@router.post(
    "",
    response_model=RespuestaMarcacion,
    summary="Marcar una ración",
    status_code=status.HTTP_200_OK,
)
def marcar(
    sesion: SesionDep,
    solicitud: SolicitudMarcacion,
    usuario: UsuarioActual,
) -> RespuestaMarcacion:
    """Aplica las reglas del comedor y registra la ración si todas pasan.

    Devuelve 200 tanto si la ración se habilita como si se rechaza: un rechazo
    no es un error de la API, es una respuesta legítima del negocio que el
    lector tiene que mostrar en pantalla. Una lectura biometrica sin usuario
    se registra como auditoria `no_identificado`. El campo `valido` lo distingue.

    La marcación biométrica (también con `metodo` omitido) da 403
    `biometrico_solo_lector` antes de tocar la lógica, sin lecturas ni
    asistencias: solo la declara un lector autorizado. La manual es solo de
    jefatura (403 `metodo_no_autorizado` para la cocinera); ver
    app/core/permisos.py.
    """
    exigir_origen_biometrico(solicitud.metodo)
    exigir_metodo_marcacion(usuario, solicitud.metodo)
    if solicitud.momento is not None and solicitud.metodo != "manual":
        raise HTTPException(
            status_code=422,
            detail="El momento solo se puede fijar con metodo='manual'",
        )

    resultado = marcacion.registrar_marcacion(
        sesion,
        usuario_id=solicitud.usuario_id,
        momento=solicitud.momento,
        dispositivo=DISPOSITIVO_NAVEGADOR,
        metodo=solicitud.metodo,
        registrado_por_cuenta=(
            usuario.id if solicitud.metodo == "manual" else None
        ),
    )
    return RespuestaMarcacion(**vars(resultado))


@router.post(
    "/lecturas/{lectura_id}/identificar",
    response_model=RespuestaIdentificacion,
    summary="Identificar una lectura no reconocida y confirmar la entrega",
    responses={
        403: {"model": ErrorIntervencionCuerpo},
        404: {"model": ErrorIntervencionCuerpo},
        409: {"model": ErrorIntervencionCuerpo},
        422: {"model": ErrorIntervencionCuerpo},
        503: {"model": ErrorIntervencionCuerpo},
    },
)
def identificar_lectura(
    sesion: SesionDep,
    lectura_id: Annotated[int, Path(gt=0, description="lecturas_biometricas.id")],
    solicitud: SolicitudIdentificacion,
    usuario: UsuarioIdentificador,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="UUID v4 por intento. Se reutiliza SOLO para repetir la misma decisión.",
        ),
    ] = None,
):
    """La cocinera identifica a quien está frente al lector y confirma la entrega.

    Solo cocinera (jefa y sistemas: 403 `rol_no_autorizado`, antes de validar
    nada más). El servidor vuelve a comprobar derecho, servicio y duplicado, y
    registra la asistencia vinculada a la lectura y una fila de auditoría. La
    lectura original no se modifica, y esto NO amplía `POST /asistencias`
    manual, que sigue siendo solo de jefatura.

    Una regla de la persona (`sin_derecho`, `duplicado`) responde 200 con
    `valido=false` y `resultado="rechazada"`: es un intento rechazado, no una
    entrega. Un conflicto sobre la lectura responde 409 con `motivo`. Un
    reintento con la misma `Idempotency-Key` y la misma persona devuelve lo
    guardado (`reintento=true`), también si el resultado fue un rechazo; con
    otra persona, 409 `clave_reutilizada_con_otro_contenido`. 503
    `resultado_incierto` quiere decir que no se sabe qué quedó: repetir con la
    misma clave.
    """
    clave = intervencion.normalizar_clave(idempotency_key)
    if clave is None:
        raise ErrorAuth(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "clave_idempotencia_invalida",
            "Falta la cabecera Idempotency-Key o no es un UUID v4.",
        )
    # La autenticación dejó la cuenta en un objeto ORM; el rollback de la
    # lógica lo expira. Se copia ahora, como valor simple.
    cuenta_id = usuario.id
    try:
        resultado = intervencion.identificar_lectura(
            sesion,
            cuenta_id=cuenta_id,
            lectura_id=lectura_id,
            usuario_id=solicitud.usuario_id,
            clave=clave,
        )
    except intervencion.ErrorIntervencion as error:
        return JSONResponse(status_code=error.status_code, content=error.cuerpo())
    return RespuestaIdentificacion(**vars(resultado))
