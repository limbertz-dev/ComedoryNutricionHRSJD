"""El reloj del laboratorio, sin base de datos."""
from datetime import datetime, timedelta

import pytest

import lab


def test_real_sigue_la_hora_del_servidor():
    reloj = lab.Reloj()
    assert abs(reloj.ahora() - datetime.now()) < timedelta(seconds=1)


def test_pausado_queda_quieto():
    reloj = lab.Reloj()
    ancla = datetime(2026, 8, 5, 12, 0)
    reloj.fijar(ancla, "pausado")
    assert reloj.ahora() == ancla
    assert reloj.ahora() == ancla


def test_corriendo_avanza_desde_el_ancla():
    reloj = lab.Reloj()
    ancla = datetime(2026, 8, 5, 12, 0)
    reloj.fijar(ancla, "corriendo")
    reloj.ancla_real -= timedelta(minutes=3)
    assert timedelta(minutes=3) <= reloj.ahora() - ancla < timedelta(minutes=3, seconds=1)


def test_modo_desconocido_o_sin_hora_se_rechaza():
    reloj = lab.Reloj()
    with pytest.raises(ValueError):
        reloj.fijar(datetime(2026, 8, 5), "rapido")
    with pytest.raises(ValueError):
        reloj.fijar(None, "pausado")


def test_restaurar_estado_guardado_o_dañado():
    reloj = lab.Reloj()
    reloj.restaurar({"modo": "pausado", "ancla": "2026-08-05T07:00:00"})
    assert reloj.ahora() == datetime(2026, 8, 5, 7, 0)
    reloj.restaurar({"modo": "pausado", "ancla": "no-es-fecha"})
    assert reloj.modo == "real"
