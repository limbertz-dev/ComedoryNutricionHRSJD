"""Login, bloqueo, cambio obligatorio de clave y vencimiento de tokens."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core import seguridad
from app.core.db import SesionLocal
from app.logica import autenticacion
from app.modelos.usuarios import IntentoLogin
from conftest import encabezado, ingresar


def _login(cliente, username, clave):
    return cliente.post("/auth/login", json={"username": username, "password": clave})


def _resultados(username: str) -> list[str]:
    with SesionLocal() as sesion:
        return list(
            sesion.execute(
                select(IntentoLogin.resultado)
                .where(IntentoLogin.username == username)
                .order_by(IntentoLogin.id)
            ).scalars()
        )


# --- login ------------------------------------------------------------------


def test_login_ok_devuelve_el_contrato(cliente, crear_usuario):
    crear_usuario("jefa1", rol="jefa")

    cuerpo = ingresar(cliente, "jefa1")

    assert set(cuerpo) == {"access", "refresh", "rol", "debe_cambiar"}
    assert cuerpo["rol"] == "jefa"
    assert cuerpo["debe_cambiar"] is False
    yo = cliente.get("/auth/yo", headers=encabezado(cuerpo["access"]))
    assert yo.status_code == 200
    assert yo.json()["username"] == "jefa1"
    assert yo.json()["rol"] == "jefa"
    assert _resultados("jefa1") == ["exitoso"]


def test_username_no_distingue_mayusculas_ni_espacios(cliente, crear_usuario):
    crear_usuario("jefa1")
    assert _login(cliente, "  JEFA1 ", "clave-segura-1").status_code == 200


def test_mala_clave_401_sin_decir_que_fallo(cliente, crear_usuario):
    crear_usuario("jefa1")

    mala = _login(cliente, "jefa1", "otra-clave")
    inexistente = _login(cliente, "nadie", "otra-clave")

    assert mala.status_code == inexistente.status_code == 401
    assert mala.json() == inexistente.json()
    assert mala.json()["motivo"] == "credenciales_invalidas"
    assert _resultados("jefa1") == ["fallido"]


def test_cuenta_inactiva_no_ingresa(cliente, crear_usuario):
    crear_usuario("baja", activo=False)
    assert _login(cliente, "baja", "clave-segura-1").status_code == 401


def test_token_de_cuenta_dada_de_baja_deja_de_servir(cliente, crear_usuario):
    usuario_id = crear_usuario("jefa1")
    access = ingresar(cliente, "jefa1")["access"]

    with SesionLocal() as sesion:
        from app.modelos.usuarios import UsuarioSistema

        sesion.get(UsuarioSistema, usuario_id).activo = False
        sesion.commit()

    respuesta = cliente.get("/auth/yo", headers=encabezado(access))
    assert respuesta.status_code == 401
    assert respuesta.json()["motivo"] == "token_invalido"


# --- bloqueo ----------------------------------------------------------------


def test_sin_bloqueo_por_omision(cliente, crear_usuario):
    """Apagado por omisión: equivocarse muchas veces nunca deja afuera a nadie."""
    crear_usuario("coci1", rol="cocinera")
    for _ in range(12):
        assert _login(cliente, "coci1", "mal").status_code == 401
    assert _login(cliente, "coci1", "clave-segura-1").status_code == 200
    assert _resultados("coci1") == ["fallido"] * 12 + ["exitoso"]


@pytest.fixture
def con_bloqueo(monkeypatch):
    """Activa el bloqueo como lo haría AUTH_INTENTOS_MAXIMOS=5 en .env."""
    monkeypatch.setattr(seguridad.ajustes(), "intentos_maximos", 5)


def test_bloqueo_al_quinto_fallido(cliente, crear_usuario, con_bloqueo):
    crear_usuario("jefa1")

    for _ in range(4):
        assert _login(cliente, "jefa1", "mal").status_code == 401
    quinto = _login(cliente, "jefa1", "mal")

    assert quinto.status_code == 423
    assert quinto.json()["motivo"] == "cuenta_bloqueada"
    assert "reintento_en" in quinto.json()
    assert int(quinto.headers["Retry-After"]) > 0

    # Bloqueada, ni la clave correcta entra; y ese intento no cuenta como fallido.
    correcta = _login(cliente, "jefa1", "clave-segura-1")
    assert correcta.status_code == 423
    assert _resultados("jefa1") == ["fallido"] * 5 + ["bloqueado"]


def test_el_bloqueo_vence_a_los_15_minutos(cliente, crear_usuario, monkeypatch, con_bloqueo):
    crear_usuario("jefa1")
    base = autenticacion.ahora()
    monkeypatch.setattr(autenticacion, "ahora", lambda: base)
    for _ in range(5):
        _login(cliente, "jefa1", "mal")
    assert _login(cliente, "jefa1", "clave-segura-1").status_code == 423

    monkeypatch.setattr(autenticacion, "ahora", lambda: base + timedelta(minutes=14, seconds=59))
    assert _login(cliente, "jefa1", "clave-segura-1").status_code == 423

    monkeypatch.setattr(autenticacion, "ahora", lambda: base + timedelta(minutes=15))
    assert _login(cliente, "jefa1", "clave-segura-1").status_code == 200


def test_fallidos_fuera_de_la_ventana_no_bloquean(cliente, crear_usuario, monkeypatch, con_bloqueo):
    crear_usuario("jefa1")
    base = autenticacion.ahora()
    for i in range(5):  # uno cada 4 minutos: 16 minutos entre el 1.º y el 5.º
        monkeypatch.setattr(autenticacion, "ahora", lambda i=i: base + timedelta(minutes=4 * i))
        assert _login(cliente, "jefa1", "mal").status_code == 401


def test_un_ingreso_exitoso_reinicia_la_cuenta(cliente, crear_usuario, con_bloqueo):
    crear_usuario("jefa1")
    for _ in range(4):
        _login(cliente, "jefa1", "mal")
    assert _login(cliente, "jefa1", "clave-segura-1").status_code == 200
    for _ in range(4):
        assert _login(cliente, "jefa1", "mal").status_code == 401


def test_username_inexistente_tambien_se_bloquea(cliente, con_bloqueo):
    for _ in range(4):
        assert _login(cliente, "fantasma", "mal").status_code == 401
    assert _login(cliente, "fantasma", "mal").status_code == 423


def test_bloqueo_es_por_cuenta(cliente, crear_usuario, con_bloqueo):
    crear_usuario("jefa1")
    crear_usuario("coci1", rol="cocinera")
    for _ in range(5):
        _login(cliente, "jefa1", "mal")
    assert _login(cliente, "coci1", "clave-segura-1").status_code == 200


# --- primer ingreso: 428 -----------------------------------------------------


def test_flujo_428_cambio_obligatorio(cliente, crear_usuario):
    crear_usuario("nueva", rol="cocinera", clave="temporal-123", debe_cambiar=True)

    respuesta = _login(cliente, "nueva", "temporal-123")
    assert respuesta.status_code == 428
    assert respuesta.json()["motivo"] == "cambio_password_pendiente"
    temporal = respuesta.json()["temporal"]
    assert "access" not in respuesta.json()

    # La política de claves se aplica.
    corta = cliente.post(
        "/auth/cambio-password", json={"password_nueva": "123"}, headers=encabezado(temporal)
    )
    assert corta.status_code == 422
    assert corta.json()["motivo"] == "password_rechazada"
    misma = cliente.post(
        "/auth/cambio-password",
        json={"password_nueva": "temporal-123"},
        headers=encabezado(temporal),
    )
    assert misma.status_code == 422

    cambio = cliente.post(
        "/auth/cambio-password",
        json={"password_nueva": "mi-clave-nueva"},
        headers=encabezado(temporal),
    )
    assert cambio.status_code == 200
    assert cambio.json()["debe_cambiar"] is False
    assert cambio.json()["rol"] == "cocinera"
    assert cliente.get("/auth/yo", headers=encabezado(cambio.json()["access"])).status_code == 200

    # El temporal era de un solo uso: la versión del token cambió.
    reuso = cliente.post(
        "/auth/cambio-password",
        json={"password_nueva": "otra-clave-mas"},
        headers=encabezado(temporal),
    )
    assert reuso.status_code == 401

    assert _login(cliente, "nueva", "temporal-123").status_code == 401
    assert _login(cliente, "nueva", "mi-clave-nueva").status_code == 200


def test_temporal_no_sirve_como_access_ni_refresh(cliente, crear_usuario):
    crear_usuario("nueva", clave="temporal-123", debe_cambiar=True)
    temporal = _login(cliente, "nueva", "temporal-123").json()["temporal"]

    yo = cliente.get("/auth/yo", headers=encabezado(temporal))
    assert yo.status_code == 403
    assert yo.json()["motivo"] == "cambio_password_pendiente"
    assert cliente.post("/auth/refresh", json={"refresh": temporal}).status_code == 401


def test_cambio_voluntario_pide_la_clave_actual(cliente, crear_usuario):
    crear_usuario("jefa1")
    access = ingresar(cliente, "jefa1")["access"]

    sin_actual = cliente.post(
        "/auth/cambio-password", json={"password_nueva": "nueva-clave-1"}, headers=encabezado(access)
    )
    assert sin_actual.status_code == 400
    mala = cliente.post(
        "/auth/cambio-password",
        json={"password_nueva": "nueva-clave-1", "password_actual": "mal"},
        headers=encabezado(access),
    )
    assert mala.status_code == 400
    assert mala.json()["motivo"] == "password_actual_incorrecta"

    bien = cliente.post(
        "/auth/cambio-password",
        json={"password_nueva": "nueva-clave-1", "password_actual": "clave-segura-1"},
        headers=encabezado(access),
    )
    assert bien.status_code == 200
    # El cambio cierra las sesiones anteriores.
    assert cliente.get("/auth/yo", headers=encabezado(access)).status_code == 401


# --- vencimiento y renovación -----------------------------------------------


def test_token_expirado_rechazado(cliente, crear_usuario):
    usuario_id = crear_usuario("jefa1")
    vencido = seguridad.emitir_token(
        usuario_id=usuario_id,
        tipo=seguridad.ACCESS,
        version=0,
        rol="jefa",
        duracion=timedelta(seconds=-1),
    )

    respuesta = cliente.get("/auth/yo", headers=encabezado(vencido))

    assert respuesta.status_code == 401
    assert respuesta.json()["motivo"] == "token_expirado"
    assert respuesta.headers["WWW-Authenticate"] == "Bearer"


def test_refresh_expirado_rechazado(cliente, crear_usuario):
    usuario_id = crear_usuario("jefa1")
    vencido = seguridad.emitir_token(
        usuario_id=usuario_id, tipo=seguridad.REFRESH, version=0, duracion=timedelta(seconds=-1)
    )
    respuesta = cliente.post("/auth/refresh", json={"refresh": vencido})
    assert respuesta.status_code == 401
    assert respuesta.json()["motivo"] == "token_expirado"


def test_token_mal_firmado_rechazado(cliente, crear_usuario):
    crear_usuario("jefa1")
    access = ingresar(cliente, "jefa1")["access"]
    adulterado = access[:-4] + ("AAAA" if not access.endswith("AAAA") else "BBBB")
    respuesta = cliente.get("/auth/yo", headers=encabezado(adulterado))
    assert respuesta.status_code == 401
    assert respuesta.json()["motivo"] == "token_invalido"


def test_refresh_da_access_nuevo(cliente, crear_usuario):
    crear_usuario("jefa1")
    sesion = ingresar(cliente, "jefa1")

    renovada = cliente.post("/auth/refresh", json={"refresh": sesion["refresh"]})

    assert renovada.status_code == 200
    assert renovada.json()["refresh"] == sesion["refresh"]
    assert cliente.get("/auth/yo", headers=encabezado(renovada.json()["access"])).status_code == 200
    # Un access no sirve como refresh, ni un refresh como access.
    assert cliente.post("/auth/refresh", json={"refresh": sesion["access"]}).status_code == 401
    assert cliente.get("/auth/yo", headers=encabezado(sesion["refresh"])).status_code == 401


def test_sin_token_401(cliente):
    respuesta = cliente.get("/auth/yo")
    assert respuesta.status_code == 401
    assert respuesta.json()["motivo"] == "falta_token"
