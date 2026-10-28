"""B1: GET /pantalla/ultimas-marcaciones con identidad inequívoca por fila.

Contrato compartido con el front:

  · Ruta, parámetros, permisos, lista y campos previos sin cambios.
  · Cada fila agrega `origen` ("lectura_biometrica" | "asistencia_manual"),
    que sale de la rama del UNION, y `clave_evento` = "<origen>:<id>".
  · `id` conserva su valor y NO es global: lectura_biometrica:7 y
    asistencia_manual:7 son filas distintas.
  · Una asistencia ligada a una lectura aparece solo como lectura_biometrica.
  · Orden: fecha_hora e id descendentes y `origen` como último desempate.
  · Ventana de hasta 100 filas, no un cursor.

Las lecturas biométricas las registra el lector de prueba (tests/lector_prueba.py);
las manuales, la jefatura por la API con el reloj del servidor. La colisión de id entre tablas
no se puede provocar por la API sin depender de AUTO_INCREMENT, así que se
prueba aparte, sobre la composición de la consulta con filas sintéticas
(SELECT de literales, sin escribir nada).
"""

import re
from datetime import datetime, timedelta

import pytest
from sqlalchemy import DateTime, cast, literal, select, text

from app.consultas import pantalla
from app.core.db import SesionLocal
from app.semillas import horarios
import reloj_prueba
from conftest import encabezado, ingresar
from lector_prueba import DISPOSITIVO
from soporte_derecho import candidato_almuerzo

RUTA = "/pantalla/ultimas-marcaciones"
ROLES = ("jefa", "cocinera", "sistemas")
DIA = datetime(2026, 9, 24, 12, 30)  # dentro del almuerzo de la semilla
USUARIO_INEXISTENTE = 999_999_999  # da sin_derecho sin depender del padrón
CAMPOS_PREVIOS = {
    "id", "fecha_hora", "usuario_id", "nombre", "categoria", "comida_id",
    "comida", "resultado", "motivo", "valido", "dispositivo",
}
CAMPOS_INTERVENCIONES = {
    "comida_origen", "decision_original", "estado_final", "resultado_final",
    "puede_identificar", "motivo_no_identificable", "identificable_hasta",
    "intervencion",
}
CAMPOS = CAMPOS_PREVIOS | {"origen", "clave_evento", "metodo"} | CAMPOS_INTERVENCIONES
ORIGENES = {"lectura_biometrica", "asistencia_manual", "racion_policia"}
FORMA_CLAVE = re.compile(r"(lectura_biometrica|asistencia_manual):[1-9]\d*")


# --- fixtures -----------------------------------------------------------------


@pytest.fixture(autouse=True)
def reloj_real():
    reloj_prueba.liberar()
    yield
    reloj_prueba.liberar()


@pytest.fixture
def tokens(cliente, crear_usuario) -> dict[str, dict[str, str]]:
    for rol in ROLES:
        crear_usuario(f"u_{rol}", rol=rol)
    return {rol: encabezado(ingresar(cliente, f"u_{rol}")["access"]) for rol in ROLES}


def _vaciar() -> None:
    with SesionLocal() as sesion:
        sesion.execute(text("DELETE FROM asistencias"))
        sesion.execute(text("DELETE FROM lecturas_biometricas"))
        sesion.execute(text("DELETE FROM horarios_comida"))
        sesion.commit()


@pytest.fixture
def con_horarios():
    """Horarios de la semilla y tablas de marcación vacías antes y después:
    cada fila de la lista es de la prueba en curso."""
    _vaciar()
    horarios.sembrar()
    yield
    _vaciar()


def _biometrico(lector, momento: datetime, **cuerpo) -> dict:
    """Lectura biométrica del lector de prueba, con el reloj en `momento`."""
    reloj_prueba.fijar(momento)
    return lector.leer(**cuerpo)


def _manual(cliente, headers, usuario_id: int, momento: datetime) -> dict:
    """Registro manual con el contrato B1: sin momento ni dispositivo; la hora
    la pone el reloj del servidor."""
    reloj_prueba.fijar(momento)
    r = cliente.post(
        "/asistencias", json={"usuario_id": usuario_id, "metodo": "manual"}, headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()


def _lista(cliente, headers, **params) -> list[dict]:
    r = cliente.get(RUTA, params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _claves(filas: list[dict]) -> list[str]:
    return [f["clave_evento"] for f in filas]


# --- forma, permisos y tabla vacía ----------------------------------------------


@pytest.mark.usefixtures("con_horarios")
@pytest.mark.parametrize("rol", ROLES)
def test_tabla_vacia_para_los_tres_roles(cliente, tokens, rol):
    assert _lista(cliente, tokens[rol], fecha=DIA.date().isoformat()) == []


def test_sin_token_401(cliente):
    r = cliente.get(RUTA)
    assert r.status_code == 401
    assert r.json()["motivo"] == "falta_token"


@pytest.mark.parametrize("limite", [0, 1001, -1])
def test_limite_fuera_de_rango_422(cliente, tokens, limite):
    r = cliente.get(RUTA, params={"limite": limite}, headers=tokens["jefa"])
    assert r.status_code == 422


# --- origen y clave por la API ----------------------------------------------------


@pytest.mark.usefixtures("con_horarios")
def test_manual_sale_como_asistencia_manual(cliente, tokens):
    usuario_id, fecha = candidato_almuerzo()
    momento = datetime.combine(fecha, DIA.time())
    marcada = _manual(cliente, tokens["jefa"], usuario_id, momento)
    assert marcada["valido"] is True, marcada

    filas = _lista(cliente, tokens["cocinera"], fecha=fecha.isoformat())
    assert len(filas) == 1
    fila = filas[0]
    assert set(fila) == CAMPOS
    # Los campos previos conservan su significado.
    assert fila["id"] == marcada["asistencia_id"]
    assert fila["usuario_id"] == usuario_id
    assert fila["comida_id"] == marcada["comida_id"]
    assert (fila["resultado"], fila["motivo"], fila["valido"]) == ("aceptada", None, True)
    assert fila["dispositivo"] == "registro-manual"
    assert datetime.fromisoformat(fila["fecha_hora"]) == momento
    # Los nuevos.
    assert fila["origen"] == "asistencia_manual"
    assert fila["clave_evento"] == f"asistencia_manual:{marcada['asistencia_id']}"


@pytest.mark.usefixtures("con_horarios")
def test_biometrico_aceptado_aparece_una_sola_vez(cliente, lector, tokens):
    """La asistencia ligada a la lectura no entra por la rama manual."""
    usuario_id, fecha = candidato_almuerzo()
    marcada = _biometrico(lector, datetime.combine(fecha, DIA.time()), usuario_id=usuario_id)
    assert marcada["valido"] is True, marcada
    assert marcada["lectura_id"] and marcada["asistencia_id"]

    filas = _lista(cliente, tokens["jefa"], fecha=fecha.isoformat())
    assert len(filas) == 1
    fila = filas[0]
    assert set(fila) == CAMPOS
    assert fila["id"] == marcada["lectura_id"]
    assert fila["origen"] == "lectura_biometrica"
    assert fila["clave_evento"] == f"lectura_biometrica:{marcada['lectura_id']}"
    assert (fila["resultado"], fila["valido"]) == ("aceptada", True)
    assert f"asistencia_manual:{marcada['asistencia_id']}" not in _claves(filas)


@pytest.mark.usefixtures("con_horarios")
def test_claves_unicas_estables_y_en_orden(cliente, lector, tokens):
    """Lecturas y una manual en el mismo día: cada clave es única, coincide
    con origen e id, y no cambia entre consultas sucesivas."""
    coci, jefa = tokens["cocinera"], tokens["jefa"]
    usuario_id, fecha = candidato_almuerzo()
    base = datetime.combine(fecha, DIA.time())

    no_identificada = _biometrico(lector, base)
    sin_derecho = _biometrico(lector, base + timedelta(minutes=1), usuario_id=USUARIO_INEXISTENTE)
    manual = _manual(cliente, jefa, usuario_id, base + timedelta(minutes=2))
    duplicada = _biometrico(lector, base + timedelta(minutes=3), usuario_id=usuario_id)
    assert no_identificada["motivo"] == "no_identificado"
    assert sin_derecho["motivo"] == "sin_derecho"
    assert manual["valido"] is True, manual
    assert duplicada["motivo"] == "duplicado"

    esperadas = [  # fecha_hora descendente
        f"lectura_biometrica:{duplicada['lectura_id']}",
        f"asistencia_manual:{manual['asistencia_id']}",
        f"lectura_biometrica:{sin_derecho['lectura_id']}",
        f"lectura_biometrica:{no_identificada['lectura_id']}",
    ]
    primera = _lista(cliente, jefa, fecha=fecha.isoformat())
    segunda = _lista(cliente, coci, fecha=fecha.isoformat())
    tercera = _lista(cliente, jefa, fecha=fecha.isoformat(), limite=1000)
    assert _claves(primera) == _claves(segunda) == _claves(tercera) == esperadas
    for fila in primera:
        assert set(fila) == CAMPOS
        assert fila["origen"] in ORIGENES
        assert fila["clave_evento"] == f"{fila['origen']}:{fila['id']}"
        assert FORMA_CLAVE.fullmatch(fila["clave_evento"])
    # Las lecturas dicen su dispositivo; el origen no sale de ahí.
    assert {f["dispositivo"] for f in primera if f["origen"] == "lectura_biometrica"} == {
        DISPOSITIVO
    }


@pytest.mark.usefixtures("con_horarios")
def test_filtros_por_fecha_comida_y_limite(cliente, lector, tokens):
    jefa = tokens["jefa"]
    hoy = [_biometrico(lector, DIA + timedelta(minutes=m)) for m in range(3)]
    ayer = _biometrico(lector, DIA - timedelta(days=1))
    almuerzo = hoy[0]["comida_id"]
    assert almuerzo is not None

    del_dia = _lista(cliente, jefa, fecha=DIA.date().isoformat())
    assert _claves(del_dia) == [f"lectura_biometrica:{m['lectura_id']}" for m in reversed(hoy)]
    assert _claves(_lista(cliente, jefa, fecha=(DIA.date() - timedelta(days=1)).isoformat())) == [
        f"lectura_biometrica:{ayer['lectura_id']}"
    ]
    assert _claves(
        _lista(cliente, jefa, fecha=DIA.date().isoformat(), comida_id=almuerzo)
    ) == _claves(del_dia)
    assert _lista(cliente, jefa, fecha=DIA.date().isoformat(), comida_id=almuerzo + 100_000) == []
    # El límite corta la ventana después de ordenar: quedan las más recientes.
    assert _claves(_lista(cliente, jefa, fecha=DIA.date().isoformat(), limite=2)) == _claves(
        del_dia
    )[:2]
    # Sin fecha, el día del reloj del servidor.
    reloj_prueba.fijar(DIA)
    assert _claves(_lista(cliente, jefa)) == _claves(del_dia)


@pytest.mark.usefixtures("con_horarios")
def test_sin_datos_personales_nuevos(cliente, lector, tokens):
    """Los dos campos nuevos no traen nada de la persona: solo origen e id."""
    _biometrico(lector, DIA, usuario_id=USUARIO_INEXISTENTE)
    for rol in ROLES:
        for fila in _lista(cliente, tokens[rol], fecha=DIA.date().isoformat()):
            assert set(fila) == CAMPOS
            assert "carnet_identidad" not in fila
            assert FORMA_CLAVE.fullmatch(fila["clave_evento"])
            assert str(USUARIO_INEXISTENTE) not in fila["clave_evento"]


# --- composición aislada: colisión de id y desempate ------------------------------


def _rama(id_: int, fecha_hora: datetime, dispositivo: str):
    """Una fila sintética con las columnas de una rama del UNION."""
    return select(
        literal(id_).label("id"),
        literal(None).label("usuario_id"),
        cast(literal(fecha_hora.isoformat(sep=" ")), DateTime).label("fecha_hora"),
        literal(None).label("nombre"),
        literal(None).label("categoria"),
        literal(None).label("comida_id"),
        literal(None).label("comida"),
        literal("aceptada").label("resultado"),
        literal(None).label("motivo"),
        literal(True).label("valido"),
        literal(dispositivo).label("dispositivo"),
    )


def _componer(lectura, manual, limite: int = 100) -> list[pantalla.Marcacion]:
    with SesionLocal() as sesion:
        return pantalla._componer_ventana(sesion, lectura, manual, limite)


def test_mismo_id_en_ambas_tablas_da_claves_distintas():
    # Los dispositivos están cruzados a propósito: el origen sale de la rama.
    filas = _componer(
        _rama(7, DIA, "registro-manual"), _rama(7, DIA, "lector-comedor-01")
    )
    assert [(f.id, f.origen, f.clave_evento) for f in filas] == [
        (7, "asistencia_manual", "asistencia_manual:7"),
        (7, "lectura_biometrica", "lectura_biometrica:7"),
    ]


def test_empate_de_fecha_e_id_tiene_orden_determinista():
    lectura, manual = _rama(7, DIA, "x"), _rama(7, DIA, "x")
    ordenes = {tuple(f.clave_evento for f in _componer(lectura, manual)) for _ in range(5)}
    assert ordenes == {("asistencia_manual:7", "lectura_biometrica:7")}
    # El límite corta después del desempate.
    assert [f.clave_evento for f in _componer(lectura, manual, limite=1)] == [
        "asistencia_manual:7"
    ]


def test_fecha_e_id_ordenan_antes_que_el_origen():
    despues = DIA + timedelta(seconds=1)
    filas = _componer(_rama(7, despues, "x"), _rama(9, DIA, "x"))
    assert [f.clave_evento for f in filas] == ["lectura_biometrica:7", "asistencia_manual:9"]
    filas = _componer(_rama(7, DIA, "x"), _rama(9, DIA, "x"))
    assert [f.clave_evento for f in filas] == ["asistencia_manual:9", "lectura_biometrica:7"]


def test_clave_evento_es_origen_e_id():
    assert pantalla.clave_evento(pantalla.ORIGEN_LECTURA, 7) == "lectura_biometrica:7"
    assert pantalla.clave_evento(pantalla.ORIGEN_MANUAL, 7) == "asistencia_manual:7"
