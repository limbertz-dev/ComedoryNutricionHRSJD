"""Horarios con efecto inmediato: POST /reglas/horarios y sus consultas.

Todo por API con el reloj de simulación congelado (cada guardado rige desde
ESE instante) y la semilla como punto de partida. Cubre: varios cambios el
mismo día, el corte exacto, la auditoría automática, el contrato estricto
(campos retirados, `base_horario_id` obligatorio), el reloj que no avanza y
que la historia nunca se reescribe.
"""

from datetime import datetime

import pytest

from conftest import encabezado, ingresar
from soporte_horarios import (  # noqa: F401  fixtures y ayudas compartidas
    CLAVES_HORARIO,
    a_las,
    abierta,
    comida_id,
    con_horarios,
    fijar,
    guardar,
    historial,
    reloj_libre,
    root,
    vacio,
    vigente_en,
)

CORTE = a_las(16, 0, 0, 250000)
ISO_CORTE = "2026-09-24T16:00:00.250000"


# --- efecto inmediato ------------------------------------------------------------


def test_guardar_rige_desde_el_instante_y_cierra_la_anterior(cliente, root, con_horarios):
    almuerzo = comida_id("almuerzo")
    base = abierta(cliente, root, almuerzo)
    assert base["vigente_desde"] == "2026-01-01T00:00:00"
    assert (base["hora_inicio"], base["hora_fin"]) == ("11:00:00", "15:00:00")

    fijar(CORTE)
    r = guardar(cliente, root, almuerzo, "12:00:00", "13:00:00", base["horario_id"])
    assert r.status_code == 201, r.text
    nueva = r.json()
    assert set(nueva) == CLAVES_HORARIO
    assert nueva["vigente_desde"] == ISO_CORTE
    assert nueva["vigente_hasta"] is None
    assert nueva["estado"] == "vigente"
    assert (nueva["hora_inicio"], nueva["hora_fin"]) == ("12:00:00", "13:00:00")
    assert nueva["cruza_medianoche"] is False

    versiones = historial(cliente, root, almuerzo)
    assert [v["horario_id"] for v in versiones] == [nueva["horario_id"], base["horario_id"]]
    anterior = versiones[1]
    # Lo único que cambió en la anterior es su cierre.
    assert anterior["vigente_hasta"] == ISO_CORTE
    assert anterior["estado"] == "anterior"
    assert (anterior["hora_inicio"], anterior["hora_fin"]) == ("11:00:00", "15:00:00")
    assert anterior["vigente_desde"] == "2026-01-01T00:00:00"


def test_antes_en_y_despues_del_corte(cliente, root, con_horarios):
    """El corte es exacto al microsegundo: antes rige la anterior; en el
    instante y después, la nueva."""
    almuerzo = comida_id("almuerzo")
    base = abierta(cliente, root, almuerzo)
    fijar(CORTE)
    nueva = guardar(cliente, root, almuerzo, "12:00:00", "13:00:00", base["horario_id"]).json()

    antes = vigente_en(cliente, root, a_las(16, 0, 0, 249999))[almuerzo]
    en = vigente_en(cliente, root, CORTE)[almuerzo]
    despues = vigente_en(cliente, root, a_las(16, 0, 0, 250001))[almuerzo]
    assert antes["horario_id"] == base["horario_id"]
    assert en["horario_id"] == nueva["horario_id"]
    assert despues["horario_id"] == nueva["horario_id"]
    # Sin `momento`, ahora (reloj congelado en el corte).
    r = cliente.get("/reglas/horarios", headers=root)
    assert {h["comida_id"]: h["horario_id"] for h in r.json()}[almuerzo] == nueva["horario_id"]


def test_varios_cambios_el_mismo_dia(cliente, root, con_horarios):
    almuerzo = comida_id("almuerzo")
    instantes = [a_las(8), a_las(10, 30), a_las(16)]
    franjas = [("11:30:00", "14:30:00"), ("12:00:00", "14:00:00"), ("12:30:00", "13:30:00")]
    base = abierta(cliente, root, almuerzo)["horario_id"]
    ids = [base]
    for instante, (inicio, fin) in zip(instantes, franjas):
        fijar(instante)
        r = guardar(cliente, root, almuerzo, inicio, fin, ids[-1])
        assert r.status_code == 201, r.text
        ids.append(r.json()["horario_id"])

    versiones = list(reversed(historial(cliente, root, almuerzo)))  # de vieja a nueva
    assert [v["horario_id"] for v in versiones] == ids
    # Cada versión cierra exactamente donde abre la siguiente: sin huecos ni
    # superposiciones.
    for previa, siguiente in zip(versiones, versiones[1:]):
        assert previa["vigente_hasta"] == siguiente["vigente_desde"]
    assert [v["estado"] for v in versiones] == ["anterior"] * 3 + ["vigente"]
    assert versiones[-1]["vigente_hasta"] is None
    # Y cada momento del día resuelve a su versión.
    esperado = [
        (a_las(7), ids[0]),
        (a_las(9), ids[1]),
        (a_las(12), ids[2]),
        (a_las(20), ids[3]),
    ]
    for momento, horario_id in esperado:
        assert vigente_en(cliente, root, momento)[almuerzo]["horario_id"] == horario_id


def test_primera_version_de_una_comida_sin_versiones(cliente, root, vacio):
    almuerzo = comida_id("almuerzo")
    assert abierta(cliente, root, almuerzo) is None
    fijar(a_las(9))
    r = guardar(cliente, root, almuerzo, "11:00:00", "15:00:00", None)
    assert r.status_code == 201, r.text
    assert r.json()["estado"] == "vigente"
    # Con una versión abierta, `null` ya no es la base correcta.
    r = guardar(cliente, root, almuerzo, "11:30:00", "15:00:00", None)
    assert r.status_code == 409, r.text
    assert r.json()["motivo"] == "version_desactualizada"


# --- auditoría y no reescribir la historia -----------------------------------------


def test_auditoria_automatica_sin_motivo(cliente, root, crear_usuario, con_horarios):
    almuerzo = comida_id("almuerzo")
    base = abierta(cliente, root, almuerzo)
    assert base["creada_por"] is None and base["motivo"] is None
    fijar(a_las(9))
    primera = guardar(cliente, root, almuerzo, "11:00:00", "14:00:00", base["horario_id"]).json()
    assert primera["creada_por"] == "root"
    assert primera["motivo"] is None
    assert isinstance(datetime.fromisoformat(primera["creada"]), datetime)

    crear_usuario("otra_cuenta", rol="sistemas")
    otra = encabezado(ingresar(cliente, "otra_cuenta")["access"])
    fijar(a_las(10))
    segunda = guardar(cliente, otra, almuerzo, "11:00:00", "13:00:00", primera["horario_id"]).json()
    assert segunda["creada_por"] == "otra_cuenta"
    assert segunda["motivo"] is None
    # La anterior conserva a su autora.
    por_id = {v["horario_id"]: v for v in historial(cliente, root, almuerzo)}
    assert por_id[primera["horario_id"]]["creada_por"] == "root"


def test_no_se_reescribe_ninguna_version(cliente, root, con_horarios):
    almuerzo = comida_id("almuerzo")
    antes = {v["horario_id"]: v for v in historial(cliente, root, almuerzo)}
    base = abierta(cliente, root, almuerzo)
    fijar(a_las(9))
    guardar(cliente, root, almuerzo, "12:00:00", "13:00:00", base["horario_id"])
    despues = {v["horario_id"]: v for v in historial(cliente, root, almuerzo)}
    original = despues[base["horario_id"]]
    for clave in (
        "hora_inicio",
        "hora_fin",
        "vigente_desde",
        "creada",
        "creada_por",
        "motivo",
    ):
        assert original[clave] == antes[base["horario_id"]][clave], clave
    assert original["vigente_hasta"] == a_las(9).isoformat()


# --- contrato estricto --------------------------------------------------------------


def _cuerpo(almuerzo: int, **extra) -> dict:
    return {
        "comida_id": almuerzo,
        "hora_inicio": "12:00:00",
        "hora_fin": "13:00:00",
        "base_horario_id": None,
        **extra,
    }


@pytest.mark.parametrize(
    "retirados",
    [
        {"vigente_desde": "2026-09-24"},
        {"motivo": "Motivo escrito por el usuario"},
        {"vigente_desde": "2026-09-24", "motivo": "Motivo escrito por el usuario"},
    ],
    ids=["vigente_desde", "motivo", "ambos"],
)
def test_campos_retirados_dan_422_claro(cliente, root, con_horarios, retirados):
    almuerzo = comida_id("almuerzo")
    base = abierta(cliente, root, almuerzo)["horario_id"]
    cuerpo = {**_cuerpo(almuerzo), "base_horario_id": base, **retirados}
    r = cliente.post("/reglas/horarios", json=cuerpo, headers=root)
    assert r.status_code == 422, r.text
    mensajes = " ".join(e["msg"] for e in r.json()["detail"])
    assert "campos retirados" in mensajes
    for campo in retirados:
        assert campo in mensajes
    # No se ignoró en silencio: no se guardó nada.
    assert len(historial(cliente, root, almuerzo)) == 1


def test_base_horario_id_es_obligatorio(cliente, root, con_horarios):
    almuerzo = comida_id("almuerzo")
    cuerpo = _cuerpo(almuerzo)
    del cuerpo["base_horario_id"]
    r = cliente.post("/reglas/horarios", json=cuerpo, headers=root)
    assert r.status_code == 422, r.text
    assert any("base_horario_id" in e["loc"] for e in r.json()["detail"])
    assert len(historial(cliente, root, almuerzo)) == 1


@pytest.mark.parametrize(
    "cambio",
    [
        {"base_horario_id": 0},
        {"comida_id": 0},
        {"campo_desconocido": 1},
        {"hora_inicio": "12:00:00.500"},
        {"hora_fin": "13:00:00+01:00"},
    ],
    ids=["base_cero", "comida_cero", "campo_extra", "fraccion", "zona"],
)
def test_cuerpo_invalido_422(cliente, root, con_horarios, cambio):
    almuerzo = comida_id("almuerzo")
    r = cliente.post("/reglas/horarios", json={**_cuerpo(almuerzo), **cambio}, headers=root)
    assert r.status_code == 422, r.text


def test_errores_con_su_motivo(cliente, root, con_horarios):
    almuerzo = comida_id("almuerzo")
    base = abierta(cliente, root, almuerzo)["horario_id"]
    fijar(a_las(9))

    r = guardar(cliente, root, almuerzo, "12:00:00", "12:00:00", base)
    assert (r.status_code, r.json()["motivo"]) == (422, "horario_invalido")

    r = guardar(cliente, root, 999999999, "12:00:00", "13:00:00", None)
    assert (r.status_code, r.json()["motivo"]) == (404, "comida_inexistente")

    r = guardar(cliente, root, almuerzo, "11:00:00", "15:00:00", base)
    assert (r.status_code, r.json()["motivo"]) == (409, "sin_cambios")

    r = guardar(cliente, root, almuerzo, "12:00:00", "13:00:00", base + 1000)
    assert (r.status_code, r.json()["motivo"]) == (409, "version_desactualizada")

    # Se superpone con el desayuno de la semilla (05:30-10:00).
    r = guardar(cliente, root, almuerzo, "09:00:00", "12:00:00", base)
    assert (r.status_code, r.json()["motivo"]) == (409, "solapa_con_otra_comida")

    # Nada de lo anterior guardó algo.
    assert len(historial(cliente, root, almuerzo)) == 1


def test_solape_con_cruce_de_medianoche(cliente, root, con_horarios):
    """La cena de la semilla (17:00-23:59:59) no admite un té que cruce la
    medianoche y la pise, pero sí uno que termine donde ella empieza."""
    te = comida_id("te")
    base = abierta(cliente, root, te)["horario_id"]
    fijar(a_las(9))
    r = guardar(cliente, root, te, "22:00:00", "02:00:00", base)
    assert (r.status_code, r.json()["motivo"]) == (409, "solapa_con_otra_comida")
    r = guardar(cliente, root, te, "12:00:00", "17:00:00", base)
    assert r.status_code == 409, r.text  # pisa el almuerzo (11:00-15:00)
    r = guardar(cliente, root, te, "15:00:00", "16:00:00", base)
    assert r.status_code == 201, r.text
    assert r.json()["cruza_medianoche"] is False


def test_cruza_medianoche_se_informa(cliente, root, vacio):
    cena = comida_id("cena")
    fijar(a_las(9))
    r = guardar(cliente, root, cena, "22:00:00", "02:00:00", None)
    assert r.status_code == 201, r.text
    assert r.json()["cruza_medianoche"] is True


# --- el reloj no se inventa ni se avanza -------------------------------------------


def test_mismo_instante_y_reloj_retrocedido_dan_409(cliente, root, con_horarios):
    almuerzo = comida_id("almuerzo")
    base = abierta(cliente, root, almuerzo)["horario_id"]
    fijar(a_las(10))
    primera = guardar(cliente, root, almuerzo, "11:30:00", "14:30:00", base)
    assert primera.status_code == 201, primera.text
    nueva = primera.json()["horario_id"]

    # Mismo instante exacto: no se crea una versión vacía ni se pisa la anterior.
    r = guardar(cliente, root, almuerzo, "12:00:00", "14:00:00", nueva)
    assert (r.status_code, r.json()["motivo"]) == (409, "instante_no_posterior")
    assert "2026-09-24T10:00:00" in r.json()["detail"]

    # Reloj simulado hacia atrás: tampoco.
    fijar(a_las(9, 59, 59, 999999))
    r = guardar(cliente, root, almuerzo, "12:00:00", "14:00:00", nueva)
    assert (r.status_code, r.json()["motivo"]) == (409, "instante_no_posterior")

    # Nada cambió: sigue una sola versión abierta, la de las 10:00.
    versiones = historial(cliente, root, almuerzo)
    assert len(versiones) == 2
    assert abierta(cliente, root, almuerzo)["horario_id"] == nueva
    assert abierta(cliente, root, almuerzo)["vigente_desde"] == a_las(10).isoformat()

    # Un microsegundo después sí se guarda: no hay reintento automático ni
    # ajuste del reloj, solo un reloj que ya avanzó.
    fijar(a_las(10, 0, 0, 1))
    r = guardar(cliente, root, almuerzo, "12:00:00", "14:00:00", nueva)
    assert r.status_code == 201, r.text
    assert r.json()["vigente_desde"] == "2026-09-24T10:00:00.000001"


def test_el_reloj_se_compara_con_toda_la_tabla(cliente, root, con_horarios):
    """Un cambio de OTRA comida a las 12:00 también cuenta: guardar a las
    11:00 en el almuerzo sería escribir en el pasado de la tabla."""
    te = comida_id("te")
    almuerzo = comida_id("almuerzo")
    base_te = abierta(cliente, root, te)["horario_id"]
    base_al = abierta(cliente, root, almuerzo)["horario_id"]
    fijar(a_las(12))
    assert guardar(cliente, root, te, "15:00:00", "16:30:00", base_te).status_code == 201
    fijar(a_las(11))
    r = guardar(cliente, root, almuerzo, "11:00:00", "14:00:00", base_al)
    assert (r.status_code, r.json()["motivo"]) == (409, "instante_no_posterior")


# --- lo retirado ---------------------------------------------------------------------


def test_no_hay_borrado_de_horarios_ni_parametro_fecha(cliente, root, con_horarios):
    almuerzo = comida_id("almuerzo")
    base = abierta(cliente, root, almuerzo)["horario_id"]
    r = cliente.delete(f"/reglas/horarios/{base}", headers=root)
    assert r.status_code in (404, 405), r.text
    assert len(historial(cliente, root, almuerzo)) == 1

    r = cliente.get("/reglas/horarios", params={"fecha": "2026-09-24"}, headers=root)
    assert (r.status_code, r.json()["motivo"]) == (422, "parametro_retirado")


def test_historial_de_comida_inexistente_404(cliente, root):
    r = cliente.get(
        "/reglas/horarios/historial", params={"comida_id": 999999999}, headers=root
    )
    assert (r.status_code, r.json()["motivo"]) == (404, "comida_inexistente")
