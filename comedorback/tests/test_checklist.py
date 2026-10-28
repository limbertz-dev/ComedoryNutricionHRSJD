"""Checklist de cocina: lista de la comida en curso, marcar y desmarcar.

La lista sale del derecho (`aplicar_reglas`) y la marca pasa por las mismas
reglas que la huella. Desmarcar: solo la misma cocinera y con la comida
todavía abierta, sin otro plazo.
"""

from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import select, text

import reloj_prueba
from app.consultas.derecho import aplicar_reglas
from app.core.db import SesionLocal
from app.modelos.comedor import AnulacionChecklist, Asistencia, HorarioComida
from app.modelos.heredados import ComidaPorTurno
from app.modelos.lector import RacionPolicia
from app.semillas import horarios
from conftest import encabezado, ingresar


@pytest.fixture
def cuentas(cliente, crear_usuario) -> dict[str, tuple[int, dict[str, str]]]:
    """nombre → (usuarios_sistema.id, encabezado con el token)."""
    roles = {"cocinera": "cocinera", "cocinera_b": "cocinera", "jefa": "jefa", "sistemas": "sistemas"}
    ids = {nombre: crear_usuario(f"chk_{nombre}", rol=rol) for nombre, rol in roles.items()}
    return {
        nombre: (uid, encabezado(ingresar(cliente, f"chk_{nombre}")["access"]))
        for nombre, uid in ids.items()
    }


@pytest.fixture
def con_horarios():
    def limpiar():
        with SesionLocal() as sesion:
            sesion.execute(text("DELETE FROM anulaciones_checklist"))
            sesion.execute(text("DELETE FROM asistencias"))
            sesion.execute(text("DELETE FROM lecturas_biometricas"))
            sesion.execute(text("DELETE FROM horarios_comida"))
            sesion.commit()

    limpiar()
    horarios.sembrar()
    yield
    limpiar()


def _derecho() -> tuple[int, date, int]:
    """(usuario_id, fecha_comida, comida_id) con derecho y comida con horario."""
    with SesionLocal() as sesion:
        con_horario = select(HorarioComida.comida_id).where(HorarioComida.activo == 1)
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
    with SesionLocal() as sesion:
        inicio, fin = sesion.execute(
            select(HorarioComida.hora_inicio, HorarioComida.hora_fin)
            .where(HorarioComida.comida_id == comida_id, HorarioComida.activo == 1)
            .order_by(HorarioComida.vigente_desde.desc())
            .limit(1)
        ).one()
    mitad = (inicio.hour * 60 + inicio.minute + fin.hour * 60 + fin.minute) // 2
    return time(mitad // 60, mitad % 60)


def _sin_derecho_ese_dia(fecha: date, comida_id: int) -> int:
    """Alguien del padrón de turnos SIN derecho a esa comida ese día."""
    with SesionLocal() as sesion:
        con = select(ComidaPorTurno.usuario_id).where(
            ComidaPorTurno.fecha_comida == fecha, ComidaPorTurno.comida_id == comida_id
        )
        uid = sesion.execute(
            select(ComidaPorTurno.usuario_id)
            .where(ComidaPorTurno.usuario_id.not_in(aplicar_reglas(con)))
            .limit(1)
        ).scalar_one_or_none()
    if uid is None:
        pytest.skip("no hay un usuario sin derecho para comparar")
    return uid


def _en_franja() -> tuple[int, date, int, datetime]:
    usuario_id, fecha, comida_id = _derecho()
    momento = datetime.combine(fecha, _mitad_franja(comida_id))
    reloj_prueba.fijar(momento)
    return usuario_id, fecha, comida_id, momento


@pytest.mark.usefixtures("con_horarios")
def test_lista_trae_a_quien_tiene_derecho(cliente, cuentas):
    usuario_id, fecha, comida_id, _ = _en_franja()
    r = cliente.get("/pantalla/checklist", headers=cuentas["cocinera"][1])
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["fuera_de_horario"] is False
    assert cuerpo["comida_id"] == comida_id
    assert cuerpo["fecha_comida"] == fecha.isoformat()
    ids = [p["usuario_id"] for p in cuerpo["personas"]]
    assert usuario_id in ids
    assert len(ids) == len(set(ids))
    with SesionLocal() as sesion:
        esperadas = sesion.execute(
            aplicar_reglas(
                select(ComidaPorTurno.usuario_id)
                .select_from(ComidaPorTurno)
                .where(ComidaPorTurno.fecha_comida == fecha)
                .where(ComidaPorTurno.comida_id == comida_id)
            ).distinct()
        ).scalars().all()
    assert set(ids) == set(esperadas)


@pytest.mark.usefixtures("con_horarios")
def test_fuera_de_horario_lista_vacia(cliente, cuentas):
    _, fecha, _ = _derecho()
    # 03:30: la semilla no tiene comida a esa hora.
    reloj_prueba.fijar(datetime.combine(fecha, time(3, 30)))
    r = cliente.get("/pantalla/checklist", headers=cuentas["cocinera"][1])
    assert r.status_code == 200, r.text
    assert r.json()["fuera_de_horario"] is True
    assert r.json()["personas"] == []


@pytest.mark.usefixtures("con_horarios")
def test_marcar_registra_con_la_cuenta_y_no_repite(cliente, cuentas):
    uid, cocinera = cuentas["cocinera"]
    usuario_id, _, _, _ = _en_franja()
    r = cliente.post("/asistencias/checklist", json={"usuario_id": usuario_id}, headers=cocinera)
    assert r.status_code == 200, r.text
    assert r.json()["valido"] is True, r.text
    with SesionLocal() as sesion:
        fila = sesion.get(Asistencia, r.json()["asistencia_id"])
        assert fila.metodo == "checklist"
        assert fila.registrado_por_cuenta == uid
        assert fila.lectura_id is None

    otra = cliente.post("/asistencias/checklist", json={"usuario_id": usuario_id}, headers=cocinera)
    assert otra.status_code == 200
    assert otra.json()["valido"] is False
    assert otra.json()["motivo"] == "duplicado"

    lista = cliente.get("/pantalla/checklist", headers=cocinera).json()
    persona = next(p for p in lista["personas"] if p["usuario_id"] == usuario_id)
    assert persona["servida"] is True
    assert persona["metodo"] == "checklist"
    assert persona["anulable"] is True


@pytest.mark.usefixtures("con_horarios")
def test_marcar_sin_derecho_se_rechaza(cliente, cuentas):
    _, fecha, comida_id, _ = _en_franja()
    sin_derecho = _sin_derecho_ese_dia(fecha, comida_id)
    r = cliente.post("/asistencias/checklist", json={"usuario_id": sin_derecho}, headers=cuentas["cocinera"][1])
    assert r.status_code == 200
    assert r.json()["valido"] is False
    assert r.json()["motivo"] == "sin_derecho"


@pytest.mark.usefixtures("con_horarios")
@pytest.mark.parametrize("rol", ["jefa", "sistemas"])
def test_solo_cocinera_marca(cliente, cuentas, rol):
    usuario_id, _, _, _ = _en_franja()
    r = cliente.post("/asistencias/checklist", json={"usuario_id": usuario_id}, headers=cuentas[rol][1])
    assert r.status_code == 403
    r = cliente.delete("/asistencias/checklist/1", headers=cuentas[rol][1])
    assert r.status_code == 403


@pytest.mark.usefixtures("con_horarios")
def test_desmarcar_en_plazo_deja_auditoria(cliente, cuentas):
    uid, cocinera = cuentas["cocinera"]
    usuario_id, _, _, momento = _en_franja()
    asistencia_id = cliente.post(
        "/asistencias/checklist", json={"usuario_id": usuario_id}, headers=cocinera
    ).json()["asistencia_id"]
    # Mucho después de marcar, pero dentro de la misma comida: se puede.
    reloj_prueba.fijar(momento + timedelta(minutes=30))
    r = cliente.delete(f"/asistencias/checklist/{asistencia_id}", headers=cocinera)
    assert r.status_code == 200, r.text
    with SesionLocal() as sesion:
        assert sesion.get(Asistencia, asistencia_id) is None
        anulacion = sesion.execute(select(AnulacionChecklist)).scalar_one()
        assert anulacion.asistencia_id == asistencia_id
        assert anulacion.usuario_id == usuario_id
        assert anulacion.cuenta_id == uid
    # Desmarcada, se puede volver a marcar.
    r = cliente.post("/asistencias/checklist", json={"usuario_id": usuario_id}, headers=cocinera)
    assert r.json()["valido"] is True


@pytest.mark.usefixtures("con_horarios")
def test_desmarcar_otra_cuenta_o_comida_cerrada(cliente, cuentas, lector):
    _, cocinera = cuentas["cocinera"]
    _, cocinera_b = cuentas["cocinera_b"]
    usuario_id, _, _, momento = _en_franja()
    asistencia_id = cliente.post(
        "/asistencias/checklist", json={"usuario_id": usuario_id}, headers=cocinera
    ).json()["asistencia_id"]

    r = cliente.delete(f"/asistencias/checklist/{asistencia_id}", headers=cocinera_b)
    assert r.status_code == 403
    assert r.json()["motivo"] == "otra_cuenta"

    # La otra cocinera la ve entregada, pero no la puede deshacer.
    lista = cliente.get("/pantalla/checklist", headers=cocinera_b).json()
    persona = next(p for p in lista["personas"] if p["usuario_id"] == usuario_id)
    assert persona["servida"] is True and persona["anulable"] is False

    # Cerrada la comida (madrugada, sin franja en la semilla): ya no se deshace.
    reloj_prueba.fijar(datetime.combine(momento.date() + timedelta(days=1), time(3, 30)))
    r = cliente.delete(f"/asistencias/checklist/{asistencia_id}", headers=cocinera)
    assert r.status_code == 409
    assert r.json()["motivo"] == "comida_cerrada"

    assert cliente.delete("/asistencias/checklist/999999999", headers=cocinera).status_code == 404
    with SesionLocal() as sesion:
        assert sesion.get(Asistencia, asistencia_id) is not None
        assert sesion.execute(select(AnulacionChecklist)).first() is None


@pytest.mark.usefixtures("con_horarios")
def test_huella_no_se_desmarca(cliente, cuentas, lector):
    _, cocinera = cuentas["cocinera"]
    usuario_id, _, _, _ = _en_franja()
    lectura = lector.leer(usuario_id=usuario_id)
    assert lectura["valido"] is True, lectura
    r = cliente.delete(f"/asistencias/checklist/{lectura['asistencia_id']}", headers=cocinera)
    assert r.status_code == 409
    assert r.json()["motivo"] == "no_es_checklist"


@pytest.mark.usefixtures("con_horarios")
def test_checklist_sale_en_ultimas_marcaciones(cliente, cuentas):
    _, cocinera = cuentas["cocinera"]
    usuario_id, _, _, momento = _en_franja()
    cliente.post("/asistencias/checklist", json={"usuario_id": usuario_id}, headers=cocinera)
    filas = cliente.get(
        "/pantalla/ultimas-marcaciones",
        params={"fecha": momento.date().isoformat()},
        headers=cuentas["jefa"][1],
    ).json()
    assert any(
        f["usuario_id"] == usuario_id and f["dispositivo"] == "checklist-cocina" for f in filas
    ), filas


# --- policías en el checklist ------------------------------------------------

DIA_POLICIA = datetime(2026, 9, 24, 12, 30)  # dentro del almuerzo de la semilla


def _vaciar_policias():
    with SesionLocal() as sesion:
        sesion.execute(text("DELETE FROM anulaciones_checklist"))
        sesion.execute(text("DELETE FROM raciones_policia"))
        sesion.execute(text("DELETE FROM policias"))
        sesion.commit()


@pytest.fixture
def en_almuerzo(con_horarios):
    _vaciar_policias()
    reloj_prueba.fijar(DIA_POLICIA)
    yield
    _vaciar_policias()


def _alta(cliente, jefa) -> dict:
    r = cliente.post("/policias", headers=jefa)
    assert r.status_code == 201, r.text
    return r.json()


def _marcar(cliente, cocinera, policia_id):
    return cliente.post("/asistencias/checklist/policias", json={"policia_id": policia_id}, headers=cocinera)


@pytest.mark.usefixtures("en_almuerzo")
def test_jefa_da_de_alta_policias_por_numero_y_de_baja(cliente, cuentas):
    _, jefa = cuentas["jefa"]
    _, sistemas = cuentas["sistemas"]
    uno, dos = _alta(cliente, jefa), _alta(cliente, sistemas)
    assert (uno["numero"], uno["nombre"], uno["activo"]) == (1, "Policía 1", True)
    assert (dos["numero"], dos["nombre"]) == (2, "Policía 2")
    r = cliente.patch(f"/policias/{uno['id']}", json={"activo": False}, headers=jefa)
    assert r.status_code == 200 and r.json()["activo"] is False
    assert [p["activo"] for p in cliente.get("/policias", headers=jefa).json()] == [False, True]
    # El número no se reutiliza: el siguiente es el 3.
    assert _alta(cliente, jefa)["numero"] == 3
    assert cliente.patch("/policias/999999", json={"activo": True}, headers=jefa).status_code == 404


@pytest.mark.usefixtures("en_almuerzo")
def test_policia_por_numero_pendiente_entregado_y_una_vez(cliente, cuentas):
    uid, cocinera = cuentas["cocinera"]
    _, cocinera_b = cuentas["cocinera_b"]
    _, jefa = cuentas["jefa"]
    uno, dos = _alta(cliente, jefa), _alta(cliente, jefa)
    antes = cliente.get(f"/pantalla/comidas-del-dia?fecha={DIA_POLICIA.date()}", headers=jefa).json()

    lista = cliente.get("/pantalla/checklist", headers=cocinera).json()["policias"]
    assert [(p["nombre"], p["servida"]) for p in lista] == [("Policía 1", False), ("Policía 2", False)]

    r = _marcar(cliente, cocinera, uno["id"])
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["valido"] is True and cuerpo["nombre"] == "Policía 1"
    with SesionLocal() as sesion:
        racion = sesion.get(RacionPolicia, cuerpo["racion_id"])
        assert (racion.policia_id, racion.nombre, racion.vinculo_id) == (uno["id"], "Policía 1", None)
        assert racion.registrado_por_cuenta == uid
    # Una ración por comida: ni la misma cocinera ni otra lo repiten.
    for cuenta in (cocinera, cocinera_b):
        r = _marcar(cliente, cuenta, uno["id"])
        assert r.status_code == 200 and r.json()["valido"] is False
        assert r.json()["motivo"] == "duplicado"

    lista = cliente.get("/pantalla/checklist", headers=cocinera).json()["policias"]
    assert [(p["nombre"], p["servida"], p["anulable"]) for p in lista] == [
        ("Policía 1", True, True), ("Policía 2", False, False)]
    otra = cliente.get("/pantalla/checklist", headers=cocinera_b).json()["policias"]
    assert otra[0]["anulable"] is False

    despues = cliente.get(f"/pantalla/comidas-del-dia?fecha={DIA_POLICIA.date()}", headers=jefa).json()
    previas = {c["comida"]: c for c in antes["comidas"]}
    por_comida = {c["comida"]: c for c in despues["comidas"]}
    assert por_comida["Almuerzo"]["policias"] == previas["Almuerzo"]["policias"] + 1
    assert por_comida["Almuerzo"]["servidas"] == previas["Almuerzo"]["servidas"]
    filas = cliente.get("/pantalla/ultimas-marcaciones",
                        params={"fecha": DIA_POLICIA.date().isoformat()}, headers=jefa).json()
    assert any(f["origen"] == "racion_policia" and f["nombre"] == "Policía 1" for f in filas)


@pytest.mark.usefixtures("en_almuerzo")
def test_policia_de_baja_inexistente_y_fuera_de_horario(cliente, cuentas):
    _, cocinera = cuentas["cocinera"]
    _, jefa = cuentas["jefa"]
    uno, dos = _alta(cliente, jefa), _alta(cliente, jefa)
    cliente.patch(f"/policias/{dos['id']}", json={"activo": False}, headers=jefa)
    assert [p["nombre"] for p in cliente.get("/pantalla/checklist", headers=cocinera).json()["policias"]] == ["Policía 1"]
    r = _marcar(cliente, cocinera, dos["id"])
    assert r.status_code == 404 and r.json()["motivo"] == "policia_inexistente"
    assert _marcar(cliente, cocinera, 999999).status_code == 404
    reloj_prueba.fijar(datetime.combine(DIA_POLICIA.date(), time(3, 30)))
    r = _marcar(cliente, cocinera, uno["id"])
    assert r.status_code == 200 and r.json()["valido"] is False
    assert r.json()["motivo"] == "fuera_horario"
    with SesionLocal() as sesion:
        assert sesion.execute(select(RacionPolicia)).first() is None


@pytest.mark.usefixtures("en_almuerzo")
@pytest.mark.parametrize("rol", ["jefa", "sistemas"])
def test_solo_cocinera_registra_policias(cliente, cuentas, rol):
    r = cliente.post("/asistencias/checklist/policias", json={"policia_id": 1}, headers=cuentas[rol][1])
    assert r.status_code == 403
    assert cliente.delete("/asistencias/checklist/policias/1", headers=cuentas[rol][1]).status_code == 403


@pytest.mark.usefixtures("en_almuerzo")
def test_cocinera_no_administra_policias(cliente, cuentas):
    _, cocinera = cuentas["cocinera"]
    assert cliente.get("/policias", headers=cocinera).status_code == 403
    assert cliente.post("/policias", headers=cocinera).status_code == 403


@pytest.mark.usefixtures("en_almuerzo")
def test_deshacer_policia_vuelve_a_pendiente(cliente, cuentas):
    uid, cocinera = cuentas["cocinera"]
    _, cocinera_b = cuentas["cocinera_b"]
    _, jefa = cuentas["jefa"]
    uno, dos = _alta(cliente, jefa), _alta(cliente, jefa)
    racion_id = _marcar(cliente, cocinera, uno["id"]).json()["racion_id"]
    r = cliente.delete(f"/asistencias/checklist/policias/{racion_id}", headers=cocinera_b)
    assert r.status_code == 403 and r.json()["motivo"] == "otra_cuenta"

    r = cliente.delete(f"/asistencias/checklist/policias/{racion_id}", headers=cocinera)
    assert r.status_code == 200, r.text
    with SesionLocal() as sesion:
        assert sesion.get(RacionPolicia, racion_id) is None
        anulacion = sesion.execute(select(AnulacionChecklist)).scalar_one()
        assert anulacion.racion_policia_id == racion_id
        assert anulacion.nombre == "Policía 1"
        assert anulacion.asistencia_id is None and anulacion.usuario_id is None
        assert anulacion.cuenta_id == uid
    # No desaparece: vuelve a pendiente y se puede entregar de nuevo.
    lista = cliente.get("/pantalla/checklist", headers=cocinera).json()["policias"]
    assert (lista[0]["nombre"], lista[0]["servida"]) == ("Policía 1", False)
    assert _marcar(cliente, cocinera, uno["id"]).json()["valido"] is True

    otra = _marcar(cliente, cocinera, dos["id"]).json()["racion_id"]
    reloj_prueba.fijar(datetime.combine(DIA_POLICIA.date(), time(3, 30)) + timedelta(days=1))
    r = cliente.delete(f"/asistencias/checklist/policias/{otra}", headers=cocinera)
    assert r.status_code == 409 and r.json()["motivo"] == "comida_cerrada"
