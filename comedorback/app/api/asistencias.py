"""Endpoint de marcación: registrar una ración servida."""

from fastapi import APIRouter, HTTPException, status

from app.core.autorizacion import (
    UsuarioActual,
    exigir_metodo_marcacion,
    exigir_origen_biometrico,
)
from app.core.db import SesionDep
from app.core.entorno import EntornoDep
from app.esquemas.marcacion import RespuestaMarcacion, SolicitudMarcacion
from app.logica import marcacion

router = APIRouter(prefix="/asistencias", tags=["asistencias"])

# Toda marcación de esta ruta llega con el token de una persona, desde el
# navegador. El dispositivo lo fija el servidor: el texto del cliente no
# distingue nada y en la bitácora parecería un lector que no existe.
DISPOSITIVO_NAVEGADOR = "simulador-navegador"


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
    entorno: EntornoDep,
) -> RespuestaMarcacion:
    """Aplica las reglas del comedor y registra la ración si todas pasan.

    Devuelve 200 tanto si la ración se habilita como si se rechaza: un rechazo
    no es un error de la API, es una respuesta legítima del negocio que el
    lector tiene que mostrar en pantalla. Una lectura biometrica sin usuario
    se registra como auditoria `no_identificado`. El campo `valido` lo distingue.

    La marcación biométrica (también con `metodo` omitido) solo se acepta en
    simulación: en producción y desarrollo da 403 `biometrico_solo_lector`
    antes de tocar la lógica, sin lecturas ni asistencias. La manual es solo
    de jefatura (403 `metodo_no_autorizado` para la cocinera); ver
    app/core/permisos.py.
    """
    exigir_origen_biometrico(entorno, solicitud.metodo)
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
