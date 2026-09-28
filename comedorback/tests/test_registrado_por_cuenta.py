"""Quién registró cada ración manual: sale del token, no del cuerpo.

`asistencias.registrado_por_cuenta` guarda el `usuarios_sistema.id` de la
cuenta del token cuando `metodo='manual'`. El campo `registrado_por` del
cuerpo se ignora (deprecado) y la columna vieja queda en NULL.
"""

from datetime import date, datetime, time

import pytest
from sqlalchemy import select, text

from app.consultas.derecho import aplicar_reglas
from app.core import reloj
from app.core.db import SesionLocal
from app.modelos.comedor import Asistencia, HorarioComida
from app.modelos.heredados import ComidaPorTurno
from app.semillas import horarios
from conftest import encabezado, ingresar


@pytest.fixture(autouse=True)
def reloj_real():
    reloj.volver_a_real()
    yield
    reloj.volver_a_real()


@pytest.fixture
def cuentas(cliente, crear_usuario) -> dict[str, tuple[int, dict[str, str]]]:
    """rol → (usuarios_sistema.id, encabezado con el token)."""
    ids = {
        rol: crear_usuario(f"cuenta_{rol}", rol=rol)
        for rol in ("jefa", "sistemas")
    }
    return {
        rol: (uid, encabezado(ingresar(cliente, f"cuenta_{rol}")["access"]))
        for rol, uid in ids.items()
    }


@pytest.fixture
def con_horarios():
    """Los horarios de la semilla, con asistencias y lecturas limpias antes
    y después: cada lectura de la tabla es de la prueba en curso."""
    with SesionLocal() as sesion:
        sesion.execute(text("DELETE FROM asistencias"))
        sesion.execute(text("DELETE FROM lecturas_biometricas"))
        sesion.execute(text("DELETE FROM horarios_comida"))
        sesion.commit()
    horarios.sembrar()
    yield
    with SesionLocal() as sesion:
        sesion.execute(text("DELETE FROM asistencias"))
        sesion.execute(text("DELETE FROM lecturas_biometricas"))
        sesion.execute(text("DELETE FROM horarios_comida"))
        sesion.commit()


def _derecho_reciente() -> tuple[int, date, int]:
    """(usuario_id, fecha_comida, comida_id) con derecho según las reglas.

    Solo SELECT. La fecha queda dentro de la vigencia de la semilla y la
    comida tiene horario, así el POST manual cae en franja.
    """
    with SesionLocal() as sesion:
        con_horario = select(HorarioComida.comida_id).where(
            HorarioComida.activo == 1
        )
        fila = sesion.execute(
            aplicar_reglas(
                select(
                    ComidaPorTurno.usuario_id,
                    ComidaPorTurno.fecha_comida,
                    ComidaPorTurno.comida_id,
                )
                .select_from(ComidaPorTurno)
                .where(ComidaPorTurno.fecha_comida >= date(2026, 1, 1))
                .where(ComidaPorTurno.comida_id.in_(con_horario))
            )
            .order_by(ComidaPorTurno.fecha_comida.desc(), ComidaPorTurno.usuario_id)
            .limit(1)
        ).first()
    if fila is None:
        pytest.skip("la base de turnos no tiene comidas con derecho en 2026")
    return fila.usuario_id, fila.fecha_comida, fila.comida_id


def _mitad_franja(comida_id: int) -> time:
    """Una hora bien dentro de la franja de la comida (semilla, sin cruces)."""
    with SesionLocal() as sesion:
        inicio, fin = sesion.execute(
            select(HorarioComida.hora_inicio, HorarioComida.hora_fin)
            .where(HorarioComida.comida_id == comida_id, HorarioComida.activo == 1)
            .order_by(HorarioComida.vigente_desde.desc())
            .limit(1)
        ).one()
    mitad = (inicio.hour * 60 + inicio.minute + fin.hour * 60 + fin.minute) // 2
    return time(mitad // 60, mitad % 60)


def _asistencia_guardada(asistencia_id: int) -> Asistencia:
    with SesionLocal() as sesion:
        fila = sesion.execute(
            select(Asistencia).where(Asistencia.id == asistencia_id)
        ).scalar_one()
        sesion.expunge(fila)
        return fila


@pytest.mark.usefixtures("con_horarios")
@pytest.mark.parametrize("rol", ["jefa", "sistemas"])
def test_manual_guarda_la_cuenta_del_token(cliente, cuentas, rol):
    uid, headers = cuentas[rol]
    usuario_id, fecha, comida_id = _derecho_reciente()
    momento = datetime.combine(fecha, _mitad_franja(comida_id))
    r = cliente.post(
        "/asistencias",
        json={"usuario_id": usuario_id, "metodo": "manual", "momento": momento.isoformat()},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["valido"] is True, r.text
    fila = _asistencia_guardada(r.json()["asistencia_id"])
    assert fila.metodo == "manual"
    assert fila.registrado_por_cuenta == uid
    assert fila.registrado_por is None


@pytest.mark.usefixtures("con_horarios")
def test_el_cuerpo_no_puede_suplantar_la_cuenta(cliente, cuentas):
    uid_jefa, jefa = cuentas["jefa"]
    uid_sistemas, _ = cuentas["sistemas"]
    assert uid_jefa != uid_sistemas
    usuario_id, fecha, comida_id = _derecho_reciente()
    momento = datetime.combine(fecha, _mitad_franja(comida_id))
    r = cliente.post(
        "/asistencias",
        json={
            "usuario_id": usuario_id,
            "metodo": "manual",
            "momento": momento.isoformat(),
            "registrado_por": uid_sistemas,
        },
        headers=jefa,
    )
    assert r.status_code == 200, r.text
    assert r.json()["valido"] is True, r.text
    fila = _asistencia_guardada(r.json()["asistencia_id"])
    assert fila.registrado_por_cuenta == uid_jefa
    assert fila.registrado_por is None


@pytest.mark.usefixtures("con_horarios")
def test_biometrico_no_guarda_cuenta(cliente, cuentas):
    _, jefa = cuentas["jefa"]
    usuario_id, fecha, comida_id = _derecho_reciente()
    reloj.fijar(datetime.combine(fecha, _mitad_franja(comida_id)), congelar=True)
    r = cliente.post(
        "/asistencias",
        json={"usuario_id": usuario_id, "metodo": "biometrico"},
        headers=jefa,
    )
    assert r.status_code == 200, r.text
    assert r.json()["valido"] is True, r.text
    fila = _asistencia_guardada(r.json()["asistencia_id"])
    assert fila.metodo == "biometrico"
    assert fila.registrado_por_cuenta is None
    assert fila.registrado_por is None
