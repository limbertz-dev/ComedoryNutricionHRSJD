"""Arranque sin SIH y claves que no se filtran.

"Arrancar" es importar la app y cargar la configuración: create_engine no
abre ninguna conexión, así que nada de esto toca MySQL ni el SIH. Las claves
de estas pruebas son inventadas.
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

CLAVE_SIH = "clave-inventada-sih-7Qx!"
CLAVE_DB = "clave-inventada-db-3Kp#"
VARIABLES = (
    "SIH_HOST", "SIH_PORT", "SIH_DATABASE", "SIH_USER", "SIH_PASSWORD",
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


def test_la_app_arranca_sin_sih_y_avisa_una_sola_vez(tmp_path):
    """Proceso nuevo, sin .env en el directorio y sin SIH_* en el entorno:
    importa la app, pide la configuración dos veces y el aviso sale una."""
    entorno = {k: v for k, v in os.environ.items() if k not in VARIABLES}
    entorno["PYTHONPATH"] = str(RAIZ_BACK)
    codigo = (
        "import logging\n"
        "logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(message)s')\n"
        "import app.main\n"
        "from app.core.config import config, obtener_configuracion\n"
        "assert obtener_configuracion() is config\n"
        "assert config.sih_host is None and config.sih_password is None\n"
        "assert not config.sih_configurado\n"
    )
    resultado = subprocess.run(
        [sys.executable, "-c", codigo],
        cwd=tmp_path, env=entorno, capture_output=True, text=True, timeout=60,
    )
    assert resultado.returncode == 0, resultado.stderr
    assert resultado.stderr.count("INFO:SIH no configurado") == 1


def test_sih_vacio_como_en_env_example_cuenta_como_ausente(cargar):
    configuracion = cargar(
        SIH_HOST="", SIH_PORT="", SIH_DATABASE="", SIH_USER="", SIH_PASSWORD=""
    )
    assert configuracion.sih_port is None
    assert configuracion.sih_password is None
    assert not configuracion.sih_configurado


def test_sih_completo_queda_configurado(cargar):
    configuracion = cargar(
        SIH_HOST="sih.local", SIH_DATABASE="estadistica", SIH_USER="lector",
        SIH_PASSWORD=CLAVE_SIH,
    )
    assert configuracion.sih_configurado
    assert configuracion.sih_password.get_secret_value() == CLAVE_SIH


def test_cliente_sih_lanza_sih_no_configurado(monkeypatch, cargar):
    from app.core import sih

    monkeypatch.setattr(sih, "config", cargar())
    with pytest.raises(sih.SIHNoConfigurado, match="SIH no configurado"):
        sih.cliente_sih()


def test_las_claves_no_salen_en_str_ni_repr(cargar):
    configuracion = cargar(
        SIH_HOST="sih.local", SIH_PASSWORD=CLAVE_SIH, DB_PASSWORD=CLAVE_DB
    )
    for texto in (
        str(configuracion),
        repr(configuracion),
        str(configuracion.model_dump()),
        repr(configuracion.sih_password),
        repr(configuracion.db_password),
    ):
        assert CLAVE_SIH not in texto
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
        {"SIH_PORT": f"no-es-puerto-{CLAVE_SIH}"},
        {"DB_PORT": f"no-es-puerto-{CLAVE_DB}"},
    ],
    ids=["bases-iguales", "sih-port-invalido", "db-port-invalido"],
)
def test_las_claves_no_salen_en_validation_error(cargar, error):
    """Ni las claves ni el valor que falló aparecen en el mensaje. Los dos
    últimos casos meten la clave en el propio valor inválido: es lo que
    pasa cuando alguien pega la clave en la línea equivocada del .env."""
    with pytest.raises(ValidationError) as excinfo:
        cargar(SIH_PASSWORD=CLAVE_SIH, DB_PASSWORD=CLAVE_DB, **error)
    for texto in (str(excinfo.value), repr(excinfo.value)):
        assert CLAVE_SIH not in texto
        assert CLAVE_DB not in texto
