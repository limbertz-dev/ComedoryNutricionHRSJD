"""Tests contra `bd_nutricion_test`, NUNCA contra la base de desarrollo.

Correr desde comedorback/ (usa las credenciales DB_HOST/DB_USER/DB_PASSWORD
de .env, pero la base la fija este archivo):

    .venv/Scripts/python -m pytest

Al empezar la sesión se BORRA y recrea `bd_nutricion_test` con
`alembic upgrade head`. Las vistas v_* leen la base de turnos (solo SELECT),
así que DB_NAME_TURNOS tiene que existir en el servidor.

Otro nombre de base: TEST_DB_NAME=otra_test (tiene que terminar en _test).
"""

import os
import re
from datetime import date
from pathlib import Path

# Antes de importar la app: la configuración se lee una sola vez al importar.
NOMBRE_BASE = os.environ.get("TEST_DB_NAME", "bd_nutricion_test")
if not re.fullmatch(r"[a-z0-9_]+_test", NOMBRE_BASE):
    raise RuntimeError(f"La base de tests debe terminar en _test: {NOMBRE_BASE!r}")
os.environ["DB_NAME"] = NOMBRE_BASE
os.environ["AUTH_JWT_SECRETO"] = "secreto-de-tests-" + "x" * 32
os.environ["AUTH_BCRYPT_RONDAS"] = "4"  # el mínimo: los tests no miden bcrypt

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event, text  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402

from app.core import seguridad  # noqa: E402
from app.core.config import config  # noqa: E402
from app.core.db import SesionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.modelos.usuarios import UsuarioSistema  # noqa: E402
import reloj_prueba  # noqa: E402
from lector_prueba import LectorDePrueba  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]

# Toda sentencia que cualquier motor ejecute durante los tests (también los
# de alembic). tests/test_zz_sin_escrituras_heredadas.py la revisa al final.
SENTENCIAS: list[str] = []


@event.listens_for(Engine, "before_cursor_execute")
def _anotar(conexion, cursor, sentencia, parametros, contexto, multiples):
    SENTENCIAS.append(sentencia)


def config_alembic() -> Config:
    return Config(str(RAIZ / "alembic.ini"))


@pytest.fixture(scope="session", autouse=True)
def base_de_prueba():
    # Doble guarda: si algo pisó DB_NAME, no se borra nada.
    assert config.db_name == NOMBRE_BASE, config.db_name
    assert config.db_name.endswith("_test")
    assert config.db_name.lower() != config.db_name_turnos.lower()

    servidor = create_engine(config.url_servidor, isolation_level="AUTOCOMMIT")
    with servidor.connect() as conexion:
        conexion.execute(text(f"DROP DATABASE IF EXISTS `{NOMBRE_BASE}`"))
        conexion.execute(
            text(
                f"CREATE DATABASE `{NOMBRE_BASE}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        )
    servidor.dispose()
    command.upgrade(config_alembic(), "head")
    yield


@pytest.fixture(autouse=True)
def tablas_auth_limpias():
    with SesionLocal() as sesion:
        # La auditoría de intervenciones apunta (RESTRICT) a cuentas, lecturas
        # y asistencias: se vacía primero, o los DELETE de abajo y los de las
        # demás pruebas reventarían por la FK.
        sesion.execute(text("DELETE FROM intervenciones_lectura"))
        # R2 deja solo la versión base (2000-01-01): los tests que asumen
        # 12 h y enfermería excluida no se enteran de versiones de otro test.
        sesion.execute(
            text(
                "DELETE FROM reglas_derecho_novedad WHERE regla_id IN "
                "(SELECT id FROM reglas_derecho WHERE vigente_desde != '2000-01-01')"
            )
        )
        sesion.execute(
            text("DELETE FROM reglas_derecho WHERE vigente_desde != '2000-01-01'")
        )
        sesion.execute(text("UPDATE reglas_derecho SET creada_por_cuenta = NULL"))
        sesion.execute(text("UPDATE horarios_comida SET creada_por_cuenta = NULL"))
        sesion.execute(text("DELETE FROM intentos_login"))
        # creada_por_cuenta se apunta a sí misma (RESTRICT): se suelta
        # primero o el DELETE reventaría por la FK.
        sesion.execute(text("UPDATE usuarios_sistema SET creada_por_cuenta = NULL"))
        sesion.execute(text("DELETE FROM usuarios_sistema"))
        sesion.commit()
    yield


@pytest.fixture
def cliente() -> TestClient:
    return TestClient(app)


@pytest.fixture
def lector() -> LectorDePrueba:
    """Registra lecturas biométricas como el lector autorizado (ver
    tests/lector_prueba.py). POST /asistencias biométrico da 403 desde una
    sesión: test_biometria_origen.py cubre ese lado."""
    return LectorDePrueba()


@pytest.fixture(autouse=True)
def reloj_real():
    """Cada prueba empieza y termina con la hora real (ver tests/reloj_prueba.py)."""
    reloj_prueba.liberar()
    yield
    reloj_prueba.liberar()


@pytest.fixture
def crear_usuario():
    def crear(
        username: str,
        rol: str = "jefa",
        clave: str = "clave-segura-1",
        *,
        debe_cambiar: bool = False,
        activo: bool = True,
    ) -> int:
        with SesionLocal() as sesion:
            usuario = UsuarioSistema(
                username=username,
                password_hash=seguridad.hashear_clave(clave),
                rol=rol,
                debe_cambiar=debe_cambiar,
                activo=activo,
                version_token=0,
            )
            sesion.add(usuario)
            sesion.commit()
            return usuario.id

    return crear


@pytest.fixture
def version_derecho():
    """FIXTURE EXCEPCIONAL: inserta una versión de `reglas_derecho`.

    La API ya no crea versiones de derecho (no hay POST), pero la evaluación
    del derecho por `fecha_turno` sigue necesitando versiones pasadas, de hoy
    y futuras para probarse. Por eso existe esta única vía interna, y solo
    acá:

      · dentro de tests/ (no hay equivalente en app/),
      · solo contra la base `_test` (se comprueba en cada llamada),
      · solo INSERT en reglas_derecho / reglas_derecho_novedad.

    No es una escritura general: la limpieza de ambas tablas ya la hacen
    `tablas_auth_limpias` y `reglas_en_base`.
    """

    def crear(
        desde: date,
        duracion_minima_horas: int,
        *,
        novedades: tuple[str, ...] = (),
        excluir_enfermeria: bool = True,
    ) -> int:
        assert config.db_name == NOMBRE_BASE and config.db_name.endswith("_test"), (
            "version_derecho solo escribe en la base de pruebas"
        )
        with SesionLocal() as sesion:
            regla_id = sesion.execute(
                text(
                    "INSERT INTO reglas_derecho (vigente_desde, duracion_minima_horas, "
                    "excluir_enfermeria, motivo, creada_por_cuenta) "
                    "VALUES (:desde, :horas, :excluir, :motivo, NULL)"
                ),
                {
                    "desde": desde,
                    "horas": duracion_minima_horas,
                    "excluir": 1 if excluir_enfermeria else 0,
                    "motivo": "Versión de prueba insertada por la fixture",
                },
            ).lastrowid
            for tipo in sorted(set(novedades)):
                sesion.execute(
                    text(
                        "INSERT INTO reglas_derecho_novedad (regla_id, tipo_novedad) "
                        "VALUES (:regla, :tipo)"
                    ),
                    {"regla": regla_id, "tipo": tipo},
                )
            sesion.commit()
        return regla_id

    return crear


def encabezado(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def ingresar(cliente: TestClient, username: str, clave: str = "clave-segura-1") -> dict:
    respuesta = cliente.post("/auth/login", json={"username": username, "password": clave})
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()
