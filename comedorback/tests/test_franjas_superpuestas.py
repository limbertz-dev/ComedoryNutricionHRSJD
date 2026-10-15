"""B1: una fila por lectura aunque varios horarios puedan cubrir su hora.

`_franja_vigente` encuentra los horarios CANDIDATOS de una lectura: los que
regían en el instante exacto de su `fecha_hora` y cuya franja cubre su hora.
Por API y por semilla ya no se pueden crear versiones que se pisen entre
comidas (el guardado lo rechaza y la semilla se omite), pero la consulta se
sigue defendiendo de datos heredados con la misma regla de siempre. La lista y
Supervisión resuelven igual (`_comida_por_lectura`):

  · con asistencia: la comida persistida, sin importar los horarios de hoy;
  · sin asistencia: la comida de los candidatos de mayor vigente_desde; si
    ahí empatan comidas distintas, comida null (la consulta no elige una);
  · sin candidatos: la lectura sigue, sin comida.

Los horarios se preparan por POST /reglas/horarios y con la semilla, dentro de
fixtures y sobre la base de tests. Las lecturas, con el lector de prueba.
Lo heredado que no se puede preparar por API se prueba sobre la subconsulta con
filas sintéticas (SELECT de literales), sin escribir nada.
"""

from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import Time, cast, literal, null, select, text, union_all

from app.consultas import pantalla
from app.core.db import SesionLocal
from app.modelos.comedor import INSTANTE
from app.semillas import horarios
import reloj_prueba
from conftest import encabezado, ingresar
from soporte_horarios import (  # noqa: F401  fixtures y ayudas compartidas
    DIA,
    a_las,
    abierta,
    comida_id,
    fijar,
    guardar,
    reloj_libre,
    vacio,
)
from soporte_derecho import candidato_almuerzo

RUTA = "/pantalla/ultimas-marcaciones"
SUPERVISION = "/pantalla/comidas-del-dia"
ROLES = ("jefa", "cocinera", "sistemas")


# --- fixtures -----------------------------------------------------------------


@pytest.fixture
def tokens(cliente, crear_usuario) -> dict[str, dict[str, str]]:
    for rol in ROLES:
        crear_usuario(f"u_{rol}", rol=rol)
    return {rol: encabezado(ingresar(cliente, f"u_{rol}")["access"]) for rol in ROLES}


def _configurar(cliente, tokens, *versiones: tuple[str, str, str, datetime]) -> None:
    """Deja `horarios_comida` como queda en la secuencia «API y después
    semilla»: cada versión por POST /reglas/horarios, con el reloj congelado en
    su instante (la API guarda desde ahí), y luego la semilla, que solo
    completa lo que no pise."""
    for codigo, inicio, fin, instante in versiones:
        comida = comida_id(codigo)
        actual = abierta(cliente, tokens["sistemas"], comida)
        fijar(instante)
        r = guardar(
            cliente,
            tokens["sistemas"],
            comida,
            inicio,
            fin,
            actual["horario_id"] if actual else None,
        )
        assert r.status_code == 201, r.text
    horarios.sembrar()


def _filas_por_comida(codigo: str) -> int:
    with SesionLocal() as sesion:
        return sesion.execute(
            text("SELECT COUNT(*) FROM horarios_comida WHERE comida_id = :c"),
            {"c": comida_id(codigo)},
        ).scalar_one()


def _marcar(lector, momento: datetime, **cuerpo) -> dict:
    reloj_prueba.fijar(momento)
    return lector.leer(**cuerpo)


def _lista(cliente, tokens, dia: date, **params) -> list[dict]:
    r = cliente.get(
        RUTA, params={"fecha": dia.isoformat(), **params}, headers=tokens["jefa"]
    )
    assert r.status_code == 200, r.text
    return r.json()


def _por_lectura(filas: list[dict]) -> dict[int, dict]:
    """Falla si una lectura aparece más de una vez."""
    claves = [f["clave_evento"] for f in filas]
    assert len(claves) == len(set(claves)), claves
    return {f["id"]: f for f in filas if f["origen"] == "lectura_biometrica"}


def _supervision(cliente, tokens, dia: date) -> dict:
    r = cliente.get(SUPERVISION, params={"fecha": dia.isoformat()}, headers=tokens["jefa"])
    assert r.status_code == 200, r.text
    return r.json()


def _rechazos(cuerpo: dict) -> dict[int, int]:
    return {f["comida_id"]: sum(f["rechazos_por_motivo"].values()) for f in cuerpo["comidas"]}


# --- API y después semilla ------------------------------------------------------


def test_la_semilla_no_pisa_ni_solapa_lo_configurado(cliente, tokens, vacio):
    """Té 14-16 por la API; después la semilla. El té ya tiene configuración y
    no se toca; el almuerzo 11-15 se OMITE porque pisa al té; el desayuno y la
    cena entran."""
    _configurar(cliente, tokens, ("te", "14:00:00", "16:00:00", a_las(9)))
    assert _filas_por_comida("te") == 1
    assert _filas_por_comida("almuerzo") == 0
    assert _filas_por_comida("desayuno") == 1
    assert _filas_por_comida("cena") == 1
    te = abierta(cliente, tokens["sistemas"], comida_id("te"))
    assert (te["hora_inicio"], te["hora_fin"]) == ("14:00:00", "16:00:00")
    assert te["vigente_desde"] == a_las(9).isoformat()


def test_semilla_dos_veces_no_duplica(cliente, tokens, vacio):
    horarios.sembrar()
    antes = {c: _filas_por_comida(c) for c in ("desayuno", "almuerzo", "te", "cena")}
    assert set(antes.values()) == {1}
    horarios.sembrar()
    assert {c: _filas_por_comida(c) for c in antes} == antes


def test_la_semilla_respeta_lo_que_root_ya_cambio(cliente, tokens, vacio):
    """Una comida con CUALQUIER versión (aunque no sea la de 2026-01-01) no se
    siembra: la semilla no inserta sobre configuraciones existentes."""
    horarios.sembrar()
    almuerzo = comida_id("almuerzo")
    base = abierta(cliente, tokens["sistemas"], almuerzo)["horario_id"]
    fijar(a_las(9))
    assert guardar(cliente, tokens["sistemas"], almuerzo, "12:00:00", "13:00:00", base).status_code == 201
    horarios.sembrar()
    assert _filas_por_comida("almuerzo") == 2
    assert abierta(cliente, tokens["sistemas"], almuerzo)["hora_inicio"] == "12:00:00"


def test_una_fila_por_lectura_y_resolucion_por_horario(
    cliente, lector, tokens, vacio
):
    """Té 14-16 por la API y la semilla alrededor:

      12:30  sin candidatos (el almuerzo se omitió)  → sin comida
      14:30  té                                      → té
      15:30  té                                      → té
      10:30  sin candidatos (franja sin cubrir)      → sin comida
    """
    _configurar(cliente, tokens, ("te", "14:00:00", "16:00:00", a_las(9)))
    almuerzo, te = comida_id("almuerzo"), comida_id("te")
    esperado = {a_las(12, 30): None, a_las(14, 30): te, a_las(15, 30): te, a_las(10, 30): None}
    marcadas = {momento: _marcar(lector, momento) for momento in esperado}

    primera = _lista(cliente, tokens, DIA)
    filas = _por_lectura(primera)
    assert len(primera) == len(marcadas) == 4
    for momento, marcada in marcadas.items():
        fila = filas[marcada["lectura_id"]]
        assert fila["comida_id"] == esperado[momento], momento
        # El motivo es el guardado: sin horario a esa hora la lectura se guardó
        # como fuera_horario, no como no_identificado.
        guardado = "no_identificado" if esperado[momento] is not None else "fuera_horario"
        assert (fila["resultado"], fila["motivo"]) == ("rechazada", guardado)
    assert filas[marcadas[a_las(10, 30)]["lectura_id"]]["comida"] is None

    # Estables entre consultas.
    segunda = _lista(cliente, tokens, DIA)
    assert [f["clave_evento"] for f in segunda] == [f["clave_evento"] for f in primera]

    # Supervisión cuenta cada rechazo una sola vez, en la misma comida.
    cuerpo = _supervision(cliente, tokens, DIA)
    rechazos = _rechazos(cuerpo)
    assert almuerzo not in rechazos  # sin ventana ese día
    assert rechazos[te] == 2
    assert cuerpo["rechazos_sin_comida"] == 2
    assert sum(rechazos.values()) + cuerpo["rechazos_sin_comida"] == len(marcadas)


def test_filtros_y_limite_despues_de_resolver(cliente, lector, tokens, vacio):
    _configurar(cliente, tokens, ("te", "14:00:00", "16:00:00", a_las(9)))
    almuerzo, te = comida_id("almuerzo"), comida_id("te")
    horas = [time(12, 30), time(14, 30), time(14, 31), time(14, 32), time(15, 30)]
    ids = {
        hora: _marcar(lector, datetime.combine(DIA, hora))["lectura_id"]
        for hora in horas
    }

    def claves(*hs: time) -> list[str]:
        return [f"lectura_biometrica:{ids[h]}" for h in hs]

    def lista(**params) -> list[str]:
        filas = _lista(cliente, tokens, DIA, **params)
        _por_lectura(filas)
        return [f["clave_evento"] for f in filas]

    # El límite corta lecturas distintas, no filas duplicadas.
    assert lista(limite=2) == claves(time(15, 30), time(14, 32))
    assert lista(comida_id=te) == claves(time(15, 30), time(14, 32), time(14, 31), time(14, 30))
    assert lista(comida_id=te, limite=3) == claves(time(15, 30), time(14, 32), time(14, 31))
    # La de las 12:30 no resuelve a ninguna comida.
    assert lista(comida_id=almuerzo) == []
    assert _lista(cliente, tokens, DIA - timedelta(days=1)) == []


# --- lectura aceptada: manda la comida persistida ---------------------------------


def test_aceptada_conserva_la_comida_persistida(cliente, lector, tokens, vacio):
    usuario_id, fecha = candidato_almuerzo()
    if fecha <= horarios.VIGENTE_DESDE:
        pytest.skip("el almuerzo candidato es anterior a la semilla")
    almuerzo = comida_id("almuerzo")
    horarios.sembrar()
    aceptada = _marcar(
        lector, datetime.combine(fecha, time(12, 30)), usuario_id=usuario_id
    )
    assert aceptada["valido"] is True, aceptada
    assert aceptada["comida_id"] == almuerzo

    # A las 13:00 root acorta el almuerzo a 11:00-12:00: a las 13:10 ya no hay
    # franja, y la ración de las 12:30 sigue siendo de almuerzo.
    base = abierta(cliente, tokens["sistemas"], almuerzo)["horario_id"]
    fijar(datetime.combine(fecha, time(13, 0)))
    assert (
        guardar(cliente, tokens["sistemas"], almuerzo, "11:00:00", "12:00:00", base).status_code
        == 201
    )
    rechazo = _marcar(lector, datetime.combine(fecha, time(13, 10)))
    assert rechazo["motivo"] == "fuera_horario"

    filas = _por_lectura(_lista(cliente, tokens, fecha))
    fila = filas[aceptada["lectura_id"]]
    assert (fila["comida_id"], fila["valido"]) == (almuerzo, True)
    assert fila["comida"] == aceptada["comida"]
    assert filas[rechazo["lectura_id"]]["comida_id"] is None
    con_almuerzo = _por_lectura(_lista(cliente, tokens, fecha, comida_id=almuerzo))
    assert set(con_almuerzo) == {aceptada["lectura_id"]}

    cuerpo = _supervision(cliente, tokens, fecha)
    servidas = {f["comida_id"]: f["servidas"] for f in cuerpo["comidas"]}
    assert servidas.get(almuerzo) == 1
    assert cuerpo["rechazos_sin_comida"] == 1


# --- la subconsulta, con filas sintéticas (datos heredados) -----------------------------


def _subconsulta(filas):
    """Un fabricante de alias sobre filas literales: cada llamada arma una
    subconsulta nueva con el nombre pedido."""

    def fabricar(nombre: str):
        partes = [select(*columnas) for columnas in filas()]
        consulta = partes[0] if len(partes) == 1 else union_all(*partes)
        return consulta.subquery(nombre)

    return fabricar


def _lecturas(*filas: tuple[int, datetime]):
    return _subconsulta(
        lambda: [
            (
                literal(i).label("id"),
                cast(literal(f.isoformat(sep=" ")), INSTANTE).label("fecha_hora"),
            )
            for i, f in filas
        ]
    )


def _horarios(*filas: tuple[int, int, str, str, str, str | None, int]):
    """(id, comida_id, hora_inicio, hora_fin, vigente_desde, vigente_hasta, activo)."""
    return _subconsulta(
        lambda: [
            (
                literal(i).label("id"),
                literal(comida).label("comida_id"),
                cast(literal(ini), Time).label("hora_inicio"),
                cast(literal(fin), Time).label("hora_fin"),
                cast(literal(desde), INSTANTE).label("vigente_desde"),
                cast(literal(hasta) if hasta else null(), INSTANTE).label("vigente_hasta"),
                literal(activo).label("activo"),
            )
            for i, comida, ini, fin, desde, hasta, activo in filas
        ]
    )


def _resolver(lecturas, horarios_, dia: date = DIA) -> dict[int, int | None]:
    sub = pantalla._comida_por_lectura(dia, lecturas=lecturas, horarios=horarios_)
    with SesionLocal() as sesion:
        filas = sesion.execute(select(sub.c.lectura_id, sub.c.comida_id)).all()
    ids = [lectura_id for lectura_id, _ in filas]
    assert len(ids) == len(set(ids)), ids  # una fila por lectura
    return dict(filas)


A_LAS_1430 = datetime.combine(DIA, time(14, 30))


@pytest.mark.parametrize(
    "candidatos,esperado",
    [
        # Empate de comidas distintas en la vigencia máxima: null.
        ([(1, 10, "14:00", "16:00", "2026-09-01 00:00:00", None, 1),
          (2, 20, "13:00", "15:00", "2026-09-01 00:00:00", None, 1)], None),
        # Una vigencia más reciente decide.
        ([(1, 10, "14:00", "16:00", "2026-09-01 00:00:00", None, 1),
          (2, 20, "13:00", "15:00", "2026-09-10 00:00:00", None, 1)], 20),
        # Dos versiones de la misma comida: esa comida, una vez.
        ([(1, 10, "11:00", "15:00", "2026-01-01 00:00:00", None, 1),
          (2, 10, "14:00", "16:00", "2026-09-01 00:00:00", None, 1)], 10),
        # El empate de abajo no importa si arriba hay una sola comida.
        ([(1, 10, "14:00", "16:00", "2026-01-01 00:00:00", None, 1),
          (2, 20, "13:00", "15:00", "2026-01-01 00:00:00", None, 1),
          (3, 30, "14:00", "15:00", "2026-09-01 00:00:00", None, 1)], 30),
        # El empate de arriba manda aunque abajo haya una sola comida.
        ([(1, 10, "14:00", "16:00", "2026-01-01 00:00:00", None, 1),
          (2, 20, "13:00", "15:00", "2026-09-01 00:00:00", None, 1),
          (3, 30, "14:00", "15:00", "2026-09-01 00:00:00", None, 1)], None),
        # Una versión más nueva que NO cubre la hora no es candidata.
        ([(1, 10, "11:00", "15:00", "2026-01-01 00:00:00", None, 1),
          (2, 20, "16:00", "17:00", "2026-09-10 00:00:00", None, 1)], 10),
        # Inactiva o vencida: no son candidatas.
        ([(1, 10, "11:00", "15:00", "2026-01-01 00:00:00", None, 1),
          (2, 20, "14:00", "16:00", "2026-09-10 00:00:00", None, 0),
          (3, 30, "14:00", "16:00", "2026-09-01 00:00:00", "2026-09-20 00:00:00", 1)], 10),
        # Una versión que EMPIEZA después de la lectura (misma fecha, más tarde)
        # no es candidata: se resuelve por instante, no por día.
        ([(1, 10, "11:00", "15:00", "2026-01-01 00:00:00", None, 1),
          (2, 20, "14:00", "16:00", "2026-09-24 18:00:00", None, 1)], 10),
    ],
    ids=[
        "empate_nulo", "vigencia_mas_nueva", "misma_comida", "empate_viejo_irrelevante",
        "empate_nuevo_manda", "nueva_no_cubre", "inactiva_y_vencida", "empieza_despues_el_mismo_dia",
    ],
)
def test_resolucion_sintetica(candidatos, esperado):
    assert _resolver(_lecturas((1, A_LAS_1430)), _horarios(*candidatos)) == {1: esperado}


def test_sintetica_el_corte_es_exclusivo_en_hasta_e_inclusivo_en_desde():
    """Misma franja, dos comidas que se relevan a las 14:30: la lectura justo
    antes cae en la primera; en el instante y después, en la segunda."""
    horarios_ = _horarios(
        (1, 10, "11:00", "15:00", "2026-01-01 00:00:00", "2026-09-24 14:30:00", 1),
        (2, 20, "11:00", "15:00", "2026-09-24 14:30:00", None, 1),
    )
    lecturas = _lecturas(
        (1, A_LAS_1430 - timedelta(microseconds=1)),
        (2, A_LAS_1430),
        (3, A_LAS_1430 + timedelta(microseconds=1)),
    )
    assert _resolver(lecturas, horarios_) == {1: 10, 2: 20, 3: 20}


def test_sintetica_sin_candidatos_y_otro_dia_no_aparecen():
    horarios_ = _horarios((1, 10, "11:00", "15:00", "2026-01-01 00:00:00", None, 1))
    lecturas = _lecturas(
        (1, A_LAS_1430),
        (2, datetime.combine(DIA, time(10, 30))),  # sin candidatos
        (3, A_LAS_1430 - timedelta(days=1)),  # otro día
    )
    # La 2 no tiene fila: el LEFT JOIN de la consulta la deja sin comida.
    assert _resolver(lecturas, horarios_) == {1: 10}


def test_sintetica_cruce_de_medianoche():
    horarios_ = _horarios((1, 40, "22:00", "02:00", "2026-01-01 00:00:00", None, 1))
    lecturas = _lecturas(
        (1, datetime.combine(DIA, time(1, 0))),
        (2, datetime.combine(DIA, time(3, 0))),
    )
    assert _resolver(lecturas, horarios_) == {1: 40}
