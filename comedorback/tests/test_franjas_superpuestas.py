"""B1: una fila por lectura aunque varios horarios cubran su hora.

`_franja_vigente` puede encontrar más de un horario candidato para una
lectura. Pasa, por ejemplo, si se configuran horarios por la API y DESPUÉS se
corre la semilla, que solo mira (comida, 2026-01-01). La lista y Supervisión
resuelven igual (`_comida_por_lectura`):

  · con asistencia: la comida persistida, sin importar los horarios de hoy;
  · sin asistencia: la comida de los candidatos de mayor vigente_desde; si
    ahí empatan comidas distintas, comida null (la consulta no elige una);
  · sin candidatos: la lectura sigue, sin comida.

Los horarios se preparan por POST /reglas/horarios y con la semilla, dentro
de fixtures y sobre la base de tests. Las marcaciones, por la API de
simulación. Lo que no se puede preparar por API de forma determinista se
prueba sobre la subconsulta con filas sintéticas (SELECT de literales).
"""

from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import Date, DateTime, Time, cast, literal, null, select, text, union_all

from app.consultas import pantalla
from app.core import reloj
from app.core.db import SesionLocal
from app.modelos.heredados import Comida
from app.semillas import horarios
from conftest import encabezado, ingresar
from test_simulacion import _candidato_almuerzo

RUTA = "/pantalla/ultimas-marcaciones"
SUPERVISION = "/pantalla/comidas-del-dia"
ROLES = ("jefa", "cocinera", "sistemas")
DIA = date(2026, 9, 24)
SEMILLA = horarios.VIGENTE_DESDE  # 2026-01-01
MOTIVO = "Prueba de franjas superpuestas B1"


# --- fixtures -----------------------------------------------------------------


@pytest.fixture(autouse=True)
def reloj_real():
    reloj.volver_a_real()
    yield
    reloj.volver_a_real()


@pytest.fixture
def tokens(cliente, crear_usuario) -> dict[str, dict[str, str]]:
    for rol in ROLES:
        crear_usuario(f"u_{rol}", rol=rol)
    return {rol: encabezado(ingresar(cliente, f"u_{rol}")["access"]) for rol in ROLES}


def _vaciar(*tablas: str) -> None:
    with SesionLocal() as sesion:
        for tabla in tablas:
            sesion.execute(text(f"DELETE FROM {tabla}"))
        sesion.commit()


@pytest.fixture
def limpio():
    todo = ("asistencias", "lecturas_biometricas", "horarios_comida")
    _vaciar(*todo)
    yield
    _vaciar(*todo)


@pytest.fixture
def configurar(cliente, tokens, limpio):
    """Deja horarios_comida como queda en la secuencia «API y después
    semilla»: borra los horarios, crea cada versión por POST /reglas/horarios
    (con el reloj en su vigencia, que la API exige hoy o futura) y siembra.
    """

    def _configurar(*versiones: tuple[str, time, time, date]) -> None:
        _vaciar("horarios_comida")
        for codigo, inicio, fin, desde in versiones:
            reloj.fijar(datetime.combine(desde, time(0, 1)), congelar=True)
            r = cliente.post(
                "/reglas/horarios",
                json={
                    "comida_id": _comida_id(codigo),
                    "hora_inicio": inicio.isoformat(),
                    "hora_fin": fin.isoformat(),
                    "vigente_desde": desde.isoformat(),
                    "motivo": MOTIVO,
                },
                headers=tokens["sistemas"],
            )
            assert r.status_code == 201, r.text
        horarios.sembrar()

    return _configurar


def _comida_id(codigo: str) -> int:
    with SesionLocal() as sesion:
        comida_id = sesion.execute(
            select(Comida.id).where(Comida.codigo == codigo)
        ).scalar_one_or_none()
    if comida_id is None:
        pytest.skip(f"v_comidas no tiene la comida '{codigo}'")
    return comida_id


def _marcar(sim, tokens, momento: datetime, **cuerpo) -> dict:
    reloj.fijar(momento, congelar=True)
    r = sim.post(
        "/asistencias", json={"metodo": "biometrico", **cuerpo}, headers=tokens["cocinera"]
    )
    assert r.status_code == 200, r.text
    return r.json()


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


def test_api_y_despues_semilla_una_fila_por_lectura(
    cliente, cliente_simulacion, tokens, configurar
):
    """Té 14–16 por la API desde DIA, después la semilla (almuerzo 11–15 y
    té 15–17 desde 2026-01-01):

      12:30  solo almuerzo                         → almuerzo
      14:30  almuerzo (semilla) y té (API, nuevo)  → té
      15:30  té (semilla) y té (API): misma comida → té
      10:30  sin candidatos                        → sin comida
    """
    configurar(("te", time(14), time(16), DIA))
    almuerzo, te = _comida_id("almuerzo"), _comida_id("te")
    esperado = {time(12, 30): almuerzo, time(14, 30): te, time(15, 30): te, time(10, 30): None}
    marcadas = {
        hora: _marcar(cliente_simulacion, tokens, datetime.combine(DIA, hora))
        for hora in esperado
    }

    primera = _lista(cliente, tokens, DIA)
    filas = _por_lectura(primera)
    assert len(primera) == len(marcadas) == 4
    for hora, marcada in marcadas.items():
        fila = filas[marcada["lectura_id"]]
        assert fila["comida_id"] == esperado[hora], hora
        # Candidato inequívoco y horarios sin cambios: coincide con el POST.
        assert fila["comida_id"] == marcada["comida_id"], hora
        assert (fila["resultado"], fila["motivo"]) == ("rechazada", "no_identificado")
    sin_comida = filas[marcadas[time(10, 30)]["lectura_id"]]
    assert sin_comida["comida"] is None

    # Estables entre consultas.
    segunda = _lista(cliente, tokens, DIA)
    assert [f["clave_evento"] for f in segunda] == [f["clave_evento"] for f in primera]

    # Supervisión cuenta cada rechazo una sola vez, en la misma comida.
    cuerpo = _supervision(cliente, tokens, DIA)
    rechazos = _rechazos(cuerpo)
    assert rechazos[almuerzo] == 1
    assert rechazos[te] == 2
    assert cuerpo["rechazos_sin_comida"] == 1
    assert sum(rechazos.values()) + cuerpo["rechazos_sin_comida"] == len(marcadas)


def test_filtros_y_limite_despues_de_resolver(cliente, cliente_simulacion, tokens, configurar):
    configurar(("te", time(14), time(16), DIA))
    almuerzo, te = _comida_id("almuerzo"), _comida_id("te")
    horas = [time(12, 30), time(14, 30), time(14, 31), time(14, 32), time(15, 30)]
    ids = {
        hora: _marcar(cliente_simulacion, tokens, datetime.combine(DIA, hora))["lectura_id"]
        for hora in horas
    }

    def claves(*hs: time) -> list[str]:
        return [f"lectura_biometrica:{ids[h]}" for h in hs]

    def lista(**params) -> list[str]:
        filas = _lista(cliente, tokens, DIA, **params)
        _por_lectura(filas)
        return [f["clave_evento"] for f in filas]

    # El límite corta lecturas distintas: antes una lectura duplicada ocupaba dos lugares.
    assert lista(limite=2) == claves(time(15, 30), time(14, 32))
    assert lista(comida_id=te) == claves(time(15, 30), time(14, 32), time(14, 31), time(14, 30))
    assert lista(comida_id=te, limite=3) == claves(time(15, 30), time(14, 32), time(14, 31))
    # Las 14:3x ya no aparecen también bajo almuerzo.
    assert lista(comida_id=almuerzo) == claves(time(12, 30))
    assert _lista(cliente, tokens, DIA - timedelta(days=1)) == []


# --- empate entre comidas distintas -----------------------------------------------


def test_empate_entre_comidas_da_comida_nula_y_cuenta_sin_comida(
    cliente, cliente_simulacion, tokens, configurar
):
    """Té 14–16 por la API desde 2026-01-01; la semilla no repite té (ya
    existe esa vigencia) pero agrega almuerzo 11–15 con la MISMA vigencia. A
    las 14:30 empatan dos comidas: la consulta no elige ninguna. No se compara
    con la comida del POST: esa decisión no quedó guardada en la lectura."""
    configurar(("te", time(14), time(16), SEMILLA))
    almuerzo, te = _comida_id("almuerzo"), _comida_id("te")
    marcada = _marcar(cliente_simulacion, tokens, datetime.combine(SEMILLA, time(14, 30)))

    filas = _lista(cliente, tokens, SEMILLA)
    assert len(filas) == 1
    fila = _por_lectura(filas)[marcada["lectura_id"]]
    assert (fila["comida_id"], fila["comida"]) == (None, None)
    assert fila["clave_evento"] == f"lectura_biometrica:{marcada['lectura_id']}"
    assert _lista(cliente, tokens, SEMILLA, comida_id=almuerzo) == []
    assert _lista(cliente, tokens, SEMILLA, comida_id=te) == []

    cuerpo = _supervision(cliente, tokens, SEMILLA)
    assert set(_rechazos(cuerpo).values()) == {0}
    assert cuerpo["rechazos_sin_comida"] == 1


# --- lectura aceptada: manda la comida persistida ---------------------------------


def test_aceptada_conserva_la_comida_persistida(cliente, cliente_simulacion, tokens, configurar):
    usuario_id, fecha = _candidato_almuerzo()
    almuerzo = _comida_id("almuerzo")
    configurar()  # solo la semilla
    aceptada = _marcar(
        cliente_simulacion, tokens, datetime.combine(fecha, time(12, 30)), usuario_id=usuario_id
    )
    assert aceptada["valido"] is True, aceptada
    assert aceptada["comida_id"] == almuerzo

    # Horarios nuevos: té 12–13 por la API desde esa fecha y otra vez la
    # semilla. A las 12:30 ahora hay dos candidatos y el más nuevo es té.
    configurar(("te", time(12), time(13), fecha))
    te = _comida_id("te")
    rechazo = _marcar(cliente_simulacion, tokens, datetime.combine(fecha, time(12, 40)))

    filas = _por_lectura(_lista(cliente, tokens, fecha))
    fila = filas[aceptada["lectura_id"]]
    assert (fila["comida_id"], fila["valido"]) == (almuerzo, True)
    assert fila["comida"] == aceptada["comida"]
    assert filas[rechazo["lectura_id"]]["comida_id"] == te
    con_te = _por_lectura(_lista(cliente, tokens, fecha, comida_id=te))
    assert aceptada["lectura_id"] not in con_te
    con_almuerzo = _por_lectura(_lista(cliente, tokens, fecha, comida_id=almuerzo))
    assert set(con_almuerzo) == {aceptada["lectura_id"]}

    cuerpo = _supervision(cliente, tokens, fecha)
    servidas = {f["comida_id"]: f["servidas"] for f in cuerpo["comidas"]}
    assert servidas.get(almuerzo) == 1
    assert _rechazos(cuerpo)[te] == 1


# --- la subconsulta, con filas sintéticas ------------------------------------------


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
                cast(literal(f.isoformat(sep=" ")), DateTime).label("fecha_hora"),
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
                cast(literal(desde), Date).label("vigente_desde"),
                cast(literal(hasta) if hasta else null(), Date).label("vigente_hasta"),
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
        ([(1, 10, "14:00", "16:00", "2026-09-01", None, 1),
          (2, 20, "13:00", "15:00", "2026-09-01", None, 1)], None),
        # Una vigencia más reciente decide.
        ([(1, 10, "14:00", "16:00", "2026-09-01", None, 1),
          (2, 20, "13:00", "15:00", "2026-09-10", None, 1)], 20),
        # Dos versiones de la misma comida: esa comida, una vez.
        ([(1, 10, "11:00", "15:00", "2026-01-01", None, 1),
          (2, 10, "14:00", "16:00", "2026-09-01", None, 1)], 10),
        # El empate de abajo no importa si arriba hay una sola comida.
        ([(1, 10, "14:00", "16:00", "2026-01-01", None, 1),
          (2, 20, "13:00", "15:00", "2026-01-01", None, 1),
          (3, 30, "14:00", "15:00", "2026-09-01", None, 1)], 30),
        # El empate de arriba manda aunque abajo haya una sola comida.
        ([(1, 10, "14:00", "16:00", "2026-01-01", None, 1),
          (2, 20, "13:00", "15:00", "2026-09-01", None, 1),
          (3, 30, "14:00", "15:00", "2026-09-01", None, 1)], None),
        # Una versión más nueva que NO cubre la hora no es candidata.
        ([(1, 10, "11:00", "15:00", "2026-01-01", None, 1),
          (2, 20, "16:00", "17:00", "2026-09-10", None, 1)], 10),
        # Inactiva o vencida: no son candidatas.
        ([(1, 10, "11:00", "15:00", "2026-01-01", None, 1),
          (2, 20, "14:00", "16:00", "2026-09-10", None, 0),
          (3, 30, "14:00", "16:00", "2026-09-01", "2026-09-20", 1)], 10),
    ],
    ids=[
        "empate_nulo", "vigencia_mas_nueva", "misma_comida", "empate_viejo_irrelevante",
        "empate_nuevo_manda", "nueva_no_cubre", "inactiva_y_vencida",
    ],
)
def test_resolucion_sintetica(candidatos, esperado):
    assert _resolver(_lecturas((1, A_LAS_1430)), _horarios(*candidatos)) == {1: esperado}


def test_sintetica_sin_candidatos_y_otro_dia_no_aparecen():
    horarios_ = _horarios((1, 10, "11:00", "15:00", "2026-01-01", None, 1))
    lecturas = _lecturas(
        (1, A_LAS_1430),
        (2, datetime.combine(DIA, time(10, 30))),  # sin candidatos
        (3, A_LAS_1430 - timedelta(days=1)),  # otro día
    )
    # La 2 no tiene fila: el LEFT JOIN de la consulta la deja sin comida.
    assert _resolver(lecturas, horarios_) == {1: 10}


def test_sintetica_cruce_de_medianoche():
    horarios_ = _horarios((1, 40, "22:00", "02:00", "2026-01-01", None, 1))
    lecturas = _lecturas(
        (1, datetime.combine(DIA, time(1, 0))),
        (2, datetime.combine(DIA, time(3, 0))),
    )
    assert _resolver(lecturas, horarios_) == {1: 40}
