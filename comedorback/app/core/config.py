"""Configuración del backend. Todo valor sensible o de entorno vive en .env."""

from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Configuracion(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    nombre_app: str = "Sistema de Comedor y Nutrición Hospitalaria"
    entorno: str = "desarrollo"

    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = ""

    # Arquitectura de dos bases en el mismo servidor MySQL:
    #
    #   db_name          la base PROPIA del comedor. Alembic la administra y
    #                    scripts/recrear_bd_limpia.py la puede borrar entera.
    #   db_name_turnos   la base del módulo de turnos (del otro ingeniero).
    #                    SOLO LECTURA: este sistema no le emite un solo ALTER,
    #                    CREATE ni INSERT. Se lee únicamente a través de las
    #                    vistas v_* que viven en db_name.
    db_name: str = "bd_nutricion"
    db_name_turnos: str = "bd_proyecto_backend"

    # Desde qué direcciones puede el navegador llamar a esta API, separadas por
    # comas. Por defecto, el servidor de desarrollo de Vite.
    #
    # Va en .env y no fijo en el código porque cambia según dónde corra el
    # front: en tu máquina es localhost:5173, en el hospital será la dirección
    # real del servidor.
    origenes_permitidos: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def origenes(self) -> list[str]:
        """Los orígenes de `origenes_permitidos`, ya separados y limpios."""
        return [o.strip() for o in self.origenes_permitidos.split(",") if o.strip()]

    @field_validator("db_name_turnos")
    @classmethod
    def _bases_distintas(cls, turnos: str, info: ValidationInfo) -> str:
        """Apuntar la base propia a la de turnos es el error más caro posible:
        alembic y el script de recreación escribirían en la base del otro
        ingeniero. Se corta al arrancar, antes de abrir una sola conexión.

        Es validador de campo y no de modelo a propósito: el error de un
        validador de modelo imprime el .env entero, contraseñas incluidas."""
        propia = info.data.get("db_name", "")
        if propia.strip().lower() == turnos.strip().lower():
            raise ValueError(
                "DB_NAME y DB_NAME_TURNOS no pueden ser la misma base: "
                f"'{turnos}' es de solo lectura para este sistema."
            )
        return turnos

    @property
    def url_base_datos(self) -> str:
        """Cadena de conexión de SQLAlchemy. La clave va escapada porque
        puede traer caracteres que romperían la URL."""
        clave = quote_plus(self.db_password)
        return (
            f"mysql+pymysql://{self.db_user}:{clave}@"
            f"{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4"
        )

    @property
    def url_servidor(self) -> str:
        """La misma conexión pero sin base elegida. Solo la usa
        scripts/recrear_bd_limpia.py para el DROP/CREATE DATABASE."""
        clave = quote_plus(self.db_password)
        return (
            f"mysql+pymysql://{self.db_user}:{clave}@"
            f"{self.db_host}:{self.db_port}/?charset=utf8mb4"
        )


@lru_cache
def obtener_configuracion() -> Configuracion:
    return Configuracion()


config = obtener_configuracion()
