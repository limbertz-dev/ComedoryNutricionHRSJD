"""GET /pantalla/comidas-del-dia: una fila por comida vigente del día.

Solo lectura para los tres roles: previstas (derecho), servidas y manuales
(asistencias por fecha_comida) y rechazos del día del reloj resueltos con la
misma lógica de franja que /ultimas-marcaciones, sin tope.
"""

from datetime import date, datetime, time

import pytest
from sqlalchemy import func, select, text

from app.consultas.derecho import aplicar_reglas, contar_personas_con_derecho
from app.core import reloj
from app.core.db import SesionLocal
from app.modelos.comedor import HorarioComida
from app.modelos.heredados import Comensal, ComidaPorTurno
from app.semillas import horarios
import reloj_prueba
from conftest import encabezado, ingresar

DIA = date(2026, 9, 24)
RUTA = "/pantalla/comidas-del-dia"
MOTIVOS = ("no_identificado", "sin_derecho", "duplicado")
CLAVES_FILA = {
    "comida_id",
    "comida",
    "hora_inicio",
    "hora_fin",
    "estado",
    "previstas",
    "servidas",
    "manuales",
    "rechazos_por_motivo",
}


@pytest.fixture(autouse=True)
def reloj_real():
    reloj_prueba.liberar()
    yield
    reloj_prueba.liberar()


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
    """Los horarios de la semilla, con asistencias y lecturas limpias antes
    y después: los conteos son exactos y no se ensucian otras pruebas."""
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


def _manual(cliente, headers, usuario_id: int, momento: datetime) -> dict:
    r = cliente.post(
        "/asistencias",
        json={
            "usuario_id": usuario_id,
            "metodo": "manual",
            "momento": momento.isoformat(),
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["valido"] is True, cuerpo
    return cuerpo


@pytest.mark.usefixtures("con_horarios")
@pytest.mark.parametrize("rol", ["jefa", "cocinera", "sistemas"])
def test_forma_y_claves_fijas(cliente, tokens, rol):
    r = cliente.get(RUTA, headers=tokens[rol])
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert set(cuerpo) == {"fecha", "comidas", "rechazos_sin_comida"}
    assert cuerpo["fecha"] == reloj.hoy().isoformat()
    assert cuerpo["rechazos_sin_comida"] == 0
    with SesionLocal() as sesion:
        esperadas = sesion.execute(
            select(func.count(func.distinct(HorarioComida.comida_id))).where(
                HorarioComida.activo == 1
            )
        ).scalar_one()
    assert len(cuerpo["comidas"]) == esperadas
    for fila in cuerpo["comidas"]:
        assert set(fila) == CLAVES_FILA, fila
        assert fila["estado"] in ("pendiente", "en_curso", "cerrada")
        assert fila["rechazos_por_motivo"] == {m: 0 for m in MOTIVOS}
    inicios = [fila["hora_inicio"] for fila in cuerpo["comidas"]]
    assert inicios == sorted(inicios)


@pytest.mark.usefixtures("con_horarios")
def test_fecha_explicita_y_previstas(cliente, tokens):
    r = cliente.get(
        RUTA, params={"fecha": DIA.isoformat()}, headers=tokens["jefa"]
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["fecha"] == DIA.isoformat()
    with SesionLocal() as sesion:
        for fila in cuerpo["comidas"]:
            assert fila["previstas"] == contar_personas_con_derecho(
                sesion, fila["comida_id"], DIA
            )


@pytest.mark.usefixtures("con_horarios")
def test_servidas_y_manuales(cliente, tokens):
    usuario_id, fecha, comida_id = _derecho_reciente()
    momento = datetime.combine(fecha, _mitad_franja(comida_id))
    assert _manual(cliente, tokens["jefa"], usuario_id, momento)[
        "fecha_comida"
    ] == fecha.isoformat()
    r = cliente.get(RUTA, params={"fecha": fecha.isoformat()}, headers=tokens["jefa"])
    assert r.status_code == 200, r.text
    filas = {fila["comida_id"]: fila for fila in r.json()["comidas"]}
    assert filas[comida_id]["servidas"] == 1
    assert filas[comida_id]["manuales"] == 1
    for cid, fila in filas.items():
        if cid != comida_id:
            assert fila["servidas"] == 0 and fila["manuales"] == 0


@pytest.mark.usefixtures("con_horarios")
def test_estado_con_reloj_congelado(cliente, tokens):
    reloj_prueba.fijar(datetime(2026, 9, 24, 12, 30))
    r = cliente.get(
        RUTA, params={"fecha": DIA.isoformat()}, headers=tokens["cocinera"]
    )
    assert r.status_code == 200, r.text
    estados = {fila["hora_inicio"]: fila["estado"] for fila in r.json()["comidas"]}
    assert estados["05:30:00"] == "cerrada"
    assert estados["11:00:00"] == "en_curso"
    assert estados["15:00:00"] == "pendiente"
    assert estados["17:00:00"] == "pendiente"


@pytest.mark.usefixtures("con_horarios")
def test_fechas_pasadas_y_futuras(cliente, tokens):
    reloj_prueba.fijar(datetime(2026, 9, 24, 12, 30))
    jefa = tokens["jefa"]
    r = cliente.get(RUTA, params={"fecha": "2026-09-20"}, headers=jefa)
    assert r.status_code == 200, r.text
    assert {fila["estado"] for fila in r.json()["comidas"]} == {"cerrada"}
    r = cliente.get(RUTA, params={"fecha": "2026-09-26"}, headers=jefa)
    assert r.status_code == 200, r.text
    assert {fila["estado"] for fila in r.json()["comidas"]} == {"pendiente"}


@pytest.mark.usefixtures("con_horarios")
def test_duplicado_resuelto_a_su_comida(cliente, lector, tokens):
    usuario_id, fecha, comida_id = _derecho_reciente()
    momento = datetime.combine(fecha, _mitad_franja(comida_id))
    _manual(cliente, tokens["jefa"], usuario_id, momento)
    reloj_prueba.fijar(momento)
    lectura = lector.leer(usuario_id=usuario_id)
    assert lectura["valido"] is False and lectura["motivo"] == "duplicado"
    r = cliente.get(RUTA, params={"fecha": fecha.isoformat()}, headers=tokens["jefa"])
    cuerpo = r.json()
    fila = {f["comida_id"]: f for f in cuerpo["comidas"]}[comida_id]
    assert fila["rechazos_por_motivo"] == {
        "no_identificado": 0,
        "sin_derecho": 0,
        "duplicado": 1,
    }
    assert cuerpo["rechazos_sin_comida"] == 0


@pytest.mark.usefixtures("con_horarios")
def test_rechazos_del_dia_y_sin_comida(cliente, lector, tokens):
    jefa = tokens["jefa"]
    # Las lecturas las registra el lector de prueba; las consultas, la API.
    reloj_prueba.fijar(datetime(2026, 9, 24, 12, 30))
    lectura = lector.leer()
    assert lectura["motivo"] == "no_identificado", lectura
    with SesionLocal() as sesion:
        mayor = sesion.execute(select(func.max(Comensal.usuario_id))).scalar() or 0
    lectura = lector.leer(usuario_id=mayor + 1000)
    assert lectura["motivo"] == "sin_derecho", lectura
    # La semilla deja 10:00-11:00 sin cubrir a propósito.
    reloj_prueba.fijar(datetime(2026, 9, 24, 10, 30))
    lectura = lector.leer()
    assert lectura["motivo"] == "fuera_horario", lectura

    r = cliente.get(RUTA, params={"fecha": DIA.isoformat()}, headers=jefa)
    cuerpo = r.json()
    filas = {fila["hora_inicio"]: fila for fila in cuerpo["comidas"]}
    assert filas["11:00:00"]["rechazos_por_motivo"] == {
        "no_identificado": 1,
        "sin_derecho": 1,
        "duplicado": 0,
    }
    assert cuerpo["rechazos_sin_comida"] == 1

    # Las mismas tres lecturas que ve el hilo del lector. Cada una muestra el
    # motivo GUARDADO: la huella fuera de horario es fuera_horario (ya no se
    # presenta como no_identificado) y comidas-del-dia la cuenta en
    # rechazos_sin_comida.
    r = cliente.get(
        "/pantalla/ultimas-marcaciones", params={"fecha": DIA.isoformat()}, headers=jefa
    )
    assert sorted(m["motivo"] for m in r.json()) == [
        "fuera_horario",
        "no_identificado",
        "sin_derecho",
    ]


@pytest.mark.usefixtures("con_horarios")
def test_fecha_invalida_422(cliente, tokens):
    r = cliente.get(RUTA, params={"fecha": "ayer"}, headers=tokens["cocinera"])
    assert r.status_code == 422
