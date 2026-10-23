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
    r = cliente.post("/lector/vinculos", headers=jefa, json={
        "identificador": "pol-1", "tipo": "policia", "nombre": "  juan   PEREZ  ", "documento": "PL-1234"})
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


def test_vinculo_de_policia_sin_persona_y_con_su_nombre(huella_policia):
    assert (huella_policia["tipo"], huella_policia["usuario_id"]) == ("policia", None)
    # Los espacios sobrantes se limpian; el nombre se guarda como se escribió.
    assert (huella_policia["nombre"], huella_policia["documento"], huella_policia["categoria"]) == (
        "juan PEREZ", "PL-1234", "Policías")


@pytest.mark.parametrize("cuerpo", [
    {"identificador": "x", "tipo": "policia", "usuario_id": 5, "nombre": "Juan Perez"},
    {"identificador": "x", "tipo": "policia"},
    {"identificador": "x", "tipo": "policia", "nombre": "  "},
    {"identificador": "x", "tipo": "policia", "nombre": "Juan Perez", "documento": "<script>"},
    {"identificador": "x", "tipo": "personal"},
    {"identificador": "x", "tipo": "personal", "usuario_id": 5, "nombre": "Juan Perez"},
])
def test_tipo_y_persona_coherentes_422(cliente, jefa, cuerpo):
    assert cliente.post("/lector/vinculos", headers=jefa, json=cuerpo).status_code == 422


def test_cada_lectura_es_una_racion_con_via_libre(cliente, huella_policia):
    lecturas = _conteo(LecturaBiometrica)
    primera = _leer(cliente).json()
    segunda = _leer(cliente).json()
    assert primera["valido"] is True and segunda["valido"] is True, (primera, segunda)
    assert (primera["nombre"], primera["comida"], primera["vinculado"]) == ("juan PEREZ", "Almuerzo", True)
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


def test_aparece_en_las_marcaciones_de_cocina_y_supervision(cliente, jefa, huella_policia):
    _leer(cliente)
    filas = cliente.get(f"/pantalla/ultimas-marcaciones?fecha={FECHA}&limite=50", headers=jefa).json()
    policias = [f for f in filas if f["origen"] == "racion_policia"]
    assert len(policias) == 1
    fila = policias[0]
    assert (fila["valido"], fila["nombre"], fila["categoria"], fila["comida"]) == (True, "juan PEREZ", "Policías", "Almuerzo")
    assert fila["resultado_final"]["comensal"]["nombre"] == "juan PEREZ"
    assert fila["estado_final"] == "racion_servida"
    assert fila["resultado_final"]["via"] == "policia" and fila["resultado_final"]["asistencia_id"] is None
    assert fila["clave_evento"] == f"racion_policia:{fila['id']}"
    assert fila["puede_identificar"] is False
    # Filtrada por comida: en el almuerzo sí, en la cena no.
    assert any(f["origen"] == "racion_policia" for f in cliente.get(
        f"/pantalla/ultimas-marcaciones?fecha={FECHA}&comida_id=2", headers=jefa).json())
    assert not any(f["origen"] == "racion_policia" for f in cliente.get(
        f"/pantalla/ultimas-marcaciones?fecha={FECHA}&comida_id=4", headers=jefa).json())


# --- cocina identifica a un policía cuando el lector no reconoce su huella -------


@pytest.fixture
def cocinera(cliente, crear_usuario):
    crear_usuario("p_cocinera", rol="cocinera")
    return encabezado(ingresar(cliente, "p_cocinera")["access"])


def _no_reconocida(cliente):
    datos = _leer(cliente, identificador=None).json()
    assert datos["motivo"] == "no_identificado", datos
    return datos["lectura_id"]


def _identificar(cliente, cabeceras, lectura_id, vinculo_id, clave=None):
    return cliente.post(f"/asistencias/lecturas/{lectura_id}/identificar-policia", json={"vinculo_id": vinculo_id},
                        headers={**cabeceras, "Idempotency-Key": clave or str(uuid.uuid4())})


def test_cocina_ve_a_los_policias_para_elegirlos(cliente, cocinera, huella_policia):
    r = cliente.get("/pantalla/policias", headers=cocinera)
    assert r.status_code == 200
    assert r.json() == [{"id": huella_policia["id"], "nombre": "juan PEREZ", "documento": "PL-1234"}]


def test_identificar_como_policia_da_una_racion_ligada_a_la_lectura(cliente, cocinera, jefa, huella_policia):
    lectura = _no_reconocida(cliente)
    clave = str(uuid.uuid4())
    r = _identificar(cliente, cocinera, lectura, huella_policia["id"], clave)
    assert r.status_code == 200, r.text
    datos = r.json()
    assert (datos["valido"], datos["nombre"], datos["comida"], datos["reintento"]) == (True, "juan PEREZ", "Almuerzo", False)
    with SesionLocal() as sesion:
        racion = sesion.get(RacionPolicia, datos["racion_id"])
    assert racion.lectura_id == lectura and racion.registrado_por_cuenta is not None

    # Reintento: lo mismo, sin otra ración.
    otra = _identificar(cliente, cocinera, lectura, huella_policia["id"], clave).json()
    assert otra["reintento"] is True and otra["racion_id"] == datos["racion_id"]
    assert _conteo(RacionPolicia) == 1

    # La lectura ya no está pendiente y sale UNA vez, entregada a ese policía.
    pendientes = cliente.get("/pantalla/lecturas-por-identificar", headers=cocinera).json()
    assert all(f["id"] != lectura for f in pendientes["lecturas"])
    filas = cliente.get(f"/pantalla/ultimas-marcaciones?fecha={FECHA}&limite=50", headers=jefa).json()
    assert not any(f["origen"] == "racion_policia" for f in filas)
    fila = next(f for f in filas if f["origen"] == "lectura_biometrica" and f["id"] == lectura)
    assert (fila["valido"], fila["estado_final"]) == (False, "racion_servida")
    assert fila["resultado_final"]["via"] == "identificacion_policia"
    assert fila["resultado_final"]["comensal"]["nombre"] == "juan PEREZ"
    assert fila["intervencion"]["registrada_por"]["usuario"] == "p_cocinera"

    # Cuenta en Policías de la comida.
    dia = cliente.get(f"/pantalla/comidas-del-dia?fecha={FECHA}", headers=jefa).json()
    assert {c["comida"]: c["policias"] for c in dia["comidas"]}["Almuerzo"] == 1


def test_una_lectura_no_se_resuelve_dos_veces(cliente, cocinera, huella_policia):
    lectura = _no_reconocida(cliente)
    assert _identificar(cliente, cocinera, lectura, huella_policia["id"]).status_code == 200
    r = _identificar(cliente, cocinera, lectura, huella_policia["id"])
    assert r.status_code == 409 and r.json()["motivo"] == "lectura_ya_resuelta"
    # Tampoco como personal (con una persona real del padrón).
    from app.modelos.heredados import Comensal
    with SesionLocal() as sesion:
        persona = sesion.execute(select(Comensal.usuario_id).limit(1)).scalar_one()
    r = cliente.post(f"/asistencias/lecturas/{lectura}/identificar", json={"usuario_id": persona},
                     headers={**cocinera, "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 409 and r.json()["motivo"] == "lectura_ya_resuelta"


def test_misma_clave_con_otro_contenido_409(cliente, cocinera, huella_policia):
    clave = str(uuid.uuid4())
    primera = _no_reconocida(cliente)
    segunda = _no_reconocida(cliente)
    assert _identificar(cliente, cocinera, primera, huella_policia["id"], clave).status_code == 200
    r = _identificar(cliente, cocinera, segunda, huella_policia["id"], clave)
    assert r.status_code == 409 and r.json()["motivo"] == "clave_reutilizada_con_otro_contenido"


def test_solo_la_cocinera_identifica(cliente, jefa, huella_policia):
    lectura = _no_reconocida(cliente)
    r = _identificar(cliente, jefa, lectura, huella_policia["id"])
    assert r.status_code == 403
    assert _conteo(RacionPolicia) == 0


def test_otro_servicio_o_policia_inexistente_no_entregan(cliente, cocinera, huella_policia):
    lectura = _no_reconocida(cliente)
    r = _identificar(cliente, cocinera, lectura, 999_999)
    assert r.status_code == 404 and r.json()["motivo"] == "policia_inexistente"
    reloj_prueba.fijar(datetime(2026, 9, 24, 19, 0))  # ya es la cena: la lectura era del almuerzo
    r = _identificar(cliente, cocinera, lectura, huella_policia["id"])
    assert r.status_code == 409
    assert _conteo(RacionPolicia) == 0


def test_una_lectura_fuera_de_horario_no_se_identifica(cliente, cocinera, huella_policia):
    reloj_prueba.fijar(datetime(2026, 9, 24, 3, 0))
    datos = _leer(cliente, identificador=None).json()
    assert datos["motivo"] == "fuera_horario"
    reloj_prueba.fijar(DIA)
    r = _identificar(cliente, cocinera, datos["lectura_id"], huella_policia["id"])
    assert r.status_code == 409 and r.json()["motivo"] == "lectura_no_resoluble"
    assert _conteo(RacionPolicia) == 0
