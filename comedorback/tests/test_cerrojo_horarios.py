"""El cerrojo `horarios_comida`: serializa los guardados incluso con la tabla
vacía y dos comidas distintas, en los dos aislamientos pertinentes.

Por qué una fila y no `SELECT ... FOR UPDATE` de la tabla de horarios: con la
tabla vacía eso solo toma el gap-lock del supremum, que no choca con el de otra
transacción, así que dos altas simultáneas pasan las dos (REPEATABLE READ: o
terminan en deadlock) y en READ COMMITTED ni siquiera hay gap-lock. El
protocolo de estas pruebas es determinista: una conexión retiene el cerrojo con
un SELECT ... FOR UPDATE (una lectura, no una escritura), se lanzan los
guardados por API y se comprueba que esperan; al soltar, se resuelven en serie.
"""

import threading
import time
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text

import reloj_prueba
from app.core.config import config
from app.core.db import SesionLocal, motor
from app.main import app
from app.modelos.comedor import CERROJO_HORARIOS
from soporte_horarios import (  # noqa: F401  fixtures y ayudas compartidas
    a_las,
    abierta,
    comida_id,
    con_horarios,
    guardar,
    historial,
    reloj_libre,
    root,
    vacio,
)

ESPERA = 1.5  # segundos que se deja a los guardados bloqueados antes de comprobarlos


@pytest.fixture(params=["REPEATABLE READ", "READ COMMITTED"])
def aislamiento(request):
    """El mismo código bajo cada aislamiento: la app usa `SesionLocal`, que
    aquí se liga a un motor con ese nivel."""
    motor_prueba = create_engine(
        config.url_base_datos,
        isolation_level=request.param,
        pool_pre_ping=True,
        future=True,
    )
    SesionLocal.configure(bind=motor_prueba)
    yield request.param
    SesionLocal.configure(bind=motor)
    motor_prueba.dispose()


@pytest.fixture
def espera_corta():
    """Un motor cuyas conexiones se rinden a 1 s de esperar un bloqueo."""
    motor_corto = create_engine(config.url_base_datos, pool_pre_ping=True, future=True)

    @event.listens_for(motor_corto, "connect")
    def _fijar_espera(dbapi, _registro):
        cursor = dbapi.cursor()
        cursor.execute("SET SESSION innodb_lock_wait_timeout = 1")
        cursor.close()

    SesionLocal.configure(bind=motor_corto)
    yield
    SesionLocal.configure(bind=motor)
    motor_corto.dispose()


@contextmanager
def retener_cerrojo():
    """Una transacción que tiene el cerrojo. Solo lectura bloqueante."""
    conexion = motor.connect()
    transaccion = conexion.begin()
    conexion.execute(
        text("SELECT nombre FROM cerrojos WHERE nombre = :nombre FOR UPDATE"),
        {"nombre": CERROJO_HORARIOS},
    )
    try:
        yield
    finally:
        transaccion.rollback()
        conexion.close()


def _cuerpo(comida: int, inicio: str, fin: str, base: int | None) -> dict:
    return {
        "comida_id": comida,
        "hora_inicio": inicio,
        "hora_fin": fin,
        "base_horario_id": base,
    }


def _lanzar(resultados: dict, clave: str, token, cuerpo: dict) -> threading.Thread:
    def tarea():
        resultados[clave] = TestClient(app).post(
            "/reglas/horarios", json=cuerpo, headers=token
        )

    hilo = threading.Thread(target=tarea, daemon=True)
    hilo.start()
    return hilo


def _esperar(hilos, resultados) -> None:
    """Comprueba que los guardados siguen bloqueados mientras el cerrojo está
    retenido."""
    time.sleep(ESPERA)
    assert all(h.is_alive() for h in hilos), "un guardado no esperó el cerrojo"
    assert resultados == {}


def _terminar(hilos) -> None:
    for hilo in hilos:
        hilo.join(30)
        assert not hilo.is_alive(), "un guardado no terminó al soltar el cerrojo"


def _filas_de_horarios() -> int:
    with SesionLocal() as sesion:
        return sesion.execute(text("SELECT COUNT(*) FROM horarios_comida")).scalar_one()


def test_el_aislamiento_de_la_prueba_se_aplica(aislamiento):
    with SesionLocal() as sesion:
        nivel = sesion.execute(text("SELECT @@transaction_isolation")).scalar_one()
    assert nivel.replace("-", " ") == aislamiento


def test_dos_comidas_distintas_con_horarios_vacios_no_se_solapan(
    cliente, root, vacio, aislamiento
):
    """Tabla vacía, dos comidas distintas, franjas que se pisan, guardadas a la
    vez. Sin el cerrojo, las dos validaciones ven la tabla vacía y las dos
    insertan. Con él, una gana y la otra ve su fila y se rechaza."""
    almuerzo, te = comida_id("almuerzo"), comida_id("te")
    reloj_prueba.fijar(a_las(9), corriendo=True)  # sigue corriendo: el segundo guardado es posterior al primero
    resultados: dict = {}
    with retener_cerrojo():
        hilos = [
            _lanzar(resultados, "almuerzo", root, _cuerpo(almuerzo, "12:00:00", "14:00:00", None)),
            _lanzar(resultados, "te", root, _cuerpo(te, "13:00:00", "15:00:00", None)),
        ]
        _esperar(hilos, resultados)
    _terminar(hilos)

    assert sorted(r.status_code for r in resultados.values()) == [201, 409]
    perdedor = next(r for r in resultados.values() if r.status_code == 409)
    assert perdedor.json()["motivo"] == "solapa_con_otra_comida"
    assert _filas_de_horarios() == 1


def test_dos_comidas_sin_solape_se_guardan_en_serie(cliente, root, vacio, aislamiento):
    almuerzo, te = comida_id("almuerzo"), comida_id("te")
    reloj_prueba.fijar(a_las(9), corriendo=True)
    resultados: dict = {}
    with retener_cerrojo():
        hilos = [
            _lanzar(resultados, "almuerzo", root, _cuerpo(almuerzo, "12:00:00", "14:00:00", None)),
            _lanzar(resultados, "te", root, _cuerpo(te, "14:00:00", "16:00:00", None)),
        ]
        _esperar(hilos, resultados)
    _terminar(hilos)

    assert [r.status_code for r in resultados.values()] == [201, 201]
    desdes = sorted(r.json()["vigente_desde"] for r in resultados.values())
    assert desdes[0] < desdes[1], "los instantes de un guardado en serie son distintos"
    assert _filas_de_horarios() == 2


def test_misma_comida_con_la_misma_base_un_solo_ganador(
    cliente, root, con_horarios, aislamiento
):
    almuerzo = comida_id("almuerzo")
    base = abierta(cliente, root, almuerzo)["horario_id"]
    reloj_prueba.fijar(a_las(9), corriendo=True)
    resultados: dict = {}
    with retener_cerrojo():
        hilos = [
            _lanzar(resultados, "a", root, _cuerpo(almuerzo, "12:00:00", "13:00:00", base)),
            _lanzar(resultados, "b", root, _cuerpo(almuerzo, "12:00:00", "14:00:00", base)),
        ]
        _esperar(hilos, resultados)
    _terminar(hilos)

    assert sorted(r.status_code for r in resultados.values()) == [201, 409]
    perdedor = next(r for r in resultados.values() if r.status_code == 409)
    assert perdedor.json()["motivo"] == "version_desactualizada"
    versiones = historial(cliente, root, almuerzo)
    assert len(versiones) == 2
    assert sum(1 for v in versiones if v["estado"] == "vigente") == 1


def test_espera_agotada_da_409_sin_reintento_automatico(cliente, root, vacio, espera_corta):
    almuerzo = comida_id("almuerzo")
    reloj_prueba.fijar(a_las(9), corriendo=True)
    with retener_cerrojo():
        r = guardar(cliente, root, almuerzo, "12:00:00", "13:00:00", None)
    assert (r.status_code, r.json()["motivo"]) == (409, "cambio_en_curso")
    assert _filas_de_horarios() == 0


def test_el_cerrojo_se_libera_en_exito_y_en_error(cliente, root, con_horarios):
    """Termine como termine el guardado, la transacción suelta el cerrojo:
    un NOWAIT inmediato lo consigue."""
    almuerzo = comida_id("almuerzo")
    base = abierta(cliente, root, almuerzo)["horario_id"]
    reloj_prueba.fijar(a_las(9))

    def cerrojo_libre() -> bool:
        with motor.connect() as conexion, conexion.begin():
            conexion.execute(
                text("SELECT nombre FROM cerrojos WHERE nombre = :nombre FOR UPDATE NOWAIT"),
                {"nombre": CERROJO_HORARIOS},
            )
        return True

    assert guardar(cliente, root, almuerzo, "11:00:00", "15:00:00", base).status_code == 409  # sin_cambios
    assert cerrojo_libre()
    assert guardar(cliente, root, 999999999, "12:00:00", "13:00:00", None).status_code == 404
    assert cerrojo_libre()
    assert guardar(cliente, root, almuerzo, "11:00:00", "14:00:00", base).status_code == 201
    assert cerrojo_libre()
