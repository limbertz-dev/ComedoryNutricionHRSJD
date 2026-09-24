"""Escritura del Control de Dietas: POST /pacientes/control, /suspender y /reanudar.

Sin MySQL ni SIH: el catálogo y `dietas_cama` se crean en un SQLite en
memoria y el censo se simula con una cama ficticia. Cada sentencia SQL queda
registrada para comprobar que las tres rutas solo INSERTAN y nunca
actualizan ni borran.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.mysql import BIGINT, TINYINT
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.consultas import control as consultas_control
from app.consultas.censo import CamaCensada
from app.core.db import obtener_sesion
from app.main import app
from app.modelos.pacientes import ColumnaInformeDieta, DietasCama, TipoDieta


# Los modelos usan tipos de MySQL; SQLite no los conoce. Solo para el dialecto
# sqlite (el de este test) se escriben como INTEGER. MySQL no se ve afectado.
@compiles(TINYINT, "sqlite")
@compiles(BIGINT, "sqlite")
def _entero_en_sqlite(_tipo, _compilador, **_kw):
    return "INTEGER"


CAMA_OCUPADA = 501
CAMA_LIBRE = 999

# Todo ficticio: ni el nombre ni la historia existen en el hospital.
CAMA_FICTICIA = CamaCensada(
    nro_historia=100001,
    nombre_paciente="PACIENTE DE PRUEBA",
    sexo="F",
    sa_codigo=38,
    sala_texto="SALA PRUEBA",
    pieza_texto="1",
    cam_codigo=CAMA_OCUPADA,
    cama_texto="C-1",
    cod_servicio_cama=208,
    cod_servicio_internacion=208,
    servicio_cama_texto="SERVICIO PRUEBA",
    servicio_internacion_texto="SERVICIO PRUEBA",
    servicio_nutricion_id=None,
    hoja_informe=None,
    grupo_informe=None,
)


@pytest.fixture
def cliente(monkeypatch):
    motor = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    sentencias: list[str] = []
    event.listen(
        motor, "before_cursor_execute",
        lambda _c, _cur, sql, *_a: sentencias.append(sql.strip().upper()),
    )
    ColumnaInformeDieta.metadata.create_all(
        motor,
        tables=[ColumnaInformeDieta.__table__, TipoDieta.__table__, DietasCama.__table__],
    )
    Sesion = sessionmaker(bind=motor, expire_on_commit=False)
    with Sesion() as s:
        s.add_all([
            ColumnaInformeDieta(id=1, nombre="CORRIENTE", codigo="corriente", orden=1, activo=True),
            ColumnaInformeDieta(id=2, nombre="BLANDA", codigo="blanda", orden=2, activo=True),
            TipoDieta(id=1, nombre="Corriente", codigo="corriente", columna_informe_id=1,
                      cuenta_racion=True, orden=1, activo=True),
            TipoDieta(id=2, nombre="Blanda", codigo="blanda", columna_informe_id=2,
                      cuenta_racion=True, orden=2, activo=True),
            TipoDieta(id=3, nombre="Dada de baja", codigo="baja", columna_informe_id=1,
                      cuenta_racion=True, orden=3, activo=False),
            TipoDieta(id=4, nombre="Eliminada", codigo="eliminada", columna_informe_id=1,
                      cuenta_racion=True, orden=4, activo=True, visible=False),
        ])
        s.commit()

    # El censo del SIH, simulado: una sola cama ocupada.
    monkeypatch.setattr(
        consultas_control,
        "buscar_cama",
        lambda _s, cam: CAMA_FICTICIA if cam == CAMA_OCUPADA else None,
    )

    def sesion_de_prueba():
        with Sesion() as s:
            yield s

    app.dependency_overrides[obtener_sesion] = sesion_de_prueba
    sentencias.clear()
    try:
        yield TestClient(app), Sesion, sentencias
    finally:
        app.dependency_overrides.pop(obtener_sesion, None)


def _hechos(Sesion) -> list[DietasCama]:
    with Sesion() as s:
        return list(s.execute(select(DietasCama).order_by(DietasCama.id)).scalars())


def _sin_update_ni_delete(sentencias: list[str]) -> None:
    assert not [q for q in sentencias if q.startswith(("UPDATE", "DELETE"))]


# --- asignar ---------------------------------------------------------------


def test_asignar_responde_201_e_inserta_un_hecho(cliente):
    http, Sesion, sentencias = cliente

    # El cuerpo exacto que manda el front: la cama y la dieta, nada más.
    r = http.post("/pacientes/control", json={"cam_codigo": CAMA_OCUPADA, "tipo_dieta_id": 1})

    assert r.status_code == 201, r.text
    cuerpo = r.json()
    assert cuerpo["cam_codigo"] == CAMA_OCUPADA
    assert cuerpo["tipo_dieta_id"] == 1
    assert cuerpo["suspendida"] is False
    assert cuerpo["motivo"] is None

    hechos = _hechos(Sesion)
    assert len(hechos) == 1
    assert hechos[0].id == cuerpo["dietas_cama_id"]
    # Lo del paciente sale del censo, no del cuerpo.
    assert hechos[0].nombre_paciente == "PACIENTE DE PRUEBA"
    assert hechos[0].sa_codigo == 38
    assert sum(q.startswith("INSERT INTO DIETAS_CAMA") for q in sentencias) == 1
    _sin_update_ni_delete(sentencias)


def test_cambiar_la_dieta_inserta_otro_hecho_sin_motivo(cliente):
    http, Sesion, sentencias = cliente

    primera = http.post("/pacientes/control", json={"cam_codigo": CAMA_OCUPADA, "tipo_dieta_id": 1})
    cambio = http.post("/pacientes/control", json={"cam_codigo": CAMA_OCUPADA, "tipo_dieta_id": 2})

    assert (primera.status_code, cambio.status_code) == (201, 201), cambio.text
    assert [h.tipo_dieta_id for h in _hechos(Sesion)] == [1, 2]
    _sin_update_ni_delete(sentencias)


def test_asignar_guarda_motivo_y_prescripcion_si_vienen(cliente):
    http, Sesion, _ = cliente

    r = http.post("/pacientes/control", json={
        "cam_codigo": CAMA_OCUPADA,
        "tipo_dieta_id": 2,
        "motivo": "  indicacion medica  ",
        "prescripcion_texto": "a tolerancia",
    })

    assert r.status_code == 201, r.text
    assert r.json()["motivo"] == "indicacion medica"
    assert _hechos(Sesion)[0].prescripcion_texto == "a tolerancia"


def test_cama_fuera_del_censo_es_409_y_no_inserta(cliente):
    http, Sesion, sentencias = cliente

    r = http.post("/pacientes/control", json={"cam_codigo": CAMA_LIBRE, "tipo_dieta_id": 1})

    assert r.status_code == 409
    assert "no figura ocupada" in r.json()["detail"]
    assert _hechos(Sesion) == []
    assert not [q for q in sentencias if q.startswith("INSERT")]


@pytest.mark.parametrize("tipo_dieta_id", [3, 4, 777])
def test_dieta_inactiva_eliminada_o_inexistente_es_422(cliente, tipo_dieta_id):
    http, Sesion, _ = cliente

    r = http.post(
        "/pacientes/control", json={"cam_codigo": CAMA_OCUPADA, "tipo_dieta_id": tipo_dieta_id}
    )

    assert r.status_code == 422
    assert _hechos(Sesion) == []


# --- suspender y reanudar --------------------------------------------------


def test_ciclo_asignar_suspender_reanudar(cliente):
    http, Sesion, sentencias = cliente
    cama = {"cam_codigo": CAMA_OCUPADA}

    asignada = http.post("/pacientes/control", json={**cama, "tipo_dieta_id": 2})
    # Suspender y reanudar con el cuerpo que manda el front: solo la cama.
    suspendida = http.post("/pacientes/control/suspender", json=cama)
    reanudada = http.post("/pacientes/control/reanudar", json=cama)

    assert [asignada.status_code, suspendida.status_code, reanudada.status_code] == [201, 201, 201]
    assert suspendida.json()["suspendida"] is True
    assert reanudada.json()["suspendida"] is False
    # La dieta no se pierde al suspender: la reanudación vuelve con la misma.
    assert suspendida.json()["tipo_dieta_id"] == reanudada.json()["tipo_dieta_id"] == 2

    hechos = _hechos(Sesion)
    assert [(h.tipo_dieta_id, bool(h.suspendida)) for h in hechos] == [
        (2, False), (2, True), (2, False),
    ]
    assert len({h.id for h in hechos}) == 3
    assert sum(q.startswith("INSERT INTO DIETAS_CAMA") for q in sentencias) == 3
    _sin_update_ni_delete(sentencias)


def test_suspender_guarda_el_motivo_si_viene(cliente):
    http, _, _ = cliente
    http.post("/pacientes/control", json={"cam_codigo": CAMA_OCUPADA, "tipo_dieta_id": 1})

    r = http.post(
        "/pacientes/control/suspender", json={"cam_codigo": CAMA_OCUPADA, "motivo": "a cirugia"}
    )

    assert r.status_code == 201, r.text
    assert r.json()["motivo"] == "a cirugia"


def test_estados_imposibles_son_409_y_no_insertan(cliente):
    http, Sesion, _ = cliente
    cama = {"cam_codigo": CAMA_OCUPADA}

    # Sin dieta hoy no hay nada que suspender ni que reanudar.
    assert http.post("/pacientes/control/suspender", json=cama).status_code == 409
    assert http.post("/pacientes/control/reanudar", json=cama).status_code == 409

    http.post("/pacientes/control", json={**cama, "tipo_dieta_id": 1})
    # Con dieta, pero sin suspender: reanudar no tiene sentido.
    assert http.post("/pacientes/control/reanudar", json=cama).status_code == 409
    http.post("/pacientes/control/suspender", json=cama)
    # Ya suspendida: suspender otra vez tampoco.
    assert http.post("/pacientes/control/suspender", json=cama).status_code == 409

    assert len(_hechos(Sesion)) == 2


def test_suspender_una_cama_fuera_del_censo_es_409(cliente):
    http, _, _ = cliente

    r = http.post("/pacientes/control/suspender", json={"cam_codigo": CAMA_LIBRE})

    assert r.status_code == 409


def test_las_tres_rutas_se_publican():
    rutas = app.openapi()["paths"]

    assert "post" in rutas["/pacientes/control"]
    assert "get" in rutas["/pacientes/control"]
    assert "post" in rutas["/pacientes/control/suspender"]
    assert "post" in rutas["/pacientes/control/reanudar"]
