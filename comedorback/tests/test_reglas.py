"""Reglas de derecho (solo lectura) y cuentas de solo lectura.

El derecho ya no se edita por API: lo que se prueba acá es que sus versiones
siguen resolviéndose por `fecha_turno`, que POST/DELETE no existen y que
intentarlos no cambia ningún valor. Las versiones que esas pruebas necesitan
(pasadas, de hoy o futuras) las inserta la fixture `version_derecho` de
conftest.py, solo en la base `_test`.

Los horarios inmediatos se prueban en test_horarios_inmediatos.py, sus
ventanas efectivas en test_ventanas_horarios.py y el cerrojo en
test_cerrojo_horarios.py.
"""

from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import func, select, text

from app.consultas.derecho import aplicar_reglas
import reloj_prueba
from app.core.db import SesionLocal
from app.modelos.heredados import Comensal, ComidaPorTurno
from conftest import encabezado, ingresar

NOVEDADES_BASE = ["permiso", "baja_medica", "vacacion", "licencia"]
CLAVES_CUENTA = {
    "id",
    "username",
    "nombre",
    "rol",
    "activo",
    "debe_cambiar",
    "ultimo_ingreso",
}
CLAVES_VERSION = {
    "id",
    "vigente_desde",
    "duracion_minima_horas",
    "novedades_que_anulan",
    "excluir_enfermeria",
    "motivo",
    "creada_por",
    "creada",
    "estado",
}


@pytest.fixture(autouse=True)
def reloj_real():
    reloj_prueba.liberar()
    yield
    reloj_prueba.liberar()


@pytest.fixture(autouse=True)
def reglas_en_base():
    yield
    with SesionLocal() as sesion:
        sesion.execute(
            text(
                "DELETE FROM reglas_derecho_novedad WHERE regla_id IN "
                "(SELECT id FROM reglas_derecho WHERE vigente_desde != '2000-01-01')"
            )
        )
        sesion.execute(
            text("DELETE FROM reglas_derecho WHERE vigente_desde != '2000-01-01'")
        )
        sesion.commit()


@pytest.fixture
def root(cliente, crear_usuario):
    crear_usuario("root", rol="sistemas")
    return encabezado(ingresar(cliente, "root")["access"])


@pytest.fixture
def roles(cliente, crear_usuario):
    crear_usuario("jefa1", rol="jefa")
    crear_usuario("coci1", rol="cocinera")
    crear_usuario("sis1", rol="sistemas")
    return {
        "jefa": encabezado(ingresar(cliente, "jefa1")["access"]),
        "cocinera": encabezado(ingresar(cliente, "coci1")["access"]),
        "sistemas": encabezado(ingresar(cliente, "sis1")["access"]),
    }


def _fijar(fecha: date) -> date:
    reloj_prueba.fijar(datetime.combine(fecha, time(12, 0)))
    return fecha


def _fecha_comida_con_derecho() -> tuple[int, date, int]:
    with SesionLocal() as sesion:
        fila = sesion.execute(
            aplicar_reglas(
                select(
                    ComidaPorTurno.usuario_id,
                    ComidaPorTurno.fecha_comida,
                    ComidaPorTurno.comida_id,
                )
            )
            .order_by(ComidaPorTurno.fecha_comida.desc(), ComidaPorTurno.usuario_id)
            .limit(1)
        ).first()
    if fila is None:
        pytest.skip("la base de turnos no tiene comidas con derecho")
    return fila.usuario_id, fila.fecha_comida, fila.comida_id


def _fecha_turno_con_derecho() -> date:
    with SesionLocal() as sesion:
        fila = sesion.execute(
            aplicar_reglas(select(ComidaPorTurno.fecha_turno))
            .order_by(ComidaPorTurno.fecha_turno.desc())
            .limit(1)
        ).first()
    if fila is None:
        pytest.skip("la base de turnos no tiene turnos con derecho")
    return fila.fecha_turno


def _usuario_enfermeria() -> int:
    """Algún usuario del padrón con categoría de enfermería."""
    with SesionLocal() as sesion:
        fila = sesion.execute(
            select(Comensal.usuario_id)
            .where(Comensal.categoria.ilike("%enfermer%"))
            .order_by(Comensal.usuario_id)
            .limit(1)
        ).first()
    if fila is None:
        pytest.skip("el padrón de pruebas no tiene usuarios de enfermería")
    return fila.usuario_id


def _turno_largo_limpio(usuario_id: int) -> tuple[date, date]:
    """(fecha_turno, fecha_comida) de un turno largo, limpio y mapeado.

    Prefiere dia_relativo 0 para que el derecho caiga en el propio día;
    si solo hay guardias con corrimiento, se usa su fecha_comida.
    """
    from app.modelos.heredados import NovedadLaboral

    with SesionLocal() as sesion:
        fila = sesion.execute(
            select(ComidaPorTurno.fecha_turno, ComidaPorTurno.fecha_comida)
            .where(ComidaPorTurno.usuario_id == usuario_id)
            .where(ComidaPorTurno.duracion_horas >= 12)
            .where(
                ~select(NovedadLaboral.id)
                .where(
                    NovedadLaboral.asignacion_id
                    == ComidaPorTurno.turno_asignado_id,
                    NovedadLaboral.tipo_novedad.in_(tuple(NOVEDADES_BASE)),
                )
                .exists()
            )
            .order_by(
                ComidaPorTurno.dia_relativo.asc(),
                ComidaPorTurno.fecha_turno.desc(),
            )
            .limit(1)
        ).first()
    if fila is None:
        pytest.skip("enfermería sin turno largo y limpio en pruebas")
    return fila.fecha_turno, fila.fecha_comida


def _derecho_hoy_count(usuario_id: int, fecha: date) -> int:
    with SesionLocal() as sesion:
        return sesion.execute(
            aplicar_reglas(
                select(func.count())
                .select_from(ComidaPorTurno)
                .where(
                    ComidaPorTurno.usuario_id == usuario_id,
                    ComidaPorTurno.fecha_comida == fecha,
                )
            )
        ).scalar_one()


def _contar_por_fecha_turno(fecha: date) -> int:
    with SesionLocal() as sesion:
        return sesion.execute(
            aplicar_reglas(
                select(func.count())
                .select_from(ComidaPorTurno)
                .where(ComidaPorTurno.fecha_turno == fecha)
            )
        ).scalar_one()


# --- versión base y listado ---------------------------------------------------


def test_version_base(cliente, root):
    r = cliente.get("/reglas/derecho", headers=root)
    assert r.status_code == 200, r.text
    datos = r.json()
    assert set(datos) == {"vigente", "versiones"}
    vigente = datos["vigente"]
    assert set(vigente) == CLAVES_VERSION
    assert vigente["vigente_desde"] == "2000-01-01"
    assert vigente["duracion_minima_horas"] == 12
    assert sorted(vigente["novedades_que_anulan"]) == sorted(NOVEDADES_BASE)
    assert vigente["excluir_enfermeria"] is True
    assert vigente["creada_por"] is None
    assert vigente["estado"] == "vigente"
    assert len(datos["versiones"]) == 1


# --- el derecho no se edita por API --------------------------------------------


@pytest.mark.parametrize("rol", ["sistemas", "jefa", "cocinera"])
def test_derecho_no_se_edita_por_api(cliente, crear_usuario, rol):
    """El servidor lo impide, no solo la pantalla: POST y DELETE no existen
    (405/404, sin importar el rol) y los valores quedan exactamente igual."""
    crear_usuario("root", rol="sistemas")
    root = encabezado(ingresar(cliente, "root")["access"])
    antes = cliente.get("/reglas/derecho", headers=root).json()
    version_id = antes["vigente"]["id"]

    crear_usuario(f"u_{rol}", rol=rol)
    token = encabezado(ingresar(cliente, f"u_{rol}")["access"])
    cuerpo = {
        "vigente_desde": "2030-01-01",
        "duracion_minima_horas": 1,
        "novedades_que_anulan": [],
        "excluir_enfermeria": False,
        "motivo": "Un intento que ya no debe existir",
    }
    assert cliente.post("/reglas/derecho", json=cuerpo, headers=token).status_code == 405
    assert cliente.delete(f"/reglas/derecho/{version_id}", headers=token).status_code in (404, 405)
    assert cliente.get("/reglas/derecho/novedades", headers=token).status_code == 404

    assert cliente.get("/reglas/derecho", headers=root).json() == antes


def test_derecho_historico_igual_tras_los_intentos(cliente, root):
    dia = _fecha_turno_con_derecho()
    _fijar(dia)
    antes = (_contar_por_fecha_turno(dia), _contar_por_fecha_turno(dia - timedelta(days=1)))
    cliente.post("/reglas/derecho", json={"duracion_minima_horas": 1}, headers=root)
    cliente.delete("/reglas/derecho/1", headers=root)
    despues = (_contar_por_fecha_turno(dia), _contar_por_fecha_turno(dia - timedelta(days=1)))
    assert despues == antes


# --- evaluación por fecha_turno de versiones ya existentes --------------------


def test_version_futura_no_cambia_hoy(cliente, root, version_derecho):
    usuario, fecha, _ = _fecha_comida_con_derecho()
    _fijar(fecha)
    antes = _derecho_hoy_count(usuario, fecha)
    assert antes > 0
    manana = fecha + timedelta(days=1)
    futura = version_derecho(manana, 48)
    versiones = cliente.get("/reglas/derecho", headers=root).json()["versiones"]
    assert {v["id"]: v["estado"] for v in versiones}[futura] == "programada"
    assert _derecho_hoy_count(usuario, fecha) == antes
    r = cliente.get(
        f"/personal/{usuario}/derecho", params={"fecha": fecha.isoformat()}, headers=root
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) > 0


def test_al_llegar_la_fecha_rige_la_version(cliente, root, version_derecho):
    dia = _fecha_turno_con_derecho()
    hoy = _fijar(dia)
    assert _contar_por_fecha_turno(hoy) > 0
    version = version_derecho(hoy, 48, novedades=tuple(NOVEDADES_BASE))
    assert cliente.get("/reglas/derecho", headers=root).json()["vigente"]["id"] == version
    assert _contar_por_fecha_turno(hoy) == 0


def test_mensual_cruza_el_cambio(cliente, root, version_derecho):
    dia = _fecha_turno_con_derecho()
    hoy = _fijar(dia)
    ayer = hoy - timedelta(days=1)
    base_ayer, base_hoy = _contar_por_fecha_turno(ayer), _contar_por_fecha_turno(hoy)
    if not base_ayer or not base_hoy:
        pytest.skip("se necesitan dos días seguidos con derecho")
    version_derecho(hoy, 48, excluir_enfermeria=False)
    # Cada asignación usa la versión de SU fecha_turno: ayer no cambia.
    assert _contar_por_fecha_turno(ayer) == base_ayer
    assert _contar_por_fecha_turno(hoy) == 0


def test_vigente_sigue_al_reloj(cliente, root, version_derecho):
    dia = _fecha_turno_con_derecho()
    _fijar(dia)
    manana = dia + timedelta(days=1)
    programada = version_derecho(manana, 20, novedades=("permiso",))
    assert cliente.get("/reglas/derecho", headers=root).json()["vigente"]["id"] != programada
    _fijar(manana)
    datos = cliente.get("/reglas/derecho", headers=root).json()
    assert datos["vigente"]["id"] == programada
    assert datos["vigente"]["estado"] == "vigente"


# --- enfermería: padrón y derecho van juntos ----------------------------------


def test_enfermeria_sigue_fuera_aunque_la_version_no_la_excluya(cliente, root, version_derecho):
    # Solo comen las categorías de app/consultas/perfiles.py; la marca
    # excluir_enfermeria de una versión no la vuelve elegible.
    usuario = _usuario_enfermeria()
    dia, fecha_comida = _turno_largo_limpio(usuario)
    hoy = _fijar(dia)
    assert cliente.get(f"/personal/{usuario}", headers=root).status_code == 404
    r = cliente.get(
        f"/personal/{usuario}/derecho",
        params={"fecha": fecha_comida.isoformat()},
        headers=root,
    )
    assert r.status_code == 200, r.text
    assert r.json() == []
    version_derecho(
        hoy, 12, novedades=tuple(NOVEDADES_BASE), excluir_enfermeria=False
    )
    assert cliente.get(f"/personal/{usuario}", headers=root).status_code == 404
    r = cliente.get(
        f"/personal/{usuario}/derecho",
        params={"fecha": fecha_comida.isoformat()},
        headers=root,
    )
    assert r.status_code == 200, r.text
    assert r.json() == []


# --- permisos -------------------------------------------------------------------


@pytest.mark.parametrize(
    "metodo,ruta,cuerpo",
    [
        ("GET", "/reglas/derecho", None),
        ("GET", "/reglas/horarios", None),
        ("GET", "/reglas/horarios/historial?comida_id=1", None),
        (
            "POST",
            "/reglas/horarios",
            {
                "comida_id": 1,
                "hora_inicio": "12:00:00",
                "hora_fin": "13:00:00",
                "base_horario_id": None,
            },
        ),
    ],
)
@pytest.mark.parametrize("rol", ["jefa", "cocinera"])
def test_reglas_solo_sistemas(cliente, crear_usuario, rol, metodo, ruta, cuerpo):
    crear_usuario(f"u_{rol}", rol=rol)
    token = encabezado(ingresar(cliente, f"u_{rol}")["access"])
    r = cliente.request(metodo, ruta, json=cuerpo, headers=token)
    assert r.status_code == 403, r.text
    assert r.json()["motivo"] == "rol_no_autorizado"


def test_cuentas_jefa_sin_sistemas_y_cocinera_403(cliente, roles):
    r = cliente.get("/cuentas", headers=roles["sistemas"])
    assert r.status_code == 200, r.text
    todas = r.json()
    assert {c["username"] for c in todas} >= {"jefa1", "coci1", "sis1"}
    assert set(todas[0]) == CLAVES_CUENTA
    assert "usuario_turnos_id" not in todas[0]
    r = cliente.get("/cuentas", headers=roles["jefa"])
    assert r.status_code == 200, r.text
    vistas = r.json()
    assert vistas
    assert {c["rol"] for c in vistas} <= {"jefa", "cocinera"}
    assert "sis1" not in {c["username"] for c in vistas}
    r = cliente.get("/cuentas", headers=roles["cocinera"])
    assert r.status_code == 403, r.text
    assert r.json()["motivo"] == "rol_no_autorizado"


# --- índices y salud --------------------------------------------------------------


def test_indices_y_tablas_nuevas():
    from sqlalchemy import inspect

    from app.core.db import motor

    inspect(motor).clear_cache()
    tablas = set(inspect(motor).get_table_names())
    assert {"reglas_derecho", "reglas_derecho_novedad", "cerrojos"} <= tablas
    unicos = {
        tuple(sorted(i["column_names"]))
        for i in inspect(motor).get_unique_constraints("reglas_derecho")
    }
    assert ("vigente_desde",) in unicos
    indices = {
        i["name"] for i in inspect(motor).get_indexes("horarios_comida")
    }
    assert "ix_horarios_comida_comida_id_vigente_desde" in indices
    for tabla in ("reglas_derecho", "reglas_derecho_novedad", "cerrojos"):
        opciones = inspect(motor).get_table_options(tabla)
        assert opciones["mysql_collate"] == "utf8mb4_unicode_ci", tabla


def test_salud_cuenta_diecisiete_tablas(cliente):
    """Diez tablas anteriores, más `cerrojos`, `intervenciones_lectura`, las
    dos del lector real (`vinculos_lector`, `solicitudes_lector`),
    `raciones_policia`, `anulaciones_checklist` y `policias`."""
    r = cliente.get("/salud")
    assert r.status_code == 200, r.text
    assert r.json()["tablas_propias"] == 17
    assert r.json()["vistas_contrato"] == 9
