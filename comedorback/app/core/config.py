"""Configuración del backend. Todo valor sensible o de entorno vive en .env."""

import logging
from functools import lru_cache
from typing import Literal
from urllib.parse import quote_plus

from pydantic import SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

registro = logging.getLogger(__name__)

# Las bases reales: la propia de producción y la del módulo de turnos.
BASES_REALES = frozenset({"bd_nutricion", "bd_proyecto_backend"})

# Los entornos posibles. ENTORNO solo da el valor por omisión con que se arma
# la app del proceso: el entorno que rige cada petición es el de la app que
# la atiende (app/core/entorno.py).
Entorno = Literal["produccion", "desarrollo", "simulacion"]


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
    # simulacion: monta /simulacion/* para mover el reloj (app/core/reloj.py)
    # y SOLO arranca contra las bases de scripts/preparar_simulacion.py.
    entorno: Entorno = "desarrollo"

    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_user: str = "root"
    # SecretStr: str(config) y repr(config) muestran '**********'. El valor
    # real solo sale con get_secret_value(), al armar la URL de conexión.
    db_password: SecretStr = SecretStr("")

    # --- SIH del hospital (SQL Server): OPCIONAL ---
    # Sin estas variables la API arranca igual y registra una sola vez
    # "SIH no configurado". Nada las usa todavía: ver app/core/sih.py.
    sih_host: str | None = None
    sih_port: int | None = None
    sih_database: str | None = None
    sih_user: str | None = None
    sih_password: SecretStr | None = None

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

    @field_validator("db_name_turnos")
    @classmethod
    def _simulacion_aislada(cls, turnos: str, info: ValidationInfo) -> str:
        """En simulación el reloj se mueve a mano: una marcación con la hora
        fijada escrita en la base real sería una ración falsa en el informe.
        Por eso ENTORNO=simulacion solo arranca contra las copias que arma
        scripts/preparar_simulacion.py (propia *_sim, turnos *_demo) y nunca
        contra las bases reales, se llamen como se llamen las copias."""
        if info.data.get("entorno") != "simulacion":
            return turnos
        propia = info.data.get("db_name", "").strip().lower()
        turnos_normal = turnos.strip().lower()
        if (
            not propia.endswith("_sim")
            or not turnos_normal.endswith("_demo")
            or {propia, turnos_normal} & BASES_REALES
        ):
            raise ValueError(
                "ENTORNO=simulacion exige DB_NAME terminado en '_sim' y "
                "DB_NAME_TURNOS terminado en '_demo' (ver "
                "scripts/preparar_simulacion.py); nunca las bases reales."
            )
        return turnos

    @field_validator(
        "sih_host", "sih_port", "sih_database", "sih_user", "sih_password",
        mode="before",
    )
    @classmethod
    def _sih_vacio_es_ausente(cls, valor: object) -> object:
        """`SIH_PORT=` vacío, tal como viene en .env.example, cuenta como no
        configurado en vez de tumbar el arranque por no ser un entero."""
        if isinstance(valor, str) and not valor.strip():
            return None
        return valor

    @property
    def sih_configurado(self) -> bool:
        """Hay datos suficientes para intentar conectar al SIH. El puerto no
        cuenta: sin él, el conector usará el 1433 de SQL Server."""
        return all(
            (self.sih_host, self.sih_database, self.sih_user, self.sih_password)
        )

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


@lru_cache
def obtener_configuracion() -> Configuracion:
    # lru_cache: se carga una vez por proceso, y el aviso sale una sola vez.
    configuracion = Configuracion()
    if not configuracion.sih_configurado:
        registro.info("SIH no configurado: la API arranca sin conexión al SIH.")
    return configuracion


config = obtener_configuracion()
