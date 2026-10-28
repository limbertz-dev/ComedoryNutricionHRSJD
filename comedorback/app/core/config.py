"""Configuración del backend. Todo valor sensible o de entorno vive en .env."""

import re
from functools import lru_cache
from typing import Literal
from urllib.parse import quote_plus

from pydantic import SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Los entornos posibles. ENTORNO solo da el valor por omisión con que se arma
# la app del proceso: el entorno que rige cada petición es el de la app que
# la atiende (app/core/entorno.py).
Entorno = Literal["produccion", "desarrollo"]


class Configuracion(BaseSettings):
    # hide_input_in_errors: un ValidationError nunca imprime el valor recibido.
    # Sin esto, un campo mal escrito en .env podía sacar una clave en el log
    # de arranque.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    nombre_app: str = "Sistema de Comedor y Nutrición Hospitalaria"
    entorno: Entorno = "desarrollo"

    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_user: str = "root"
    # SecretStr: str(config) y repr(config) muestran '**********'. El valor
    # real solo sale con get_secret_value(), al armar la URL de conexión.
    db_password: SecretStr = SecretStr("")

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

    # Lectores biométricos autorizados: `nombre=clave` separados por `;`, por
    # ejemplo `LECTORES=cocina-01=<clave de 32+ caracteres>`. El nombre queda en
    # lecturas_biometricas.dispositivo; la clave la manda el puente en la
    # cabecera X-Lector-Token. Vacío: ningún lector puede registrar lecturas.
    lectores: SecretStr = SecretStr("")

    @field_validator("lectores")
    @classmethod
    def _lectores_validos(cls, valor: SecretStr) -> SecretStr:
        """Se corta al arrancar con un mensaje que no muestra ninguna clave."""
        _leer_lectores(valor.get_secret_value())
        return valor

    @property
    def lectores_por_clave(self) -> dict[str, str]:
        """{clave: nombre del lector}."""
        return _leer_lectores(self.lectores.get_secret_value())

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
        clave = quote_plus(self.db_password.get_secret_value())
        return (
            f"mysql+pymysql://{self.db_user}:{clave}@"
            f"{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4"
        )

    @property
    def url_servidor(self) -> str:
        """La misma conexión pero sin base elegida. Solo la usa
        scripts/recrear_bd_limpia.py para el DROP/CREATE DATABASE."""
        clave = quote_plus(self.db_password.get_secret_value())
        return (
            f"mysql+pymysql://{self.db_user}:{clave}@"
            f"{self.db_host}:{self.db_port}/?charset=utf8mb4"
        )


NOMBRE_LECTOR = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
LARGO_MINIMO_CLAVE_LECTOR = 32


def _leer_lectores(texto: str) -> dict[str, str]:
    """`nombre=clave;nombre=clave` -> {clave: nombre}. Los errores nombran el
    lector o la posición, nunca la clave."""
    lectores: dict[str, str] = {}
    for posicion, par in enumerate((p.strip() for p in texto.split(";")), 1):
        if not par:
            continue
        nombre, separador, clave = (x.strip() for x in par.partition("="))
        if not separador or not NOMBRE_LECTOR.fullmatch(nombre):
            raise ValueError(
                f"LECTORES, entrada {posicion}: va como nombre=clave, con un nombre "
                "en minúsculas, números y guiones (máx. 40)."
            )
        if len(clave) < LARGO_MINIMO_CLAVE_LECTOR:
            raise ValueError(
                f"LECTORES: la clave de '{nombre}' tiene que tener al menos "
                f"{LARGO_MINIMO_CLAVE_LECTOR} caracteres."
            )
        if clave in lectores or nombre in lectores.values():
            raise ValueError(f"LECTORES: '{nombre}' o su clave está repetido.")
        lectores[clave] = nombre
    return lectores


@lru_cache
def obtener_configuracion() -> Configuracion:
    # lru_cache: se carga una vez por proceso.
    return Configuracion()


config = obtener_configuracion()
