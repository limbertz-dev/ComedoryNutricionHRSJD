"""El reloj único del servidor: real por defecto, simulable solo a propósito.

La hora del negocio (marcación, pantalla, historial, informes) sale de
`reloj.ahora()` / `reloj.hoy()`. La de la seguridad (bloqueo de login, JWT)
sale de `reloj.real()` y no se mueve aunque el reloj esté fijado.
"""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core import reloj
from app.logica import autenticacion
from conftest import encabezado, ingresar

APP = Path(__file__).resolve().parents[1] / "app"
FIJADO = datetime(2026, 9, 24, 12, 30)


@pytest.fixture(autouse=True)
def reloj_real():
    reloj.volver_a_real()
    yield
    reloj.volver_a_real()


@pytest.fixture
def real_controlado(monkeypatch):
    """Reemplaza la hora real por una que el test mueve a mano."""
    actual = {"t": datetime(2026, 9, 25, 8, 0)}
    monkeypatch.setattr(reloj, "real", lambda: actual["t"])
    return actual


def test_sin_fijar_da_la_hora_real():
    antes = datetime.now()
    ahora = reloj.ahora()
    despues = datetime.now()
    assert antes <= ahora <= despues
    assert reloj.hoy() == ahora.date()
    assert not reloj.estado().simulado


def test_fijar_sigue_corriendo_desde_el_momento_fijado(real_controlado):
    reloj.fijar(FIJADO)
    assert reloj.ahora() == FIJADO
    real_controlado["t"] += timedelta(minutes=5)
    assert reloj.ahora() == FIJADO + timedelta(minutes=5)
    assert reloj.hoy() == FIJADO.date()
    estado = reloj.estado()
    assert estado.simulado and not estado.congelado


def test_congelado_no_avanza(real_controlado):
    reloj.fijar(FIJADO, congelar=True)
    real_controlado["t"] += timedelta(hours=3)
    assert reloj.ahora() == FIJADO
    assert reloj.estado().congelado


@pytest.mark.parametrize("congelar", [False, True])
def test_avanzar_suma_sobre_lo_fijado(real_controlado, congelar):
    reloj.fijar(FIJADO, congelar=congelar)
    reloj.avanzar(timedelta(minutes=90))
    assert reloj.ahora() == FIJADO + timedelta(minutes=90)


def test_avanzar_sin_fijar_simula_desde_la_real(real_controlado):
    reloj.avanzar(timedelta(days=1))
    assert reloj.ahora() == real_controlado["t"] + timedelta(days=1)
    assert reloj.estado().simulado


def test_volver_a_real(real_controlado):
    reloj.fijar(FIJADO)
    reloj.volver_a_real()
    assert reloj.ahora() == real_controlado["t"]
    assert not reloj.estado().simulado


def test_fijar_con_zona_se_guarda_en_hora_local():
    con_zona = datetime(2026, 9, 24, 16, 30, tzinfo=timezone.utc)
    reloj.fijar(con_zona, congelar=True)
    assert reloj.ahora() == con_zona.astimezone().replace(tzinfo=None)
    assert reloj.ahora().tzinfo is None


def test_la_seguridad_sigue_en_hora_real(cliente, crear_usuario):
    """Con el reloj en 2020, el bloqueo de login usa la hora real y un token
    recién emitido no nace vencido."""
    reloj.fijar(datetime(2020, 1, 1, 12, 0))
    assert abs(autenticacion.ahora() - datetime.now()) < timedelta(seconds=5)

    crear_usuario("jefa1")
    token = ingresar(cliente, "jefa1")["access"]
    assert cliente.get("/auth/yo", headers=encabezado(token)).status_code == 200


# Lo único que puede leer la hora por fuera de app/core/reloj.py: la hora de
# MySQL en los created_at/updated_at (server_default=func.now()), que registra
# cuándo se escribió de verdad la fila.
LEER_HORA = re.compile(
    r"datetime\.(?:now|utcnow|today)\(|date\.today\(|time\.time\(|"
    r"func\.(?:now|curdate|current_timestamp|current_date)\(|NOW\(\)|CURDATE\(\)"
)


def test_nadie_lee_la_hora_por_fuera_del_reloj():
    ajenas = []
    for archivo in sorted(APP.rglob("*.py")):
        if archivo.name == "reloj.py" and archivo.parent.name == "core":
            continue
        for numero, linea in enumerate(archivo.read_text(encoding="utf-8").splitlines(), 1):
            if not LEER_HORA.search(linea):
                continue
            if archivo.parent.name == "modelos" and "server_default=func.now()" in linea:
                continue
            ajenas.append(f"{archivo.relative_to(APP)}:{numero}: {linea.strip()}")
    assert ajenas == []
