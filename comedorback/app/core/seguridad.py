"""Ajustes y primitivas de la autenticación: hash de claves y tokens JWT.

Los ajustes viven aquí y no en app/core/config.py a propósito: la auth tiene
su propio prefijo en .env (`AUTH_*`) y su propia clase, así que se puede
cambiar sin tocar la configuración que usa el resto del sistema.

Variables de .env (todas opcionales salvo el secreto fuera de desarrollo):

    AUTH_JWT_SECRETO          firma de los tokens, 32+ caracteres. OBLIGATORIO
                              si ENTORNO no es "desarrollo". En desarrollo, si
                              falta, se genera uno al azar en cada arranque
                              (las sesiones se pierden al reiniciar la API).
    AUTH_ACCESS_MINUTOS       vida del token de acceso (15)
    AUTH_REFRESH_HORAS        vida del token de renovación (12, un turno largo)
    AUTH_TEMPORAL_MINUTOS     vida del token de cambio obligatorio de clave (10)
    AUTH_BCRYPT_RONDAS        costo de bcrypt (12; los tests usan 4)
    AUTH_INTENTOS_MAXIMOS     fallidos que bloquean la cuenta (5)
    AUTH_VENTANA_MINUTOS      en cuántos minutos tienen que caer esos fallidos (15)
    AUTH_BLOQUEO_MINUTOS      cuánto dura el bloqueo (15)
"""

import logging
import secrets
from datetime import timedelta
from functools import lru_cache

import bcrypt
import jwt
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core import reloj
from app.core.config import config

log = logging.getLogger(__name__)

# Tipos de token. Van dentro del token (`typ`) y cada dependencia acepta
# solo los suyos: un refresh no abre endpoints y un temporal solo sirve para
# cambiar la clave.
ACCESS = "access"
REFRESH = "refresh"
TEMPORAL = "temporal"

# bcrypt solo mira los primeros 72 bytes de la clave. Más largo se rechaza al
# fijarla, en vez de truncar en silencio.
MAX_BYTES_CLAVE = 72


class AjustesSeguridad(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", env_prefix="AUTH_", extra="ignore"
    )

    jwt_secreto: str = ""
    jwt_algoritmo: str = "HS256"
    access_minutos: int = 15
    refresh_horas: int = 12
    temporal_minutos: int = 10

    bcrypt_rondas: int = 12

    intentos_maximos: int = 5
    ventana_minutos: int = 15
    bloqueo_minutos: int = 15

    largo_minimo_clave: int = 8


@lru_cache
def ajustes() -> AjustesSeguridad:
    return AjustesSeguridad()


@lru_cache
def _secreto() -> str:
    secreto = ajustes().jwt_secreto
    if secreto:
        if len(secreto) < 32:
            raise RuntimeError("AUTH_JWT_SECRETO debe tener al menos 32 caracteres.")
        return secreto
    if config.entorno != "desarrollo":
        raise RuntimeError(
            "AUTH_JWT_SECRETO es obligatorio fuera de desarrollo: sin él, "
            "cualquiera que conozca el código podría firmar tokens."
        )
    # Al azar y no fijo en el código: un secreto por defecto que se cuela a
    # producción es una puerta abierta; uno efímero solo cierra sesiones.
    log.warning(
        "AUTH_JWT_SECRETO no está definido: se usa uno efímero y las "
        "sesiones se pierden al reiniciar la API."
    )
    return secrets.token_urlsafe(48)


# --- claves -----------------------------------------------------------------


def hashear_clave(clave: str) -> str:
    sal = bcrypt.gensalt(rounds=ajustes().bcrypt_rondas)
    return bcrypt.hashpw(clave.encode("utf-8"), sal).decode("ascii")


def verificar_clave(clave: str, hash_guardado: str) -> bool:
    try:
        return bcrypt.checkpw(clave.encode("utf-8"), hash_guardado.encode("ascii"))
    except ValueError:
        # Clave de más de 72 bytes o hash corrupto: no coincide, sin excepción.
        return False


@lru_cache
def hash_senuelo() -> str:
    """Hash contra el que se compara cuando el usuario no existe.

    Sin esto, "usuario inexistente" responde en 1 ms y "clave incorrecta" en
    250 ms, y el tiempo de respuesta delata qué nombres de usuario existen.
    """
    return hashear_clave(secrets.token_urlsafe(16))


# --- tokens -----------------------------------------------------------------


class TokenInvalido(Exception):
    """El token no sirve. `motivo` es "token_expirado" o "token_invalido"."""

    def __init__(self, motivo: str):
        super().__init__(motivo)
        self.motivo = motivo


def emitir_token(
    *,
    usuario_id: int,
    tipo: str,
    version: int,
    rol: str | None = None,
    duracion: timedelta | None = None,
) -> str:
    """Firma un token. `version` es `usuarios_sistema.version_token`: cambiar
    la clave la incrementa y todos los tokens anteriores dejan de servir."""
    if duracion is None:
        a = ajustes()
        duracion = {
            ACCESS: timedelta(minutes=a.access_minutos),
            REFRESH: timedelta(hours=a.refresh_horas),
            TEMPORAL: timedelta(minutes=a.temporal_minutos),
        }[tipo]
    emitido = reloj.real_utc()
    carga = {
        "sub": str(usuario_id),
        "typ": tipo,
        "ver": version,
        "iat": emitido,
        "exp": emitido + duracion,
    }
    if rol is not None:
        carga["rol"] = rol
    return jwt.encode(carga, _secreto(), algorithm=ajustes().jwt_algoritmo)


def leer_token(token: str) -> dict:
    """Valida firma y vencimiento. El tipo lo decide quien llama."""
    try:
        carga = jwt.decode(
            token,
            _secreto(),
            algorithms=[ajustes().jwt_algoritmo],
            options={"require": ["sub", "typ", "ver", "exp"]},
        )
    except jwt.ExpiredSignatureError as error:
        raise TokenInvalido("token_expirado") from error
    except jwt.InvalidTokenError as error:
        raise TokenInvalido("token_invalido") from error
    if not str(carga["sub"]).isdigit():
        raise TokenInvalido("token_invalido")
    return carga
