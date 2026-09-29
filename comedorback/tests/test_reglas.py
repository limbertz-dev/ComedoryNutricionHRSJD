"""R2: horarios y parámetros versionados, cuentas de solo lectura.

Datos por API; limpieza como la existente; reloj congelado con reloj.fijar.
La base de turnos solo se lee (SELECT) para elegir personas y fechas reales.
"""

from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import func, select, text

from app.consultas.derecho import aplicar_reglas
from app.core import reloj
from app.core.db import SesionLocal
from app.modelos.heredados import Comensal, Comida, ComidaPorTurno, NovedadLaboral
from app.semillas import horarios as semilla_horarios
from conftest import encabezado, ingresar

MOTIVO = "Motivo de prueba con más de diez caracteres"
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
CLAVES_HORARIO = {
    "horario_id",
    "comida_id",
    "comida",
    "hora_inicio",
    "hora_fin",
    "cruza_medianoche",
    "vigente_desde",
    "vigente_hasta",
    "motivo",
    "creada_por",
}


@pytest.fixture(autouse=True)
def reloj_real():
    reloj.volver_a_real()
    yield
    reloj.volver_a_real()


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


@pytest.fixture
def con_horarios():
    with SesionLocal() as sesion:
        sesion.execute(text("DELETE FROM asistencias"))
        sesion.execute(text("DELETE FROM lecturas_biometricas"))
        sesion.execute(text("DELETE FROM horarios_comida"))
        sesion.commit()
    semilla_horarios.sembrar()
    yield
    with SesionLocal() as sesion:
        sesion.execute(text("DELETE FROM asistencias"))
        sesion.execute(text("DELETE FROM lecturas_biometricas"))
        sesion.execute(text("DELETE FROM horarios_comida"))
        sesion.commit()


def _fijar(fecha: date) -> date:
    reloj.fijar(datetime.combine(fecha, time(12, 0)), congelar=True)
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


def _comidas() -> dict[str, tuple[int, str]]:
    with SesionLocal() as sesion:
        filas = sesion.execute(select(Comida.id, Comida.codigo, Comida.nombre)).all()
    return {codigo: (i, nombre) for i, codigo, nombre in filas}


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
                    NovedadLaboral.tipo_novedad.in_(
                        ("permiso", "baja_medica", "vacacion", "licencia")
                    ),
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
    assert sorted(vigente["novedades_que_anulan"]) == [
        "baja_medica",
        "licencia",
        "permiso",
        "vacacion",
    ]
    assert vigente["excluir_enfermeria"] is True
    assert vigente["creada_por"] is None
    assert vigente["estado"] == "vigente"
    assert len(datos["versiones"]) == 1


def test_novedades_reales(cliente, root):
    r = cliente.get("/reglas/derecho/novedades", headers=root)
    assert r.status_code == 200, r.text
    tipos = r.json()
    assert isinstance(tipos, list)
    for esperado in ("permiso", "baja_medica", "vacacion", "licencia"):
        assert esperado in tipos


# --- programada no cambia hoy; al llegar sí -----------------------------------


def test_programada_no_cambia_hoy(cliente, root):
    usuario, fecha, _ = _fecha_comida_con_derecho()
    _fijar(fecha)
    antes = _derecho_hoy_count(usuario, fecha)
    assert antes > 0
    manana = fecha + timedelta(days=1)
    r = cliente.post(
        "/reglas/derecho",
        json={
            "vigente_desde": manana.isoformat(),
            "duracion_minima_horas": 48,
            "novedades_que_anulan": [],
            "excluir_enfermeria": True,
            "motivo": MOTIVO,
        },
        headers=root,
    )
    assert r.status_code == 201, r.text
    assert r.json()["estado"] == "programada"
    assert _derecho_hoy_count(usuario, fecha) == antes
    r = cliente.get(f"/personal/{usuario}/derecho", params={"fecha": fecha.isoformat()}, headers=root)
    assert r.status_code == 200, r.text
    assert len(r.json()) > 0


def test_al_llegar_fecha_nadie_tiene_derecho(cliente, root):
    dia = _fecha_turno_con_derecho()
    hoy = _fijar(dia)
    with SesionLocal() as sesion:
        antes = sesion.execute(
            aplicar_reglas(
                select(func.count())
                .select_from(ComidaPorTurno)
                .where(ComidaPorTurno.fecha_turno == hoy)
            )
        ).scalar_one()
    assert antes > 0
    r = cliente.post(
        "/reglas/derecho",
        json={
            "vigente_desde": hoy.isoformat(),
            "duracion_minima_horas": 48,
            "novedades_que_anulan": ["permiso", "baja_medica", "vacacion", "licencia"],
            "excluir_enfermeria": True,
            "motivo": MOTIVO,
        },
        headers=root,
    )
    assert r.status_code == 201, r.text
    assert r.json()["estado"] == "vigente"
    with SesionLocal() as sesion:
        ahora = sesion.execute(
            aplicar_reglas(
                select(func.count())
                .select_from(ComidaPorTurno)
                .where(ComidaPorTurno.fecha_turno == hoy)
            )
        ).scalar_one()
        ayer = sesion.execute(
            aplicar_reglas(
                select(func.count())
                .select_from(ComidaPorTurno)
                .where(ComidaPorTurno.fecha_turno == hoy - timedelta(days=1))
            )
        ).scalar_one()
    assert ahora == 0
    if ayer:
        pass


def test_mensual_cruza_el_cambio(cliente, root):
    dia = _fecha_turno_con_derecho()
    hoy = _fijar(dia)
    ayer = hoy - timedelta(days=1)
    with SesionLocal() as sesion:
        base_ayer = sesion.execute(
            aplicar_reglas(
                select(func.count())
                .select_from(ComidaPorTurno)
                .where(ComidaPorTurno.fecha_turno == ayer)
            )
        ).scalar_one()
        base_hoy = sesion.execute(
            aplicar_reglas(
                select(func.count())
                .select_from(ComidaPorTurno)
                .where(ComidaPorTurno.fecha_turno == hoy)
            )
        ).scalar_one()
    if not base_ayer or not base_hoy:
        pytest.skip("se necesitan dos días seguidos con derecho")
    r = cliente.post(
        "/reglas/derecho",
        json={
            "vigente_desde": hoy.isoformat(),
            "duracion_minima_horas": 48,
            "novedades_que_anulan": [],
            "excluir_enfermeria": False,
            "motivo": MOTIVO,
        },
        headers=root,
    )
    assert r.status_code == 201, r.text
    with SesionLocal() as sesion:
        sigue_ayer = sesion.execute(
            aplicar_reglas(
                select(func.count())
                .select_from(ComidaPorTurno)
                .where(ComidaPorTurno.fecha_turno == ayer)
            )
        ).scalar_one()
        cambio_hoy = sesion.execute(
            aplicar_reglas(
                select(func.count())
                .select_from(ComidaPorTurno)
                .where(ComidaPorTurno.fecha_turno == hoy)
            )
        ).scalar_one()
    assert sigue_ayer == base_ayer
    assert cambio_hoy == 0


def test_vigente_sigue_al_reloj(cliente, root):
    dia = _fecha_turno_con_derecho()
    _fijar(dia)
    manana = dia + timedelta(days=1)
    r = cliente.post(
        "/reglas/derecho",
        json={
            "vigente_desde": manana.isoformat(),
            "duracion_minima_horas": 20,
            "novedades_que_anulan": ["permiso"],
            "excluir_enfermeria": True,
            "motivo": MOTIVO,
        },
        headers=root,
    )
    assert r.status_code == 201, r.text
    programada = r.json()["id"]
    assert cliente.get("/reglas/derecho", headers=root).json()["vigente"]["id"] != programada
    _fijar(manana)
    datos = cliente.get("/reglas/derecho", headers=root).json()
    assert datos["vigente"]["id"] == programada
    assert datos["vigente"]["estado"] == "vigente"


# --- enfermería: padrón y derecho van juntos ----------------------------------


def test_padron_y_derecho_incluyen_enfermeria_hoy(cliente, root):
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
    r = cliente.post(
        "/reglas/derecho",
        json={
            "vigente_desde": hoy.isoformat(),
            "duracion_minima_horas": 12,
            "novedades_que_anulan": ["permiso", "baja_medica", "vacacion", "licencia"],
            "excluir_enfermeria": False,
            "motivo": MOTIVO,
        },
        headers=root,
    )
    assert r.status_code == 201, r.text
    assert cliente.get(f"/personal/{usuario}", headers=root).status_code == 200
    r = cliente.get(
        f"/personal/{usuario}/derecho",
        params={"fecha": fecha_comida.isoformat()},
        headers=root,
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) > 0
    with SesionLocal() as sesion:
        ayer = sesion.execute(
            aplicar_reglas(
                select(func.count())
                .select_from(ComidaPorTurno)
                .where(
                    ComidaPorTurno.usuario_id == usuario,
                    ComidaPorTurno.fecha_turno == hoy - timedelta(days=1),
                )
            )
        ).scalar_one()
        hay_ayer = sesion.execute(
            select(ComidaPorTurno.fecha_turno)
            .where(
                ComidaPorTurno.usuario_id == usuario,
                ComidaPorTurno.fecha_turno == hoy - timedelta(days=1),
            )
            .limit(1)
        ).first()
    if hay_ayer is not None:
        assert ayer == 0


# --- horarios: pasado intacto, cierre y reapertura ------------------------------


def test_horario_nuevo_no_cambia_dia_anterior(cliente, root, con_horarios):
    comidas = _comidas()
    if "almuerzo" not in comidas:
        pytest.skip("v_comidas sin almuerzo")
    almuerzo_id, _ = comidas["almuerzo"]
    hoy = _fijar(date(2026, 9, 24))
    ayer = hoy - timedelta(days=1)
    antes_ayer = {
        c["comida_id"]: c
        for c in cliente.get(
            "/reglas/horarios", params={"fecha": ayer.isoformat()}, headers=root
        ).json()
    }
    assert antes_ayer[almuerzo_id]["hora_inicio"].startswith("11:00")
    r = cliente.post(
        "/reglas/horarios",
        json={
            "comida_id": almuerzo_id,
            "hora_inicio": "12:00:00",
            "hora_fin": "13:00:00",
            "vigente_desde": hoy.isoformat(),
            "motivo": MOTIVO,
        },
        headers=root,
    )
    assert r.status_code == 201, r.text
    assert r.json()["vigente_desde"] == hoy.isoformat()
    assert r.json()["vigente_hasta"] is None
    despues_ayer = {
        c["comida_id"]: c
        for c in cliente.get(
            "/reglas/horarios", params={"fecha": ayer.isoformat()}, headers=root
        ).json()
    }
    # Ayer resuelve a la MISMA versión y el MISMO horario; lo único que
    # cambia es el cierre: vigente_hasta pasa de None a ayer (hoy − 1).
    assert despues_ayer[almuerzo_id]["horario_id"] == antes_ayer[almuerzo_id]["horario_id"]
    assert despues_ayer[almuerzo_id]["hora_inicio"] == antes_ayer[almuerzo_id]["hora_inicio"]
    assert despues_ayer[almuerzo_id]["hora_fin"] == antes_ayer[almuerzo_id]["hora_fin"]
    assert (
        despues_ayer[almuerzo_id]["vigente_desde"]
        == antes_ayer[almuerzo_id]["vigente_desde"]
    )
    assert despues_ayer[almuerzo_id]["vigente_hasta"] == ayer.isoformat()
    hoy_almuerzo = {
        c["comida_id"]: c
        for c in cliente.get(
            "/reglas/horarios", params={"fecha": hoy.isoformat()}, headers=root
        ).json()
    }[almuerzo_id]
    assert hoy_almuerzo["hora_inicio"].startswith("12:00")
    historial = cliente.get(
        "/reglas/horarios/historial", params={"comida_id": almuerzo_id}, headers=root
    ).json()
    assert [h["vigente_desde"] for h in historial] == sorted(
        [h["vigente_desde"] for h in historial], reverse=True
    )
    anterior = next(h for h in historial if h["vigente_desde"] != hoy.isoformat())
    assert anterior["vigente_hasta"] == (hoy - timedelta(days=1)).isoformat()


def test_borrar_programado_reabre_anterior(cliente, root, con_horarios):
    comidas = _comidas()
    if "almuerzo" not in comidas:
        pytest.skip("v_comidas sin almuerzo")
    almuerzo_id, _ = comidas["almuerzo"]
    hoy = _fijar(date(2026, 9, 24))
    manana = hoy + timedelta(days=1)
    r = cliente.post(
        "/reglas/horarios",
        json={
            "comida_id": almuerzo_id,
            "hora_inicio": "12:00:00",
            "hora_fin": "13:00:00",
            "vigente_desde": manana.isoformat(),
            "motivo": MOTIVO,
        },
        headers=root,
    )
    assert r.status_code == 201, r.text
    nuevo_id = r.json()["horario_id"]
    r = cliente.delete(f"/reglas/horarios/{nuevo_id}", headers=root)
    assert r.status_code == 204, r.text
    historial = cliente.get(
        "/reglas/horarios/historial", params={"comida_id": almuerzo_id}, headers=root
    ).json()
    assert nuevo_id not in {h["horario_id"] for h in historial}
    assert historial[0]["vigente_hasta"] is None


def test_solape_con_programada_futura(cliente, root, con_horarios):
    comidas = _comidas()
    if "desayuno" not in comidas or "almuerzo" not in comidas:
        pytest.skip("faltan desayuno o almuerzo en v_comidas")
    desayuno_id, _ = comidas["desayuno"]
    almuerzo_id, _ = comidas["almuerzo"]
    hoy = _fijar(date(2026, 10, 1))
    dia_20 = date(2026, 10, 20)
    dia_15 = date(2026, 10, 15)
    r = cliente.post(
        "/reglas/horarios",
        json={
            "comida_id": almuerzo_id,
            "hora_inicio": "10:30:00",
            "hora_fin": "14:00:00",
            "vigente_desde": dia_20.isoformat(),
            "motivo": MOTIVO,
        },
        headers=root,
    )
    assert r.status_code == 201, r.text
    assert hoy < dia_15 < dia_20
    r = cliente.post(
        "/reglas/horarios",
        json={
            "comida_id": desayuno_id,
            "hora_inicio": "05:30:00",
            "hora_fin": "11:00:00",
            "vigente_desde": dia_15.isoformat(),
            "motivo": MOTIVO,
        },
        headers=root,
    )
    assert r.status_code == 409, r.text
    assert r.json()["motivo"] == "solapa_con_otra_comida"


def test_solape_al_reves_programar_la_otra(cliente, root, con_horarios):
    comidas = _comidas()
    if "desayuno" not in comidas or "almuerzo" not in comidas:
        pytest.skip("faltan desayuno o almuerzo en v_comidas")
    desayuno_id, _ = comidas["desayuno"]
    almuerzo_id, _ = comidas["almuerzo"]
    _fijar(date(2026, 10, 1))
    r = cliente.post(
        "/reglas/horarios",
        json={
            "comida_id": desayuno_id,
            "hora_inicio": "05:30:00",
            "hora_fin": "11:00:00",
            "vigente_desde": date(2026, 10, 15).isoformat(),
            "motivo": MOTIVO,
        },
        headers=root,
    )
    assert r.status_code == 201, r.text
    r = cliente.post(
        "/reglas/horarios",
        json={
            "comida_id": almuerzo_id,
            "hora_inicio": "10:30:00",
            "hora_fin": "14:00:00",
            "vigente_desde": date(2026, 10, 20).isoformat(),
            "motivo": MOTIVO,
        },
        headers=root,
    )
    assert r.status_code == 409, r.text
    assert r.json()["motivo"] == "solapa_con_otra_comida"


# --- borrado de derecho --------------------------------------------------------


def test_borrar_derecho_programado(cliente, root):
    hoy = _fijar(date(2026, 9, 24))
    manana = hoy + timedelta(days=1)
    r = cliente.post(
        "/reglas/derecho",
        json={
            "vigente_desde": manana.isoformat(),
            "duracion_minima_horas": 12,
            "novedades_que_anulan": [],
            "excluir_enfermeria": True,
            "motivo": MOTIVO,
        },
        headers=root,
    )
    assert r.status_code == 201, r.text
    version_id = r.json()["id"]
    r = cliente.delete(f"/reglas/derecho/{version_id}", headers=root)
    assert r.status_code == 204, r.text
    ids = {v["id"] for v in cliente.get("/reglas/derecho", headers=root).json()["versiones"]}
    assert version_id not in ids


def test_no_borrar_vigente_ni_pasada(cliente, root):
    _fijar(date(2026, 9, 24))
    base_id = cliente.get("/reglas/derecho", headers=root).json()["vigente"]["id"]
    r = cliente.delete(f"/reglas/derecho/{base_id}", headers=root)
    assert r.status_code == 409, r.text
    assert r.json()["motivo"] == "version_ya_vigente"
    r = cliente.delete("/reglas/derecho/999999999", headers=root)
    assert r.status_code == 404, r.text
    assert r.json()["motivo"] == "version_inexistente"


# --- cada error con su motivo ---------------------------------------------------


def test_error_vigencia_en_el_pasado(cliente, root):
    hoy = _fijar(date(2026, 9, 24))
    ayer = hoy - timedelta(days=1)
    r = cliente.post(
        "/reglas/derecho",
        json={
            "vigente_desde": ayer.isoformat(),
            "duracion_minima_horas": 12,
            "novedades_que_anulan": [],
            "excluir_enfermeria": True,
            "motivo": MOTIVO,
        },
        headers=root,
    )
    assert r.status_code == 422, r.text
    assert r.json()["motivo"] == "vigencia_en_el_pasado"


def test_error_motivo_obligatorio(cliente, root):
    hoy = _fijar(date(2026, 9, 24))
    for cuerpo in (
        {
            "vigente_desde": hoy.isoformat(),
            "duracion_minima_horas": 12,
            "novedades_que_anulan": [],
            "excluir_enfermeria": True,
            "motivo": "corto",
        },
        {
            "vigente_desde": hoy.isoformat(),
            "duracion_minima_horas": 12,
            "novedades_que_anulan": [],
            "excluir_enfermeria": True,
            "motivo": "   ",
        },
    ):
        r = cliente.post("/reglas/derecho", json=cuerpo, headers=root)
        assert r.status_code == 422, r.text
        assert r.json()["motivo"] == "motivo_obligatorio"


def test_error_version_en_esa_fecha_derecho(cliente, root):
    hoy = _fijar(date(2026, 9, 24))
    cuerpo = {
        "vigente_desde": hoy.isoformat(),
        "duracion_minima_horas": 12,
        "novedades_que_anulan": [],
        "excluir_enfermeria": True,
        "motivo": MOTIVO,
    }
    assert cliente.post("/reglas/derecho", json=cuerpo, headers=root).status_code == 201
    r = cliente.post("/reglas/derecho", json=cuerpo, headers=root)
    assert r.status_code == 409, r.text
    assert r.json()["motivo"] == "version_en_esa_fecha"


def test_errores_horarios(cliente, root, con_horarios):
    comidas = _comidas()
    if "almuerzo" not in comidas:
        pytest.skip("v_comidas sin almuerzo")
    almuerzo_id, _ = comidas["almuerzo"]
    hoy = _fijar(date(2026, 9, 24))
    base = {
        "comida_id": almuerzo_id,
        "hora_inicio": "12:00:00",
        "hora_fin": "13:00:00",
        "vigente_desde": hoy.isoformat(),
        "motivo": MOTIVO,
    }
    r = cliente.post(
        "/reglas/horarios",
        json={**base, "vigente_desde": (hoy - timedelta(days=1)).isoformat()},
        headers=root,
    )
    assert r.status_code == 422, r.text
    assert r.json()["motivo"] == "vigencia_en_el_pasado"
    r = cliente.post(
        "/reglas/horarios",
        json={**base, "hora_inicio": "12:00:00", "hora_fin": "12:00:00"},
        headers=root,
    )
    assert r.status_code == 422, r.text
    assert r.json()["motivo"] == "horario_invalido"
    r = cliente.post(
        "/reglas/horarios", json={**base, "motivo": "corto"}, headers=root
    )
    assert r.status_code == 422, r.text
    assert r.json()["motivo"] == "motivo_obligatorio"
    r = cliente.post(
        "/reglas/horarios", json={**base, "comida_id": 999999999}, headers=root
    )
    assert r.status_code == 404, r.text
    assert r.json()["motivo"] == "comida_inexistente"
    assert cliente.post("/reglas/horarios", json=base, headers=root).status_code == 201
    r = cliente.post("/reglas/horarios", json=base, headers=root)
    assert r.status_code == 409, r.text
    assert r.json()["motivo"] == "version_en_esa_fecha"
    r = cliente.delete("/reglas/horarios/999999999", headers=root)
    assert r.status_code == 404, r.text
    assert r.json()["motivo"] == "version_inexistente"
    vigente_id = cliente.get(
        "/reglas/horarios/historial", params={"comida_id": almuerzo_id}, headers=root
    ).json()[0]["horario_id"]
    _fijar(hoy + timedelta(days=30))
    r = cliente.delete(f"/reglas/horarios/{vigente_id}", headers=root)
    assert r.status_code == 409, r.text
    assert r.json()["motivo"] == "version_ya_vigente"


def test_solape_directo_entre_comidas(cliente, root, con_horarios):
    comidas = _comidas()
    if "desayuno" not in comidas or "almuerzo" not in comidas:
        pytest.skip("faltan desayuno o almuerzo")
    desayuno_id, _ = comidas["desayuno"]
    hoy = _fijar(date(2026, 9, 24))
    r = cliente.post(
        "/reglas/horarios",
        json={
            "comida_id": desayuno_id,
            "hora_inicio": "12:00:00",
            "hora_fin": "13:00:00",
            "vigente_desde": hoy.isoformat(),
            "motivo": MOTIVO,
        },
        headers=root,
    )
    assert r.status_code == 409, r.text
    assert r.json()["motivo"] == "solapa_con_otra_comida"


# --- permisos -------------------------------------------------------------------


@pytest.mark.parametrize(
    "metodo,ruta,cuerpo",
    [
        ("GET", "/reglas/derecho", None),
        ("GET", "/reglas/derecho/novedades", None),
        (
            "POST",
            "/reglas/derecho",
            {
                "vigente_desde": "2026-10-01",
                "duracion_minima_horas": 12,
                "novedades_que_anulan": [],
                "excluir_enfermeria": True,
                "motivo": MOTIVO,
            },
        ),
        ("DELETE", "/reglas/derecho/1", None),
        ("GET", "/reglas/horarios", None),
        ("GET", "/reglas/horarios/historial?comida_id=1", None),
        (
            "POST",
            "/reglas/horarios",
            {
                "comida_id": 1,
                "hora_inicio": "12:00:00",
                "hora_fin": "13:00:00",
                "vigente_desde": "2026-10-01",
                "motivo": MOTIVO,
            },
        ),
        ("DELETE", "/reglas/horarios/1", None),
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
    assert {"reglas_derecho", "reglas_derecho_novedad"} <= tablas
    unicos = {
        tuple(sorted(i["column_names"]))
        for i in inspect(motor).get_unique_constraints("reglas_derecho")
    }
    assert ("vigente_desde",) in unicos
    indices = {
        i["name"] for i in inspect(motor).get_indexes("horarios_comida")
    }
    assert "ix_horarios_comida_comida_id_vigente_desde" in indices
    for tabla in ("reglas_derecho", "reglas_derecho_novedad"):
        opciones = inspect(motor).get_table_options(tabla)
        assert opciones["mysql_collate"] == "utf8mb4_unicode_ci", tabla


def test_salud_cuenta_diez_tablas(cliente):
    r = cliente.get("/salud")
    assert r.status_code == 200, r.text
    assert r.json()["tablas_propias"] == 10
    assert r.json()["vistas_contrato"] == 9
