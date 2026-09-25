"""Control del reloj para probar con fechas pasadas. Solo ENTORNO=simulacion.

app/main.py monta este router únicamente en simulación: en producción y en
desarrollo /simulacion/* no existe (404). Y la configuración no deja arrancar
la simulación contra las bases reales (app/core/config.py).

La hora se fija ACÁ, con rol de jefatura; la marcación sigue sin aceptar la
hora del cliente en el biométrico. Mover el reloj no toca la seguridad: el
bloqueo de login y los JWT usan la hora real (app/core/reloj.py).
"""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, status

from app.consultas import franjas
from app.core import reloj
from app.core.db import SesionDep
from app.esquemas.simulacion import AvanzarReloj, EstadoReloj, FijarReloj, ProximaFranja

router = APIRouter(prefix="/simulacion", tags=["simulación"])


def _estado() -> EstadoReloj:
    return EstadoReloj(**asdict(reloj.estado()))


@router.get("/reloj", response_model=EstadoReloj, summary="Hora que ve el sistema")
def ver_reloj() -> EstadoReloj:
    return _estado()


@router.put("/reloj", response_model=EstadoReloj, summary="Fijar el reloj")
def fijar_reloj(solicitud: FijarReloj) -> EstadoReloj:
    reloj.fijar(solicitud.momento, congelar=solicitud.congelar)
    return _estado()


@router.post("/reloj/avanzar", response_model=EstadoReloj, summary="Adelantar el reloj")
def avanzar_reloj(solicitud: AvanzarReloj) -> EstadoReloj:
    reloj.avanzar(solicitud.cuanto)
    return _estado()


@router.post(
    "/reloj/proxima-franja",
    response_model=ProximaFranja,
    summary="Saltar al inicio de la próxima franja de comida",
)
def proxima_franja(sesion: SesionDep) -> ProximaFranja:
    """Fija el reloj en el inicio de la próxima franja según `horarios_comida`
    (si hoy no queda ninguna, la primera de mañana). El servidor decide la
    hora; el reloj sigue corriendo desde ahí. 409 si no hay ninguna."""
    franja = franjas.proxima_franja(sesion, reloj.ahora())
    if franja is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No hay ninguna franja de comida vigente hoy ni mañana.",
        )
    reloj.fijar(franja.inicio)
    return ProximaFranja(**asdict(franja), reloj=_estado())


@router.delete("/reloj", response_model=EstadoReloj, summary="Volver a la hora real")
def volver_a_real() -> EstadoReloj:
    reloj.volver_a_real()
    return _estado()
