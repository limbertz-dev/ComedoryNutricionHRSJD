"""Dependencias de FastAPI que deciden quién pasa.

Todo error de auth lleva un `motivo` legible por máquina además del `detail`
para personas, así el front sabe qué hacer sin interpretar textos:

    401 falta_token            no mandó Authorization: Bearer
    401 token_invalido         firma mala, token de otro tipo, cuenta dada
                               de baja o sesión anulada por cambio de clave
    401 token_expirado         el front renueva con POST /auth/refresh
    403 cambio_password_pendiente   token temporal (o clave temporal): solo
                               sirve POST /auth/cambio-password
    403 rol_no_autorizado      el rol no abre ese recurso
    403 metodo_no_autorizado   la cocinera intentó una marcación manual
    403 biometrico_solo_lector marcación biométrica desde una sesión fuera
                               de simulación (cualquier rol)
"""

from collections.abc import Callable, Iterable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core import seguridad
from app.core.db import SesionDep
from app.core.permisos import BIOMETRICO_DESDE_SESION, MARCACION_MANUAL
from app.modelos.usuarios import UsuarioSistema


class ErrorAuth(HTTPException):
    """HTTPException con `motivo`. El manejador de app/main.py lo agrega al
    cuerpo: {"detail": "...", "motivo": "..."}."""

    def __init__(self, status_code: int, motivo: str, detail: str):
        headers = (
            {"WWW-Authenticate": "Bearer"}
            if status_code == status.HTTP_401_UNAUTHORIZED
            else None
        )
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.motivo = motivo


def no_autenticado(motivo: str, detail: str = "Sesión inválida o vencida.") -> ErrorAuth:
    return ErrorAuth(status.HTTP_401_UNAUTHORIZED, motivo, detail)


def prohibido(motivo: str, detail: str) -> ErrorAuth:
    return ErrorAuth(status.HTTP_403_FORBIDDEN, motivo, detail)


CAMBIO_PENDIENTE = (
    "Debe cambiar la contraseña temporal antes de usar el sistema."
)

# auto_error=False: sin token respondemos nosotros, con 401 y motivo, en vez
# del 403 genérico que devuelve HTTPBearer.
_bearer = HTTPBearer(auto_error=False, description="Token de acceso de POST /auth/login")
Credenciales = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]


def leer_carga(credenciales: HTTPAuthorizationCredentials | None) -> dict:
    if credenciales is None:
        raise no_autenticado("falta_token", "Falta el token de acceso.")
    try:
        return seguridad.leer_token(credenciales.credentials)
    except seguridad.TokenInvalido as error:
        raise no_autenticado(error.motivo) from error


def cargar_usuario(sesion: Session, carga: dict) -> UsuarioSistema:
    """La cuenta dueña del token, si sigue activa y el token sigue vigente.

    Se consulta la base en cada petición a propósito: dar de baja una cuenta
    o cambiarle la clave corta sus sesiones en el acto, sin esperar a que
    venza el token.
    """
    usuario = sesion.get(UsuarioSistema, int(carga["sub"]))
    if usuario is None or not usuario.activo or usuario.version_token != carga["ver"]:
        raise no_autenticado("token_invalido")
    return usuario


def usuario_actual(sesion: SesionDep, credenciales: Credenciales) -> UsuarioSistema:
    """La cuenta de un token de ACCESO. Un temporal no pasa de acá."""
    carga = leer_carga(credenciales)
    if carga["typ"] == seguridad.TEMPORAL:
        raise prohibido("cambio_password_pendiente", CAMBIO_PENDIENTE)
    if carga["typ"] != seguridad.ACCESS:
        raise no_autenticado("token_invalido")
    usuario = cargar_usuario(sesion, carga)
    if usuario.debe_cambiar:
        raise prohibido("cambio_password_pendiente", CAMBIO_PENDIENTE)
    return usuario


UsuarioActual = Annotated[UsuarioSistema, Depends(usuario_actual)]


def requiere_rol(
    *roles: str, lectura: Iterable[str] = ()
) -> Callable[..., UsuarioSistema]:
    """Dependencia: pasa solo una cuenta cuyo rol esté en `roles`.

    `lectura` son roles que pasan únicamente en GET/HEAD. Uso:

        app.include_router(r, dependencies=[Depends(requiere_rol("jefa", "sistemas"))])
    """
    completo = frozenset(roles)
    solo_lectura = frozenset(lectura)

    def dependencia(request: Request, usuario: UsuarioActual) -> UsuarioSistema:
        if usuario.rol in completo:
            return usuario
        if usuario.rol in solo_lectura:
            if request.method in ("GET", "HEAD"):
                return usuario
            raise prohibido(
                "rol_no_autorizado",
                f"El rol '{usuario.rol}' solo puede consultar este recurso.",
            )
        raise prohibido(
            "rol_no_autorizado",
            f"El rol '{usuario.rol}' no tiene acceso a este recurso.",
        )

    return dependencia


def exigir_origen_biometrico(entorno: str, metodo: str) -> None:
    """Biométrico desde una sesión humana solo en simulación.

    Con un token de persona, `metodo='biometrico'` es solo lo que el navegador
    declara: nada prueba que alguien haya apoyado el dedo. Fuera de
    simulación se rechaza sin mirar el rol y sin convertirlo en manual.
    `entorno` es el de la app (app/core/entorno.py).
    """
    if metodo == "biometrico" and entorno not in BIOMETRICO_DESDE_SESION:
        raise prohibido(
            "biometrico_solo_lector",
            "La marcación biométrica requiere un lector autorizado fuera de simulación.",
        )


def exigir_metodo_marcacion(usuario: UsuarioSistema, metodo: str) -> None:
    """Manual solo jefatura: registrar a mano salta el lector."""
    if metodo == "manual" and usuario.rol not in MARCACION_MANUAL:
        raise prohibido(
            "metodo_no_autorizado",
            f"El rol '{usuario.rol}' solo puede marcar con el lector biométrico.",
        )
