"""Configuración del backend. Todo valor sensible o de entorno vive en .env."""

from functools import lru_cache
from urllib.parse import quote_plus

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
    db_name: str = "bd_nutricion"

    # Base del modulo de turnos, del otro ingeniero. Este sistema solo la
    # LEE, y el usuario de la aplicacion solo tiene SELECT sobre ella.
    # No se cablea: en la maquina de desarrollo y en el servidor del
    # hospital puede llamarse distinto.
    db_name_turnos: str = "bd_proyecto_backend"

    # --- SIH del hospital: SQL Server, base `bdestadistica` ---
    #
    # SOLO LECTURA, sin excepciones. El usuario con el que se conecta solo
    # tiene SELECT: el SIH es el sistema del que depende el hospital entero.
    #
    # Si queda vacio, el modulo de pacientes NO se cae: arranca en modo
    # manual. Es deliberado — la red del hospital se corta y la licenciada
    # no puede quedarse sin poder trabajar.
    #
    # El puerto por defecto es el 1433 de SQL Server, pero la instancia del
    # hospital escucha en uno propio: va en .env, no cableado.
    sih_host: str = ""
    sih_port: int = 1433
    sih_database: str = "bdestadistica"
    sih_user: str = ""
    sih_password: str = ""

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

    @property
    def url_base_datos(self) -> str:
        """Cadena de conexión de SQLAlchemy. La clave va escapada porque
        puede traer caracteres que romperían la URL."""
        clave = quote_plus(self.db_password)
        return (
            f"mysql+pymysql://{self.db_user}:{clave}@"
            f"{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4"
        )


@lru_cache
def obtener_configuracion() -> Configuracion:
    return Configuracion()


config = obtener_configuracion()
