"""api.activa huérfana: se retira solo con el puerto libre y la marca vieja."""
import os
import socket
import time

import comun as c


def _puerto_libre():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _marca(tmp_path, monkeypatch, edad):
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    marca = tmp_path / 'api.activa'
    marca.touch()
    hace = time.time() - edad
    os.utime(marca, (hace, hace))
    return marca


def test_sin_marca_no_hace_nada(tmp_path, monkeypatch):
    monkeypatch.setattr(c, 'CARPETA', tmp_path)
    assert c.retirar_marca_api_huerfana(puerto=_puerto_libre()) is False


def test_marca_reciente_se_conserva_porque_la_api_puede_estar_arrancando(tmp_path, monkeypatch):
    marca = _marca(tmp_path, monkeypatch, edad=5)
    assert c.retirar_marca_api_huerfana(puerto=_puerto_libre()) is False
    assert marca.exists()


def test_marca_vieja_con_puerto_libre_se_retira(tmp_path, monkeypatch):
    marca = _marca(tmp_path, monkeypatch, edad=600)
    assert c.retirar_marca_api_huerfana(puerto=_puerto_libre()) is True
    assert not marca.exists()


def test_marca_vieja_con_api_escuchando_se_conserva(tmp_path, monkeypatch):
    marca = _marca(tmp_path, monkeypatch, edad=600)
    with socket.socket() as servidor:
        servidor.bind(('127.0.0.1', 0))
        servidor.listen()
        assert c.retirar_marca_api_huerfana(puerto=servidor.getsockname()[1]) is False
    assert marca.exists()
