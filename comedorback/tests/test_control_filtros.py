"""Filtros de GET /pacientes/control: sala por código, hoja y sin clasificar.

Sin base de datos ni SIH: el filtro se prueba con filas en memoria y la ruta
con la sesión sustituida y `control_del_dia` simulado. Los datos son ficticios.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.consultas import control as consultas_control
from app.consultas.control import ControlDelDia, FilaControl, FiltroControl, filtrar_filas
from app.core.db import obtener_sesion
from app.main import app


def _fila(cam: int, sa_codigo: int | None, sala: str, hoja: str | None) -> FilaControl:
    return FilaControl(
        cam_codigo=cam,
        cama_texto=str(cam),
        sa_codigo=sa_codigo,
        sala_texto=sala,
        pieza_texto="100",
        nro_historia=None,
        nombre_paciente=None,
        sexo=None,
        servicio_nutricion_id=1 if hoja else None,
        hoja_informe=hoja,
        grupo_informe=None,
        servicio_cama_texto=None,
        por_sala=False,
        sin_clasificar=hoja is None,
        dieta=None,
        suspendida=False,
        cambio=None,
        suspension=None,
        hechos_hoy=0,
        en_censo=True,
    )


FILAS = [
    _fila(1, 2, "PED", "PEDIATRIA"),
    _fila(2, 4, "PED", "PEDIATRIA"),  # mismo texto de sala, otro código
    _fila(3, 38, "INFT VARONES", None),
    _fila(4, 38, "INFT VARONES", "COLOPROCTOLOGIA"),
    _fila(5, 151, ".", None),
]


def _camas(filas: list[FilaControl]) -> list[int]:
    return [f.cam_codigo for f in filas]


# --- el filtro, sin HTTP ---------------------------------------------------


def test_sin_filtro_devuelve_todas():
    assert _camas(filtrar_filas(FILAS, None)) == [1, 2, 3, 4, 5]
    assert _camas(filtrar_filas(FILAS, FiltroControl())) == [1, 2, 3, 4, 5]


def test_sala_filtra_por_codigo_y_no_por_texto():
    # Dos salas se llaman "PED": el código 2 no trae la cama de la sala 4.
    assert _camas(filtrar_filas(FILAS, FiltroControl(sala=2))) == [1]
    assert _camas(filtrar_filas(FILAS, FiltroControl(sala=38))) == [3, 4]


def test_hoja_filtra():
    assert _camas(filtrar_filas(FILAS, FiltroControl(hoja="PEDIATRIA"))) == [1, 2]


def test_hoja_inexistente_da_lista_vacia():
    assert filtrar_filas(FILAS, FiltroControl(hoja="NO EXISTE")) == []


def test_sin_clasificar_solo_trae_las_de_la_bandera():
    assert _camas(filtrar_filas(FILAS, FiltroControl(sin_clasificar=True))) == [3, 5]


def test_los_filtros_se_combinan_con_and():
    assert _camas(filtrar_filas(FILAS, FiltroControl(sala=38, sin_clasificar=True))) == [3]
    assert _camas(filtrar_filas(FILAS, FiltroControl(sala=38, hoja="COLOPROCTOLOGIA"))) == [4]
    assert filtrar_filas(FILAS, FiltroControl(sala=2, hoja="COLOPROCTOLOGIA")) == []


def test_los_totales_se_cuentan_sobre_las_filas_devueltas():
    dia = ControlDelDia(
        fecha=date(2026, 9, 22), es_hoy=True, sih_disponible=True, sih_mensaje="ok",
        leido_en=None, filas=filtrar_filas(FILAS, FiltroControl(sala=38)),
    )
    assert dia.total_camas == 2
    assert dia.sin_clasificar == 1


# --- la ruta --------------------------------------------------------------


@pytest.fixture
def cliente(monkeypatch):
    """TestClient sin MySQL: la sesión es un objeto vacío y el control del día
    se arma con FILAS pasando por el filtro real."""
    pedidos: list[FiltroControl | None] = []

    def control_simulado(_sesion, fecha, filtro=None):
        pedidos.append(filtro)
        return ControlDelDia(
            fecha=fecha, es_hoy=True, sih_disponible=True, sih_mensaje="ok",
            leido_en=None, filas=filtrar_filas(FILAS, filtro),
        )

    def sesion_vacia():
        yield object()

    monkeypatch.setattr(consultas_control, "control_del_dia", control_simulado)
    app.dependency_overrides[obtener_sesion] = sesion_vacia
    try:
        yield TestClient(app), pedidos
    finally:
        app.dependency_overrides.pop(obtener_sesion, None)


def test_la_ruta_aplica_sala_hoja_y_sin_clasificar(cliente):
    http, pedidos = cliente

    r = http.get("/pacientes/control", params={"fecha": "2026-09-22", "sala": 38})
    assert r.status_code == 200
    assert [f["cam_codigo"] for f in r.json()["filas"]] == [3, 4]
    assert r.json()["total_camas"] == 2
    assert pedidos[-1] == FiltroControl(sala=38)

    r = http.get("/pacientes/control", params={"hoja": "PEDIATRIA"})
    assert [f["cam_codigo"] for f in r.json()["filas"]] == [1, 2]

    r = http.get("/pacientes/control", params={"hoja": "NO EXISTE"})
    assert r.status_code == 200
    assert r.json()["filas"] == []

    r = http.get("/pacientes/control", params={"sin_clasificar": "true"})
    assert [f["cam_codigo"] for f in r.json()["filas"]] == [3, 5]

    r = http.get("/pacientes/control", params={"sala": 38, "sin_clasificar": "true"})
    assert [f["cam_codigo"] for f in r.json()["filas"]] == [3]

    r = http.get("/pacientes/control")
    assert len(r.json()["filas"]) == 5
    assert pedidos[-1] == FiltroControl()


@pytest.mark.parametrize(
    "params",
    [
        {"sala": "PED"},
        {"sala": "3.5"},
        {"sala": 0},
        {"sala": -1},
        {"hoja": ""},
        {"hoja": "   "},
        {"sin_clasificar": "quizas"},
    ],
)
def test_parametros_invalidos_dan_422(cliente, params):
    http, pedidos = cliente
    r = http.get("/pacientes/control", params=params)
    assert r.status_code == 422
    assert pedidos == []
