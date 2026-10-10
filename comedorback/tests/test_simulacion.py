"""Modo simulación: /simulacion/* solo con ENTORNO=simulacion, y nunca contra
las bases reales.

La app de simulación se arma con `crear_app("simulacion")` sobre la misma
`bd_nutricion_test`: lo que se prueba acá es el montaje del router, los
permisos y que el resto del sistema lea el reloj. La guarda de bases
(_sim/_demo) se prueba aparte, al cargar la configuración.
"""

import os
import subprocess
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import bindparam, select, text

from app.consultas.derecho import aplicar_reglas
from app.core import reloj
from app.core.config import Configuracion, config
from app.core.db import SesionLocal
from app.main import crear_app
from app.modelos.heredados import Comida, ComidaPorTurno
from app.semillas import horarios
from conftest import encabezado, ingresar

RAIZ_BACK = Path(__file__).resolve().parents[1]
DIA_DEMO = date(2026, 9, 24)
RELOJ = "/simulacion/reloj"


@pytest.fixture(autouse=True)
def reloj_real():
    reloj.volver_a_real()
    yield
    reloj.volver_a_real()


@pytest.fixture
def sim() -> TestClient:
    return TestClient(crear_app("simulacion"))


@pytest.fixture
def tokens(cliente, crear_usuario) -> dict[str, dict[str, str]]:
    for rol in ("jefa", "cocinera", "sistemas"):
        crear_usuario(f"u_{rol}", rol=rol)
    return {
        rol: encabezado(ingresar(cliente, f"u_{rol}")["access"])
        for rol in ("jefa", "cocinera", "sistemas")
    }


@pytest.fixture
def con_horarios():
    """Los horarios de la semilla, en la base de tests. Se limpia todo lo que
    la marcación haya escrito: las demás pruebas no esperan filas acá."""
    horarios.sembrar()
    yield
    with SesionLocal() as sesion:
        sesion.execute(text("DELETE FROM asistencias"))
        sesion.execute(text("DELETE FROM lecturas_biometricas"))
        sesion.execute(text("DELETE FROM horarios_comida"))
        sesion.commit()


# --- montaje y permisos -------------------------------------------------------


@pytest.mark.parametrize("entorno", ["produccion", "desarrollo"])
def test_router_no_existe_fuera_de_simulacion(tokens, entorno):
    cliente = TestClient(crear_app(entorno))
    for metodo in ("GET", "PUT", "DELETE"):
        assert cliente.request(metodo, RELOJ, headers=tokens["jefa"]).status_code == 404
    assert cliente.post(f"{RELOJ}/proxima-franja", headers=tokens["jefa"]).status_code == 404


def test_la_app_por_defecto_de_los_tests_no_monta_simulacion(cliente, tokens):
    assert config.entorno != "simulacion"
    assert cliente.get(RELOJ, headers=tokens["sistemas"]).status_code == 404


@pytest.mark.parametrize("rol,esperado", [("jefa", 200), ("sistemas", 200), ("cocinera", 403)])
def test_reloj_solo_jefatura(sim, tokens, rol, esperado):
    assert sim.get(RELOJ, headers=tokens[rol]).status_code == esperado


def test_cocinera_no_mueve_el_reloj(sim, tokens):
    coci = tokens["cocinera"]
    intentos = [
        sim.put(RELOJ, json={"momento": "2026-09-24T12:30:00"}, headers=coci),
        sim.post(f"{RELOJ}/avanzar", json={"minutos": 5}, headers=coci),
        sim.post(f"{RELOJ}/proxima-franja", headers=coci),
        sim.delete(RELOJ, headers=coci),
    ]
    assert [r.status_code for r in intentos] == [403] * 4
    assert not reloj.estado().simulado


def test_sin_token_401(sim):
    respuesta = sim.get(RELOJ)
    assert respuesta.status_code == 401
    assert respuesta.json()["motivo"] == "falta_token"


# --- endpoints del reloj ------------------------------------------------------


def _ahora_de(respuesta) -> datetime:
    return datetime.fromisoformat(respuesta.json()["ahora"])


def test_fijar_avanzar_y_volver(sim, tokens):
    jefa = tokens["jefa"]
    r = sim.get(RELOJ, headers=jefa)
    assert r.json()["simulado"] is False

    r = sim.put(RELOJ, json={"momento": "2026-09-24T12:30:00"}, headers=jefa)
    assert r.status_code == 200, r.text
    assert r.json()["simulado"] is True
    assert timedelta(0) <= _ahora_de(r) - datetime(2026, 9, 24, 12, 30) < timedelta(seconds=5)

    r = sim.post(f"{RELOJ}/avanzar", json={"horas": 1, "minutos": 15}, headers=jefa)
    assert r.status_code == 200, r.text
    assert timedelta(0) <= _ahora_de(r) - datetime(2026, 9, 24, 13, 45) < timedelta(seconds=5)

    r = sim.delete(RELOJ, headers=jefa)
    assert r.json()["simulado"] is False
    assert abs(_ahora_de(r) - datetime.now()) < timedelta(seconds=5)


def test_fijar_congelado(sim, tokens):
    r = sim.put(
        RELOJ, json={"momento": "2026-09-24T12:30:00", "congelar": True}, headers=tokens["jefa"]
    )
    assert r.json()["congelado"] is True
    assert _ahora_de(r) == datetime(2026, 9, 24, 12, 30)


@pytest.mark.parametrize("cuerpo", [{}, {"minutos": 0}, {"minutos": -5}])
def test_avanzar_exige_un_avance_positivo(sim, tokens, cuerpo):
    r = sim.post(f"{RELOJ}/avanzar", json=cuerpo, headers=tokens["jefa"])
    assert r.status_code == 422


def test_salud_informa_entorno_y_reloj(sim):
    r = sim.get("/salud")
    reloj_salud = r.json()["reloj"]
    # El entorno de la app que respondió, aunque config diga otro.
    assert r.json()["entorno"] == "simulacion"
    assert reloj_salud["simulado"] is False

    reloj.fijar(datetime(2026, 9, 24, 12, 30), congelar=True)
    reloj_salud = sim.get("/salud").json()["reloj"]
    assert reloj_salud["simulado"] is True
    assert reloj_salud["ahora"] == "2026-09-24T12:30:00"
    assert abs(datetime.fromisoformat(reloj_salud["real"]) - datetime.now()) < timedelta(seconds=5)


# --- próxima franja -----------------------------------------------------------


def _proxima(sim, tokens, desde: datetime):
    reloj.fijar(desde, congelar=True)
    return sim.post(f"{RELOJ}/proxima-franja", headers=tokens["jefa"])


@pytest.mark.usefixtures("con_horarios")
@pytest.mark.parametrize(
    "desde,esperado,codigo",
    [
        (datetime(2026, 9, 24, 12, 30), datetime(2026, 9, 24, 15, 0), "te"),
        (datetime(2026, 9, 24, 4, 0), datetime(2026, 9, 24, 5, 30), "desayuno"),
        # Justo en el inicio: la próxima es la siguiente, no la misma.
        (datetime(2026, 9, 24, 11, 0), datetime(2026, 9, 24, 15, 0), "te"),
        # Hoy no queda ninguna: la primera de mañana.
        (datetime(2026, 9, 24, 18, 0), datetime(2026, 9, 25, 5, 30), "desayuno"),
    ],
    ids=["almuerzo->te", "madrugada->desayuno", "en-el-inicio", "noche->manana"],
)
def test_proxima_franja(sim, tokens, desde, esperado, codigo):
    r = _proxima(sim, tokens, desde)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert datetime.fromisoformat(cuerpo["inicio"]) == esperado
    with SesionLocal() as sesion:
        comida_id = sesion.execute(
            select(Comida.id).where(Comida.codigo == codigo)
        ).scalar_one()
    assert cuerpo["comida_id"] == comida_id
    # El reloj queda fijado en ese inicio y sigue corriendo.
    assert cuerpo["reloj"]["simulado"] is True
    assert cuerpo["reloj"]["congelado"] is False
    assert timedelta(0) <= reloj.ahora() - esperado < timedelta(seconds=5)


@pytest.mark.usefixtures("con_horarios")
def test_proxima_franja_respeta_la_vigencia(sim, tokens):
    """Un horario que todavía no rige mañana no cuenta."""
    with SesionLocal() as sesion:
        sesion.execute(
            text("UPDATE horarios_comida SET vigente_desde = '2026-09-26'")
        )
        sesion.commit()
    r = _proxima(sim, tokens, datetime(2026, 9, 24, 18, 0))
    assert r.status_code == 409
    assert reloj.ahora() == datetime(2026, 9, 24, 18, 0)


def test_proxima_franja_sin_horarios_409(sim, tokens):
    r = _proxima(sim, tokens, datetime(2026, 9, 24, 12, 30))
    assert r.status_code == 409
    assert reloj.ahora() == datetime(2026, 9, 24, 12, 30)


# --- el resto del sistema lee el reloj ----------------------------------------


def _candidato_almuerzo() -> tuple[int, date]:
    """Alguien con derecho al almuerzo según las reglas y con la asignación en
    estado 'programado' en la base de turnos (solo SELECT). Prefiere el
    24/09, el día del escenario demo, si la base lo tiene."""
    with SesionLocal() as sesion:
        almuerzo = sesion.execute(
            select(Comida.id).where(Comida.codigo == "almuerzo")
        ).scalar_one()
        filas = sesion.execute(
            aplicar_reglas(
                select(
                    ComidaPorTurno.usuario_id,
                    ComidaPorTurno.fecha_comida,
                    ComidaPorTurno.turno_asignado_id,
                ).where(ComidaPorTurno.comida_id == almuerzo)
            )
        ).all()
        programados = set(
            sesion.execute(
                text(
                    f"SELECT id FROM `{config.db_name_turnos}`.turnos_asignados "
                    "WHERE estado = 'programado' AND id IN :ids"
                ).bindparams(bindparam("ids", expanding=True)),
                {"ids": [f.turno_asignado_id for f in filas] or [0]},
            ).scalars()
        )
    candidatos = sorted(
        ((f.fecha_comida == DIA_DEMO, f.fecha_comida, f.usuario_id)
         for f in filas if f.turno_asignado_id in programados),
        reverse=True,
    )
    if not candidatos:
        pytest.skip("la base de turnos no tiene ningún almuerzo programado con derecho")
    _, fecha, usuario_id = candidatos[0]
    return usuario_id, fecha


@pytest.mark.usefixtures("con_horarios")
def test_marcacion_con_el_reloj_fijado_en_el_almuerzo(sim, tokens):
    usuario_id, fecha = _candidato_almuerzo()
    fijado = datetime.combine(fecha, time(12, 30))
    r = sim.put(RELOJ, json={"momento": fijado.isoformat()}, headers=tokens["jefa"])
    assert r.status_code == 200, r.text

    r = sim.post(
        "/asistencias",
        json={"usuario_id": usuario_id, "metodo": "biometrico"},
        headers=tokens["cocinera"],
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["valido"] is True, cuerpo
    assert cuerpo["fecha_comida"] == fecha.isoformat()

    with SesionLocal() as sesion:
        fila = sesion.execute(
            text(
                "SELECT usuario_id, fecha_comida, fecha_hora, metodo FROM asistencias "
                "WHERE id = :id"
            ),
            {"id": cuerpo["asistencia_id"]},
        ).one()
    assert fila.usuario_id == usuario_id
    assert fila.fecha_comida == fecha
    assert fila.metodo == "biometrico"
    assert timedelta(0) <= fila.fecha_hora - fijado < timedelta(seconds=5)


@pytest.mark.usefixtures("con_horarios")
def test_biometrico_sigue_sin_aceptar_hora_del_cliente(sim, tokens):
    reloj.fijar(datetime(2026, 9, 24, 12, 30))
    r = sim.post(
        "/asistencias",
        json={"usuario_id": 1, "metodo": "biometrico", "momento": "2026-09-24T12:30:00"},
        headers=tokens["jefa"],
    )
    assert r.status_code == 422


@pytest.mark.usefixtures("con_horarios")
def test_pantalla_sin_parametros_usa_el_reloj(sim, tokens):
    reloj.fijar(datetime(2026, 9, 24, 12, 30), congelar=True)
    r = sim.get("/pantalla/estado", headers=tokens["cocinera"])
    assert r.status_code == 200, r.text
    assert datetime.fromisoformat(r.json()["momento"]) == datetime(2026, 9, 24, 12, 30)
    assert r.json()["fuera_de_horario"] is False


def test_historial_sin_fecha_usa_el_reloj(sim, tokens):
    reloj.fijar(datetime(2025, 3, 10, 9, 0), congelar=True)
    jefa = tokens["jefa"]
    assert sim.get("/historial/diario", headers=jefa).json()["fecha"] == "2025-03-10"
    mensual = sim.get("/historial/mensual", headers=jefa).json()
    assert (mensual["gestion"], mensual["mes"]) == (2025, 3)


# --- arranque: la simulación nunca contra las bases reales --------------------

VARIABLES = ("ENTORNO", "DB_NAME", "DB_NAME_TURNOS")


@pytest.fixture
def cargar(monkeypatch):
    for variable in VARIABLES:
        monkeypatch.delenv(variable, raising=False)

    def _cargar(**entorno) -> Configuracion:
        for variable, valor in entorno.items():
            monkeypatch.setenv(variable, valor)
        return Configuracion(_env_file=None)

    return _cargar


@pytest.mark.parametrize(
    "propia,turnos",
    [
        ("bd_nutricion", "bd_proyecto_backend"),
        ("bd_nutricion_sim", "bd_proyecto_backend"),
        ("bd_nutricion", "bd_turnos_demo"),
        ("BD_NUTRICION", "bd_turnos_demo"),
        ("otra_base", "otra_demo"),
        ("bd_nutricion_sim", "bd_proyecto_backend_sim"),
    ],
)
def test_simulacion_contra_bases_reales_no_arranca(cargar, propia, turnos):
    with pytest.raises(ValidationError, match="simulaci"):
        cargar(ENTORNO="simulacion", DB_NAME=propia, DB_NAME_TURNOS=turnos)


def test_simulacion_con_sus_bases_arranca(cargar):
    configuracion = cargar(
        ENTORNO="simulacion", DB_NAME="bd_nutricion_sim", DB_NAME_TURNOS="bd_turnos_demo"
    )
    assert configuracion.entorno == "simulacion"


@pytest.mark.parametrize("entorno", ["produccion", "desarrollo"])
def test_fuera_de_simulacion_la_guarda_no_aplica(cargar, entorno):
    configuracion = cargar(
        ENTORNO=entorno, DB_NAME="bd_nutricion", DB_NAME_TURNOS="bd_proyecto_backend"
    )
    assert configuracion.entorno == entorno


def test_entorno_desconocido_no_arranca(cargar):
    with pytest.raises(ValidationError):
        cargar(ENTORNO="prod")


def _arrancar(tmp_path, **variables) -> subprocess.CompletedProcess:
    entorno = {k: v for k, v in os.environ.items() if k not in VARIABLES}
    entorno.update(variables, PYTHONPATH=str(RAIZ_BACK))
    codigo = (
        "import app.main\n"
        "rutas = app.main.app.openapi()['paths']\n"
        "print(sorted(r for r in rutas if r.startswith('/simulacion')))\n"
    )
    return subprocess.run(
        [sys.executable, "-c", codigo],
        cwd=tmp_path, env=entorno, capture_output=True, text=True, timeout=60,
    )


def test_arranque_bloqueado_contra_la_base_real(tmp_path):
    resultado = _arrancar(
        tmp_path, ENTORNO="simulacion", DB_NAME="bd_nutricion", DB_NAME_TURNOS="bd_proyecto_backend"
    )
    assert resultado.returncode != 0
    assert "simulaci" in resultado.stderr


def test_arranque_en_simulacion_monta_el_router(tmp_path):
    resultado = _arrancar(
        tmp_path, ENTORNO="simulacion", DB_NAME="bd_nutricion_sim", DB_NAME_TURNOS="bd_turnos_demo"
    )
    assert resultado.returncode == 0, resultado.stderr
    assert "/simulacion/reloj" in resultado.stdout


def test_arranque_en_produccion_no_monta_el_router(tmp_path):
    resultado = _arrancar(tmp_path, ENTORNO="produccion")
    assert resultado.returncode == 0, resultado.stderr
    assert resultado.stdout.strip() == "[]"
