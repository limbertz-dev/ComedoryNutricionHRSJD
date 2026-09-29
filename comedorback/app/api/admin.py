"""Administración de cuentas para root. Solo rol sistemas (ACCESO["admin"]).

CONTRATO con el front (no cambiar sin avisar):

    GET  /admin/cuentas                todas, con vínculo, nombre y último ingreso
    GET  /admin/candidatos?busqueda=   personas del padrón (búsqueda de 2+ letras)
    POST /admin/cuentas                201 {cuenta, clave_temporal}
    POST /admin/cuentas/{id}/desactivar      200 cuenta (cierra sus sesiones)
    POST /admin/cuentas/{id}/reactivar       200 cuenta
    POST /admin/cuentas/{id}/reiniciar-clave 200 {cuenta, clave_temporal}

Los errores traen además `motivo`: username_en_uso, persona_ya_tiene_cuenta,
persona_inexistente, login_invalido, rol_no_permitido, cuenta_inexistente,
no_puede_desactivarse_a_si_misma, ultima_cuenta_sistemas.
"""

from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from app.core.autorizacion import ErrorAuth, UsuarioActual
from app.core.db import SesionDep
from app.esquemas.admin import Candidato, CrearCuenta, CuentaAdmin, CuentaConClave
from app.esquemas.auth import ErrorConMotivo
from app.logica import cuentas
from app.logica.cuentas import ErrorCuenta

router = APIRouter(prefix="/admin", tags=["administración"])

CON_MOTIVO = {
    403: {"model": ErrorConMotivo},
    404: {"model": ErrorConMotivo},
    409: {"model": ErrorConMotivo},
    422: {"model": ErrorConMotivo},
}


@router.get(
    "/cuentas",
    response_model=list[CuentaAdmin],
    summary="Todas las cuentas",
    responses={403: {"model": ErrorConMotivo}},
)
def listar_cuentas(sesion: SesionDep) -> list[CuentaAdmin]:
    return [CuentaAdmin(**d) for d in cuentas.listar_cuentas(sesion)]


@router.get(
    "/candidatos",
    response_model=list[Candidato],
    summary="Personas del padrón para vincular",
    responses={403: {"model": ErrorConMotivo}},
)
def listar_candidatos(
    sesion: SesionDep,
    busqueda: Annotated[
        str, Query(min_length=2, max_length=100, description="Busca en nombre y login")
    ],
    limite: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[Candidato]:
    return [
        Candidato(**d)
        for d in cuentas.buscar_candidatos(sesion, busqueda, limite)
    ]


@router.post(
    "/cuentas",
    response_model=CuentaConClave,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una cuenta",
    responses=CON_MOTIVO,
)
def crear_cuenta(
    sesion: SesionDep, datos: CrearCuenta, usuario: UsuarioActual
) -> CuentaConClave:
    """Vinculada {rol, usuario_turnos_id} o sin vínculo {rol, username, nombre}.

    La clave temporal se devuelve una sola vez: no se guarda en ningún log.
    """
    try:
        cuenta, clave = cuentas.crear_cuenta(
            sesion,
            datos.rol,
            datos.usuario_turnos_id,
            datos.username,
            datos.nombre,
            usuario,
        )
    except ErrorCuenta as error:
        raise ErrorAuth(error.status_code, error.motivo, error.detail) from error
    return CuentaConClave(
        cuenta=CuentaAdmin(**cuentas.cuenta_para_respuesta(sesion, cuenta)),
        clave_temporal=clave,
    )


@router.post(
    "/cuentas/{cuenta_id}/desactivar",
    response_model=CuentaAdmin,
    summary="Desactivar una cuenta",
    responses=CON_MOTIVO,
)
def desactivar_cuenta(
    sesion: SesionDep,
    cuenta_id: Annotated[int, Path(gt=0, description="Id de la cuenta")],
    usuario: UsuarioActual,
) -> CuentaAdmin:
    """Cierra sus sesiones en el acto. Ni a sí misma ni a la última de sistemas."""
    try:
        cuenta = cuentas.cambiar_activo(sesion, cuenta_id, False, usuario)
    except ErrorCuenta as error:
        raise ErrorAuth(error.status_code, error.motivo, error.detail) from error
    return CuentaAdmin(**cuentas.cuenta_para_respuesta(sesion, cuenta))


@router.post(
    "/cuentas/{cuenta_id}/reactivar",
    response_model=CuentaAdmin,
    summary="Reactivar una cuenta",
    responses=CON_MOTIVO,
)
def reactivar_cuenta(
    sesion: SesionDep,
    cuenta_id: Annotated[int, Path(gt=0, description="Id de la cuenta")],
    usuario: UsuarioActual,
) -> CuentaAdmin:
    try:
        cuenta = cuentas.cambiar_activo(sesion, cuenta_id, True, usuario)
    except ErrorCuenta as error:
        raise ErrorAuth(error.status_code, error.motivo, error.detail) from error
    return CuentaAdmin(**cuentas.cuenta_para_respuesta(sesion, cuenta))


@router.post(
    "/cuentas/{cuenta_id}/reiniciar-clave",
    response_model=CuentaConClave,
    summary="Dar una clave temporal nueva",
    responses=CON_MOTIVO,
)
def reiniciar_clave(
    sesion: SesionDep,
    cuenta_id: Annotated[int, Path(gt=0, description="Id de la cuenta")],
) -> CuentaConClave:
    """Deja debe_cambiar en 1 y cierra sus sesiones. El próximo login da 428."""
    try:
        cuenta, clave = cuentas.reiniciar_clave(sesion, cuenta_id)
    except ErrorCuenta as error:
        raise ErrorAuth(error.status_code, error.motivo, error.detail) from error
    return CuentaConClave(
        cuenta=CuentaAdmin(**cuentas.cuenta_para_respuesta(sesion, cuenta)),
        clave_temporal=clave,
    )
