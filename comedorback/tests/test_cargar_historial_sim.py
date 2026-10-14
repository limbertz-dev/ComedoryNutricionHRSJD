"""scripts/cargar_historial_sim.py: el momento de cada ración cae en una ventana
efectiva de su comida.

Pruebas SINTÉTICAS: el script se importa por su ruta y solo se ejercitan sus
funciones puras con filas de horario inventadas. No se ejecuta `main()`, no se
conecta a ninguna base, no se llama a ninguna API y no se escribe nada. Importar
el script no debe tener efectos: no lee argumentos, no toca el entorno ni el
directorio de trabajo y no importa `preparar_simulacion` (que cambia de
directorio y carga la configuración de la app).
"""

import importlib.util
import os
import sys
from argparse import Namespace
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest

from app.consultas import horarios as consulta
from soporte_horarios import DIA, a_las

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "cargar_historial_sim.py"
MANANA = DIA + timedelta(days=1)
ENERO = datetime(2026, 1, 1)


def _importar():
    """Importa el script SIN registrarlo en sys.modules."""
    spec = importlib.util.spec_from_file_location("cargar_historial_sim_prueba", SCRIPT)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture
def script():
    return _importar()


# --- importar no tiene efectos ---------------------------------------------------------


def test_importar_no_tiene_efectos_laterales(monkeypatch):
    # Si el módulo leyera sys.argv al importar, esto lo rompería o lo fijaría.
    monkeypatch.setattr(sys, "argv", ["cargar_historial_sim.py", "--sim", "una_base_real"])
    entorno, cwd, modulos = dict(os.environ), os.getcwd(), set(sys.modules)

    modulo = _importar()

    assert dict(os.environ) == entorno  # ni ENTORNO ni DB_NAME ni DB_NAME_TURNOS
    assert os.getcwd() == cwd  # preparar_simulacion hace os.chdir al importarse
    assert "preparar_simulacion" not in sys.modules
    assert modulo.args is None
    assert "cargar_historial_sim_prueba" not in sys.modules  # ni se registra
    assert not {m for m in set(sys.modules) - modulos if m.startswith("preparar_simulacion")}
    # Lo que sí expone: las funciones, sin haberlas ejecutado.
    for nombre in ("main", "_argumentos", "_momento", "_instante_en_ventanas", "_guardas"):
        assert callable(getattr(modulo, nombre))


def test_los_argumentos_solo_se_leen_cuando_se_piden(script):
    leidos = script._argumentos(["--sim", "bd_x_sim", "--demo", "bd_y_demo", "--porcentaje", "50"])
    assert (leidos.sim, leidos.demo, leidos.porcentaje) == ("bd_x_sim", "bd_y_demo", 50)
    assert leidos.solo_programados is False
    assert script._argumentos(["--solo-programados"]).solo_programados is True
    assert script.args is None  # `_argumentos` no los guarda: eso lo hace main()


# --- las guardas de simulación se conservan ----------------------------------------------


def _con_argumentos(script, monkeypatch, **cambios):
    base = dict(
        sim="bd_nutricion_sim",
        demo="bd_turnos_demo",
        desde=date(2026, 9, 21),
        hasta=date(2026, 9, 23),
        porcentaje=80,
    )
    monkeypatch.setattr(script, "args", Namespace(**{**base, **cambios}))


def test_guardas_aceptan_la_configuracion_por_defecto(script, monkeypatch):
    _con_argumentos(script, monkeypatch)
    script._guardas()  # no aborta


@pytest.mark.parametrize(
    "cambios",
    [
        {"sim": "bd_nutricion"},  # una base real
        {"demo": "bd_proyecto_backend"},
        {"desde": date(2026, 9, 23), "hasta": date(2026, 9, 21)},
        {"desde": date(2026, 9, 20), "hasta": date(2026, 9, 25)},  # toca la demo en vivo
        {"desde": date(2026, 9, 27), "hasta": date(2026, 9, 30)},
        {"porcentaje": 0},
        {"porcentaje": 101},
    ],
    ids=["sim_real", "demo_real", "rango_invertido", "toca_24", "toca_27", "pct_cero", "pct_100_mas"],
)
def test_guardas_abortan(script, monkeypatch, capsys, cambios):
    _con_argumentos(script, monkeypatch, **cambios)
    with pytest.raises(SystemExit) as salida:
        script._guardas()
    assert salida.value.code == 1
    assert "ABORTADO" in capsys.readouterr().err


# --- el instante pertenece a una ventana válida -------------------------------------------


def _v(inicio: time, fin: time, desde: datetime, hasta: datetime | None = None):
    """Una versión de la comida 1, como la devuelve `_versiones`."""
    return (1, "Comida", inicio, fin, desde, hasta)


def _ventanas(versiones, dia: date) -> list[tuple[datetime, datetime]]:
    (comida,) = consulta._ventanas(list(versiones), dia)
    return [(v.inicio, v.fin) for v in comida.ventanas]


def _resuelve(versiones, instante: datetime):
    """Lo que haría `resolver_comida_en_curso` con ese instante, en Python
    puro e independiente de las ventanas: (comida_id, fecha_comida) o None."""
    for comida, _nombre, inicio, fin, desde, hasta in versiones:
        if not (desde <= instante and (hasta is None or instante < hasta)):
            continue
        hora, cruza = instante.time(), fin < inicio
        dentro = (hora >= inicio or hora < fin) if cruza else (inicio <= hora < fin)
        if dentro:
            fecha = instante.date()
            if cruza and hora < fin:
                fecha -= timedelta(days=1)
            return comida, fecha
    return None


USUARIOS = range(1, 401)

ESCENARIOS = {
    # Almuerzo 11-15; a las 16:00 se guarda 12-13: la ventana del día sigue siendo 11-15.
    "cambio_posterior_al_cierre": [
        _v(time(11), time(15), ENERO, a_las(16)),
        _v(time(12), time(13), a_las(16)),
    ],
    # Guardada a las 16:00 con 11-20: dos ventanas, 11-15 y 16-20 (no 11-20).
    "ampliada_por_la_tarde": [
        _v(time(11), time(15), ENERO, a_las(16)),
        _v(time(11), time(20), a_las(16)),
    ],
    # Cambio a mitad de franja: 11-15 hasta las 13:00, 11-14 desde entonces.
    "acortada_a_mitad_de_franja": [
        _v(time(11), time(15), ENERO, a_las(13)),
        _v(time(11), time(14), a_las(13)),
    ],
    # Hueco: 11-12 hasta las 12:30; 14-15 desde entonces.
    "con_hueco": [
        _v(time(11), time(12), ENERO, a_las(12, 30)),
        _v(time(14), time(15), a_las(12, 30)),
    ],
    # Cruza la medianoche: 22:00-02:00.
    "cruza_la_medianoche": [_v(time(22), time(2), ENERO)],
    # Cruza la medianoche y cambia en la madrugada: 22-02 hasta 00:30, 23-01 desde entonces.
    "cruce_con_cambio_en_la_madrugada": [
        _v(time(22), time(2), ENERO, a_las(0, 30, dia=MANANA)),
        _v(time(23), time(1), a_las(0, 30, dia=MANANA)),
    ],
    # El corte tiene microsegundos: la ventana nueva arranca en 16:00:00.25.
    "corte_con_microsegundos": [
        _v(time(11), time(15), ENERO, a_las(16, 0, 0, 250000)),
        _v(time(11), time(20), a_las(16, 0, 0, 250000)),
    ],
}


@pytest.mark.parametrize("nombre", list(ESCENARIOS))
def test_el_instante_cae_en_una_ventana_y_la_api_lo_resolveria_igual(script, nombre):
    versiones = ESCENARIOS[nombre]
    ventanas = _ventanas(versiones, DIA)
    assert ventanas, nombre
    for usuario in USUARIOS:
        instante = script._instante_en_ventanas(ventanas, f"momento|{DIA}|1|{usuario}")
        assert instante is not None
        # 1. Pertenece a una ventana efectiva: inicio inclusivo, fin exclusivo.
        assert any(ini <= instante < fin for ini, fin in ventanas), (nombre, instante)
        # 2. La resolución independiente de la API da la misma comida y fecha_comida.
        assert _resuelve(versiones, instante) == (1, DIA), (nombre, instante)


def test_la_ventana_ampliada_empieza_en_el_corte_y_no_hay_instantes_en_el_hueco(script):
    ventanas = _ventanas(ESCENARIOS["ampliada_por_la_tarde"], DIA)
    assert ventanas == [(a_las(11), a_las(15)), (a_las(16), a_las(20))]
    instantes = [
        script._instante_en_ventanas(ventanas, f"momento|{DIA}|1|{u}") for u in USUARIOS
    ]
    assert not [i for i in instantes if a_las(15) <= i < a_las(16)]  # el hueco
    assert [i for i in instantes if i < a_las(15)]  # usa la ventana de la mañana
    # La ventana de la tarde arranca a las 16:00 (el corte), no a las 11:00
    # nominales: ningún instante cae entre las 15:00 y las 16:00, y los
    # posteriores a las 15:00 son todos de la ventana nueva.
    de_la_tarde = [i for i in instantes if i >= a_las(15)]
    assert de_la_tarde and min(de_la_tarde) >= a_las(16)


def test_la_ventana_con_corte_en_microsegundos_arranca_en_el_corte(script):
    ventanas = _ventanas(ESCENARIOS["corte_con_microsegundos"], DIA)
    assert ventanas[1][0] == a_las(16, 0, 0, 250000)
    instantes = {
        script._instante_en_ventanas(ventanas, f"momento|{DIA}|1|{u}") for u in USUARIOS
    }
    assert a_las(16, 0, 0, 250000) <= max(instantes)
    assert not [i for i in instantes if a_las(15) <= i < a_las(16, 0, 0, 250000)]


def test_cruce_de_medianoche_da_instantes_en_las_dos_fechas_con_la_misma_fecha_comida(script):
    versiones = ESCENARIOS["cruza_la_medianoche"]
    ventanas = _ventanas(versiones, DIA)
    assert ventanas == [(a_las(22), a_las(2, dia=MANANA))]
    instantes = [
        script._instante_en_ventanas(ventanas, f"momento|{DIA}|1|{u}") for u in USUARIOS
    ]
    antes_de_medianoche = [i for i in instantes if i.date() == DIA]
    despues = [i for i in instantes if i.date() == MANANA]
    assert antes_de_medianoche and despues
    # La madrugada del día siguiente sigue siendo la ración del día que empezó.
    assert {_resuelve(versiones, i) for i in instantes} == {(1, DIA)}


def test_cruce_con_cambio_en_la_madrugada_es_una_sola_ventana_continua(script):
    versiones = ESCENARIOS["cruce_con_cambio_en_la_madrugada"]
    assert _ventanas(versiones, DIA) == [(a_las(22), a_las(1, dia=MANANA))]


def test_con_una_sola_ventana_es_el_calculo_de_siempre(script):
    clave = f"momento|{DIA}|1|77"
    unica = [(a_las(11), a_las(15))]
    assert script._instante_en_ventanas(unica, clave) == a_las(11) + timedelta(
        minutes=script._sha(clave) % 240
    )


def test_es_determinista_y_depende_de_la_clave(script):
    ventanas = _ventanas(ESCENARIOS["ampliada_por_la_tarde"], DIA)
    una = script._instante_en_ventanas(ventanas, "clave-a")
    assert script._instante_en_ventanas(ventanas, "clave-a") == una
    assert {script._instante_en_ventanas(ventanas, f"clave-{n}") for n in range(50)} != {una}


def test_sin_minutos_enteros_no_hay_instante(script):
    assert script._instante_en_ventanas([], "x") is None
    assert script._instante_en_ventanas([(a_las(11), a_las(11, 0, 59))], "x") is None
    # Una ventana de menos de un minuto no estorba a las demás.
    ventanas = [(a_las(11), a_las(11, 0, 30)), (a_las(14), a_las(15))]
    instante = script._instante_en_ventanas(ventanas, "x")
    assert a_las(14) <= instante < a_las(15)


def test_el_fin_de_la_ventana_queda_fuera(script):
    """Con un sobrante menor a un minuto (cena 17:00-23:59:59) el instante
    queda estrictamente antes del fin."""
    ventanas = [(a_las(17), a_las(23, 59, 59))]
    for usuario in USUARIOS:
        instante = script._instante_en_ventanas(ventanas, f"momento|{DIA}|1|{usuario}")
        assert a_las(17) <= instante < a_las(23, 59, 59)
