"""Arranque y claves que no se filtran.

"Arrancar" es importar la app y cargar la configuración: create_engine no
abre ninguna conexión, así que nada de esto toca MySQL. Las claves de estas
pruebas son inventadas.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

RAIZ_BACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ_BACK))

from app.core.config import Configuracion  # noqa: E402

CLAVE_DB = "clave-inventada-db-3Kp#"
VARIABLES = (
    "DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME", "DB_NAME_TURNOS",
)


@pytest.fixture(autouse=True)
def entorno_limpio(monkeypatch):
    """Ninguna variable de la máquina se cuela en las pruebas."""
    for variable in VARIABLES:
        monkeypatch.delenv(variable, raising=False)


@pytest.fixture
def cargar(monkeypatch):
    """Configuración solo desde variables de entorno, sin leer ningún .env."""

    def _cargar(**entorno) -> Configuracion:
        for variable, valor in entorno.items():
            monkeypatch.setenv(variable, valor)
        return Configuracion(_env_file=None)

    return _cargar


def test_la_app_arranca_sin_env(tmp_path):
    """Proceso nuevo, sin .env en el directorio: importa la app y la
    configuración se carga una sola vez."""
    entorno = {k: v for k, v in os.environ.items() if k not in VARIABLES}
    entorno["PYTHONPATH"] = str(RAIZ_BACK)
    codigo = (
        "import app.main\n"
        "from app.core.config import config, obtener_configuracion\n"
        "assert obtener_configuracion() is config\n"
    )
    resultado = subprocess.run(
        [sys.executable, "-c", codigo],
        cwd=tmp_path, env=entorno, capture_output=True, text=True, timeout=60,
    )
    assert resultado.returncode == 0, resultado.stderr


def test_variables_sih_viejas_en_el_env_no_rompen_el_arranque(cargar):
    """Un .env de antes con SIH_* (el conector se retiró) se ignora."""
    configuracion = cargar(SIH_HOST="sih.local", SIH_PORT="no-es-puerto")
    assert not hasattr(configuracion, "sih_host")


def test_las_claves_no_salen_en_str_ni_repr(cargar):
    configuracion = cargar(DB_PASSWORD=CLAVE_DB)
    for texto in (
        str(configuracion),
        repr(configuracion),
        str(configuracion.model_dump()),
        repr(configuracion.db_password),
    ):
        assert CLAVE_DB not in texto


def test_la_url_de_conexion_sigue_llevando_la_clave_escapada(cargar):
    """SecretStr no cambia la conexión: la clave llega igual a SQLAlchemy."""
    from urllib.parse import quote_plus

    configuracion = cargar(DB_PASSWORD=CLAVE_DB)
    assert f":{quote_plus(CLAVE_DB)}@" in configuracion.url_base_datos
    assert f":{quote_plus(CLAVE_DB)}@" in configuracion.url_servidor


@pytest.mark.parametrize(
    "error",
    [
        {"DB_NAME": "misma_base", "DB_NAME_TURNOS": "misma_base"},
        {"DB_PORT": f"no-es-puerto-{CLAVE_DB}"},
    ],
    ids=["bases-iguales", "db-port-invalido"],
)
def test_las_claves_no_salen_en_validation_error(cargar, error):
    """Ni la clave ni el valor que falló aparecen en el mensaje. El último caso
    mete la clave en el propio valor inválido: es lo que pasa cuando alguien
    pega la clave en la línea equivocada del .env."""
    with pytest.raises(ValidationError) as excinfo:
        cargar(DB_PASSWORD=CLAVE_DB, **error)
    for texto in (str(excinfo.value), repr(excinfo.value)):
        assert CLAVE_DB not in texto
