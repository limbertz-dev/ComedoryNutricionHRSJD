"""scripts/preparar_escenario_sintetico.py, en tres niveles que NO se sustituyen:

  1. UNITARIAS, sin MySQL (siempre corren). Funciones puras del script, su
     auditor de escrituras y, sobre un SQLite en memoria, las reglas de
     app/consultas/derecho.py aplicadas a una PROYECCIÓN de `v_comidas_por_turno`
     calculada en Python. Esa proyección no ejerce las vistas reales ni MySQL:
     solo prueba que la función de reglas decide como se espera con esas
     filas. En SQLite las filas viven en tablas `memoria_*` y las v_* son
     vistas encima; tests/test_zz_sin_escrituras_heredadas.py sigue intacto
     y revisa también ese SQL.

  2. PREPARACIÓN REAL en MySQL y 3. DERECHO CALCULADO por las vistas y reglas
     reales: solo con ESCENARIO_SINTETICO_INTEGRACION=1. Corren el script como
     proceso aparte sobre bases con nombre al azar que no existían (se
     comprueba) y que la prueba borra al final; nunca una base que no haya
     creado ella. El derecho de cada caso sale de las vistas v_* de la base
     propia, que leen la base sintética, y de app/consultas/derecho.py.

Por qué el script corre como proceso aparte: escribe tablas con nombre
heredado (`users`, `turnos_asignados`) dentro de su base sintética, y la regla
por nombre de test_zz las marcaría aunque no sean de la base de turnos. En vez
de debilitar test_zz, el script trae un auditor propio más estricto, que corta
la sentencia antes de ejecutarla. Las pruebas de integración aplican además la
expresión de test_zz, leída de su archivo, a todo el SQL que el script
registró: la única excepción admitida es la base sintética del escenario.
"""

import ast
import importlib.util
import json
import os
import re
import secrets
import subprocess
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

RAIZ = Path(__file__).resolve().parents[2]
SCRIPT = RAIZ / "scripts" / "preparar_escenario_sintetico.py"
VERSIONES = RAIZ / "comedorback" / "alembic" / "versions"
TEST_ZZ = Path(__file__).resolve().parent / "test_zz_sin_escrituras_heredadas.py"
FECHA = date(2026, 10, 20)
DEMO, SIM = "bd_x_demo", "bd_x_sim"


def _cargar(ruta: Path, nombre: str):
    """Importa un archivo SIN registrarlo en sys.modules."""
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="module")
def script():
    return _cargar(SCRIPT, "preparar_escenario_sintetico_prueba")


def _patron_test_zz() -> re.Pattern:
    """La expresión ESCRITURA de test_zz, leída de su fuente (importarlo
    traería conftest). Si alguien la cambia, estas pruebas usan la nueva."""
    arbol = ast.parse(TEST_ZZ.read_text(encoding="utf-8"))
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "ESCRITURA" for t in nodo.targets
        ):
            llamada = nodo.value
            return re.compile(ast.literal_eval(llamada.args[0]), re.IGNORECASE)
    raise AssertionError("test_zz ya no define ESCRITURA")


def _test_zz_la_marca(patron, sentencia: str, base_turnos: str = "bd_proyecto_backend"):
    from app.core.tablas_heredadas import TABLAS_HEREDADAS, VISTAS_CONTRATO, VISTAS_HEREDADAS

    prohibidas = TABLAS_HEREDADAS | VISTAS_HEREDADAS | set(VISTAS_CONTRATO)
    m = patron.match(sentencia)
    return bool(m) and (
        (m.group(1) or "").lower() == base_turnos.lower() or m.group(2).lower() in prohibidas
    )


# =====================================================================================
# 1. UNITARIAS (sin MySQL)
# =====================================================================================

# --- importar no tiene efectos -------------------------------------------------------


def test_importar_no_tiene_efectos(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["x.py", "--sim", "bd_nutricion"])
    entorno, cwd, modulos = dict(os.environ), os.getcwd(), set(sys.modules)

    modulo = _cargar(SCRIPT, "preparar_escenario_sintetico_importado")

    assert dict(os.environ) == entorno
    assert os.getcwd() == cwd
    assert "preparar_escenario_sintetico_importado" not in sys.modules
    nuevos = set(sys.modules) - modulos
    assert not {m for m in nuevos if m.startswith(("app", "sqlalchemy", "preparar_"))}
    assert callable(modulo.main)


# --- nombres de bases ----------------------------------------------------------------


def test_los_nombres_por_defecto_son_validos(script):
    assert script.errores_de_nombres(
        script.DEMO_POR_DEFECTO, script.SIM_POR_DEFECTO, {"bd_nutricion", "bd_proyecto_backend"}
    ) == []


@pytest.mark.parametrize(
    "demo, sim, esperado",
    [
        ("bd_proyecto_backend", "bd_x_sim", "_demo"),
        ("bd_x_demo", "bd_nutricion", "_sim"),
        ("bd_turnos_demo", "bd_x_sim", "protegida"),  # clon con datos reales
        ("bd_x_demo", "bd_nutricion_sim", "protegida"),  # idem
        ("BD_TURNOS_DEMO", "bd_x_sim", "protegida"),
        ("bd_x_demo", "bd_x_demo", "_sim"),
        ("bd-x_demo", "bd_x_sim", "inválido"),
        ("bd_x`_demo", "bd_x_sim", "inválido"),
        ("bd_x_demo", "mi_propia_sim", "protegida"),  # la que diga .env
    ],
)
def test_nombres_rechazados(script, demo, sim, esperado):
    errores = script.errores_de_nombres(demo, sim, {"mi_propia_sim"})
    assert errores and any(esperado in e for e in errores), errores


# --- el escenario es sintético ---------------------------------------------------------


BINARIOS = re.compile(r"\b(BLOB|TINYBLOB|MEDIUMBLOB|LONGBLOB|BINARY|VARBINARY|BIT)\b", re.I)
BIOMETRICOS = re.compile(r"imagen|foto|huella|plantilla|template|biometr", re.I)


def test_ninguna_columna_binaria_ni_biometrica(script):
    for tabla, columnas in script.ESQUEMA.items():
        for nombre, definicion in columnas:
            assert not BINARIOS.search(definicion), (tabla, nombre)
            assert not BIOMETRICOS.search(nombre), (tabla, nombre)


def test_la_identificacion_simulada_es_solo_texto(script):
    (fila,) = script.CATALOGO["escenario_identificaciones"]
    assert fila["usuario_id"] == script.USUARIO_ID
    assert fila["origen"] == "simulado"
    assert all(isinstance(v, (str, int)) for v in fila.values())
    assert fila["identificador"].startswith("SIM-")


def test_ids_en_rangos_sinteticos(script):
    for tabla, filas in script.CATALOGO.items():
        if tabla == "comidas":  # los 4 tiempos de comida, 1..4 como en el módulo de turnos
            assert sorted(f["id"] for f in filas) == [1, 2, 3, 4]
            continue
        for fila in filas:
            clave = fila[script.clave_de(tabla)]
            assert isinstance(clave, str) or clave >= 9000, (tabla, clave)
    assert all(900_001 <= c["usuario_id"] <= 900_999 for c in script.CASOS)
    assert len({c["usuario_id"] for c in script.CASOS}) == len(script.CASOS)
    assert len({c["login"] for c in script.CASOS}) == len(script.CASOS)


def test_ids_de_asignacion_deterministas_unicos_y_su_formula_sql(script):
    filas = script.filas_de_la_fecha(FECHA)["turnos_asignados"]
    assert filas == script.filas_de_la_fecha(FECHA)["turnos_asignados"]
    otra = script.filas_de_la_fecha(FECHA + timedelta(days=1))["turnos_asignados"]
    ids = [f["id"] for f in filas + otra]
    assert len(ids) == len(set(ids))
    # _sin_filas_ajenas recalcula cada id en SQL con DATEDIFF desde el ancla.
    for fila in filas + otra:
        fecha = date.fromisoformat(fila["fecha"])
        en_sql = (
            script.BASE_ID_ASIGNACION
            + (fila["usuario_id"] - script.BASE_USUARIO) * 1_000_000
            + script.ANCLA_ORDINAL.toordinal()
            + (fecha - script.ANCLA_ORDINAL).days
        )
        assert en_sql == fila["id"]


def test_cada_negativo_difiere_del_principal_en_un_solo_factor(script):
    principal = script.caso("principal")
    factores = ("categoria_id", "turno_id", "novedad", "desfase")
    for c in script.CASOS:
        if not c["caso"].startswith("negativo_"):
            continue
        distintos = [f for f in factores if c[f] != principal[f]]
        assert len(distintos) == 1, (c["caso"], distintos)
        assert c["derecho"] is False and c["factor"]
    contraste = script.caso("contraste_novedad")
    assert [f for f in factores if contraste[f] != principal[f]] == []
    assert contraste["derecho"] is True


def test_el_catalogo_encaja_con_las_semillas_y_las_reglas(script):
    from app.consultas.derecho import DURACION_MINIMA_HORAS
    from app.semillas.coeficientes import COEFICIENTES
    from app.semillas.horarios import HORARIOS
    from app.semillas.mapeo_categorias import MAPEO

    turnos = {t["id"]: t for t in script.CATALOGO["turnos"]}
    assert turnos[script.TURNO_12H]["duracion_horas"] == 12 >= DURACION_MINIMA_HORAS
    assert turnos[script.TURNO_8H]["duracion_horas"] < DURACION_MINIMA_HORAS
    mapeados = {tc["turno_id"]: tc for tc in script.CATALOGO["turno_comida"]}
    assert script.TURNO_12H_SIN_COMIDA not in mapeados
    assert mapeados[script.TURNO_12H]["comida_id"] == script.COMIDA_ID
    assert mapeados[script.TURNO_12H]["dia_relativo"] == 0
    comidas = {c["id"]: c["codigo"] for c in script.CATALOGO["comidas"]}
    assert comidas[script.COMIDA_ID] == script.COMIDA_CODIGO == "almuerzo"
    assert script.COMIDA_CODIGO in {c for c, *_ in HORARIOS}
    assert script.COMIDA_CODIGO in {c for c, _ in COEFICIENTES}
    assert script.CATEGORIA_NOMBRE in {n for n, _ in MAPEO}
    assert "enfermer" not in script.CATEGORIA_NOMBRE.lower()


def test_comensales_y_cuentas_separados(script):
    assert script.caso("principal")["login"] == script.USUARIO_LOGIN == "usuariosimulado"
    # En esta etapa solo las dos cocineras: jefa y sistemas no se crean.
    assert [(c["username"], c["rol"]) for c in script.CUENTAS] == [
        ("cocinera2", "cocinera"), ("cocinera3", "cocinera"),
    ]
    assert not {c["username"] for c in script.CUENTAS} & {c["login"] for c in script.CASOS}
    assert len({c["nombre"] for c in script.CUENTAS}) == 2


def test_sin_env_la_conexion_sale_solo_de_variables_de_entorno(script):
    todas = {"DB_HOST": "h", "DB_PORT": "1", "DB_USER": "u", "DB_PASSWORD": ""}
    assert script.variables_faltantes(todas, hay_env=False) == []
    assert script.variables_faltantes({}, hay_env=False) == [
        "DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD",
    ]
    assert script.variables_faltantes({"DB_HOST": "h"}, hay_env=False) == [
        "DB_PORT", "DB_USER", "DB_PASSWORD",
    ]
    assert script.variables_faltantes({}, hay_env=True) == []


# --- el esquema mínimo cubre exactamente lo que leen las vistas ---------------------------


def _cuerpos_de_vistas() -> list[str]:
    cuerpos = []
    for archivo in ("0c294cd98c3a_vistas_contrato_turnos.py", "2555bc00750e_cuentas_desde_el_padron.py"):
        modulo = _cargar(VERSIONES / archivo, f"migracion_{archivo[:12]}")
        for valor in vars(modulo).values():
            if isinstance(valor, str) and "{t}." in valor:
                cuerpos.append(valor)
            elif isinstance(valor, dict):
                cuerpos += [v for v in valor.values() if isinstance(v, str) and "{t}." in v]
    assert len(cuerpos) >= 10  # 9 vistas + la v_comensales con login
    return cuerpos


def _referencias(cuerpo: str) -> dict[str, set[str]]:
    usadas: dict[str, set[str]] = defaultdict(set)
    alias: dict[str, str] = {}
    for m in re.finditer(r"(?:FROM|JOIN)\s+\{t\}\.`(\w+)`(?:[ \t]+(?!ON\b|GROUP\b)(\w+))?", cuerpo):
        tabla, a = m.groups()
        usadas[tabla]
        if a:
            alias[a] = tabla
    for a, columna in re.findall(r"\b(\w+)\.`(\w+)`", cuerpo):
        if a in alias:
            usadas[alias[a]].add(columna)
    # SELECT sin alias sobre una sola tabla (catálogos y la subconsulta de fichas).
    for m in re.finditer(
        r"SELECT\s+((?:(?!SELECT).)*?)\s+FROM\s+\{t\}\.`(\w+)`(?![ \t]+(?!GROUP\b)\w)((?:\s+GROUP BY\s+`\w+`)?)",
        cuerpo,
        re.S,
    ):
        lista, tabla, grupo = m.groups()
        lista = re.sub(r"AS\s+`\w+`", "", lista)
        usadas[tabla] |= set(re.findall(r"`(\w+)`", lista + grupo))
    return usadas


def test_el_esquema_minimo_es_exactamente_el_que_leen_las_vistas(script):
    leidas: dict[str, set[str]] = defaultdict(set)
    for cuerpo in _cuerpos_de_vistas():
        for tabla, columnas in _referencias(cuerpo).items():
            leidas[tabla] |= columnas
    propias = {script.MARCADOR_TABLA, "escenario_identificaciones"}
    esquema = {
        t: {c for c, _ in columnas} for t, columnas in script.ESQUEMA.items() if t not in propias
    }
    assert set(leidas) == set(esquema)
    for tabla in esquema:
        assert leidas[tabla] == esquema[tabla], tabla


def test_ddl_solo_crea_dentro_de_la_base_pedida(script):
    for tabla in script.ESQUEMA:
        ddl = script.ddl_tabla(DEMO, tabla)
        assert ddl.startswith(f"CREATE TABLE IF NOT EXISTS `{DEMO}`.`{tabla}`")
        assert "utf8mb4_unicode_ci" in ddl
        for destino in re.findall(r"REFERENCES (\S+) ", ddl):
            assert re.fullmatch(r"`\w+`", destino), destino
            assert destino.strip("`") in script.ESQUEMA
    assert script.tipo_base("BIGINT UNSIGNED NOT NULL") == "bigint"
    assert script.tipo_base("ENUM('simulado') NOT NULL") == "enum"


def _sql_del_script() -> list[str]:
    """Los fragmentos de texto de cada `text(...)` del script: el SQL que
    ejecuta (el DDL sale de ddl_tabla y se prueba aparte)."""
    arbol = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    fragmentos = []
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name) and nodo.func.id == "text":
            partes = [n.value for n in ast.walk(nodo.args[0]) if isinstance(n, ast.Constant)
                      and isinstance(n.value, str)]
            fragmentos.append("".join(partes))
    assert len(fragmentos) > 20
    return fragmentos


def test_el_sql_del_script_nunca_borra_ni_actualiza(script):
    for sql in _sql_del_script():
        assert not re.search(
            r"\b(DELETE|UPDATE\s|DROP|TRUNCATE|ALTER|REPLACE\s+INTO|RENAME)\b", sql, re.I
        ), sql
    destinos = {
        m for sql in _sql_del_script() for m in re.findall(r"INSERT INTO\s+(\S+)", sql)
    }
    # demo.marcador / demo.<tabla del ESQUEMA> / usuarios_sistema por el motor
    # de --sim / la novedad del contraste, en la base de turnos de la
    # simulación (DB_NAME_TURNOS = --demo) y dentro de una transacción revertida.
    assert destinos == {"``.``", "usuarios_sistema", "``.`novedades_laborales`"}, destinos
    fuente = SCRIPT.read_text(encoding="utf-8")
    assert "make_url(config.url_base_datos).set(database=args.sim)" in fuente
    assert "transaccion.rollback()" in fuente
    assert not re.search(r"INSERT INTO\s+\S*(asistencias|lecturas_biometricas)", fuente)
    assert "registrar_marcacion" not in fuente


# --- auditor de escrituras ----------------------------------------------------------


def _veredicto(script, sentencia, paso, base_conexion=SIM):
    from app.core.tablas_heredadas import TABLAS_HEREDADAS, VISTAS_CONTRATO, VISTAS_HEREDADAS

    escritura = script.clasificar_escritura(sentencia, base_conexion)
    if escritura is None:
        return "lectura"
    motivo = script.motivo_de_rechazo(
        escritura, sentencia, paso=paso, demo=DEMO, sim=SIM,
        propias=frozenset({"asistencias", "usuarios_sistema", "horarios_comida",
                           "categoria_reporte_map", "coeficientes_racion"}),
        heredadas=frozenset(t.lower() for t in TABLAS_HEREDADAS),
        vistas=frozenset(v.lower() for v in set(VISTAS_CONTRATO) | VISTAS_HEREDADAS),
    )
    return "ok" if motivo is None else "rechazada"


AUTORIZADAS = [
    ("principal", "CREATE DATABASE `bd_x_demo` CHARACTER SET utf8mb4", None),
    ("principal", "CREATE DATABASE `bd_x_sim` CHARACTER SET utf8mb4", None),
    ("principal", "CREATE TABLE IF NOT EXISTS `bd_x_demo`.`users` (`id` BIGINT)", None),
    ("principal", "INSERT INTO `bd_x_demo`.`turnos_asignados` (`id`) VALUES (%(id)s)", None),
    ("principal", "INSERT INTO `bd_x_demo`.`escenario_sintetico` (clave) VALUES (%(c)s)", None),
    ("principal", "INSERT INTO usuarios_sistema (username) VALUES (%(u)s)", SIM),
    ("alembic", "CREATE TABLE alembic_version (version_num VARCHAR(32))", SIM),
    ("alembic", "INSERT INTO alembic_version (version_num) VALUES ('x')", SIM),
    ("alembic", "UPDATE alembic_version SET version_num='y'", SIM),
    ("alembic", "ALTER TABLE asistencias ADD COLUMN x INT", SIM),
    ("alembic", "CREATE INDEX ix_a ON asistencias (x)", SIM),
    ("alembic", "CREATE OR REPLACE SQL SECURITY INVOKER VIEW `v_comidas` AS SELECT `id` FROM `bd_x_demo`.`comidas`", SIM),
    ("semilla", "INSERT INTO horarios_comida (comida_id) VALUES (%(c)s)", SIM),
    ("evidencia", "INSERT INTO `bd_x_demo`.`novedades_laborales` (`id`) VALUES (%(id)s)", SIM),
]

RECHAZADAS = [
    # fuera del escenario
    ("principal", "INSERT INTO `bd_proyecto_backend`.`users` (id) VALUES (1)", None),
    ("principal", "INSERT INTO `bd_nutricion`.`usuarios_sistema` (id) VALUES (1)", None),
    ("principal", "CREATE DATABASE `bd_nutricion_sim`", None),
    ("principal", "CREATE DATABASE `otra_demo`", None),
    ("principal", "INSERT INTO usuarios_sistema (id) VALUES (1)", None),  # sin base
    ("evidencia", "INSERT INTO `bd_turnos_demo`.`novedades_laborales` (id) VALUES (1)", SIM),
    # vistas heredadas o del contrato, en cualquier base
    ("principal", "INSERT INTO `bd_x_demo`.`v_comensales` (x) VALUES (1)", None),
    ("alembic", "INSERT INTO v_comidas_por_turno (x) VALUES (1)", SIM),
    ("alembic", "UPDATE v_novedades_laborales SET x = 1", SIM),
    ("alembic", "DROP VIEW IF EXISTS `v_comensales`", SIM),
    ("alembic", "ALTER TABLE vw_personal_comidas_externo ADD x INT", SIM),
    # nombres heredados fuera de la base sintética
    ("alembic", "CREATE TABLE users (id INT)", SIM),
    ("semilla", "INSERT INTO turnos_asignados (id) VALUES (1)", SIM),
    # nunca borra, actualiza ni trunca en sus propios pasos
    ("principal", "UPDATE `bd_x_demo`.`users` SET name = 'x'", None),
    ("principal", "DELETE FROM `bd_x_demo`.`novedades_laborales`", None),
    ("principal", "TRUNCATE TABLE `bd_x_demo`.`users`", None),
    ("principal", "DROP DATABASE `bd_x_demo`", None),
    ("principal", "DROP TABLE `bd_x_demo`.`users`", None),
    ("semilla", "DELETE FROM horarios_comida", SIM),
    ("alembic", "DROP TABLE asistencias", SIM),
    ("evidencia", "UPDATE asistencias SET x = 1", SIM),
    ("evidencia", "INSERT INTO asistencias (id) VALUES (1)", SIM),
    # alembic: vistas que leen otra base, tablas que no son propias, FK afuera
    ("alembic", "CREATE OR REPLACE SQL SECURITY INVOKER VIEW `v_comidas` AS SELECT `id` FROM `bd_proyecto_backend`.`comidas`", SIM),
    ("alembic", "CREATE OR REPLACE VIEW `v_mia` AS SELECT 1 FROM `bd_x_demo`.`comidas`", SIM),
    ("alembic", "CREATE TABLE tabla_ajena (id INT)", SIM),
    ("alembic", "ALTER TABLE asistencias ADD FOREIGN KEY (u) REFERENCES `bd_proyecto_backend`.`users` (id)", SIM),
    # lo que no se sabe clasificar no se ejecuta
    ("principal", "LOAD DATA INFILE 'x' INTO TABLE `bd_x_demo`.`users`", None),
    ("principal", "GRANT ALL ON *.* TO x", None),
    ("principal", "WITH x AS (SELECT 1) DELETE FROM `bd_x_demo`.`users`", None),
    ("principal", "RENAME TABLE `bd_x_demo`.`users` TO `bd_x_demo`.`u2`", None),
]


@pytest.mark.parametrize("paso, sentencia, base", AUTORIZADAS)
def test_auditor_autoriza_solo_destinos_sinteticos(script, paso, sentencia, base):
    assert _veredicto(script, sentencia, paso, base) == "ok"


@pytest.mark.parametrize("paso, sentencia, base", RECHAZADAS)
def test_auditor_rechaza(script, paso, sentencia, base):
    assert _veredicto(script, sentencia, paso, base) == "rechazada"


@pytest.mark.parametrize(
    "sentencia",
    ["SELECT * FROM users", "SELECT id FROM cerrojos FOR UPDATE", "SHOW CREATE TABLE x",
     "SET SESSION sql_mode = ''", "CHECKSUM TABLE `bd_x_demo`.`users`", "ROLLBACK", "SAVEPOINT s1",
     "WITH x AS (SELECT 1) SELECT * FROM x"],
)
def test_auditor_deja_pasar_lecturas(script, sentencia):
    assert script.clasificar_escritura(sentencia, SIM) is None


def test_auditor_es_al_menos_tan_estricto_como_test_zz(script):
    """Toda sentencia que test_zz marca como escritura ajena la rechaza el
    auditor en todos los pasos, salvo una: la tabla de nombre heredado DENTRO
    de la base sintética del escenario, en el paso principal."""
    patron = _patron_test_zz()
    corpus = [s for _, s, _ in AUTORIZADAS + RECHAZADAS] + [
        script.ddl_tabla(DEMO, t) for t in script.ESQUEMA
    ] + [
        "INSERT INTO users (id) VALUES (1)",
        "INSERT INTO `bd_proyecto_backend`.`turnos` (id) VALUES (1)",
        "UPDATE `bd_proyecto_backend`.`comidas` SET estado = 0",
        "DELETE FROM `v_comensales`",
        "REPLACE INTO turno_comida VALUES (1)",
        "TRUNCATE TABLE novedades_laborales",
        "ALTER TABLE `bd_proyecto_backend`.`users` ADD x INT",
    ]
    marcadas = [s for s in corpus if _test_zz_la_marca(patron, s)]
    assert len(marcadas) > 15
    for sentencia in marcadas:
        for paso in script.PASOS:
            for base in (None, SIM, DEMO):
                veredicto = _veredicto(script, sentencia, paso, base)
                escritura = script.clasificar_escritura(sentencia, base)
                excepcion = (
                    paso == "principal"
                    and escritura["base"] == DEMO
                    and escritura["verbo"] in {"CREATE TABLE", "INSERT"}
                    and escritura["objeto"] in script.ESQUEMA
                ) or (
                    paso == "evidencia"
                    and escritura["base"] == DEMO
                    and escritura["verbo"] == "INSERT"
                    and escritura["objeto"] == "novedades_laborales"
                )
                assert veredicto == ("ok" if excepcion else "rechazada"), (paso, base, sentencia)


def test_el_auditor_corta_la_sentencia_antes_de_ejecutarla(script, tmp_path):
    """Con el listener real sobre un SQLite: lo rechazado no llega a la base
    y queda anotado; lo autorizado se ejecuta. Sin nombres heredados, para no
    ensuciar el registro de test_zz con sentencias de prueba."""
    motor = create_engine("sqlite://")
    registro = tmp_path / "auditoria.jsonl"
    with motor.begin() as cx:
        cx.exec_driver_sql("CREATE TABLE tabla_x (id INT)")
    quitar = script.instalar_auditor(
        paso="principal", demo=DEMO, sim=SIM, registro=registro, objetivo=motor,
        propias=frozenset(), base_conexion=lambda conexion: DEMO,
    )
    try:
        with pytest.raises(script.AuditoriaViolada):
            with motor.begin() as cx:
                cx.exec_driver_sql("INSERT INTO tabla_x VALUES (1)")  # tabla_x no es del ESQUEMA
        with motor.begin() as cx:
            cx.exec_driver_sql("CREATE TABLE escenario_identificaciones (identificador TEXT)")
    finally:
        quitar()
    with motor.connect() as cx:
        assert cx.exec_driver_sql("SELECT COUNT(*) FROM tabla_x").scalar_one() == 0
        assert cx.exec_driver_sql(
            "SELECT COUNT(*) FROM sqlite_master WHERE name = 'escenario_identificaciones'"
        ).scalar_one() == 1
    anotadas = [json.loads(linea) for linea in registro.read_text(encoding="utf-8").splitlines()]
    assert [(a["objeto"], a["autorizada"]) for a in anotadas] == [
        ("tabla_x", False), ("escenario_identificaciones", True),
    ]
    assert script.problemas_de_auditoria(anotadas, DEMO, SIM)


# --- colisiones --------------------------------------------------------------------


def _marcador(script, sim=SIM, **cambios):
    return {"clave": script.MARCADOR_CLAVE, "version": script.MARCADOR_VERSION, "base_sim": sim, **cambios}


def _clasificar(script, **cambios):
    datos = dict(
        demo_existe=False, marcador=None, sim=SIM, sim_existe=False,
        sim_tablas=set(), vistas_sim={}, demo=DEMO,
    )
    datos.update(cambios)
    return script.clasificar(**datos)


def test_bases_ausentes_se_crean(script):
    assert _clasificar(script) == ("ausente", "ausente", [])


def test_bases_propias_se_reutilizan(script):
    vistas = {"v_comensales": f"select ... from `{DEMO}`.`users`"}
    resultado = _clasificar(
        script, demo_existe=True, marcador=_marcador(script), sim_existe=True,
        sim_tablas={"alembic_version", "asistencias"}, vistas_sim=vistas,
    )
    assert resultado == ("propia", "propia", [])
    # Corrida interrumpida tras crear --sim vacía: también es propia.
    assert _clasificar(script, demo_existe=True, marcador=_marcador(script), sim_existe=True)[:2] == (
        "propia", "propia",
    )


@pytest.mark.parametrize(
    "cambios",
    [
        dict(demo_existe=True, marcador=None),
        dict(demo_existe=True, marcador={"clave": "otra", "version": 2, "base_sim": SIM}),
        dict(demo_existe=True, marcador={"clave": "comedor-escenario-sintetico", "version": 1, "base_sim": SIM}),
        dict(demo_existe=True, marcador={"clave": "comedor-escenario-sintetico", "version": 2, "base_sim": "bd_otra_sim"}),
        dict(sim_existe=True),
        dict(sim_existe=True, sim_tablas={"alembic_version"}),
    ],
)
def test_colisiones_ajenas_abortan(script, cambios):
    estado_demo, estado_sim, motivos = _clasificar(script, **cambios)
    assert "ajena" in (estado_demo, estado_sim) and motivos


def test_sim_propia_con_vistas_a_otra_base_es_ajena(script):
    estado = _clasificar(
        script, demo_existe=True, marcador=_marcador(script), sim_existe=True,
        sim_tablas={"alembic_version"}, vistas_sim={"v_comidas": "from `bd_proyecto_backend`.`comidas`"},
    )
    assert estado[1] == "ajena"
    estado = _clasificar(
        script, demo_existe=True, marcador=_marcador(script), sim_existe=True, sim_tablas={"otra"},
    )
    assert estado[1] == "ajena"


def _cuenta(script, username, **cambios):
    plan = next(c for c in script.CUENTAS if c["username"] == username)
    fila = dict(username=username, rol=plan["rol"], activo=1, debe_cambiar=1,
                usuario_turnos_id=None, nombre=plan["nombre"])
    fila.update(cambios)
    return fila


def test_cuentas_propias_existentes_no_son_conflicto(script):
    existentes = {c["username"]: _cuenta(script, c["username"]) for c in script.CUENTAS}
    assert script.errores_de_cuentas(existentes) == []
    assert script.errores_de_cuentas({}) == []


@pytest.mark.parametrize(
    "username, cambios",
    [
        ("cocinera2", dict(rol="jefa")),
        ("cocinera2", dict(nombre=None)),  # la creó otro (p. ej. app.semillas.admin)
        ("cocinera3", dict(usuario_turnos_id=123)),
        ("cocinera3", dict(activo=0)),  # dada de baja: no se reactiva
        ("cocinera3", dict(rol="sistemas")),
        ("cocinera2", dict(usuario_turnos_id=900003)),
    ],
)
def test_cuentas_en_conflicto(script, username, cambios):
    assert script.errores_de_cuentas({username: _cuenta(script, username, **cambios)})


@pytest.mark.parametrize("login", ["usuariosimulado", "simneg_novedad"])
def test_ningun_comensal_puede_tener_cuenta(script, login):
    fila = dict(username=login, rol="jefa", activo=1, debe_cambiar=0, usuario_turnos_id=None, nombre=None)
    assert script.errores_de_cuentas({login: fila})


# --- claves: se piden, se validan y nunca se muestran --------------------------------------


def _claves_en_entorno(monkeypatch, **valores):
    for cuenta in ("COCINERA2", "COCINERA3"):
        monkeypatch.delenv(f"ESCENARIO_CLAVE_{cuenta}", raising=False)
    for nombre, valor in valores.items():
        monkeypatch.setenv(f"ESCENARIO_CLAVE_{nombre.upper()}", valor)


def test_claves_desde_el_entorno_sin_mostrarlas(script, monkeypatch, capsys):
    _claves_en_entorno(monkeypatch, cocinera2="clave-prueba-dos", cocinera3="clave-prueba-tres")
    claves = script._pedir_claves(list(script.CUENTAS), 8, False)
    assert claves == {"cocinera2": "clave-prueba-dos", "cocinera3": "clave-prueba-tres"}
    salida = capsys.readouterr()
    assert "clave-prueba" not in salida.out + salida.err


def test_claves_sin_revelar_al_azar_y_distintas(script, monkeypatch, capsys):
    _claves_en_entorno(monkeypatch)
    claves = script._pedir_claves(list(script.CUENTAS), 8, True)
    assert set(claves) == {"cocinera2", "cocinera3"}
    assert len(set(claves.values())) == 2 and all(len(c) >= 32 for c in claves.values())
    salida = capsys.readouterr()
    assert not any(c in salida.out + salida.err for c in claves.values())


@pytest.mark.parametrize(
    "dos, tres, esperado",
    [
        ("corta", "clave-prueba-tres", "menos de 8"),
        ("cocinera2", "clave-prueba-tres", "nombre de usuario"),
        ("misma-clave-larga", "misma-clave-larga", "distintas"),
        ("x" * 73, "clave-prueba-tres", "72 bytes"),
    ],
)
def test_claves_rechazadas_sin_eco(script, monkeypatch, dos, tres, esperado):
    _claves_en_entorno(monkeypatch, cocinera2=dos, cocinera3=tres)
    with pytest.raises(script.Abortado) as error:
        script._pedir_claves(list(script.CUENTAS[:2]), 8, False)
    assert esperado in str(error.value)
    assert dos not in str(error.value) or dos == "cocinera2"


def test_sin_consola_y_sin_variable_aborta(script, monkeypatch):
    _claves_en_entorno(monkeypatch)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    with pytest.raises(script.Abortado, match="ESCENARIO_CLAVE_COCINERA3"):
        script._pedir_claves([script.CUENTAS[1]], 8, False)


def test_solo_se_piden_las_claves_de_las_cuentas_que_faltan(script, monkeypatch):
    _claves_en_entorno(monkeypatch)
    assert script._pedir_claves([], 8, False) == {}


# --- reglas sobre una PROYECCIÓN SQLite (no son las vistas ni MySQL) ---------------------------


MIGRACION_REGLAS = "f13dd53094ae_reglas_de_derecho_versionadas.py"


def _proyeccion(script, fecha):
    """Filas con la forma de `v_comidas_por_turno` calculadas EN PYTHON a partir
    del plan del script: asignación ⋈ turno ⋈ turno_comida ⋈ comida ⋈ user ⟕
    categoría, fecha_comida = fecha + dia_relativo. Es una réplica a mano de
    la vista: lo que valide sobre ella no vale para la vista real."""
    c = script.CATALOGO
    turnos = {t["id"]: t for t in c["turnos"]}
    comidas = {x["id"]: x for x in c["comidas"]}
    usuarios = {u["id"]: u for u in c["users"]}
    categorias = {x["id"]: x for x in c["categorias"]}
    filas = []
    for ta in script.filas_de_la_fecha(fecha)["turnos_asignados"]:
        t = turnos[ta["turno_id"]]
        for tc in (x for x in c["turno_comida"] if x["turno_id"] == t["id"]):
            u = usuarios[ta["usuario_id"]]
            dia = date.fromisoformat(ta["fecha"])
            filas.append(dict(
                turno_asignado_id=ta["id"], usuario_id=u["id"], servicio_id=ta["servicio_id"],
                fecha_turno=dia.isoformat(), dia_relativo=tc["dia_relativo"],
                fecha_comida=(dia + timedelta(days=tc["dia_relativo"])).isoformat(),
                comida_id=tc["comida_id"], comida=comidas[tc["comida_id"]]["nombre"],
                turno_id=t["id"], turno=t["nombre_turno"], duracion_horas=t["duracion_horas"],
                categoria_id=u["categoria_id"], categoria=categorias[u["categoria_id"]]["nombre"],
            ))
    return filas


def _base_en_memoria(script, fecha=FECHA):
    """SQLite en memoria. Las filas van a tablas `memoria_*` y las v_* son
    vistas encima, para que el ORM de la app las lea con su nombre. Esto no
    esquiva test_zz: lo que se prueba acá es la función de reglas, y el
    registro de test_zz ve todo este SQL igual."""
    reglas = _cargar(VERSIONES / MIGRACION_REGLAS, "migracion_reglas_prueba")
    motor = create_engine("sqlite://")
    with motor.begin() as cx:
        cx.exec_driver_sql(
            "CREATE TABLE memoria_comidas_por_turno (turno_asignado_id INT, usuario_id INT, "
            "servicio_id INT, fecha_turno DATE, dia_relativo INT, fecha_comida DATE, comida_id INT, "
            "comida TEXT, turno_id INT, turno TEXT, duracion_horas INT, categoria_id INT, categoria TEXT)"
        )
        cx.exec_driver_sql(
            "CREATE TABLE memoria_novedades (id INT, asignacion_id INT, tipo_novedad TEXT, "
            "usuario_solicitante_id INT, usuario_reemplazo_id INT, fecha_original DATE, "
            "fecha_nueva DATE, con_devolucion INT)"
        )
        cx.exec_driver_sql(
            "CREATE TABLE reglas_derecho (id INT, vigente_desde DATE, duracion_minima_horas INT, "
            "excluir_enfermeria INT, motivo TEXT, creada_por_cuenta INT, created_at TIMESTAMP)"
        )
        cx.exec_driver_sql("CREATE TABLE reglas_derecho_novedad (id INT, regla_id INT, tipo_novedad TEXT)")
        cx.exec_driver_sql("CREATE VIEW v_comidas_por_turno AS SELECT * FROM memoria_comidas_por_turno")
        cx.exec_driver_sql("CREATE VIEW v_novedades_laborales AS SELECT * FROM memoria_novedades")
        # La versión base, tal como la inserta la migración f13dd53094ae.
        cx.execute(
            text("INSERT INTO reglas_derecho VALUES (1, :d, 12, 1, :m, NULL, NULL)"),
            {"d": reglas.BASE_DESDE, "m": reglas.BASE_MOTIVO},
        )
        for tipo in reglas.BASE_NOVEDADES:
            cx.execute(text("INSERT INTO reglas_derecho_novedad VALUES (NULL, 1, :t)"), {"t": tipo})
        for fila in _proyeccion(script, fecha):
            cx.execute(
                text(f"INSERT INTO memoria_comidas_por_turno ({', '.join(fila)}) "
                     f"VALUES ({', '.join(':' + k for k in fila)})"),
                fila,
            )
        for novedad in script.filas_de_la_fecha(fecha)["novedades_laborales"]:
            cx.execute(
                text(f"INSERT INTO memoria_novedades ({', '.join(novedad)}) "
                     f"VALUES ({', '.join(':' + k for k in novedad)})"),
                novedad,
            )
    return motor


def test_unitaria_reglas_sobre_la_proyeccion_deciden_cada_caso(script):
    from app.consultas import derecho

    with Session(_base_en_memoria(script)) as sesion:
        for c in script.CASOS:
            obtenido = derecho.buscar_derecho(sesion, c["usuario_id"], script.COMIDA_ID, FECHA)
            assert (obtenido is not None) == c["derecho"], c["caso"]
        assert derecho.contar_personas_con_derecho(sesion, script.COMIDA_ID, FECHA) == 2
        (unico,) = derecho.derechos_del_dia(sesion, script.USUARIO_ID, FECHA)
        assert (unico.comida_id, unico.fecha_comida, unico.dia_relativo) == (script.COMIDA_ID, FECHA, 0)
        assert unico.turno_asignado_id == script.id_asignacion(FECHA)


def test_unitaria_contraste_de_novedad_sobre_la_proyeccion(script):
    from app.consultas import derecho

    motor = _base_en_memoria(script)
    asignacion = script.fila_asignacion(FECHA, script.CONTRASTE_ID)
    with motor.connect() as cx:
        transaccion = cx.begin()
        with Session(bind=cx) as sesion:
            assert derecho.buscar_derecho(sesion, script.CONTRASTE_ID, script.COMIDA_ID, FECHA)
            novedad = script.fila_novedad(asignacion, script.NOVEDAD_IMPEDITIVA)
            cx.execute(
                text(f"INSERT INTO memoria_novedades ({', '.join(novedad)}) "
                     f"VALUES ({', '.join(':' + k for k in novedad)})"),
                novedad,
            )
            assert derecho.buscar_derecho(sesion, script.CONTRASTE_ID, script.COMIDA_ID, FECHA) is None
        transaccion.rollback()
    with Session(motor) as sesion:
        assert derecho.buscar_derecho(sesion, script.CONTRASTE_ID, script.COMIDA_ID, FECHA)


# --- la evidencia decide si el escenario quedó listo -------------------------------------------


def _evidencia_buena(script):
    medido = lambda d, nov=(): {"derecho_al_almuerzo": d, "novedades_v_novedades_laborales": list(nov)}  # noqa: E731
    return {
        "casos": [
            {"caso": c["caso"], "derecho_esperado": c["derecho"], "derecho_al_almuerzo": c["derecho"]}
            for c in script.CASOS
        ],
        "contraste_novedad": {
            "sin_novedad": medido(True),
            "con_novedad": medido(False, [script.NOVEDAD_IMPEDITIVA]),
            "novedad_persistida_tras_revertir": 0,
        },
        "cuentas_de_comensales": 0,
        "comida_en_curso_a_mitad_de_ventana": {"comida_id": script.COMIDA_ID},
        "cuentas": [
            {"username": c["username"], "rol": c["rol"], "activo": True, "vinculo_padron": None}
            for c in script.CUENTAS
        ],
    }


def test_evidencia_completa_sin_problemas(script):
    assert script.problemas_de_evidencia(_evidencia_buena(script)) == []


@pytest.mark.parametrize(
    "romper",
    [
        lambda e: e["casos"][0].update(derecho_al_almuerzo=False),  # principal sin derecho
        lambda e: e["casos"][1].update(derecho_al_almuerzo=True),  # un negativo con derecho
        lambda e: e["contraste_novedad"]["sin_novedad"].update(derecho_al_almuerzo=False),
        lambda e: e["contraste_novedad"]["con_novedad"].update(derecho_al_almuerzo=True),
        lambda e: e["contraste_novedad"]["con_novedad"].update(novedades_v_novedades_laborales=[]),
        lambda e: e["contraste_novedad"].update(novedad_persistida_tras_revertir=1),
        lambda e: e.update(cuentas_de_comensales=1),
        lambda e: e.update(comida_en_curso_a_mitad_de_ventana=None),
        lambda e: e["cuentas"].pop(),
        lambda e: e["cuentas"][0].update(rol="jefa"),
        lambda e: e["cuentas"][1].update(vinculo_padron=5),
    ],
)
def test_evidencia_incompleta(script, romper):
    evidencia = _evidencia_buena(script)
    romper(evidencia)
    assert script.problemas_de_evidencia(evidencia)


# =====================================================================================
# 2 y 3. PREPARACIÓN REAL Y DERECHO POR LAS VISTAS REALES (MySQL, opt-in)
# =====================================================================================


integracion = pytest.mark.skipif(
    os.environ.get("ESCENARIO_SINTETICO_INTEGRACION") != "1",
    reason="contra MySQL solo con ESCENARIO_SINTETICO_INTEGRACION=1 (destino autorizado por Limbert)",
)


@pytest.fixture
def bases_nuevas():
    """Nombres al azar que NO existen; al final borra solo las que creó la prueba."""
    from app.core.config import config

    servidor = create_engine(config.url_servidor, isolation_level="AUTOCOMMIT")
    creadas: list[str] = []

    def nombres():
        sufijo = secrets.token_hex(4)
        demo, sim = f"bd_esc{sufijo}_demo", f"bd_esc{sufijo}_sim"
        with servidor.connect() as cx:
            for base in (demo, sim):
                assert cx.execute(
                    text("SELECT 1 FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = :b"), {"b": base}
                ).first() is None
        creadas.extend([demo, sim])
        return demo, sim

    yield servidor, nombres
    with servidor.connect() as cx:
        for base in creadas:
            assert re.fullmatch(r"bd_esc[0-9a-f]{8}_(demo|sim)", base)
            cx.execute(text(f"DROP DATABASE IF EXISTS `{base}`"))
    servidor.dispose()


def _correr(demo, sim, *extra, claves=None, fecha=FECHA):
    entorno = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    for cuenta in ("COCINERA2", "COCINERA3"):
        entorno.pop(f"ESCENARIO_CLAVE_{cuenta}", None)
    entorno.update(claves or {})
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--demo", demo, "--sim", sim, "--fecha", fecha.isoformat(), *extra],
        capture_output=True, text=True, encoding="utf-8", env=entorno, stdin=subprocess.DEVNULL,
    )


def _claves():
    return {
        "ESCENARIO_CLAVE_COCINERA2": "c2-" + secrets.token_urlsafe(12),
        "ESCENARIO_CLAVE_COCINERA3": "c3-" + secrets.token_urlsafe(12),
    }


def _foto(cx, base):
    tablas = cx.execute(
        text("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = :b AND TABLE_TYPE = 'BASE TABLE'"),
        {"b": base},
    ).scalars().all()
    return dict(cx.execute(text("CHECKSUM TABLE " + ", ".join(f"`{base}`.`{t}`" for t in sorted(tablas)))).all())


def _esquemas(cx):
    return set(cx.execute(text("SELECT SCHEMA_NAME FROM information_schema.SCHEMATA")).scalars())


def _auditoria(salida: str) -> list[dict]:
    ruta = re.search(r"Registro de auditoría \(SQL sin parámetros\): (.+)", salida).group(1).strip()
    return [json.loads(x) for x in Path(ruta).read_text(encoding="utf-8").splitlines() if x]


def _verificar_auditoria(registros, demo, sim):
    """Todo el SQL de escritura del preparador, de sus cuatro procesos."""
    from app.core.config import config
    from app.core.tablas_heredadas import VISTAS_CONTRATO, VISTAS_HEREDADAS

    assert {r["paso"] for r in registros} >= {"principal", "alembic", "semilla", "evidencia"}
    assert all(r["autorizada"] for r in registros)
    assert {r["base"] for r in registros} <= {demo, sim}
    vistas = {v.lower() for v in set(VISTAS_CONTRATO) | VISTAS_HEREDADAS}
    assert not [r for r in registros if r["objeto"].lower() in vistas and r["verbo"] != "CREATE VIEW"]
    assert {r["verbo"] for r in registros} & {"DELETE", "DROP TABLE", "DROP VIEW", "DROP DATABASE",
                                              "TRUNCATE"} == set()
    # La expresión de test_zz sobre el mismo SQL: solo marca escrituras dentro
    # de la base sintética del escenario, nunca en la base de turnos real.
    patron = _patron_test_zz()
    marcadas = [r for r in registros if _test_zz_la_marca(patron, r["sentencia"], config.db_name_turnos)]
    assert marcadas, "el preparador escribe users/turnos_asignados en la base sintética"
    assert {r["base"] for r in marcadas} == {demo}
    assert {r["paso"] for r in marcadas} <= {"principal", "evidencia"}


@integracion
def test_integracion_prepara_repite_sin_cambios_y_no_registra_racion(bases_nuevas, tmp_path):
    servidor, nombres = bases_nuevas
    demo, sim = nombres()
    claves = _claves()
    manifiesto = tmp_path / "manifiesto.json"
    with servidor.connect() as cx:
        antes = _esquemas(cx)

    primera = _correr(demo, sim, "--manifiesto", str(manifiesto), claves=claves)
    assert primera.returncode == 0, primera.stderr
    for clave in claves.values():
        assert clave not in primera.stdout + primera.stderr + manifiesto.read_text(encoding="utf-8")
    _verificar_auditoria(_auditoria(primera.stdout), demo, sim)

    datos = json.loads(manifiesto.read_text(encoding="utf-8"))
    assert [c["username"] for c in datos["cuentas"]] == ["cocinera2", "cocinera3"]
    assert all(c["rol"] == "cocinera" and c["vinculo_padron"] is None and c["debe_cambiar"]
               for c in datos["cuentas"])
    assert datos["comensal"]["usuario_id"] == 900001
    assert datos["comensal"]["cuentas_de_acceso_vinculadas"] == 0
    assert datos["derecho_principal"]["obtenido"] is True
    assert datos["turno"]["duracion_horas"] == 12 and datos["asignacion"]["fecha"] == FECHA.isoformat()
    assert datos["novedades_de_la_asignacion"] == []
    assert datos["ventana"]
    controles = datos["controles_12h_no_bastan"]
    assert {c["caso"] for c in controles} == {
        "negativo_categoria", "negativo_novedad", "negativo_sin_mapeo", "negativo_otra_fecha",
    }
    assert all(c["turno_horas"] == 12 and c["derecho_obtenido"] is False for c in controles)
    assert [c["caso"] for c in datos["control_adicional_duracion"]] == ["negativo_duracion"]
    assert datos["aislamiento"]["esquemas_creados"] == sorted([demo, sim])
    assert datos["aislamiento"]["base_propia"]["view_table_usage_esquemas"] == [demo]
    assert datos["aislamiento"]["escrituras_fuera_del_escenario"] == []
    contraste = datos["contraste_novedad"]
    assert contraste["sin_novedad"]["derecho_al_almuerzo"] is True
    assert contraste["con_novedad"]["derecho_al_almuerzo"] is False
    assert contraste["sin_novedad"]["filas_v_comidas_por_turno"] == contraste["con_novedad"]["filas_v_comidas_por_turno"]
    assert contraste["novedad_persistida_tras_revertir"] == 0
    assert datos["racion_principal"] == {"raciones": 0, "lecturas": 0, "disponible_para_cocina": True}

    with servidor.connect() as cx:
        assert _esquemas(cx) - antes == {demo, sim}
        assert antes - _esquemas(cx) == set()
        foto_demo, foto_sim = _foto(cx, demo), _foto(cx, sim)
        hashes = dict(cx.execute(text(f"SELECT username, password_hash FROM `{sim}`.usuarios_sistema")).all())
        assert set(hashes) == {"cocinera2", "cocinera3"}
        for tabla in ("asistencias", "lecturas_biometricas", "intervenciones_lectura"):
            assert cx.execute(text(f"SELECT COUNT(*) FROM `{sim}`.`{tabla}`")).scalar_one() == 0
        leidas = set(cx.execute(
            text("SELECT DISTINCT TABLE_SCHEMA FROM information_schema.VIEW_TABLE_USAGE WHERE VIEW_SCHEMA = :b"),
            {"b": sim},
        ).scalars())
        assert leidas == {demo}

    # Repetir: sin claves (las cuentas ya existen) y sin escribir nada.
    segunda = _correr(demo, sim)
    assert segunda.returncode == 0, segunda.stderr
    assert "0 filas creadas" in segunda.stdout
    _verificar_auditoria(_auditoria(segunda.stdout), demo, sim)
    with servidor.connect() as cx:
        assert _foto(cx, demo) == foto_demo
        assert _foto(cx, sim) == foto_sim
        assert dict(cx.execute(text(f"SELECT username, password_hash FROM `{sim}`.usuarios_sistema")).all()) == hashes


@integracion
def test_integracion_colision_ajena_aborta_sin_tocar_nada(bases_nuevas):
    servidor, nombres = bases_nuevas
    demo, sim = nombres()
    with servidor.connect() as cx:
        cx.execute(text(f"CREATE DATABASE `{demo}`"))
        cx.execute(text(f"CREATE TABLE `{demo}`.`otra` (id INT PRIMARY KEY)"))
        cx.execute(text(f"INSERT INTO `{demo}`.`otra` VALUES (1)"))
        foto = _foto(cx, demo)

    resultado = _correr(demo, sim, claves=_claves())
    assert resultado.returncode == 1
    assert "colisión" in resultado.stderr
    with servidor.connect() as cx:
        assert _foto(cx, demo) == foto
        assert sim not in _esquemas(cx)


@integracion
def test_integracion_racion_registrada_no_se_borra(bases_nuevas):
    servidor, nombres = bases_nuevas
    demo, sim = nombres()
    primera = _correr(demo, sim, "--claves-sin-revelar")
    assert primera.returncode == 0, primera.stderr
    with servidor.connect() as cx:
        assert cx.execute(text(f"SELECT COUNT(*) FROM `{sim}`.usuarios_sistema WHERE debe_cambiar = 1")).scalar_one() == 2
        # Simula el flujo de cocina: el almuerzo principal ya servido.
        cx.execute(
            text(
                f"INSERT INTO `{sim}`.asistencias (usuario_id, fecha_comida, comida_id, "
                "categoria_reporte_id, metodo, fecha_hora) SELECT 900001, :f, 2, id, 'manual', NOW() "
                f"FROM `{sim}`.categorias_reporte LIMIT 1"
            ),
            {"f": FECHA},
        )
    resultado = _correr(demo, sim)
    assert resultado.returncode == 3
    assert "YA se registró" in resultado.stderr
    with servidor.connect() as cx:
        assert cx.execute(text(f"SELECT COUNT(*) FROM `{sim}`.asistencias")).scalar_one() == 1
