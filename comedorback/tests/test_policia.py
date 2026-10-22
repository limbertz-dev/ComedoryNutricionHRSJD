"""Raciones de policía por el lector: vía libre, separadas del personal, y
solo cuentan como ración en la columna Policías.

  · Una huella vinculada como `policia` (sin persona del padrón) da una
    ración en `raciones_policia` en cada lectura, sin derecho ni duplicado.
  · Fuera de horario no se registra. Un reintento del puente no da dos.
  · Informes y resumen la suman en Policías; las demás columnas, el cupo del
    personal y las lecturas no cambian. Sin policías, todo da lo mismo que antes.
"""

import uuid
from datetime import datetime

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text

from app.consultas import informes, raciones
from app.core.config import config
from app.core.db import SesionLocal
from app.modelos.comedor import Asistencia, LecturaBiometrica
from app.modelos.lector import RacionPolicia
from app.semillas import horarios
import reloj_prueba
from conftest import encabezado, ingresar

DIA = datetime(2026, 9, 24, 12, 30)  # dentro del almuerzo de la semilla
FECHA = DIA.date()
CLAVE = "clave-de-prueba-del-lector-cocina-01"
LECTOR = {"X-Lector-Token": CLAVE}


@pytest.fixture(autouse=True)
def lector(monkeypatch):
    monkeypatch.setattr(config, "lectores", SecretStr(f"cocina-01={CLAVE}"))


def _vaciar():
    with SesionLocal() as sesion:
        for tabla in ("raciones_policia", "solicitudes_lector", "vinculos_lector", "horarios_comida"):
            sesion.execute(text(f"DELETE FROM {tabla}"))
        sesion.commit()


@pytest.fixture
def jefa(cliente, crear_usuario):
    crear_usuario("p_jefa", rol="jefa")
    return encabezado(ingresar(cliente, "p_jefa")["access"])


@pytest.fixture
def huella_policia(cliente, jefa):
    _vaciar()
    horarios.sembrar()
    reloj_prueba.fijar(DIA)
    r = cliente.post("/lector/vinculos", headers=jefa, json={"identificador": "pol-1", "tipo": "policia"})
    assert r.status_code == 201, r.text
    yield r.json()
    _vaciar()


def _leer(cliente, identificador="pol-1", clave=None):
    return cliente.post("/lector/lecturas", json={"identificador": identificador},
                        headers={**LECTOR, "Idempotency-Key": clave or str(uuid.uuid4())})


def _conteo(modelo):
    with SesionLocal() as sesion:
        return sesion.execute(select(func.count()).select_from(modelo)).scalar_one()


def _columna(informe, nombre):
    i = informe.categorias.index(nombre)
    return [fila.celdas[i] for fila in informe.filas]


def test_vinculo_de_policia_sin_persona(huella_policia):
    assert (huella_policia["tipo"], huella_policia["usuario_id"]) == ("policia", None)
    assert (huella_policia["nombre"], huella_policia["categoria"]) == ("Policía", "Policías")


@pytest.mark.parametrize("cuerpo", [
    {"identificador": "x", "tipo": "policia", "usuario_id": 5},
    {"identificador": "x", "tipo": "personal"},
])
def test_tipo_y_persona_coherentes_422(cliente, jefa, cuerpo):
    assert cliente.post("/lector/vinculos", headers=jefa, json=cuerpo).status_code == 422


def test_cada_lectura_es_una_racion_con_via_libre(cliente, huella_policia):
    lecturas = _conteo(LecturaBiometrica)
    primera = _leer(cliente).json()
    segunda = _leer(cliente).json()
    assert primera["valido"] is True and segunda["valido"] is True, (primera, segunda)
    assert (primera["nombre"], primera["comida"], primera["vinculado"]) == ("Policía", "Almuerzo", True)
    assert _conteo(RacionPolicia) == 2
    # No escribe lecturas ni raciones de personal.
    assert _conteo(LecturaBiometrica) == lecturas


def test_reintento_del_puente_no_da_dos(cliente, huella_policia):
    clave = str(uuid.uuid4())
    _leer(cliente, clave=clave)
    segunda = _leer(cliente, clave=clave).json()
    assert segunda["reintento"] is True
    assert _conteo(RacionPolicia) == 1


def test_fuera_de_horario_no_registra(cliente, huella_policia):
    reloj_prueba.fijar(datetime(2026, 9, 24, 3, 0))
    datos = _leer(cliente).json()
    assert (datos["valido"], datos["motivo"]) == (False, "fuera_horario")
    assert _conteo(RacionPolicia) == 0


def test_huella_de_policia_dada_de_baja_ya_no_registra(cliente, jefa, huella_policia):
    cliente.delete(f"/lector/vinculos/{huella_policia['id']}", headers=jefa)
    assert _leer(cliente).json()["motivo"] == "no_identificado"
    assert _conteo(RacionPolicia) == 0


def test_informe_suma_solo_en_policias_y_lo_demas_no_cambia(cliente, huella_policia):
    with SesionLocal() as sesion:
        antes = informes.informe_rango(sesion, FECHA, FECHA)
    for _ in range(3):
        _leer(cliente)
    with SesionLocal() as sesion:
        despues = informes.informe_rango(sesion, FECHA, FECHA)

    assert despues.categorias == antes.categorias
    almuerzo = [f.etiqueta for f in despues.filas].index("Almuerzo")
    esperado = _columna(antes, "Policías")
    esperado[almuerzo] += 3
    assert _columna(despues, "Policías") == esperado
    for nombre in despues.categorias:
        if nombre != "Policías":
            assert _columna(despues, nombre) == _columna(antes, nombre), nombre
    assert despues.total_general == antes.total_general + 3


def test_resumen_y_supervision(cliente, jefa, huella_policia):
    antes = cliente.get(f"/pantalla/comidas-del-dia?fecha={FECHA}", headers=jefa).json()
    estado_antes = cliente.get("/pantalla/estado", headers=jefa).json()
    _leer(cliente)
    _leer(cliente)

    dia = cliente.get(f"/pantalla/comidas-del-dia?fecha={FECHA}", headers=jefa).json()
    por_comida = {c["comida"]: c for c in dia["comidas"]}
    previas = {c["comida"]: c for c in antes["comidas"]}
    assert por_comida["Almuerzo"]["policias"] == 2
    # Las servidas al personal y el cupo no se mezclan con los policías.
    assert por_comida["Almuerzo"]["servidas"] == previas["Almuerzo"]["servidas"]

    estado = cliente.get("/pantalla/estado", headers=jefa).json()
    assert estado["totales_del_dia"]["raciones_servidas"] == estado_antes["totales_del_dia"]["raciones_servidas"] + 2
    assert estado["totales_del_dia"]["lecturas"] == estado_antes["totales_del_dia"]["lecturas"]
    assert estado["cupo"] == estado_antes["cupo"]
    categorias = {c["categoria"]: c["raciones"] for c in estado["por_categoria"]}
    previas_cat = {c["categoria"]: c["raciones"] for c in estado_antes["por_categoria"]}
    assert categorias["Policías"] == previas_cat["Policías"] + 2


def test_sin_policias_la_fuente_es_asistencias():
    """La unión de raciones, sin policías, cuenta lo mismo que asistencias."""
    with SesionLocal() as sesion:
        assert sesion.execute(select(func.count()).select_from(RacionPolicia)).scalar_one() == 0
        r = raciones.fuente()
        assert (sesion.execute(select(func.count()).select_from(r)).scalar_one()
                == sesion.execute(select(func.count()).select_from(Asistencia)).scalar_one())
