"""Endpoint de marcación: registrar una ración servida."""

from fastapi import APIRouter, HTTPException, status

from app.core.db import SesionDep
from app.esquemas.marcacion import RespuestaMarcacion, SolicitudMarcacion
from app.logica import marcacion

router = APIRouter(prefix="/asistencias", tags=["asistencias"])


@router.post(
    "",
    response_model=RespuestaMarcacion,
    summary="Marcar una ración",
    status_code=status.HTTP_200_OK,
)
def marcar(sesion: SesionDep, solicitud: SolicitudMarcacion) -> RespuestaMarcacion:
    """Aplica las reglas del comedor y registra la ración si todas pasan.

    Devuelve 200 tanto si la ración se habilita como si se rechaza: un rechazo
    no es un error de la API, es una respuesta legítima del negocio que el
    lector tiene que mostrar en pantalla. Una lectura biometrica sin usuario
    se registra como auditoria `no_identificado`. El campo `valido` lo distingue.
    """
    if solicitud.momento is not None and solicitud.metodo != "manual":
        raise HTTPException(
            status_code=422,
            detail="El momento solo se puede fijar con metodo='manual'",
        )

    resultado = marcacion.registrar_marcacion(
        sesion,
        usuario_id=solicitud.usuario_id,
        momento=solicitud.momento,
        dispositivo=solicitud.dispositivo,
        metodo=solicitud.metodo,
        registrado_por=solicitud.registrado_por,
    )
    return RespuestaMarcacion(**vars(resultado))
