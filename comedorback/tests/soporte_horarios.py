"""Soporte común de las pruebas de horarios inmediatos.

Los datos se preparan SOLO por las vías autorizadas: `POST /reglas/horarios`
con el reloj de simulación y `semillas.horarios.sembrar()`. La limpieza usa los
mismos DELETE que ya usan las demás pruebas, sobre tablas propias de la base
`_test`.
"""

from datetime import date, datetime, time

import pytest
from sqlalchemy import select, text

from app.core import reloj
from app.core.db import SesionLocal
from app.modelos.heredados import Comida
from app.semillas import horarios
from conftest import encabezado, ingresar

DIA = date(2026, 9, 24)
CLAVES_HORARIO = {
    "horario_id",
    "comida_id",
    "comida",
    "hora_inicio",
    "hora_fin",
    "cruza_medianoche",
    "vigente_desde",
    "vigente_hasta",
    "motivo",
    "creada_por",
    "creada",
    "estado",
}


def a_las(hora: int, minuto: int = 0, segundo: int = 0, micro: int = 0, dia: date = DIA):
    return datetime.combine(dia, time(hora, minuto, segundo, micro))


def fijar(momento: datetime) -> None:
    """Reloj congelado: el instante de guardado es exactamente `momento`."""
    reloj.fijar(momento, congelar=True)


def comida_id(codigo: str) -> int:
    with SesionLocal() as sesion:
        valor = sesion.execute(
            select(Comida.id).where(Comida.codigo == codigo)
        ).scalar_one_or_none()
    if valor is None:
        pytest.skip(f"v_comidas no tiene la comida '{codigo}'")
    return valor


def limpiar_horarios() -> None:
    with SesionLocal() as sesion:
        sesion.execute(text("DELETE FROM asistencias"))
        sesion.execute(text("DELETE FROM lecturas_biometricas"))
        sesion.execute(text("DELETE FROM horarios_comida"))
        sesion.commit()


def guardar(cliente, token, comida: int, inicio: str, fin: str, base: int | None):
    return cliente.post(
        "/reglas/horarios",
        json={
            "comida_id": comida,
            "hora_inicio": inicio,
            "hora_fin": fin,
            "base_horario_id": base,
        },
        headers=token,
    )


def historial(cliente, token, comida: int) -> list[dict]:
    r = cliente.get(
        "/reglas/horarios/historial", params={"comida_id": comida}, headers=token
    )
    assert r.status_code == 200, r.text
    return r.json()


def abierta(cliente, token, comida: int) -> dict | None:
    """La versión abierta de la comida, o None si no tiene."""
    return next((h for h in historial(cliente, token, comida) if h["estado"] == "vigente"), None)


def vigente_en(cliente, token, momento: datetime) -> dict[int, dict]:
    r = cliente.get(
        "/reglas/horarios", params={"momento": momento.isoformat()}, headers=token
    )
    assert r.status_code == 200, r.text
    return {h["comida_id"]: h for h in r.json()}


@pytest.fixture
def reloj_libre():
    reloj.volver_a_real()
    yield
    reloj.volver_a_real()


@pytest.fixture
def root(cliente, crear_usuario, reloj_libre):
    crear_usuario("root", rol="sistemas")
    return encabezado(ingresar(cliente, "root")["access"])


@pytest.fixture
def vacio(reloj_libre):
    """`horarios_comida` sin una sola fila."""
    limpiar_horarios()
    yield
    limpiar_horarios()


@pytest.fixture
def con_horarios(reloj_libre):
    """Los horarios de la semilla (2026-01-01 a medianoche), nada más."""
    limpiar_horarios()
    horarios.sembrar()
    yield
    limpiar_horarios()
