"""El lector biométrico real: su clave, sus lecturas y los vínculos de huellas.

  · /lector/salud y /lector/lecturas entran con X-Lector-Token (LECTORES en
    .env), nunca con la sesión de una persona.
  · Una lectura pasa por la misma marcación de siempre, con la hora del
    servidor; un identificador sin vínculo activo es `no_identificado`.
  · La misma Idempotency-Key devuelve lo guardado sin escribir otra lectura.
  · Los vínculos los crea y da de baja la jefatura.
"""

import uuid
from datetime import datetime, time

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import func, select, text

from app.core.config import Configuracion, config
from app.core.db import SesionLocal
from app.modelos.comedor import Asistencia, LecturaBiometrica
from app.modelos.lector import SolicitudLector
from app.semillas import horarios
import reloj_prueba
from conftest import encabezado, ingresar
from soporte_derecho import candidato_almuerzo

CLAVE = "clave-de-prueba-del-lector-cocina-01"
OTRA = "clave-de-prueba-del-lector-cocina-02"
LECTOR = {"X-Lector-Token": CLAVE}


@pytest.fixture(autouse=True)
def lectores(monkeypatch):
    monkeypatch.setattr(config, "lectores", SecretStr(f"cocina-01={CLAVE};cocina-02={OTRA}"))


def _vaciar() -> None:
    with SesionLocal() as sesion:
        for tabla in ("solicitudes_lector", "vinculos_lector", "intervenciones_lectura",
                      "asistencias", "lecturas_biometricas", "horarios_comida"):
            sesion.execute(text(f"DELETE FROM {tabla}"))
        sesion.commit()


@pytest.fixture
def con_horarios():
    _vaciar()
    horarios.sembrar()
    yield
    _vaciar()


@pytest.fixture
def jefa(cliente, crear_usuario):
    crear_usuario("jefa_lector", rol="jefa")
    return encabezado(ingresar(cliente, "jefa_lector")["access"])


@pytest.fixture
def en_almuerzo():
    """(usuario con derecho al almuerzo, reloj fijo dentro del almuerzo)."""
    usuario, fecha = candidato_almuerzo()
    reloj_prueba.fijar(datetime.combine(fecha, time(12, 30)))
    return usuario


def _leer(cliente, identificador, clave=None, cabeceras=LECTOR):
    return cliente.post(
        "/lector/lecturas",
        json={"identificador": identificador},
        headers={**cabeceras, "Idempotency-Key": clave or str(uuid.uuid4())},
    )


def _conteos():
    with SesionLocal() as sesion:
        return tuple(
            sesion.execute(select(func.count()).select_from(t)).scalar_one()
            for t in (LecturaBiometrica, Asistencia, SolicitudLector)
        )


# --- la clave del lector ----------------------------------------------------------


def test_sin_clave_401_falta_token(cliente):
    for metodo, ruta in (("GET", "/lector/salud"), ("POST", "/lector/lecturas")):
        r = cliente.request(metodo, ruta, json={})
        assert r.status_code == 401, r.text
        assert r.json()["motivo"] == "falta_token"


def test_clave_desconocida_401_sin_escribir(cliente):
    antes = _conteos()
    r = _leer(cliente, "1", cabeceras={"X-Lector-Token": "x" * 40})
    assert r.status_code == 401
    assert r.json()["motivo"] == "lector_no_autorizado"
    assert _conteos() == antes


def test_el_token_de_una_persona_no_abre_el_lector(cliente, jefa):
    r = cliente.get("/lector/salud", headers=jefa)
    assert r.status_code == 401
    assert r.json()["motivo"] == "falta_token"


@pytest.mark.usefixtures("con_horarios")
def test_salud_dice_el_lector_y_la_comida(cliente, en_almuerzo):
    r = cliente.get("/lector/salud", headers={"X-Lector-Token": OTRA})
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["dispositivo"] == "cocina-02"
    assert datos["comida_en_curso"] == "Almuerzo"
    assert datos["vinculos_activos"] == 0


@pytest.mark.parametrize("valor", [
    "sin-igual", "Mayus=" + "x" * 40, "corta=abc", f"a={'x' * 40};a={'y' * 40}",
])
def test_lectores_mal_escritos_no_arrancan_ni_muestran_la_clave(valor):
    with pytest.raises(ValidationError) as error:
        Configuracion(lectores=valor)
    assert "x" * 40 not in str(error.value)


# --- lecturas -------------------------------------------------------------------------


@pytest.mark.usefixtures("con_horarios")
def test_lectura_vinculada_registra_la_racion_con_el_nombre_del_lector(cliente, jefa, en_almuerzo):
    assert cliente.post("/lector/vinculos", json={"identificador": "17", "usuario_id": en_almuerzo},
                        headers=jefa).status_code == 201
    r = _leer(cliente, "17")
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["valido"] is True, datos
    assert (datos["usuario_id"], datos["dispositivo"], datos["vinculado"], datos["reintento"]) == (
        en_almuerzo, "cocina-01", True, False)
    with SesionLocal() as sesion:
        lectura = sesion.get(LecturaBiometrica, datos["lectura_id"])
        asistencia = sesion.get(Asistencia, datos["asistencia_id"])
    assert lectura.dispositivo == "cocina-01"
    assert lectura.fecha_hora == datetime.combine(lectura.fecha_hora.date(), time(12, 30))
    assert (asistencia.metodo, asistencia.lectura_id) == ("biometrico", lectura.id)


@pytest.mark.usefixtures("con_horarios")
def test_segundo_toque_es_duplicado(cliente, jefa, en_almuerzo):
    cliente.post("/lector/vinculos", json={"identificador": "17", "usuario_id": en_almuerzo}, headers=jefa)
    assert _leer(cliente, "17").json()["valido"] is True
    segundo = _leer(cliente, "17").json()
    assert (segundo["valido"], segundo["motivo"]) == (False, "duplicado")


@pytest.mark.usefixtures("con_horarios")
@pytest.mark.parametrize("identificador", [None, "999"])
def test_sin_vinculo_queda_para_que_cocina_identifique(cliente, en_almuerzo, identificador):
    datos = _leer(cliente, identificador).json()
    assert (datos["valido"], datos["motivo"], datos["usuario_id"], datos["vinculado"]) == (
        False, "no_identificado", None, False)
    assert datos["lectura_id"] and datos["asistencia_id"] is None


@pytest.mark.usefixtures("con_horarios")
def test_reintento_con_la_misma_clave_no_escribe_otra_lectura(cliente, jefa, en_almuerzo):
    cliente.post("/lector/vinculos", json={"identificador": "17", "usuario_id": en_almuerzo}, headers=jefa)
    clave = str(uuid.uuid4())
    primera = _leer(cliente, "17", clave).json()
    antes = _conteos()
    segunda = _leer(cliente, "17", clave).json()
    assert _conteos() == antes
    assert segunda["reintento"] is True
    assert {k: v for k, v in segunda.items() if k != "reintento"} == {
        k: v for k, v in primera.items() if k != "reintento"}


@pytest.mark.usefixtures("con_horarios")
def test_misma_clave_con_otro_identificador_409(cliente, en_almuerzo):
    clave = str(uuid.uuid4())
    assert _leer(cliente, "1", clave).status_code == 200
    r = _leer(cliente, "2", clave)
    assert r.status_code == 409
    assert r.json()["motivo"] == "clave_reutilizada_con_otro_contenido"


@pytest.mark.usefixtures("con_horarios")
def test_misma_clave_desde_otro_lector_409(cliente, en_almuerzo):
    clave = str(uuid.uuid4())
    assert _leer(cliente, "1", clave).status_code == 200
    r = _leer(cliente, "1", clave, cabeceras={"X-Lector-Token": OTRA})
    assert r.status_code == 409


@pytest.mark.parametrize("clave", [None, "", "no-es-uuid", "00000000-0000-1000-8000-000000000000"])
def test_clave_de_idempotencia_obligatoria_y_v4(cliente, clave):
    antes = _conteos()
    cabeceras = dict(LECTOR) if clave is None else {**LECTOR, "Idempotency-Key": clave}
    r = cliente.post("/lector/lecturas", json={"identificador": "1"}, headers=cabeceras)
    assert r.status_code == 422
    assert _conteos() == antes


@pytest.mark.parametrize("identificador", ["", "con espacio", "x" * 65, "1;DROP"])
def test_identificador_invalido_422(cliente, identificador):
    assert _leer(cliente, identificador).status_code == 422


def test_el_puente_no_puede_fijar_la_hora(cliente):
    """`momento` no es parte del contrato: se ignora y manda el reloj del servidor."""
    from app.esquemas.lector import SolicitudLectura
    assert set(SolicitudLectura.model_fields) == {"identificador"}


# --- vínculos (jefatura) --------------------------------------------------------------


@pytest.mark.usefixtures("con_horarios")
def test_vinculos_alta_lista_conflicto_y_baja(cliente, jefa, en_almuerzo):
    alta = cliente.post("/lector/vinculos", json={"identificador": "17", "usuario_id": en_almuerzo},
                        headers=jefa)
    assert alta.status_code == 201, alta.text
    vinculo = alta.json()
    assert vinculo["activo"] is True and vinculo["nombre"]

    repetido = cliente.post("/lector/vinculos", json={"identificador": "17", "usuario_id": en_almuerzo},
                            headers=jefa)
    assert repetido.status_code == 409
    assert repetido.json()["motivo"] == "identificador_en_uso"

    assert [v["identificador"] for v in cliente.get("/lector/vinculos", headers=jefa).json()] == ["17"]

    baja = cliente.delete(f"/lector/vinculos/{vinculo['id']}", headers=jefa)
    assert baja.status_code == 200 and baja.json()["activo"] is False
    assert cliente.get("/lector/vinculos", headers=jefa).json() == []
    assert len(cliente.get("/lector/vinculos?activos=false", headers=jefa).json()) == 1

    # Dado de baja, el identificador ya no reconoce a la persona...
    assert _leer(cliente, "17").json()["motivo"] == "no_identificado"
    # ...y se puede volver a vincular.
    assert cliente.post("/lector/vinculos", json={"identificador": "17", "usuario_id": en_almuerzo},
                        headers=jefa).status_code == 201


def test_vincular_a_alguien_fuera_del_padron_422(cliente, jefa):
    r = cliente.post("/lector/vinculos", json={"identificador": "5", "usuario_id": 999_999_999}, headers=jefa)
    assert r.status_code == 422


def test_baja_de_vinculo_inexistente_404(cliente, jefa):
    assert cliente.delete("/lector/vinculos/999999", headers=jefa).status_code == 404


# --- plantillas (lectores USB ZKTeco) -------------------------------------------------

PLANTILLA = "U1MyMQAAA" + "A" * 40 + "=="


@pytest.mark.usefixtures("con_horarios")
def test_plantillas_solo_para_el_lector_y_nunca_en_vinculos(cliente, jefa, en_almuerzo):
    alta = cliente.post("/lector/vinculos", headers=jefa, json={
        "identificador": "zk-1", "usuario_id": en_almuerzo, "plantilla": PLANTILLA})
    assert alta.status_code == 201, alta.text
    assert "plantilla" not in alta.json()
    assert all("plantilla" not in v for v in cliente.get("/lector/vinculos", headers=jefa).json())

    r = cliente.get("/lector/plantillas", headers=LECTOR)
    assert r.status_code == 200
    assert r.json() == [{"id": alta.json()["id"], "identificador": "zk-1", "plantilla": PLANTILLA}]
    assert cliente.get("/lector/plantillas", headers=jefa).status_code == 401

    cliente.delete(f"/lector/vinculos/{alta.json()['id']}", headers=jefa)
    assert cliente.get("/lector/plantillas", headers=LECTOR).json() == []


@pytest.mark.parametrize("plantilla", ["no es base64!", "A" * 9000])
def test_plantilla_invalida_422(cliente, jefa, plantilla):
    r = cliente.post("/lector/vinculos", headers=jefa,
                     json={"identificador": "zk-2", "usuario_id": 1, "plantilla": plantilla})
    assert r.status_code == 422
