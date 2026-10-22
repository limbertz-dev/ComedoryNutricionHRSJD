"""Administración de cuentas para root. Solo rol sistemas (ACCESO["admin"]).

CONTRATO con el front (no cambiar sin avisar):

    GET  /admin/cuentas                no eliminadas, con nombre y último ingreso
    GET  /admin/candidatos?busqueda=   personas del padrón (búsqueda de 2+ letras)
    POST /admin/cuentas                {..., password} → 201 {cuenta}
    PATCH /admin/cuentas/{id}          {nombre?, rol?} → 200 cuenta
    POST /admin/cuentas/{id}/desactivar      200 cuenta (cierra sus sesiones)
    POST /admin/cuentas/{id}/reactivar       200 cuenta
    DELETE /admin/cuentas/{id}              204 baja lógica, sin borrar historial
    POST /admin/cuentas/{id}/clave     {password} → 200 {cuenta} (cierra sus sesiones)

Root elige la contraseña: la cuenta entra con ella sin cambio obligatorio.
Las contraseñas nunca vuelven en una respuesta.

Los errores traen además `motivo`: username_en_uso, persona_ya_tiene_cuenta,
persona_inexistente, login_invalido, rol_no_permitido, password_rechazada,
cuenta_inexistente, no_puede_desactivarse_a_si_misma, ultima_cuenta_sistemas.
"""

from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status

from app.core.autorizacion import ErrorAuth, UsuarioActual
from app.core.db import SesionDep
from app.esquemas.admin import ActualizarCuenta, Candidato, CrearCuenta, CuentaAdmin, CuentaRespuesta, NuevaClave
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
    response_model=CuentaRespuesta,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una cuenta",
    responses=CON_MOTIVO,
)
def crear_cuenta(
    sesion: SesionDep, datos: CrearCuenta, usuario: UsuarioActual
) -> CuentaRespuesta:
    """Vinculada {rol, usuario_turnos_id, password} o sin vínculo
    {rol, username, nombre, password}. Queda lista para ingresar."""
    try:
        cuenta = cuentas.crear_cuenta(
            sesion,
            datos.rol,
            datos.usuario_turnos_id,
            datos.username,
            datos.nombre,
            datos.password,
            usuario,
        )
    except ErrorCuenta as error:
        raise ErrorAuth(error.status_code, error.motivo, error.detail) from error
    return CuentaRespuesta(cuenta=CuentaAdmin(**cuentas.cuenta_para_respuesta(sesion, cuenta)))


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


@router.patch(
    "/cuentas/{cuenta_id}",
    response_model=CuentaAdmin,
    summary="Editar nombre y rol de una cuenta",
    responses=CON_MOTIVO,
)
def editar_cuenta(
    sesion: SesionDep,
    datos: ActualizarCuenta,
    cuenta_id: Annotated[int, Path(gt=0, description="Id de la cuenta")],
) -> CuentaAdmin:
    try:
        cuenta = cuentas.editar_cuenta(sesion, cuenta_id, datos.nombre, datos.rol)
    except ErrorCuenta as error:
        raise ErrorAuth(error.status_code, error.motivo, error.detail) from error
    return CuentaAdmin(**cuentas.cuenta_para_respuesta(sesion, cuenta))


@router.delete(
    "/cuentas/{cuenta_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Ocultar y desactivar una cuenta conservando sus registros",
    responses=CON_MOTIVO,
)
def eliminar_cuenta(
    sesion: SesionDep,
    cuenta_id: Annotated[int, Path(gt=0, description="Id de la cuenta")],
    usuario: UsuarioActual,
) -> Response:
    try:
        cuentas.eliminar_cuenta(sesion, cuenta_id, usuario)
    except ErrorCuenta as error:
        raise ErrorAuth(error.status_code, error.motivo, error.detail) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/cuentas/{cuenta_id}/clave",
    response_model=CuentaRespuesta,
    summary="Cambiar la contraseña de una cuenta",
    responses=CON_MOTIVO,
)
def cambiar_clave(
    sesion: SesionDep,
    datos: NuevaClave,
    cuenta_id: Annotated[int, Path(gt=0, description="Id de la cuenta")],
) -> CuentaRespuesta:
    """Root fija la contraseña nueva. Cierra las sesiones abiertas de esa
    cuenta y no pide cambio en el próximo ingreso."""
    try:
        cuenta = cuentas.cambiar_clave(sesion, cuenta_id, datos.password)
    except ErrorCuenta as error:
        raise ErrorAuth(error.status_code, error.motivo, error.detail) from error
    return CuentaRespuesta(cuenta=CuentaAdmin(**cuentas.cuenta_para_respuesta(sesion, cuenta)))
