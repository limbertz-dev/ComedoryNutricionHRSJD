"""Lista de cuentas de solo lectura para la jefa. Jefa y sistemas (ACCESO["cuentas"]).

CONTRATO con el front (no cambiar sin avisar):

    GET /cuentas   [{id, username, nombre, rol, activo, debe_cambiar, ultimo_ingreso}]

La jefa NO recibe cuentas de rol sistemas; la cocinera recibe 403.
Sin datos del padrón ni usuario_turnos_id. Reutiliza listar de logica/cuentas.
"""

from fastapi import APIRouter

from app.core.autorizacion import UsuarioActual
from app.core.db import SesionDep
from app.esquemas.auth import ErrorConMotivo
from app.esquemas.cuentas import CuentaLectura
from app.logica import cuentas

router = APIRouter(prefix="/cuentas", tags=["cuentas"])


@router.get(
    "",
    response_model=list[CuentaLectura],
    summary="Cuentas en solo lectura",
    responses={403: {"model": ErrorConMotivo}},
)
def listar_cuentas(
    sesion: SesionDep, usuario: UsuarioActual
) -> list[CuentaLectura]:
    todas = cuentas.listar_cuentas(sesion)
    if usuario.rol == "jefa":
        todas = [c for c in todas if c["rol"] != "sistemas"]
    return [
        CuentaLectura(
            id=c["id"],
            username=c["username"],
            nombre=c["nombre"],
            rol=c["rol"],
            activo=c["activo"],
            debe_cambiar=c["debe_cambiar"],
            ultimo_ingreso=c["ultimo_ingreso"],
        )
        for c in todas
    ]
