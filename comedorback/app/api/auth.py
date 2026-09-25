"""Ingreso al sistema: login, cambio de clave, renovación y "quién soy".

CONTRATO con el front (no cambiar sin avisar):

    POST /auth/login             200 {access, refresh, rol, debe_cambiar}
                                 401 credenciales inválidas
                                 423 {reintento_en}  cuenta bloqueada
                                 428 {temporal}      clave temporal: cambiarla
    POST /auth/cambio-password   con el temporal del 428 o con un access
    POST /auth/refresh           {refresh} -> 200 como login, con access nuevo
    GET  /auth/yo                {id, username, rol, debe_cambiar}

Los errores traen además `motivo` (ver app/core/autorizacion.py).
"""

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder

from app.core import seguridad
from app.core.autorizacion import (
    CAMBIO_PENDIENTE,
    Credenciales,
    ErrorAuth,
    UsuarioActual,
    cargar_usuario,
    leer_carga,
    no_autenticado,
    prohibido,
)
from app.core.db import SesionDep
from app.esquemas.auth import (
    CambioPendiente,
    CuentaBloqueada,
    ErrorConMotivo,
    SesionIniciada,
    SolicitudCambioPassword,
    SolicitudLogin,
    SolicitudRefresh,
    Yo,
)
from app.logica import autenticacion
from app.modelos.usuarios import UsuarioSistema

router = APIRouter(prefix="/auth", tags=["autenticación"])


def _sesion_para(usuario: UsuarioSistema, refresh: str | None = None) -> SesionIniciada:
    return SesionIniciada(
        access=seguridad.emitir_token(
            usuario_id=usuario.id,
            tipo=seguridad.ACCESS,
            version=usuario.version_token,
            rol=usuario.rol,
        ),
        refresh=refresh
        or seguridad.emitir_token(
            usuario_id=usuario.id,
            tipo=seguridad.REFRESH,
            version=usuario.version_token,
        ),
        rol=usuario.rol,
        debe_cambiar=bool(usuario.debe_cambiar),
    )


def _bloqueada(hasta) -> JSONResponse:
    reintento = hasta.astimezone()  # hora local, con su desfase explícito
    segundos = max(1, int((hasta - autenticacion.ahora()).total_seconds()))
    cuerpo = CuentaBloqueada(
        detail="Cuenta bloqueada por intentos fallidos. Intente más tarde.",
        motivo="cuenta_bloqueada",
        reintento_en=reintento,
    )
    return JSONResponse(
        jsonable_encoder(cuerpo),
        status_code=status.HTTP_423_LOCKED,
        headers={"Retry-After": str(segundos)},
    )


@router.post(
    "/login",
    response_model=SesionIniciada,
    summary="Iniciar sesión",
    responses={
        401: {"model": ErrorConMotivo, "description": "Credenciales inválidas"},
        423: {"model": CuentaBloqueada, "description": "Cuenta bloqueada"},
        428: {"model": CambioPendiente, "description": "Clave temporal: cambiarla"},
    },
)
def login(sesion: SesionDep, datos: SolicitudLogin, request: Request):
    """401 no dice si falló el usuario o la clave, a propósito."""
    ip = request.client.host if request.client else None
    ingreso = autenticacion.ingresar(sesion, datos.username, datos.password, ip)

    if ingreso.hasta is not None:
        return _bloqueada(ingreso.hasta)
    if ingreso.usuario is None:
        raise no_autenticado("credenciales_invalidas", "Usuario o contraseña incorrectos.")

    usuario = ingreso.usuario
    if usuario.debe_cambiar:
        temporal = seguridad.emitir_token(
            usuario_id=usuario.id,
            tipo=seguridad.TEMPORAL,
            version=usuario.version_token,
        )
        cuerpo = CambioPendiente(
            detail=CAMBIO_PENDIENTE, motivo="cambio_password_pendiente", temporal=temporal
        )
        return JSONResponse(
            jsonable_encoder(cuerpo), status_code=status.HTTP_428_PRECONDITION_REQUIRED
        )
    return _sesion_para(usuario)


@router.post(
    "/cambio-password",
    response_model=SesionIniciada,
    summary="Cambiar la contraseña",
    responses={
        400: {"model": ErrorConMotivo, "description": "Contraseña actual incorrecta"},
        401: {"model": ErrorConMotivo},
        422: {"model": ErrorConMotivo, "description": "La clave nueva no cumple la política"},
        423: {"model": CuentaBloqueada},
    },
)
def cambio_password(
    sesion: SesionDep, datos: SolicitudCambioPassword, credenciales: Credenciales, request: Request
):
    """Acepta el token temporal del 428 o un token de acceso.

    Con el de acceso (cambio voluntario) pide la clave actual; un error ahí
    cuenta como intento fallido para el bloqueo, para que un token robado no
    sirva para adivinarla. Devuelve una sesión nueva: las anteriores, y el
    propio temporal, quedan anuladas.
    """
    carga = leer_carga(credenciales)
    if carga["typ"] not in (seguridad.TEMPORAL, seguridad.ACCESS):
        raise no_autenticado("token_invalido")
    usuario = cargar_usuario(sesion, carga)

    if carga["typ"] == seguridad.ACCESS:
        if usuario.debe_cambiar:
            raise prohibido("cambio_password_pendiente", CAMBIO_PENDIENTE)
        if not datos.password_actual:
            raise ErrorAuth(400, "password_actual_requerida", "Falta la contraseña actual.")
        ip = request.client.host if request.client else None
        ingreso = autenticacion.ingresar(sesion, usuario.username, datos.password_actual, ip)
        if ingreso.hasta is not None:
            return _bloqueada(ingreso.hasta)
        if ingreso.usuario is None:
            raise ErrorAuth(
                400, "password_actual_incorrecta", "La contraseña actual no es correcta."
            )

    try:
        autenticacion.validar_clave_nueva(usuario, datos.password_nueva)
    except autenticacion.ClaveRechazada as error:
        raise ErrorAuth(422, "password_rechazada", str(error)) from error

    autenticacion.fijar_clave(sesion, usuario, datos.password_nueva, temporal=False)
    return _sesion_para(usuario)


@router.post(
    "/refresh",
    response_model=SesionIniciada,
    summary="Renovar el token de acceso",
    responses={401: {"model": ErrorConMotivo}, 403: {"model": ErrorConMotivo}},
)
def refresh(sesion: SesionDep, datos: SolicitudRefresh) -> SesionIniciada:
    """Devuelve un access nuevo y el MISMO refresh: la sesión no se estira
    más allá de AUTH_REFRESH_HORAS desde el login."""
    try:
        carga = seguridad.leer_token(datos.refresh)
    except seguridad.TokenInvalido as error:
        raise no_autenticado(error.motivo) from error
    if carga["typ"] != seguridad.REFRESH:
        raise no_autenticado("token_invalido")
    usuario = cargar_usuario(sesion, carga)
    if usuario.debe_cambiar:
        raise prohibido("cambio_password_pendiente", CAMBIO_PENDIENTE)
    return _sesion_para(usuario, refresh=datos.refresh)


@router.get(
    "/yo",
    response_model=Yo,
    summary="La cuenta de la sesión actual",
    responses={401: {"model": ErrorConMotivo}, 403: {"model": ErrorConMotivo}},
)
def yo(usuario: UsuarioActual) -> Yo:
    return Yo(
        id=usuario.id,
        username=usuario.username,
        rol=usuario.rol,
        debe_cambiar=bool(usuario.debe_cambiar),
    )
