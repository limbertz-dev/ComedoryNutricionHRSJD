"""Ventanas efectivas: la intersección entre la ocurrencia de una franja y la
vigencia de su versión.

Primero la aritmética pura (sin base): cambios a mitad de franja, huecos,
cruce de medianoche, la ventana que empieza en el corte y no en la hora
nominal. Después lo que cada consumidor hace con ella: supervisión,
historial, y marcación y lectura alrededor del corte.
"""

from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import text

from app.consultas import horarios as consulta
from app.consultas.historial import NO_RECIBIDA, PENDIENTE, _estado
from app.core.db import SesionLocal
from conftest import encabezado, ingresar
from soporte_horarios import (  # noqa: F401  fixtures y ayudas compartidas
    DIA,
    a_las,
    abierta,
    comida_id,
    con_horarios,
    fijar,
    guardar,
    reloj_libre,
    root,
    vacio,
)

ENERO = datetime(2026, 1, 1)
MANANA = DIA + timedelta(days=1)


def _v(comida: int, inicio: time, fin: time, desde: datetime, hasta: datetime | None = None):
    """Una fila como la devuelve `_versiones`."""
    return (comida, f"comida{comida}", inicio, fin, desde, hasta)


def _ventanas(dia: date, *versiones):
    return consulta._ventanas(list(versiones), dia)


def _tramos(comida) -> list[tuple[datetime, datetime]]:
    return [(v.inicio, v.fin) for v in comida.ventanas]


# --- aritmética pura ------------------------------------------------------------------


def test_almuerzo_terminado_antes_del_cambio_no_se_redefine():
    """Almuerzo 11:00-15:00; a las 16:00 se guarda 12:00-13:00. La ventana de
    ese día sigue siendo la que fue: la versión nueva no la toca."""
    corte = a_las(16)
    (almuerzo,) = _ventanas(
        DIA,
        _v(1, time(11), time(15), ENERO, corte),
        _v(1, time(12), time(13), corte),
    )
    assert _tramos(almuerzo) == [(a_las(11), a_las(15))]
    assert (almuerzo.ultima.hora_inicio, almuerzo.ultima.hora_fin) == (time(11), time(15))
    # Al día siguiente rige entera la versión nueva.
    (manana,) = _ventanas(
        MANANA,
        _v(1, time(11), time(15), ENERO, corte),
        _v(1, time(12), time(13), corte),
    )
    assert _tramos(manana) == [(a_las(12, dia=MANANA), a_las(13, dia=MANANA))]


def test_la_ventana_nueva_empieza_en_el_corte_no_en_la_hora_nominal():
    """Guardada a las 16:00 con 11:00-20:00: ventana efectiva desde las 16:00,
    sin descartarla porque su inicio nominal era las 11:00 y sin reescribir
    la de la mañana."""
    corte = a_las(16)
    (almuerzo,) = _ventanas(
        DIA,
        _v(1, time(11), time(15), ENERO, corte),
        _v(1, time(11), time(20), corte),
    )
    assert _tramos(almuerzo) == [(a_las(11), a_las(15)), (a_las(16), a_las(20))]
    assert (almuerzo.ultima.hora_inicio, almuerzo.ultima.hora_fin) == (time(11), time(20))


def test_cambio_a_mitad_de_franja_une_los_tramos_contiguos():
    # Se acorta a las 13:00 de 11-15 a 11-14: un solo tramo 11:00-14:00.
    corte = a_las(13)
    (acortada,) = _ventanas(
        DIA,
        _v(1, time(11), time(15), ENERO, corte),
        _v(1, time(11), time(14), corte),
    )
    assert _tramos(acortada) == [(a_las(11), a_las(14))]
    # Se alarga a las 12:00 de 11-13 a 11-15: un solo tramo 11:00-15:00.
    corte = a_las(12)
    (alargada,) = _ventanas(
        DIA,
        _v(1, time(11), time(13), ENERO, corte),
        _v(1, time(11), time(15), corte),
    )
    assert _tramos(alargada) == [(a_las(11), a_las(15))]


def test_huecos_entre_ventanas():
    corte = a_las(12, 30)
    (comida,) = _ventanas(
        DIA,
        _v(1, time(11), time(12), ENERO, corte),
        _v(1, time(14), time(15), corte),
    )
    assert _tramos(comida) == [(a_las(11), a_las(12)), (a_las(14), a_las(15))]
    ventanas = comida.ventanas
    assert consulta.estado_en(ventanas, a_las(10)) == "pendiente"
    assert consulta.estado_en(ventanas, a_las(11, 30)) == "en_curso"
    # En el hueco: todavía hay una ventana por delante.
    assert consulta.estado_en(ventanas, a_las(13)) == "pendiente"
    assert consulta.estado_en(ventanas, a_las(15)) == "cerrada"


def test_cruce_de_medianoche_se_ancla_en_el_dia_que_empezo():
    cena = _v(1, time(22), time(2), ENERO)
    (hoy,) = _ventanas(DIA, cena)
    assert _tramos(hoy) == [(a_las(22), a_las(2, dia=MANANA))]
    # La madrugada del día D pertenece a la ocurrencia anclada en D-1.
    (ayer,) = _ventanas(DIA - timedelta(days=1), cena)
    assert _tramos(ayer) == [(a_las(22, dia=DIA - timedelta(days=1)), a_las(2))]


def test_cambio_en_la_madrugada_de_una_franja_que_cruza():
    corte = a_las(0, 30, dia=MANANA)
    (cena,) = _ventanas(
        DIA,
        _v(1, time(22), time(2), ENERO, corte),
        _v(1, time(23), time(1), corte),
    )
    # 22:00-00:30 (versión vieja) + 00:30-01:00 (nueva): un tramo continuo.
    assert _tramos(cena) == [(a_las(22), a_las(1, dia=MANANA))]
    assert (cena.ultima.hora_inicio, cena.ultima.hora_fin) == (time(23), time(1))
    # El día siguiente ya es de la versión nueva completa.
    (siguiente,) = _ventanas(MANANA, _v(1, time(22), time(2), ENERO, corte), _v(1, time(23), time(1), corte))
    assert _tramos(siguiente) == [(a_las(23, dia=MANANA), a_las(1, dia=MANANA + timedelta(days=1)))]


def test_versiones_que_no_tocan_el_dia_no_dan_ventana():
    futura = _v(1, time(11), time(15), a_las(0, dia=DIA + timedelta(days=2)))
    cerrada = _v(2, time(11), time(15), ENERO, a_las(0))
    assert _ventanas(DIA, futura, cerrada) == []


def test_orden_cronologico_por_la_franja_de_la_ultima_ventana():
    comidas = _ventanas(
        DIA,
        _v(7, time(17), time(23), ENERO),
        _v(3, time(5, 30), time(10), ENERO),
        _v(5, time(11), time(15), ENERO),
    )
    assert [c.comida_id for c in comidas] == [3, 5, 7]


def test_interseccion_vacia_y_borde_exclusivo():
    inicio, fin = time(11), time(15)
    assert consulta.interseccion(DIA, inicio, fin, a_las(15), None) is None
    assert consulta.interseccion(DIA, inicio, fin, ENERO, a_las(11)) is None
    assert consulta.interseccion(DIA, inicio, fin, ENERO, a_las(11, 0, 0, 1)) == (
        a_las(11),
        a_las(11, 0, 0, 1),
    )


# --- consumidores por día --------------------------------------------------------------


def _tokens(cliente, crear_usuario):
    for rol in ("jefa", "cocinera"):
        crear_usuario(f"u_{rol}", rol=rol)
    return {rol: encabezado(ingresar(cliente, f"u_{rol}")["access"]) for rol in ("jefa", "cocinera")}


def _supervision(cliente, token, dia: date, ahora: datetime) -> dict[int, dict]:
    fijar(ahora)
    r = cliente.get(
        "/pantalla/comidas-del-dia", params={"fecha": dia.isoformat()}, headers=token
    )
    assert r.status_code == 200, r.text
    return {f["comida_id"]: f for f in r.json()["comidas"]}


def test_ejemplo_del_almuerzo_en_supervision(cliente, crear_usuario, root, con_horarios):
    jefa = _tokens(cliente, crear_usuario)["jefa"]
    almuerzo = comida_id("almuerzo")
    base = abierta(cliente, root, almuerzo)["horario_id"]
    fijar(a_las(16))
    assert guardar(cliente, root, almuerzo, "12:00:00", "13:00:00", base).status_code == 201

    # Antes del cierre original (replay a las 14:00): sigue en curso.
    fila = _supervision(cliente, jefa, DIA, a_las(14))[almuerzo]
    assert fila["estado"] == "en_curso"
    # Cerró a las 15:00, no a las 13:00 de la versión nueva.
    assert _supervision(cliente, jefa, DIA, a_las(15, 30))[almuerzo]["estado"] == "cerrada"
    despues = _supervision(cliente, jefa, DIA, a_las(16, 5))[almuerzo]
    assert despues["estado"] == "cerrada"
    assert (despues["hora_inicio"], despues["hora_fin"]) == ("11:00:00", "15:00:00")
    # Mañana rige la nueva franja.
    manana = _supervision(cliente, jefa, MANANA, a_las(16, 5))[almuerzo]
    assert manana["estado"] == "pendiente"
    assert (manana["hora_inicio"], manana["hora_fin"]) == ("12:00:00", "13:00:00")


def test_ampliar_por_la_tarde_abre_una_ventana_nueva(cliente, crear_usuario, root, vacio):
    jefa = _tokens(cliente, crear_usuario)["jefa"]
    almuerzo = comida_id("almuerzo")
    fijar(a_las(9))
    base = guardar(cliente, root, almuerzo, "11:00:00", "15:00:00", None).json()["horario_id"]
    fijar(a_las(16))
    assert guardar(cliente, root, almuerzo, "11:00:00", "20:00:00", base).status_code == 201

    assert _supervision(cliente, jefa, DIA, a_las(10))[almuerzo]["estado"] == "pendiente"
    assert _supervision(cliente, jefa, DIA, a_las(12))[almuerzo]["estado"] == "en_curso"
    # Desde las 16:00 vuelve a haber ventana: efecto inmediato.
    assert _supervision(cliente, jefa, DIA, a_las(16, 5))[almuerzo]["estado"] == "en_curso"
    assert _supervision(cliente, jefa, DIA, a_las(20, 30))[almuerzo]["estado"] == "cerrada"


def test_historial_cierres_pendientes_y_no_recibidas(cliente, root, con_horarios):
    """Conservar el comida_id de la asistencia no alcanza: el cierre de la
    ventana decide si una ración sin recibir es pendiente o no recibida."""
    almuerzo = comida_id("almuerzo")
    base = abierta(cliente, root, almuerzo)["horario_id"]
    fijar(a_las(16))
    assert guardar(cliente, root, almuerzo, "12:00:00", "13:00:00", base).status_code == 201

    with SesionLocal() as sesion:
        fines = consulta.fines_de_ventana(sesion, DIA)
        fines_manana = consulta.fines_de_ventana(sesion, MANANA)
    assert fines[almuerzo] == a_las(15)  # no las 13:00 de la versión nueva
    assert fines_manana[almuerzo] == a_las(13, dia=MANANA)
    # Replay a las 14:00: la ventana de las 11-15 seguía abierta.
    assert _estado(True, None, fines[almuerzo], a_las(14)) == PENDIENTE
    assert _estado(True, None, fines[almuerzo], a_las(15)) == NO_RECIBIDA
    assert _estado(True, None, fines[almuerzo], a_las(16, 5)) == NO_RECIBIDA


def test_ampliada_por_la_tarde_vuelve_a_pendiente_en_el_historial(cliente, root, vacio):
    almuerzo = comida_id("almuerzo")
    fijar(a_las(9))
    base = guardar(cliente, root, almuerzo, "11:00:00", "15:00:00", None).json()["horario_id"]
    fijar(a_las(16))
    assert guardar(cliente, root, almuerzo, "11:00:00", "20:00:00", base).status_code == 201
    with SesionLocal() as sesion:
        fin = consulta.fines_de_ventana(sesion, DIA)[almuerzo]
    assert fin == a_las(20)
    assert _estado(True, None, fin, a_las(16, 5)) == PENDIENTE
    assert _estado(True, None, fin, a_las(20)) == NO_RECIBIDA


def test_cena_que_cruza_cierra_al_dia_siguiente(cliente, root, vacio):
    cena = comida_id("cena")
    fijar(a_las(9))
    assert guardar(cliente, root, cena, "22:00:00", "02:00:00", None).status_code == 201
    with SesionLocal() as sesion:
        assert consulta.fines_de_ventana(sesion, DIA)[cena] == a_las(2, dia=MANANA)


# --- marcación y lectura: el instante del evento -----------------------------------------


def _marcar(lector, momento: datetime) -> dict:
    fijar(momento)
    return lector.leer()


def test_marcaciones_antes_en_y_despues_del_corte(
    cliente, lector, crear_usuario, root, con_horarios
):
    """Almuerzo 11:00-15:00; a las 14:00:00.5 se acorta a 11:00-14:00. Una
    huella a un microsegundo del corte cae en la versión de ese instante, y la
    lectura guarda ese instante con microsegundos (DATETIME(6))."""
    tokens = _tokens(cliente, crear_usuario)
    almuerzo = comida_id("almuerzo")
    base = abierta(cliente, root, almuerzo)["horario_id"]
    corte = a_las(14, 0, 0, 500000)
    fijar(corte)
    assert guardar(cliente, root, almuerzo, "11:00:00", "14:00:00", base).status_code == 201

    antes = _marcar(lector, a_las(14, 0, 0, 499999))
    en = _marcar(lector, corte)
    despues = _marcar(lector, a_las(14, 0, 0, 500001))
    # Antes del corte rige 11-15: huella sin identificar. Desde el corte, 11-14: fuera.
    assert (antes["motivo"], antes["comida_id"]) == ("no_identificado", almuerzo)
    assert (en["motivo"], en["comida_id"]) == ("fuera_horario", None)
    assert (despues["motivo"], despues["comida_id"]) == ("fuera_horario", None)

    with SesionLocal() as sesion:
        guardados = {
            fila[0]: fila[1]
            for fila in sesion.execute(
                text("SELECT id, fecha_hora FROM lecturas_biometricas")
            ).all()
        }
    assert guardados[antes["lectura_id"]] == a_las(14, 0, 0, 499999)
    assert guardados[en["lectura_id"]] == corte
    assert guardados[despues["lectura_id"]] == a_las(14, 0, 0, 500001)

    # La lista y Supervisión re-resuelven con el instante guardado, sin
    # mandar una lectura al otro lado del corte.
    fijar(a_las(18))
    r = cliente.get(
        "/pantalla/ultimas-marcaciones",
        params={"fecha": DIA.isoformat()},
        headers=tokens["jefa"],
    )
    assert r.status_code == 200, r.text
    comida_por_lectura = {m["id"]: m["comida_id"] for m in r.json()}
    assert comida_por_lectura[antes["lectura_id"]] == almuerzo
    assert comida_por_lectura[en["lectura_id"]] is None
    assert comida_por_lectura[despues["lectura_id"]] is None
