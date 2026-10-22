"""Administración de cuentas para root y cierre de la fuga hacia la cocinera.

Cuentas de prueba con el fixture crear_usuario; el resto de los datos solo
por API. Lo único que se lee directo (SELECT) es el padrón de turnos, para
elegir personas reales: login usable, login malo, ids inexistentes y ground
truth del carnet.
"""

import pytest
from sqlalchemy import func, inspect, select

from app.consultas.derecho import aplicar_reglas, no_es_enfermeria
from app.consultas.perfiles import categoria_permitida_sql
from app.core.db import SesionLocal, motor
from app.modelos.heredados import Comensal, ComidaPorTurno
from conftest import encabezado, ingresar

CLAVES_CUENTA = {
    "id",
    "username",
    "rol",
    "activo",
    "debe_cambiar",
    "usuario_turnos_id",
    "vinculada",
    "nombre",
    "categoria",
    "creada",
    "ultimo_ingreso",
}

CLAVES_CANDIDATO = {"usuario_turnos_id", "login", "nombre", "categoria", "cuenta_id"}

CLAVE = "clave-elegida-1"


@pytest.fixture
def root(cliente, crear_usuario):
    crear_usuario("root", rol="sistemas")
    return encabezado(ingresar(cliente, "root")["access"])


@pytest.fixture
def roles(cliente, crear_usuario):
    crear_usuario("jefa1", rol="jefa")
    crear_usuario("coci1", rol="cocinera")
    return {
        "jefa": encabezado(ingresar(cliente, "jefa1")["access"]),
        "cocinera": encabezado(ingresar(cliente, "coci1")["access"]),
    }


def _persona_usable(excluir=()) -> tuple | None:
    """Alguien del padrón cuyo login sirve como username (1..50 normalizado)."""
    with SesionLocal() as sesion:
        filas = sesion.execute(
            select(
                Comensal.usuario_id, Comensal.login, Comensal.nombre_completo
            ).order_by(Comensal.usuario_id)
        ).all()
    for fila in filas:
        if fila.usuario_id in excluir or not fila.login:
            continue
        if fila.login.strip().lower() == "root":
            continue
        if 1 <= len(fila.login.strip().lower()) <= 50:
            return fila
    return None


def _login(cliente, username: str, clave: str):
    return cliente.post("/auth/login", json={"username": username, "password": clave})


# --- matriz de permisos -----------------------------------------------------


@pytest.mark.parametrize(
    "metodo,ruta,cuerpo",
    [
        ("GET", "/admin/cuentas", None),
        ("GET", "/admin/candidatos?busqueda=ab", None),
        ("POST", "/admin/cuentas", {"rol": "jefa", "username": "x", "nombre": "X"}),
        ("POST", "/admin/cuentas/1/desactivar", None),
        ("POST", "/admin/cuentas/1/reactivar", None),
        ("POST", "/admin/cuentas/1/clave", {"password": CLAVE}),
    ],
)
@pytest.mark.parametrize("rol", ["jefa", "cocinera"])
def test_admin_solo_sistemas(cliente, crear_usuario, rol, metodo, ruta, cuerpo):
    crear_usuario(f"u_{rol}", rol=rol)
    token = encabezado(ingresar(cliente, f"u_{rol}")["access"])
    r = cliente.request(metodo, ruta, json=cuerpo, headers=token)
    assert r.status_code == 403, r.text
    assert r.json()["motivo"] == "rol_no_autorizado"


def test_listar_cuentas(cliente, root):
    r = cliente.get("/admin/cuentas", headers=root)
    assert r.status_code == 200, r.text
    por_nombre = {c["username"]: c for c in r.json()}
    assert por_nombre["root"]["rol"] == "sistemas"
    assert por_nombre["root"]["vinculada"] is False
    assert por_nombre["root"]["usuario_turnos_id"] is None
    assert set(por_nombre["root"]) == CLAVES_CUENTA


# --- creación ---------------------------------------------------------------


def test_crear_cuenta_vinculada(cliente, root):
    persona = _persona_usable()
    if persona is None:
        pytest.skip("el padrón no tiene logins usables como username")
    r = cliente.post(
        "/admin/cuentas",
        json={"password": CLAVE, "rol": "cocinera", "usuario_turnos_id": persona.usuario_id},
        headers=root,
    )
    assert r.status_code == 201, r.text
    cuenta = r.json()["cuenta"]
    assert set(cuenta) == CLAVES_CUENTA
    assert cuenta["username"] == persona.login.strip().lower()
    assert cuenta["rol"] == "cocinera"
    assert cuenta["activo"] is True
    assert cuenta["debe_cambiar"] is False
    assert cuenta["vinculada"] is True
    assert cuenta["usuario_turnos_id"] == persona.usuario_id
    assert cuenta["nombre"] == persona.nombre_completo
    assert set(r.json()) == {"cuenta"}

    r = cliente.get("/admin/cuentas", headers=root)
    assert r.status_code == 200, r.text
    assert cuenta["id"] in {c["id"] for c in r.json()}


def test_crear_cuenta_sin_vinculo(cliente, root):
    r = cliente.post(
        "/admin/cuentas",
        json={"password": CLAVE, "rol": "jefa", "username": "JefaSimulada", "nombre": "Jefa Simulada"},
        headers=root,
    )
    assert r.status_code == 201, r.text
    cuenta = r.json()["cuenta"]
    assert set(cuenta) == CLAVES_CUENTA
    assert cuenta["username"] == "jefasimulada"
    assert cuenta["vinculada"] is False
    assert cuenta["usuario_turnos_id"] is None
    assert cuenta["nombre"] == "Jefa Simulada"
    assert cuenta["categoria"] is None
    assert cuenta["debe_cambiar"] is False
    assert set(r.json()) == {"cuenta"}

    # Entra directo con la clave que eligió root: sin 428 ni cambio obligatorio.
    r = _login(cliente, "jefasimulada", CLAVE)
    assert r.status_code == 200, r.text
    assert r.json()["debe_cambiar"] is False


@pytest.mark.parametrize(
    "clave,username",
    [("corta", "x-corta"), ("a" * 73, "x-larga"), ("Cocinera4", "cocinera4")],
)
def test_crear_cuenta_clave_rechazada(cliente, root, clave, username):
    r = cliente.post(
        "/admin/cuentas",
        json={"password": clave, "rol": "cocinera", "username": username, "nombre": "C"},
        headers=root,
    )
    assert r.status_code == 422, r.text
    assert r.json()["motivo"] == "password_rechazada"
    nombres = {c["username"] for c in cliente.get("/admin/cuentas", headers=root).json()}
    assert username not in nombres


def test_crear_cuenta_sin_clave_422(cliente, root):
    r = cliente.post(
        "/admin/cuentas",
        json={"rol": "cocinera", "username": "sin-clave", "nombre": "C"},
        headers=root,
    )
    assert r.status_code == 422, r.text


def test_crear_username_en_uso(cliente, root):
    r = cliente.post(
        "/admin/cuentas",
        json={"password": CLAVE, "rol": "jefa", "username": "dupli", "nombre": "D"},
        headers=root,
    )
    assert r.status_code == 201, r.text
    r = cliente.post(
        "/admin/cuentas",
        json={"password": CLAVE, "rol": "cocinera", "username": "DUPLI", "nombre": "D2"},
        headers=root,
    )
    assert r.status_code == 409, r.text
    assert r.json()["motivo"] == "username_en_uso"


def test_crear_vinculada_username_en_uso(cliente, root):
    persona = _persona_usable()
    if persona is None:
        pytest.skip("el padrón no tiene logins usables como username")
    r = cliente.post(
        "/admin/cuentas",
        json={
            "password": CLAVE,
            "rol": "jefa",
            "username": persona.login.strip(),
            "nombre": "Ocupa el login",
        },
        headers=root,
    )
    assert r.status_code == 201, r.text
    r = cliente.post(
        "/admin/cuentas",
        json={"password": CLAVE, "rol": "cocinera", "usuario_turnos_id": persona.usuario_id},
        headers=root,
    )
    assert r.status_code == 409, r.text
    assert r.json()["motivo"] == "username_en_uso"


def test_crear_persona_ya_tiene_cuenta(cliente, root):
    persona = _persona_usable()
    if persona is None:
        pytest.skip("el padrón no tiene logins usables como username")
    r = cliente.post(
        "/admin/cuentas",
        json={"password": CLAVE, "rol": "jefa", "usuario_turnos_id": persona.usuario_id},
        headers=root,
    )
    assert r.status_code == 201, r.text
    r = cliente.post(
        "/admin/cuentas",
        json={"password": CLAVE, "rol": "cocinera", "usuario_turnos_id": persona.usuario_id},
        headers=root,
    )
    assert r.status_code == 409, r.text
    assert r.json()["motivo"] == "persona_ya_tiene_cuenta"


def test_crear_vinculada_persona_inexistente(cliente, root):
    with SesionLocal() as sesion:
        mayor = sesion.execute(select(func.max(Comensal.usuario_id))).scalar_one()
    r = cliente.post(
        "/admin/cuentas",
        json={"password": CLAVE, "rol": "jefa", "usuario_turnos_id": (mayor or 0) + 1},
        headers=root,
    )
    assert r.status_code == 404, r.text
    assert r.json()["motivo"] == "persona_inexistente"


def test_crear_vinculada_login_invalido(cliente, root):
    with SesionLocal() as sesion:
        filas = sesion.execute(select(Comensal.usuario_id, Comensal.login)).all()
    mala = next(
        (
            f
            for f in filas
            if not (f.login or "").strip() or len((f.login or "").strip()) > 50
        ),
        None,
    )
    if mala is None:
        pytest.skip("el padrón no tiene logins vacíos ni mayores de 50")
    r = cliente.post(
        "/admin/cuentas",
        json={"password": CLAVE, "rol": "jefa", "usuario_turnos_id": mala.usuario_id},
        headers=root,
    )
    assert r.status_code == 422, r.text
    assert r.json()["motivo"] == "login_invalido"


@pytest.mark.parametrize("rol", ["sistemas", "inventado"])
def test_crear_cuenta_rol_no_permitido(cliente, root, rol):
    r = cliente.post(
        "/admin/cuentas",
        json={"password": CLAVE, "rol": rol, "username": "x1", "nombre": "X"},
        headers=root,
    )
    assert r.status_code == 422, r.text
    assert r.json()["motivo"] == "rol_no_permitido"


@pytest.mark.parametrize(
    "cuerpo",
    [
        {},
        {"rol": "jefa"},
        {"rol": "jefa", "username": "solo-username"},
        {
            "rol": "jefa",
            "usuario_turnos_id": 1,
            "username": "x",
            "nombre": "X",
        },
    ],
)
def test_crear_cuenta_forma_invalida_422(cliente, root, cuerpo):
    r = cliente.post("/admin/cuentas", json=cuerpo, headers=root)
    assert r.status_code == 422, r.text


def test_cuenta_inexistente_404(cliente, root):
    r = cliente.post("/admin/cuentas/999999999/desactivar", headers=root)
    assert r.status_code == 404, r.text
    assert r.json()["motivo"] == "cuenta_inexistente"


# --- candidatos -------------------------------------------------------------


def test_candidatos_busca_en_nombre_y_login(cliente, root):
    persona = _persona_usable()
    if persona is None:
        pytest.skip("el padrón no tiene logins usables como username")
    r = cliente.get(
        "/admin/candidatos",
        params={"busqueda": persona.login, "limite": 100},
        headers=root,
    )
    assert r.status_code == 200, r.text
    por_id = {c["usuario_turnos_id"]: c for c in r.json()}
    assert persona.usuario_id in por_id
    candidato = por_id[persona.usuario_id]
    assert set(candidato) == CLAVES_CANDIDATO
    assert candidato["login"] == persona.login
    assert candidato["cuenta_id"] is None

    if persona.nombre_completo and len(persona.nombre_completo.strip()) >= 2:
        r = cliente.get(
            "/admin/candidatos",
            params={"busqueda": persona.nombre_completo, "limite": 100},
            headers=root,
        )
        assert r.status_code == 200, r.text
        assert persona.usuario_id in {c["usuario_turnos_id"] for c in r.json()}

    r = cliente.post(
        "/admin/cuentas",
        json={"password": CLAVE, "rol": "jefa", "usuario_turnos_id": persona.usuario_id},
        headers=root,
    )
    assert r.status_code == 201, r.text
    id_cuenta = r.json()["cuenta"]["id"]
    r = cliente.get(
        "/admin/candidatos",
        params={"busqueda": persona.login, "limite": 100},
        headers=root,
    )
    por_id = {c["usuario_turnos_id"]: c for c in r.json()}
    assert por_id[persona.usuario_id]["cuenta_id"] == id_cuenta


def test_candidatos_busqueda_corta_422(cliente, root):
    r = cliente.get("/admin/candidatos", params={"busqueda": "a"}, headers=root)
    assert r.status_code == 422, r.text


# --- estado y clave ---------------------------------------------------------


def test_desactivar_cierra_sesiones(cliente, root):
    r = cliente.post(
        "/admin/cuentas",
        json={"password": CLAVE, "rol": "cocinera", "username": "coci-sesion", "nombre": "C"},
        headers=root,
    )
    assert r.status_code == 201, r.text
    cuenta_id = r.json()["cuenta"]["id"]
    access = _login(cliente, "coci-sesion", CLAVE).json()["access"]
    assert cliente.get("/auth/yo", headers=encabezado(access)).status_code == 200

    r = cliente.post(f"/admin/cuentas/{cuenta_id}/desactivar", headers=root)
    assert r.status_code == 200, r.text
    assert r.json()["activo"] is False

    r = cliente.get("/auth/yo", headers=encabezado(access))
    assert r.status_code == 401, r.text
    assert r.json()["motivo"] == "token_invalido"

    r = cliente.post(f"/admin/cuentas/{cuenta_id}/reactivar", headers=root)
    assert r.status_code == 200, r.text
    assert r.json()["activo"] is True
    # La sesión vieja sigue muerta: reactivar no resucita tokens.
    assert cliente.get("/auth/yo", headers=encabezado(access)).status_code == 401
    # Pero la cuenta sirve de nuevo.
    assert _login(cliente, "coci-sesion", CLAVE).status_code == 200


def test_cambiar_clave_entra_directo_y_cierra_sesiones(cliente, root):
    r = cliente.post(
        "/admin/cuentas",
        json={"password": CLAVE, "rol": "jefa", "username": "jefa-clave", "nombre": "J"},
        headers=root,
    )
    assert r.status_code == 201, r.text
    cuenta_id = r.json()["cuenta"]["id"]
    access = _login(cliente, "jefa-clave", CLAVE).json()["access"]

    r = cliente.post(
        f"/admin/cuentas/{cuenta_id}/clave", json={"password": "otra-clave-2"}, headers=root
    )
    assert r.status_code == 200, r.text
    assert set(r.json()) == {"cuenta"}
    assert r.json()["cuenta"]["debe_cambiar"] is False

    # La sesión abierta con la clave vieja se cierra.
    assert cliente.get("/auth/yo", headers=encabezado(access)).status_code == 401
    assert _login(cliente, "jefa-clave", CLAVE).status_code == 401
    r = _login(cliente, "jefa-clave", "otra-clave-2")
    assert r.status_code == 200, r.text
    assert r.json()["debe_cambiar"] is False


def test_cambiar_clave_rechazada_no_cambia_nada(cliente, root):
    r = cliente.post(
        "/admin/cuentas",
        json={"password": CLAVE, "rol": "jefa", "username": "jefa-corta", "nombre": "J"},
        headers=root,
    )
    cuenta_id = r.json()["cuenta"]["id"]
    r = cliente.post(f"/admin/cuentas/{cuenta_id}/clave", json={"password": "corta"}, headers=root)
    assert r.status_code == 422, r.text
    assert r.json()["motivo"] == "password_rechazada"
    assert _login(cliente, "jefa-corta", CLAVE).status_code == 200


def test_cambiar_clave_de_cuenta_inexistente_404(cliente, root):
    r = cliente.post("/admin/cuentas/999999999/clave", json={"password": CLAVE}, headers=root)
    assert r.status_code == 404, r.text
    assert r.json()["motivo"] == "cuenta_inexistente"


def test_no_puede_desactivarse_a_si_misma(cliente, root):
    yo = cliente.get("/auth/yo", headers=root).json()
    r = cliente.post(f"/admin/cuentas/{yo['id']}/desactivar", headers=root)
    assert r.status_code == 409, r.text
    assert r.json()["motivo"] == "no_puede_desactivarse_a_si_misma"
    assert cliente.get("/auth/yo", headers=root).status_code == 200


def test_nunca_queda_sin_cuentas_sistemas(cliente, crear_usuario):
    crear_usuario("root", rol="sistemas")
    id_otra = crear_usuario("otra", rol="sistemas")
    root = encabezado(ingresar(cliente, "root")["access"])

    r = cliente.post(f"/admin/cuentas/{id_otra}/desactivar", headers=root)
    assert r.status_code == 200, r.text

    yo = cliente.get("/auth/yo", headers=root).json()
    r = cliente.post(f"/admin/cuentas/{yo['id']}/desactivar", headers=root)
    assert r.status_code == 409, r.text

    activas = [
        c
        for c in cliente.get("/admin/cuentas", headers=root).json()
        if c["rol"] == "sistemas" and c["activo"]
    ]
    assert len(activas) == 1

    r = cliente.post(f"/admin/cuentas/{id_otra}/reactivar", headers=root)
    assert r.status_code == 200, r.text
    assert r.json()["activo"] is True


def test_ultimo_ingreso(cliente, root):
    cuentas = {
        c["username"]: c for c in cliente.get("/admin/cuentas", headers=root).json()
    }
    # El fixture ingresó como root: tiene último ingreso.
    assert cuentas["root"]["ultimo_ingreso"] is not None
    r = cliente.post(
        "/admin/cuentas",
        json={"password": CLAVE, "rol": "jefa", "username": "jefa-nueva", "nombre": "J"},
        headers=root,
    )
    assert r.status_code == 201, r.text
    assert r.json()["cuenta"]["ultimo_ingreso"] is None


# --- T3: la cocinera no ve carnet ni tipo ------------------------------------


def _verdad_padron(limite=200) -> dict:
    """Ground truth con el mismo filtro y orden que GET /personal."""
    with SesionLocal() as sesion:
        filas = sesion.execute(
            select(Comensal)
            .where(no_es_enfermeria(Comensal.categoria))
            .where(categoria_permitida_sql(Comensal.categoria))
            .order_by(
                Comensal.nombre_completo.is_(None),
                Comensal.nombre_completo,
                Comensal.usuario_id,
            )
            .limit(limite)
        ).scalars().all()
        return {
            c.usuario_id: {
                "carnet_identidad": c.carnet_identidad,
                "tipo_trabajador": c.tipo_trabajador,
                "numero_item": c.numero_item,
            }
            for c in filas
        }


def test_cocinera_no_ve_ci_ni_tipo_en_padron(cliente, roles):
    verdad = _verdad_padron()
    if not verdad:
        pytest.skip("el padrón no tiene comensales")
    if not any(v["carnet_identidad"] for v in verdad.values()):
        pytest.skip("ningún carnet cargado: el enmascarado no se probaría")
    rj = cliente.get("/personal", params={"limite": 200}, headers=roles["jefa"])
    rc = cliente.get("/personal", params={"limite": 200}, headers=roles["cocinera"])
    assert rj.status_code == 200, rj.text
    assert rc.status_code == 200, rc.text
    dj = {d["usuario_id"]: d for d in rj.json()["datos"]}
    dc = {d["usuario_id"]: d for d in rc.json()["datos"]}
    assert set(dj) == set(dc) == set(verdad)
    for uid, v in verdad.items():
        assert dj[uid]["carnet_identidad"] == v["carnet_identidad"]
        assert dj[uid]["tipo_trabajador"] == v["tipo_trabajador"]
        assert dc[uid]["carnet_identidad"] is None
        assert dc[uid]["tipo_trabajador"] is None
        assert dc[uid]["numero_item"] == dj[uid]["numero_item"] == v["numero_item"]


def test_cocinera_no_ve_ci_ni_tipo_en_ficha(cliente, roles):
    verdad = _verdad_padron()
    uid = next(
        (u for u, v in verdad.items() if v["carnet_identidad"] is not None), None
    )
    if uid is None:
        pytest.skip("ningún carnet cargado: el enmascarado no se probaría")
    rj = cliente.get(f"/personal/{uid}", headers=roles["jefa"])
    rc = cliente.get(f"/personal/{uid}", headers=roles["cocinera"])
    assert rj.status_code == 200, rj.text
    assert rc.status_code == 200, rc.text
    assert rj.json()["carnet_identidad"] == verdad[uid]["carnet_identidad"]
    assert rj.json()["tipo_trabajador"] == verdad[uid]["tipo_trabajador"]
    assert rc.json()["carnet_identidad"] is None
    assert rc.json()["tipo_trabajador"] is None
    assert rc.json()["numero_item"] == rj.json()["numero_item"]


def _con_derecho_y_carnet():
    """(usuario_id, fecha, carnet) con derecho y carnet cargado, o skip."""
    with SesionLocal() as sesion:
        filas = sesion.execute(
            aplicar_reglas(
                select(ComidaPorTurno.usuario_id, ComidaPorTurno.fecha_comida)
            )
            .order_by(ComidaPorTurno.fecha_comida.desc(), ComidaPorTurno.usuario_id)
            .limit(200)
        ).all()
        if not filas:
            pytest.skip("la base de turnos no tiene ninguna comida con derecho")
        carnets = dict(
            sesion.execute(
                select(Comensal.usuario_id, Comensal.carnet_identidad).where(
                    Comensal.usuario_id.in_([f.usuario_id for f in filas])
                )
            ).all()
        )
    for fila in filas:
        if carnets.get(fila.usuario_id) is not None:
            return fila.usuario_id, fila.fecha_comida, carnets[fila.usuario_id]
    pytest.skip("nadie con derecho tiene carnet cargado")


def test_cocinera_no_ve_ci_en_dia_personal(cliente, roles):
    uid, fecha, carnet = _con_derecho_y_carnet()
    params = {"persona_id": uid, "fecha": fecha.isoformat()}
    rj = cliente.get("/pantalla/dia-personal", params=params, headers=roles["jefa"])
    rc = cliente.get(
        "/pantalla/dia-personal", params=params, headers=roles["cocinera"]
    )
    assert rj.status_code == 200, rj.text
    assert rc.status_code == 200, rc.text
    assert rj.json()["datos"], "sin datos, el enmascarado no se probaría"
    assert rj.json()["datos"][0]["carnet_identidad"] == carnet
    assert rc.json()["datos"][0]["carnet_identidad"] is None
    dj, dc = dict(rj.json()["datos"][0]), dict(rc.json()["datos"][0])
    dj.pop("carnet_identidad")
    dc.pop("carnet_identidad")
    assert dc == dj


# --- la vista ----------------------------------------------------------------


def test_v_comensales_tiene_login_y_nada_sensible():
    inspect(motor).clear_cache()
    columnas = {c["name"] for c in inspect(motor).get_columns("v_comensales")}
    assert {
        "usuario_id",
        "login",
        "nombre_completo",
        "carnet_identidad",
        "tipo_trabajador",
        "numero_item",
        "categoria_id",
        "categoria",
        "categoria_nivel",
        "tiene_ficha",
    } <= columnas
    assert not (columnas & {"password", "email", "remember_token", "email_verified_at"})


def test_conteo_de_vistas_sigue_en_nueve(cliente):
    r = cliente.get("/salud")
    assert r.status_code == 200, r.text
    assert r.json()["vistas_contrato"] == 9
