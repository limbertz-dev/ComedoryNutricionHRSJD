"""Prepara un escenario de cocina EXCLUSIVAMENTE SINTÉTICO en bases dedicadas.

    comedorback/.venv/Scripts/python scripts/preparar_escenario_sintetico.py --solo-inventario
    comedorback/.venv/Scripts/python scripts/preparar_escenario_sintetico.py --fecha 2026-10-16 \\
        --manifiesto manifiesto.json [--claves-sin-revelar]

Deja listo, sin registrar ninguna ración:

  · `--demo` (*_demo): base de turnos creada desde cero con el esquema MÍNIMO
    que leen las vistas v_* del contrato. No es un clon: no se copia ni se
    lee una fila ni el DDL de ninguna base existente; todas las filas son las
    constantes de este archivo.
  · `--sim` (*_sim): `alembic upgrade head` + la semilla general, con las
    vistas apuntadas a `--demo`. Las reglas de derecho son las que inserta la
    migración: este script no las escribe.
  · Comensal principal `usuariosimulado` (900001): categoría Administrativo,
    turno de 12 h que otorga el almuerzo del mismo día, asignación en
    `--fecha`, sin novedades, SIN cuenta de acceso. Su almuerzo queda
    disponible para el flujo de cocina.
  · Casos negativos independientes (900002-900006): cada uno difiere del
    principal en UN solo factor (duración, categoría, mapeo turno->comida,
    novedad impeditiva, fecha).
  · Contraste de novedad (900007): la MISMA asignación da derecho sin novedad
    y no lo da con una novedad impeditiva. La novedad se inserta dentro de
    una transacción que se revierte: el estado guardado no la tiene.
  · Cuentas `cocinera2`, `cocinera3` (rol cocinera) y `jefa` (rol jefa), sin
    vínculo con el padrón y con clave temporal (debe_cambiar = 1).
  · Asociación simulada `SIM-ID-900001` -> 900001 en
    `escenario_identificaciones` de `--demo`: solo texto, sin imagen, huella
    ni plantilla. El lector simulado identifica por `usuario_id`.

AUDITORÍA DE ESCRITURAS. Cada proceso del preparador (este, alembic, la
semilla y la evidencia) instala `before_cursor_execute` sobre todos los
motores y clasifica cada sentencia. Una escritura fuera de lo autorizado
para su paso se corta ANTES de ejecutarse y aborta la corrida:

  · nunca fuera de `--demo` / `--sim`, nunca sin base resoluble;
  · nunca INSERT/UPDATE/DELETE/ALTER/DROP sobre una vista v_* o vw_*;
  · tablas con nombre heredado (users, turnos_asignados, ...) solo dentro
    de `--demo`, que lleva el marcador de este escenario;
  · ningún DELETE, UPDATE, DROP ni TRUNCATE en ningún paso propio;
  · alembic: solo tablas propias de bd_nutricion y CREATE VIEW v_* cuyo
    cuerpo nombre únicamente `--demo`.

Todas las sentencias de escritura (sin parámetros: ni claves ni hashes) van a
un registro JSONL; el resumen entra en el manifiesto.

Claves: por consola sin eco, por ESCENARIO_CLAVE_COCINERA2 / _COCINERA3 /
_JEFA, o `--claves-sin-revelar` (al azar, no se guardan ni se muestran: la
cuenta queda inutilizable hasta `python -m app.semillas.admin --username X
--resetear`, que el operador corre en su propia consola). Nunca se imprimen.

Repetible: con los mismos parámetros la segunda corrida no escribe nada.
Ante colisiones ajenas (base sin marcador, fila o tabla distinta, cuenta con
otro rol, vínculo o nombre) aborta sin corregir.

Salida: 0 listo; 1 abortado; 3 el almuerzo principal de esa fecha ya se
registró (no se borra: correr con otra --fecha).
"""

import argparse
import getpass
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
RAIZ_BACK = RAIZ / "comedorback"

IDENTIFICADOR = re.compile(r"^[A-Za-z0-9_]+$")
BASES_DEL_SISTEMA = frozenset({"mysql", "sys", "information_schema", "performance_schema"})
# Las reales, y las de scripts/preparar_simulacion.py: esas dos son copias
# de datos reales del hospital y este escenario no se mezcla con ellas.
BASES_PROTEGIDAS = frozenset(
    {"bd_nutricion", "bd_proyecto_backend", "bd_turnos_demo", "bd_nutricion_sim"}
)

DEMO_POR_DEFECTO = "bd_turnos_escenario_demo"
SIM_POR_DEFECTO = "bd_nutricion_escenario_sim"

MARCADOR_TABLA = "escenario_sintetico"
MARCADOR_CLAVE = "comedor-escenario-sintetico"
MARCADOR_VERSION = 2

# --- datos sintéticos -------------------------------------------------------------
# Ids en rangos que el padrón real no usa, para reconocerlos a simple vista.

COMIDA_CODIGO = "almuerzo"
COMIDA_ID = 2
ESTADO_ASIGNACION = "programado"
NOVEDAD_IMPEDITIVA = "permiso"
BASE_ID_ASIGNACION = 90_000_000
BASE_USUARIO = 900_000
ANCLA_ORDINAL = date(2000, 1, 1)  # el mismo id se recalcula en SQL con DATEDIFF

CATEGORIA_ADMIN = 9001
CATEGORIA_ENFERMERIA = 9002
SERVICIO_ID = 9001
TURNO_12H = 9001
TURNO_8H = 9002
TURNO_12H_SIN_COMIDA = 9003

USUARIO_ID = 900001
USUARIO_LOGIN = "usuariosimulado"
IDENTIFICADOR_SIMULADO = "SIM-ID-900001"
CATEGORIA_NOMBRE = "Administrativo"  # mapeada por app/semillas/mapeo_categorias.py
TURNO_DURACION_HORAS = 12

# Un comensal por caso. Cada negativo difiere del principal en `factor` y en
# nada más. `desfase`: la asignación cae en --fecha + desfase.
CASOS: tuple[dict, ...] = (
    dict(caso="principal", usuario_id=900001, login=USUARIO_LOGIN, nombre="USUARIO SIMULADO",
         categoria_id=CATEGORIA_ADMIN, turno_id=TURNO_12H, novedad=None, desfase=0,
         derecho=True, factor=None),
    dict(caso="negativo_duracion", usuario_id=900002, login="simneg_duracion",
         nombre="SIMULADO NEGATIVO DURACION", categoria_id=CATEGORIA_ADMIN, turno_id=TURNO_8H,
         novedad=None, desfase=0, derecho=False, factor="turno de 8 h (mínimo vigente: 12 h)"),
    dict(caso="negativo_categoria", usuario_id=900003, login="simneg_enfermeria",
         nombre="SIMULADO NEGATIVO CATEGORIA", categoria_id=CATEGORIA_ENFERMERIA,
         turno_id=TURNO_12H, novedad=None, desfase=0, derecho=False,
         factor="categoría Enfermería (excluida por la regla vigente)"),
    dict(caso="negativo_sin_mapeo", usuario_id=900004, login="simneg_sin_mapeo",
         nombre="SIMULADO NEGATIVO MAPEO", categoria_id=CATEGORIA_ADMIN,
         turno_id=TURNO_12H_SIN_COMIDA, novedad=None, desfase=0, derecho=False,
         factor="turno de 12 h sin fila en turno_comida"),
    dict(caso="negativo_novedad", usuario_id=900005, login="simneg_novedad",
         nombre="SIMULADO NEGATIVO NOVEDAD", categoria_id=CATEGORIA_ADMIN, turno_id=TURNO_12H,
         novedad=NOVEDAD_IMPEDITIVA, desfase=0, derecho=False,
         factor=f"novedad '{NOVEDAD_IMPEDITIVA}' guardada sobre su asignación"),
    dict(caso="negativo_otra_fecha", usuario_id=900006, login="simneg_otra_fecha",
         nombre="SIMULADO NEGATIVO FECHA", categoria_id=CATEGORIA_ADMIN, turno_id=TURNO_12H,
         novedad=None, desfase=1, derecho=False, factor="asignación al día siguiente"),
    dict(caso="contraste_novedad", usuario_id=900007, login="simcontraste_novedad",
         nombre="SIMULADO CONTRASTE NOVEDAD", categoria_id=CATEGORIA_ADMIN, turno_id=TURNO_12H,
         novedad=None, desfase=0, derecho=True,
         factor=f"misma asignación medida sin y con novedad '{NOVEDAD_IMPEDITIVA}' (revertida)"),
)
CONTRASTE_ID = 900007

CUENTAS = (
    {"username": "cocinera2", "rol": "cocinera", "nombre": "Cocinera simulada 2",
     "variable": "ESCENARIO_CLAVE_COCINERA2"},
    {"username": "cocinera3", "rol": "cocinera", "nombre": "Cocinera simulada 3",
     "variable": "ESCENARIO_CLAVE_COCINERA3"},
    {"username": "jefa", "rol": "jefa", "nombre": "Jefa simulada",
     "variable": "ESCENARIO_CLAVE_JEFA"},
)

OPCIONES_TABLA = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"

# Esquema mínimo de la base de turnos sintética: SOLO las tablas y columnas
# que nombran las vistas del contrato (0c294cd98c3a y 2555bc00750e), con los
# tipos de app/modelos/heredados.py. Más las dos tablas del escenario.
# Ninguna columna binaria: tests/test_escenario_sintetico.py lo comprueba.
ESQUEMA: dict[str, list[tuple[str, str]]] = {
    MARCADOR_TABLA: [
        ("clave", "VARCHAR(40) NOT NULL PRIMARY KEY"),
        ("version", "INT NOT NULL"),
        ("base_sim", "VARCHAR(64) NOT NULL"),
        ("creado", "DATETIME NOT NULL"),
    ],
    "categorias": [
        ("id", "BIGINT UNSIGNED NOT NULL PRIMARY KEY"),
        ("nombre", "VARCHAR(255) NOT NULL"),
        ("nivel", "INT NOT NULL"),
        ("descripcion", "VARCHAR(255) NULL"),
    ],
    "servicios": [
        ("id", "BIGINT UNSIGNED NOT NULL PRIMARY KEY"),
        ("nombre", "VARCHAR(255) NOT NULL"),
        ("descripcion", "TEXT NULL"),
        ("cantidad_pacientes", "INT NOT NULL"),
    ],
    "comidas": [
        ("id", "BIGINT UNSIGNED NOT NULL PRIMARY KEY"),
        ("nombre", "VARCHAR(255) NOT NULL"),
        ("codigo", "VARCHAR(255) NOT NULL UNIQUE"),
        ("estado", "TINYINT(1) NOT NULL"),
    ],
    "users": [
        ("id", "BIGINT UNSIGNED NOT NULL PRIMARY KEY"),
        ("name", "VARCHAR(255) NOT NULL UNIQUE"),
        ("categoria_id", "BIGINT UNSIGNED NULL"),
    ],
    "personas": [
        ("id", "BIGINT UNSIGNED NOT NULL PRIMARY KEY"),
        ("user_id", "BIGINT UNSIGNED NULL"),
        ("nombre_completo", "VARCHAR(100) NULL"),
        ("carnet_identidad", "VARCHAR(100) NULL"),
        ("tipo_trabajador", "VARCHAR(30) NULL"),
        ("numero_tipo_salario", "VARCHAR(30) NULL"),
    ],
    "usuario_servicios": [
        ("id", "BIGINT UNSIGNED NOT NULL PRIMARY KEY"),
        ("usuario_id", "BIGINT UNSIGNED NOT NULL"),
        ("servicio_id", "BIGINT UNSIGNED NOT NULL"),
        ("estado", "TINYINT(1) NOT NULL"),
        ("fecha_ingreso", "DATE NOT NULL"),
    ],
    "turnos": [
        ("id", "BIGINT UNSIGNED NOT NULL PRIMARY KEY"),
        ("nombre_turno", "VARCHAR(255) NOT NULL"),
        ("hora_inicio", "TIME NOT NULL"),
        ("hora_fin", "TIME NOT NULL"),
        ("duracion_horas", "INT NOT NULL"),
        ("categoria_id", "BIGINT UNSIGNED NOT NULL"),
    ],
    "turno_comida": [
        ("id", "BIGINT UNSIGNED NOT NULL PRIMARY KEY"),
        ("turno_id", "BIGINT UNSIGNED NOT NULL"),
        ("comida_id", "BIGINT UNSIGNED NOT NULL"),
        ("dia_relativo", "TINYINT UNSIGNED NOT NULL"),
    ],
    "turnos_asignados": [
        ("id", "BIGINT UNSIGNED NOT NULL PRIMARY KEY"),
        ("usuario_id", "BIGINT UNSIGNED NOT NULL"),
        ("servicio_id", "BIGINT UNSIGNED NOT NULL"),
        ("area_id", "BIGINT UNSIGNED NULL"),
        ("fecha", "DATE NOT NULL"),
        ("estado", "VARCHAR(50) NOT NULL"),
        ("es_intercambio", "TINYINT(1) NOT NULL"),
        ("turno_id", "BIGINT UNSIGNED NOT NULL"),
    ],
    "novedades_laborales": [
        ("id", "BIGINT UNSIGNED NOT NULL PRIMARY KEY"),
        ("asignacion_id", "BIGINT UNSIGNED NOT NULL"),
        ("tipo_novedad", "VARCHAR(30) NOT NULL"),
        ("usuario_solicitante_id", "BIGINT UNSIGNED NOT NULL"),
        ("usuario_reemplazo_id", "BIGINT UNSIGNED NULL"),
        ("fecha_original", "DATE NOT NULL"),
        ("fecha_nueva", "DATE NULL"),
        ("con_devolucion", "TINYINT(1) NOT NULL"),
    ],
    "escenario_identificaciones": [
        ("identificador", "VARCHAR(40) NOT NULL PRIMARY KEY"),
        ("usuario_id", "BIGINT UNSIGNED NOT NULL UNIQUE"),
        ("origen", "ENUM('simulado') NOT NULL"),
        ("descripcion", "VARCHAR(255) NOT NULL"),
    ],
}

# Restricciones internas de la base sintética (no hay FK hacia ninguna otra).
FKS: dict[str, list[str]] = {
    "users": ["FOREIGN KEY (`categoria_id`) REFERENCES `categorias` (`id`)"],
    "personas": ["FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)"],
    "usuario_servicios": [
        "FOREIGN KEY (`usuario_id`) REFERENCES `users` (`id`)",
        "FOREIGN KEY (`servicio_id`) REFERENCES `servicios` (`id`)",
    ],
    "turnos": ["FOREIGN KEY (`categoria_id`) REFERENCES `categorias` (`id`)"],
    "turno_comida": [
        "FOREIGN KEY (`turno_id`) REFERENCES `turnos` (`id`)",
        "FOREIGN KEY (`comida_id`) REFERENCES `comidas` (`id`)",
    ],
    "turnos_asignados": [
        "FOREIGN KEY (`usuario_id`) REFERENCES `users` (`id`)",
        "FOREIGN KEY (`servicio_id`) REFERENCES `servicios` (`id`)",
        "FOREIGN KEY (`turno_id`) REFERENCES `turnos` (`id`)",
    ],
    "novedades_laborales": ["FOREIGN KEY (`asignacion_id`) REFERENCES `turnos_asignados` (`id`)"],
    "escenario_identificaciones": ["FOREIGN KEY (`usuario_id`) REFERENCES `users` (`id`)"],
}


def _catalogo() -> dict[str, list[dict]]:
    return {
        "categorias": [
            {"id": CATEGORIA_ADMIN, "nombre": CATEGORIA_NOMBRE, "nivel": 1,
             "descripcion": "Categoria sintetica del escenario de cocina"},
            {"id": CATEGORIA_ENFERMERIA, "nombre": "Enfermería", "nivel": 1,
             "descripcion": "Categoria sintetica: caso negativo por categoria"},
        ],
        "servicios": [
            {"id": SERVICIO_ID, "nombre": "Servicio simulado",
             "descripcion": "Sala sintetica del escenario de cocina", "cantidad_pacientes": 0},
        ],
        "comidas": [
            {"id": 1, "nombre": "Desayuno", "codigo": "desayuno", "estado": 1},
            {"id": COMIDA_ID, "nombre": "Almuerzo", "codigo": COMIDA_CODIGO, "estado": 1},
            {"id": 3, "nombre": "Té", "codigo": "te", "estado": 1},
            {"id": 4, "nombre": "Cena", "codigo": "cena", "estado": 1},
        ],
        "users": [
            {"id": c["usuario_id"], "name": c["login"], "categoria_id": c["categoria_id"]}
            for c in CASOS
        ],
        "personas": [
            {"id": c["usuario_id"], "user_id": c["usuario_id"], "nombre_completo": c["nombre"],
             "carnet_identidad": f"SIM-{c['usuario_id']}", "tipo_trabajador": "simulado",
             "numero_tipo_salario": None}
            for c in CASOS
        ],
        "usuario_servicios": [
            {"id": c["usuario_id"], "usuario_id": c["usuario_id"], "servicio_id": SERVICIO_ID,
             "estado": 1, "fecha_ingreso": "2026-01-01"}
            for c in CASOS
        ],
        "turnos": [
            {"id": TURNO_12H, "nombre_turno": "Turno simulado 12 h", "hora_inicio": "07:00:00",
             "hora_fin": "19:00:00", "duracion_horas": TURNO_DURACION_HORAS,
             "categoria_id": CATEGORIA_ADMIN},
            {"id": TURNO_8H, "nombre_turno": "Turno simulado 8 h", "hora_inicio": "07:00:00",
             "hora_fin": "15:00:00", "duracion_horas": 8, "categoria_id": CATEGORIA_ADMIN},
            {"id": TURNO_12H_SIN_COMIDA, "nombre_turno": "Turno simulado 12 h sin comida",
             "hora_inicio": "07:00:00", "hora_fin": "19:00:00", "duracion_horas": 12,
             "categoria_id": CATEGORIA_ADMIN},
        ],
        "turno_comida": [
            {"id": TURNO_12H, "turno_id": TURNO_12H, "comida_id": COMIDA_ID, "dia_relativo": 0},
            {"id": TURNO_8H, "turno_id": TURNO_8H, "comida_id": COMIDA_ID, "dia_relativo": 0},
        ],
        "escenario_identificaciones": [
            {"identificador": IDENTIFICADOR_SIMULADO, "usuario_id": USUARIO_ID,
             "origen": "simulado",
             "descripcion": "Identificacion simulada del lector: solo texto, sin "
                            "imagen, huella ni plantilla biometrica."},
        ],
    }


# Filas fijas, en orden de carga (padres primero).
CATALOGO: dict[str, list[dict]] = _catalogo()


# --- funciones puras --------------------------------------------------------------


def clave_de(tabla: str) -> str:
    return "identificador" if tabla == "escenario_identificaciones" else "id"


def caso(nombre: str) -> dict:
    return next(c for c in CASOS if c["caso"] == nombre)


def id_asignacion(fecha: date, usuario_id: int = USUARIO_ID) -> int:
    """Id determinista de una asignación: repetir no duplica."""
    return BASE_ID_ASIGNACION + (usuario_id - BASE_USUARIO) * 1_000_000 + fecha.toordinal()


def fila_asignacion(fecha: date, usuario_id: int = USUARIO_ID) -> dict:
    c = next(x for x in CASOS if x["usuario_id"] == usuario_id)
    dia = fecha + timedelta(days=c["desfase"])
    return {
        "id": id_asignacion(dia, usuario_id),
        "usuario_id": usuario_id,
        "servicio_id": SERVICIO_ID,
        "area_id": None,
        "fecha": dia.isoformat(),
        "estado": ESTADO_ASIGNACION,
        "es_intercambio": 0,
        "turno_id": c["turno_id"],
    }


def filas_de_la_fecha(fecha: date) -> dict[str, list[dict]]:
    """Asignaciones y novedades que la fecha agrega, en orden de carga."""
    asignaciones = [fila_asignacion(fecha, c["usuario_id"]) for c in CASOS]
    novedades = []
    for c, a in zip(CASOS, asignaciones):
        if c["novedad"]:
            novedades.append(fila_novedad(a, c["novedad"]))
    return {"turnos_asignados": asignaciones, "novedades_laborales": novedades}


def fila_novedad(asignacion: dict, tipo: str) -> dict:
    return {
        "id": asignacion["id"],
        "asignacion_id": asignacion["id"],
        "tipo_novedad": tipo,
        "usuario_solicitante_id": asignacion["usuario_id"],
        "usuario_reemplazo_id": None,
        "fecha_original": asignacion["fecha"],
        "fecha_nueva": None,
        "con_devolucion": 0,
    }


def ddl_tabla(base: str, tabla: str) -> str:
    columnas = [f"`{c}` {tipo}" for c, tipo in ESQUEMA[tabla]]
    cuerpo = ",\n  ".join(columnas + FKS.get(tabla, []))
    return f"CREATE TABLE IF NOT EXISTS `{base}`.`{tabla}` (\n  {cuerpo}\n) {OPCIONES_TABLA}"


def tipo_base(definicion: str) -> str:
    """'BIGINT UNSIGNED NOT NULL ...' -> 'bigint' (el DATA_TYPE de MySQL)."""
    return re.match(r"[A-Za-z]+", definicion).group(0).lower()


def errores_de_nombres(demo: str, sim: str, protegidas: set[str]) -> list[str]:
    errores = []
    for nombre in (demo, sim):
        if not IDENTIFICADOR.match(nombre):
            errores.append(f"nombre de base inválido: {nombre!r}")
    if not demo.endswith("_demo"):
        errores.append(f"--demo tiene que terminar en '_demo': {demo!r}")
    if not sim.endswith("_sim"):
        errores.append(f"--sim tiene que terminar en '_sim': {sim!r}")
    if demo.lower() == sim.lower():
        errores.append("--demo y --sim no pueden ser la misma base.")
    vedadas = {p.lower() for p in protegidas} | BASES_PROTEGIDAS | BASES_DEL_SISTEMA
    for nombre in (demo, sim):
        if nombre.lower() in vedadas:
            errores.append(f"'{nombre}' está protegida: este escenario nunca la usa.")
    return errores


def clasificar(
    *,
    demo_existe: bool,
    marcador: dict | None,
    sim: str,
    sim_existe: bool,
    sim_tablas: set[str],
    vistas_sim: dict[str, str],
    demo: str,
) -> tuple[str, str, list[str]]:
    """Estado de las dos bases: (demo, sim, motivos de colisión).

    `propia` exige el marcador de este script, con la versión y la base
    `--sim` que se piden. Una `--sim` es propia solo si la `--demo` propia la
    nombra, y o está vacía (corrida interrumpida después de crearla) o tiene
    alembic y sus vistas leen `--demo`.
    """
    motivos: list[str] = []
    if not demo_existe:
        estado_demo = "ausente"
    elif (
        marcador is not None
        and marcador.get("clave") == MARCADOR_CLAVE
        and marcador.get("version") == MARCADOR_VERSION
        and marcador.get("base_sim", "").lower() == sim.lower()
    ):
        estado_demo = "propia"
    else:
        estado_demo = "ajena"
        motivos.append(
            f"'{demo}' existe y no tiene el marcador de este escenario para '{sim}'."
        )

    if not sim_existe:
        estado_sim = "ausente"
    elif estado_demo != "propia":
        estado_sim = "ajena"
        motivos.append(f"'{sim}' existe y ninguna '{demo}' de este escenario la reclama.")
    elif not sim_tablas and not vistas_sim:
        estado_sim = "propia"
    elif "alembic_version" not in sim_tablas:
        estado_sim = "ajena"
        motivos.append(f"'{sim}' tiene tablas pero no alembic_version.")
    else:
        ajenas = sorted(v for v, d in vistas_sim.items() if f"`{demo}`" not in d)
        if ajenas:
            estado_sim = "ajena"
            motivos.append(f"vistas de '{sim}' que no leen '{demo}': {ajenas}")
        else:
            estado_sim = "propia"
    return estado_demo, estado_sim, motivos


def errores_de_clave(username: str, clave: str, largo_minimo: int) -> list[str]:
    """Mismas exigencias que el cambio de clave (app/logica/autenticacion.py).
    Los mensajes nunca incluyen la clave."""
    errores = []
    if len(clave) < largo_minimo:
        errores.append(f"la clave de '{username}' tiene menos de {largo_minimo} caracteres.")
    if len(clave.encode("utf-8")) > 72:
        errores.append(f"la clave de '{username}' supera 72 bytes.")
    if clave.strip().lower() == username:
        errores.append(f"la clave de '{username}' no puede ser el nombre de usuario.")
    return errores


def errores_de_cuentas(existentes: dict[str, dict]) -> list[str]:
    """Una cuenta del escenario que ya existe tiene que ser exactamente la
    nuestra; y ningún comensal del escenario puede tener cuenta."""
    errores = []
    logins = {c["login"] for c in CASOS}
    ids = {c["usuario_id"] for c in CASOS}
    for username, fila in existentes.items():
        if username in logins or fila.get("usuario_turnos_id") in ids:
            errores.append(
                f"la cuenta '{username}' está vinculada a un comensal del escenario o "
                "lleva su login: los comensales no tienen cuenta de acceso."
            )
    for cuenta in CUENTAS:
        fila = existentes.get(cuenta["username"])
        if fila is None:
            continue
        if (
            fila["rol"] != cuenta["rol"]
            or fila["usuario_turnos_id"] is not None
            or fila["nombre"] != cuenta["nombre"]
        ):
            errores.append(
                f"'{cuenta['username']}' ya existe y no es la cuenta de este escenario "
                f"(rol {fila['rol']})."
            )
        elif not fila["activo"]:
            errores.append(
                f"'{cuenta['username']}' está dada de baja. Este script no reactiva "
                "cuentas: reactivarla es decisión de sistemas."
            )
    return errores


# --- auditoría de escrituras -------------------------------------------------------

# Toda sentencia que empiece así es (o puede ser) una escritura. Si además no
# la reconoce ESCRITURA, se rechaza: lo que no se sabe clasificar no se ejecuta.
COMIENZO_DE_ESCRITURA = re.compile(
    r"^\s*(INSERT|REPLACE|UPDATE|DELETE|TRUNCATE|ALTER|DROP|CREATE|RENAME|LOAD|GRANT|"
    r"REVOKE|CALL|HANDLER|IMPORT|LOCK|SET\s+PASSWORD|SET\s+GLOBAL|SET\s+PERSIST|WITH)\b",
    re.I,
)
ESCRITURA = re.compile(
    r"""^\s*(?:
      (?P<verbo>INSERT(?:\s+IGNORE)?\s+INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM
               |TRUNCATE(?:\s+TABLE)?|ALTER\s+TABLE|DROP\s+(?:TABLE|VIEW)(?:\s+IF\s+EXISTS)?
               |CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?|RENAME\s+TABLE)
        \s+(?:`?(?P<base>\w+)`?\.)?`?(?P<objeto>\w+)`?
    | (?P<verbo_base>CREATE\s+(?:DATABASE|SCHEMA)(?:\s+IF\s+NOT\s+EXISTS)?
                    |DROP\s+(?:DATABASE|SCHEMA)(?:\s+IF\s+EXISTS)?)
        \s+`?(?P<nombre_base>\w+)`?
    | (?P<verbo_vista>CREATE\s+(?:OR\s+REPLACE\s+)?(?:ALGORITHM\s*=\s*\w+\s+)?
                     (?:DEFINER\s*=\s*\S+\s+)?(?:SQL\s+SECURITY\s+\w+\s+)?VIEW)
        \s+(?:`?(?P<base_vista>\w+)`?\.)?`?(?P<vista>\w+)`?
    | (?P<verbo_indice>(?:CREATE\s+(?:UNIQUE\s+)?|DROP\s+)INDEX)\s+`?\w+`?\s+ON
        \s+(?:`?(?P<base_indice>\w+)`?\.)?`?(?P<tabla_indice>\w+)`?
    )""",
    re.I | re.X,
)

PASOS = ("principal", "alembic", "semilla", "evidencia")
VERBOS_DML = {"INSERT", "REPLACE", "UPDATE", "DELETE"}


class AuditoriaViolada(Exception):
    """Una escritura fuera de lo autorizado. Se lanza ANTES de ejecutarla."""


def clasificar_escritura(sentencia: str, base_por_defecto: str | None) -> dict | None:
    """None si no es escritura; si lo es, {verbo, base, objeto, tipo}.

    `verbo` es la primera palabra significativa (INSERT, UPDATE, CREATE TABLE,
    CREATE VIEW, ...). Una escritura sin base explícita va a la base de la
    conexión. Una que no se sabe analizar sale con tipo 'desconocida'.
    """
    if not COMIENZO_DE_ESCRITURA.match(sentencia):
        return None
    if re.match(r"^\s*WITH\b", sentencia, re.I) and not re.search(
        r"\b(INSERT|UPDATE|DELETE|REPLACE)\b", sentencia, re.I
    ):
        return None
    m = ESCRITURA.match(sentencia)
    if m is None:
        return {"verbo": sentencia.split()[0].upper(), "base": None, "objeto": None,
                "tipo": "desconocida"}
    if m.group("verbo"):
        palabras = m.group("verbo").upper().split()
        verbo = " ".join(w for w in palabras if w not in {"IGNORE", "INTO", "FROM", "IF",
                                                          "EXISTS", "NOT"})
        if verbo.startswith("TRUNCATE"):
            verbo = "TRUNCATE"
        tipo = "tabla"
        base, objeto = m.group("base"), m.group("objeto")
    elif m.group("verbo_base"):
        verbo = " ".join(m.group("verbo_base").upper().split()[:2]).replace("SCHEMA", "DATABASE")
        tipo, base, objeto = "base", m.group("nombre_base"), m.group("nombre_base")
    elif m.group("verbo_vista"):
        verbo, tipo = "CREATE VIEW", "vista"
        base, objeto = m.group("base_vista"), m.group("vista")
    else:
        verbo = "DROP INDEX" if m.group("verbo_indice").upper().startswith("DROP") else "CREATE INDEX"
        tipo, base, objeto = "indice", m.group("base_indice"), m.group("tabla_indice")
    return {"verbo": verbo, "base": base or base_por_defecto, "objeto": objeto, "tipo": tipo}


def motivo_de_rechazo(
    escritura: dict,
    sentencia: str,
    *,
    paso: str,
    demo: str,
    sim: str,
    propias: frozenset[str],
    heredadas: frozenset[str],
    vistas: frozenset[str],
) -> str | None:
    """None si la escritura está autorizada para el paso; si no, el motivo."""
    verbo, base, objeto = escritura["verbo"], escritura["base"], escritura["objeto"]
    if escritura["tipo"] == "desconocida":
        return f"escritura que el auditor no sabe clasificar ({verbo})"
    if base is None:
        return "escritura sin base explícita ni base de conexión"
    base_l, demo_l, sim_l = base.lower(), demo.lower(), sim.lower()
    objeto_l = (objeto or "").lower()
    if base_l not in {demo_l, sim_l}:
        return f"escritura fuera del escenario: `{base}`"
    if escritura["tipo"] != "vista" and objeto_l in vistas:
        return f"escritura sobre la vista `{objeto}`"
    if objeto_l in heredadas and base_l != demo_l:
        return f"tabla heredada `{objeto}` fuera de la base sintética"
    if re.search(r"REFERENCES\s+`?\w+`?\s*\.", sentencia, re.I):
        return "FK hacia otra base"

    if paso == "principal":
        if verbo == "CREATE DATABASE":
            return None if base_l in {demo_l, sim_l} else "CREATE DATABASE no autorizado"
        if verbo == "CREATE TABLE" and base_l == demo_l and objeto in ESQUEMA:
            return None
        if verbo == "INSERT" and base_l == demo_l and objeto in ESQUEMA:
            return None
        if verbo == "INSERT" and base_l == sim_l and objeto_l == "usuarios_sistema":
            return None
        return f"{verbo} `{base}`.`{objeto}` no autorizado en el paso principal"
    if paso == "alembic":
        if base_l != sim_l:
            return "alembic solo escribe en --sim"
        if verbo == "CREATE VIEW":
            bases = {b.lower() for b in re.findall(r"`(\w+)`\s*\.\s*`", sentencia)}
            if objeto_l in vistas and bases == {demo_l}:
                return None
            return f"vista `{objeto}` con lecturas fuera de `{demo}`: {sorted(bases)}"
        if verbo in {"DROP TABLE", "DROP VIEW", "TRUNCATE", "RENAME TABLE", "DROP DATABASE"}:
            return f"{verbo} no autorizado en alembic"
        if objeto_l in propias or objeto_l == "alembic_version":
            return None
        return f"alembic sobre `{objeto}`, que no es tabla propia"
    if paso == "semilla":
        if base_l == sim_l and verbo in {"INSERT", "UPDATE"} and objeto_l in propias:
            return None
        return f"{verbo} `{base}`.`{objeto}` no autorizado en la semilla"
    if paso == "evidencia":
        # Solo el contraste de novedad, dentro de una transacción revertida.
        if verbo == "INSERT" and base_l == demo_l and objeto_l == "novedades_laborales":
            return None
        return f"{verbo} `{base}`.`{objeto}` no autorizado en la evidencia"
    return f"paso desconocido: {paso}"


def instalar_auditor(*, paso: str, demo: str, sim: str, registro: Path | None, objetivo=None,
                     propias: frozenset[str] | None = None, base_conexion=None):
    """Escucha `before_cursor_execute` en todos los motores (o en `objetivo`).
    `base_conexion(conexion)` da la base de una sentencia sin base explícita;
    por defecto, la de la URL del motor. Devuelve una función que quita el
    listener."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    from app.core.tablas_heredadas import TABLAS_HEREDADAS, VISTAS_CONTRATO, VISTAS_HEREDADAS

    if propias is None:
        import app.modelos  # noqa: F401  registra las tablas en Base.metadata
        from app.core.db import Base

        propias = frozenset(Base.metadata.tables)
    heredadas = frozenset(t.lower() for t in TABLAS_HEREDADAS)
    vistas = frozenset(v.lower() for v in set(VISTAS_CONTRATO) | VISTAS_HEREDADAS)
    objetivo = objetivo if objetivo is not None else Engine
    base_conexion = base_conexion or (lambda conexion: conexion.engine.url.database)

    def anotar(datos: dict) -> None:
        if registro is not None:
            with open(registro, "a", encoding="utf-8") as archivo:
                archivo.write(json.dumps(datos, ensure_ascii=False) + "\n")

    def revisar(conexion, cursor, sentencia, parametros, contexto, multiples):
        escritura = clasificar_escritura(sentencia, base_conexion(conexion))
        if escritura is None:
            return
        motivo = motivo_de_rechazo(
            escritura, sentencia, paso=paso, demo=demo, sim=sim,
            propias=propias, heredadas=heredadas, vistas=vistas,
        )
        anotar({"paso": paso, **escritura, "autorizada": motivo is None,
                "motivo": motivo, "sentencia": " ".join(sentencia.split())[:2000]})
        if motivo is not None:
            raise AuditoriaViolada(f"[{paso}] {motivo}")

    event.listen(objetivo, "before_cursor_execute", revisar)
    return lambda: event.remove(objetivo, "before_cursor_execute", revisar)


def resumir_auditoria(registros: list[dict]) -> list[dict]:
    conteo = Counter(
        (r["paso"], r["verbo"], r["base"], r["objeto"], r["autorizada"]) for r in registros
    )
    return [
        {"paso": p, "verbo": v, "base": b, "objeto": o, "autorizada": a, "sentencias": n}
        for (p, v, b, o, a), n in sorted(conteo.items(), key=lambda x: tuple(map(str, x[0])))
    ]


def problemas_de_auditoria(registros: list[dict], demo: str, sim: str) -> list[str]:
    problemas = [f"{r['paso']}: {r['motivo']}" for r in registros if not r["autorizada"]]
    fuera = {r["base"] for r in registros} - {demo, sim}
    if fuera:
        problemas.append(f"escrituras fuera del escenario: {sorted(map(str, fuera))}")
    return problemas


# --- salida -----------------------------------------------------------------------


class Abortado(Exception):
    """Termina la corrida con salida 1 y el mensaje en stderr."""


def _salida_utf8() -> None:
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", line_buffering=True)
        except (AttributeError, ValueError):
            pass


def _paso(numero: int, mensaje: str) -> None:
    print(f"[{numero}/7] {mensaje}")


# --- base de datos (todo lo de abajo necesita MySQL) -------------------------------


def _text():
    from sqlalchemy import text

    return text


def _existe(conexion, base: str) -> bool:
    text = _text()
    return conexion.execute(
        text("SELECT 1 FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = :b"), {"b": base}
    ).first() is not None


def _tablas(conexion, base: str) -> set[str]:
    text = _text()
    return set(
        conexion.execute(
            text(
                "SELECT TABLE_NAME FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = :b AND TABLE_TYPE = 'BASE TABLE'"
            ),
            {"b": base},
        ).scalars()
    )


def _vistas(conexion, base: str) -> dict[str, str]:
    text = _text()
    return dict(
        conexion.execute(
            text(
                "SELECT TABLE_NAME, VIEW_DEFINITION FROM information_schema.VIEWS "
                "WHERE TABLE_SCHEMA = :b"
            ),
            {"b": base},
        ).all()
    )


def _checksums(conexion, base: str) -> dict[str, int | None]:
    """CHECKSUM TABLE: un número por tabla. No devuelve ni lee filas a Python."""
    text = _text()
    tablas = sorted(_tablas(conexion, base))
    if not tablas:
        return {}
    lista = ", ".join(f"`{base}`.`{t}`" for t in tablas)
    filas = conexion.execute(text(f"CHECKSUM TABLE {lista}")).all()
    return {nombre.split(".", 1)[1]: suma for nombre, suma in filas}


def _huella(sumas: dict[str, int | None]) -> str:
    cuerpo = "\n".join(f"{t}:{s}" for t, s in sorted(sumas.items()))
    return hashlib.sha256(cuerpo.encode()).hexdigest()[:16]


def _protegidas_presentes(conexion, protegidas: set[str]) -> list[str]:
    return sorted(b for b in protegidas if IDENTIFICADOR.match(b) and _existe(conexion, b))


def _leer_marcador(conexion, demo: str) -> dict | None:
    text = _text()
    if MARCADOR_TABLA not in _tablas(conexion, demo):
        return None
    fila = conexion.execute(
        text(
            f"SELECT clave, version, base_sim FROM `{demo}`.`{MARCADOR_TABLA}` "
            "WHERE clave = :c"
        ),
        {"c": MARCADOR_CLAVE},
    ).mappings().first()
    return dict(fila) if fila else None


def _inventario(conexion, demo: str, sim: str) -> dict:
    demo_existe = _existe(conexion, demo)
    sim_existe = _existe(conexion, sim)
    estado_demo, estado_sim, motivos = clasificar(
        demo_existe=demo_existe,
        marcador=_leer_marcador(conexion, demo) if demo_existe else None,
        sim=sim,
        sim_existe=sim_existe,
        sim_tablas=_tablas(conexion, sim) if sim_existe else set(),
        vistas_sim=_vistas(conexion, sim) if sim_existe else {},
        demo=demo,
    )
    if motivos:
        raise Abortado(
            "colisión con bases ajenas; no se escribió nada:\n  - " + "\n  - ".join(motivos)
        )
    return {"demo": estado_demo, "sim": estado_sim}


def _cuentas_existentes(conexion, sim: str) -> dict[str, dict]:
    from sqlalchemy import bindparam

    text = _text()
    if "usuarios_sistema" not in _tablas(conexion, sim):
        return {}
    filas = conexion.execute(
        text(
            f"SELECT username, rol, activo, debe_cambiar, usuario_turnos_id, nombre "
            f"FROM `{sim}`.`usuarios_sistema` "
            "WHERE username IN :nombres OR usuario_turnos_id IN :ids"
        ).bindparams(bindparam("nombres", expanding=True), bindparam("ids", expanding=True)),
        {
            "nombres": [c["username"] for c in CUENTAS] + [c["login"] for c in CASOS],
            "ids": [c["usuario_id"] for c in CASOS],
        },
    ).mappings().all()
    return {f["username"]: dict(f) for f in filas}


def _pedir_claves(faltantes: list[dict], largo_minimo: int, sin_revelar: bool) -> dict[str, str]:
    """Lee las claves de las cuentas a crear. Nunca las imprime ni las
    devuelve en un mensaje de error."""
    claves: dict[str, str] = {}
    for cuenta in faltantes:
        if sin_revelar:
            # Nadie la conoce: la cuenta queda inutilizable hasta que el
            # operador la resetee en su consola con app.semillas.admin.
            claves[cuenta["username"]] = secrets.token_urlsafe(32)
            continue
        clave = os.environ.get(cuenta["variable"])
        if clave is None:
            if not sys.stdin.isatty():
                raise Abortado(
                    f"falta la clave de '{cuenta['username']}': defina "
                    f"{cuenta['variable']}, use --claves-sin-revelar o corra en una consola."
                )
            clave = getpass.getpass(f"Clave temporal para '{cuenta['username']}': ")
            if getpass.getpass("Repítala: ") != clave:
                raise Abortado(f"las claves de '{cuenta['username']}' no coinciden.")
        errores = errores_de_clave(cuenta["username"], clave, largo_minimo)
        if errores:
            raise Abortado("; ".join(errores))
        claves[cuenta["username"]] = clave
    if len(set(claves.values())) != len(claves):
        raise Abortado("las cuentas del escenario son independientes: usen claves distintas.")
    return claves


def _mysql_compatible(conexion) -> str:
    text = _text()
    version = conexion.execute(text("SELECT VERSION()")).scalar_one()
    numeros = tuple(int(n) for n in re.findall(r"\d+", version)[:3])
    if numeros < (8, 0, 4):
        raise Abortado(f"MySQL {version}: las vistas necesitan REGEXP_REPLACE (8.0.4+).")
    return version


def _cabeza_alembic() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cabezas = ScriptDirectory.from_config(Config(str(RAIZ_BACK / "alembic.ini"))).get_heads()
    if len(cabezas) != 1:
        raise Abortado(f"alembic tiene {len(cabezas)} cabezas ({cabezas}): no se migra.")
    return cabezas[0]


def _crear_demo(conexion, demo: str, sim: str, estado: str) -> None:
    text = _text()
    if estado == "ausente":
        conexion.execute(
            text(f"CREATE DATABASE `{demo}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        )
        # El marcador va primero: si la corrida se corta acá, la base ya se
        # reconoce como propia en la siguiente.
        conexion.exec_driver_sql(ddl_tabla(demo, MARCADOR_TABLA))
        conexion.execute(
            text(
                f"INSERT INTO `{demo}`.`{MARCADOR_TABLA}` (clave, version, base_sim, creado) "
                "VALUES (:c, :v, :s, NOW())"
            ),
            {"c": MARCADOR_CLAVE, "v": MARCADOR_VERSION, "s": sim},
        )
    for tabla in ESQUEMA:
        conexion.exec_driver_sql(ddl_tabla(demo, tabla))


def _verificar_esquema_demo(conexion, demo: str) -> None:
    text = _text()
    filas = conexion.execute(
        text(
            "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = :b"
        ),
        {"b": demo},
    ).all()
    reales: dict[str, set[tuple[str, str]]] = {}
    for tabla, columna, tipo in filas:
        reales.setdefault(tabla, set()).add((columna, tipo.lower()))
    esperadas = {
        tabla: {(c, tipo_base(d)) for c, d in columnas} for tabla, columnas in ESQUEMA.items()
    }
    distintas = sorted(t for t in esperadas if reales.get(t) != esperadas[t])
    sobrantes = sorted(set(reales) - set(esperadas))
    if distintas or sobrantes:
        raise Abortado(
            f"'{demo}' no tiene el esquema del escenario: distintas={distintas}, "
            f"sobrantes={sobrantes}. No se corrige: revísela a mano."
        )


def _converger_fila(conexion, demo: str, tabla: str, fila: dict) -> str:
    """Inserta la fila si falta; si está, exige que sea idéntica."""
    text = _text()
    clave = clave_de(tabla)
    existe = conexion.execute(
        text(f"SELECT 1 FROM `{demo}`.`{tabla}` WHERE `{clave}` = :k"), {"k": fila[clave]}
    ).first()
    if existe is None:
        columnas = ", ".join(f"`{c}`" for c in fila)
        valores = ", ".join(f":{c}" for c in fila)
        conexion.execute(
            text(f"INSERT INTO `{demo}`.`{tabla}` ({columnas}) VALUES ({valores})"), fila
        )
        return "creada"
    # Comparación byte a byte: con utf8mb4_unicode_ci, 'Té' y 'te' serían iguales.
    igual = " AND ".join(f"CAST(`{c}` AS BINARY) <=> CAST(:{c} AS BINARY)" for c in fila)
    if conexion.execute(text(f"SELECT 1 FROM `{demo}`.`{tabla}` WHERE {igual}"), fila).first():
        return "igual"
    raise Abortado(
        f"{demo}.{tabla} {clave}={fila[clave]} existe con otros valores: colisión. "
        "No se modifica."
    )


def _sin_filas_ajenas(conexion, demo: str) -> None:
    """La base sintética contiene SOLO filas de este archivo."""
    text = _text()
    problemas = []
    for tabla, filas in CATALOGO.items():
        clave = clave_de(tabla)
        esperadas = {f[clave] for f in filas}
        presentes = set(conexion.execute(text(f"SELECT `{clave}` FROM `{demo}`.`{tabla}`")).scalars())
        if presentes != esperadas:
            problemas.append(f"{tabla}: {sorted(map(str, presentes ^ esperadas))} no coinciden")
    pares = ", ".join(f"({c['usuario_id']}, {c['turno_id']})" for c in CASOS)
    ancla = {"ancla": ANCLA_ORDINAL, "ord": ANCLA_ORDINAL.toordinal()}
    asignaciones = conexion.execute(
        text(
            f"SELECT COUNT(*) FROM `{demo}`.`turnos_asignados` WHERE NOT ("
            f"(usuario_id, turno_id) IN ({pares}) AND id = :base + "
            "(usuario_id - :u0) * 1000000 + :ord + DATEDIFF(fecha, :ancla))"
        ),
        {"base": BASE_ID_ASIGNACION, "u0": BASE_USUARIO, **ancla},
    ).scalar_one()
    if asignaciones:
        problemas.append(f"turnos_asignados: {asignaciones} filas que no son del escenario")
    con_novedad = [c["usuario_id"] for c in CASOS if c["novedad"]]
    novedades = conexion.execute(
        text(
            f"SELECT COUNT(*) FROM `{demo}`.`novedades_laborales` n "
            f"LEFT JOIN `{demo}`.`turnos_asignados` ta ON ta.id = n.asignacion_id "
            "WHERE NOT COALESCE(n.id = n.asignacion_id AND n.tipo_novedad = :tipo "
            f"AND ta.usuario_id IN ({', '.join(map(str, con_novedad))}), FALSE)"
        ),
        {"tipo": NOVEDAD_IMPEDITIVA},
    ).scalar_one()
    if novedades:
        problemas.append(f"novedades_laborales: {novedades} filas que no son del escenario")
    if problemas:
        raise Abortado(f"'{demo}' tiene filas ajenas al escenario: " + "; ".join(problemas))


def _sembrar_demo(motor, demo: str, sim: str, estado: str, fecha: date) -> dict[str, int]:
    conteo = {"creada": 0, "igual": 0}
    with motor.begin() as conexion:
        _crear_demo(conexion, demo, sim, estado)
        _verificar_esquema_demo(conexion, demo)
        cargas = {**CATALOGO, **filas_de_la_fecha(fecha)}
        for tabla, filas in cargas.items():
            for fila in filas:
                conteo[_converger_fila(conexion, demo, tabla, fila)] += 1
        _sin_filas_ajenas(conexion, demo)
    return conteo


def _entorno_sim(demo: str, sim: str, registro: Path) -> dict[str, str]:
    # Las variables de entorno le ganan a comedorback/.env: alembic, la
    # semilla y la evidencia ven SOLO las bases del escenario.
    return {
        **os.environ,
        "ENTORNO": "simulacion",
        "DB_NAME": sim,
        "DB_NAME_TURNOS": demo,
        "PYTHONIOENCODING": "utf-8",
        "ESCENARIO_AUDITORIA": str(registro),
    }


def _paso_interno(paso: str, args, registro: Path) -> str:
    resultado = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--paso-interno", paso,
         "--demo", args.demo, "--sim", args.sim, "--fecha", args.fecha_efectiva.isoformat()],
        cwd=RAIZ_BACK,
        env=_entorno_sim(args.demo, args.sim, registro),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if resultado.returncode:
        raise Abortado(f"falló el paso '{paso}':\n{resultado.stdout}\n{resultado.stderr}")
    return resultado.stdout


def _migrar_sim(servidor, args, estado: str, cabeza: str, registro: Path) -> None:
    text = _text()
    if estado == "ausente":
        with servidor.connect() as conexion:
            conexion.execute(
                text(f"CREATE DATABASE `{args.sim}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            )
    _paso_interno("alembic", args, registro)
    with servidor.connect() as conexion:
        version = conexion.execute(
            text(f"SELECT version_num FROM `{args.sim}`.`alembic_version`")
        ).scalars().all()
        vistas = _vistas(conexion, args.sim)
        for vista in vistas:
            conexion.execute(text(f"SELECT 1 FROM `{args.sim}`.`{vista}` LIMIT 1")).all()
        # Lo que el servidor registra como leído por cada vista, no el texto.
        leidas = conexion.execute(
            text(
                "SELECT DISTINCT VIEW_NAME, TABLE_SCHEMA FROM information_schema.VIEW_TABLE_USAGE "
                "WHERE VIEW_SCHEMA = :b"
            ),
            {"b": args.sim},
        ).all()
    if version != [cabeza]:
        raise Abortado(f"'{args.sim}' quedó en {version}, no en la cabeza {cabeza}: no se siembra.")
    from app.core.tablas_heredadas import VISTAS_CONTRATO

    if set(vistas) != set(VISTAS_CONTRATO):
        raise Abortado(f"vistas inesperadas en '{args.sim}': {sorted(vistas)}")
    fuera = sorted({(v, b) for v, b in leidas if b.lower() != args.demo.lower()})
    sin_uso = set(VISTAS_CONTRATO) - {v for v, _ in leidas}
    if fuera or sin_uso:
        raise Abortado(
            f"VIEW_TABLE_USAGE de '{args.sim}': lecturas fuera de '{args.demo}' {fuera}, "
            f"vistas sin tablas registradas {sorted(sin_uso)}"
        )


def _crear_cuentas(motor_sim, claves: dict[str, str]) -> list[str]:
    from app.core import seguridad

    text = _text()
    creadas = []
    with motor_sim.begin() as conexion:
        for cuenta in CUENTAS:
            clave = claves.get(cuenta["username"])
            if clave is None:
                continue
            conexion.execute(
                text(
                    "INSERT INTO usuarios_sistema (username, password_hash, rol, debe_cambiar, "
                    "activo, version_token, usuario_turnos_id, nombre, creada_por_cuenta) "
                    "VALUES (:u, :h, :r, 1, 1, 0, NULL, :n, NULL)"
                ),
                {
                    "u": cuenta["username"],
                    "h": seguridad.hashear_clave(clave),
                    "r": cuenta["rol"],
                    "n": cuenta["nombre"],
                },
            )
            creadas.append(cuenta["username"])
    return creadas


# --- pasos internos (corren con DB_NAME / DB_NAME_TURNOS del escenario) ------------


def _exigir_bases_del_escenario(args) -> None:
    from app.core.config import config

    if (config.db_name, config.db_name_turnos) != (args.sim, args.demo):
        raise Abortado(
            f"paso interno con bases inesperadas: {config.db_name}/{config.db_name_turnos}"
        )


def _correr_alembic() -> None:
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(str(RAIZ_BACK / "alembic.ini")), "head")


def _correr_semilla() -> None:
    from app.semillas.__main__ import main as sembrar

    sembrar()


def _derecho_de(sesion, usuario_id: int, fecha: date) -> dict:
    from sqlalchemy import select

    from app.consultas import derecho as consultas_derecho
    from app.modelos.heredados import ComidaPorTurno, NovedadLaboral, TurnoAsignado

    asignaciones = sesion.execute(
        select(TurnoAsignado).where(TurnoAsignado.usuario_id == usuario_id)
        .order_by(TurnoAsignado.fecha)
    ).scalars().all()
    filas_vista = sesion.execute(
        select(ComidaPorTurno).where(
            ComidaPorTurno.usuario_id == usuario_id, ComidaPorTurno.fecha_comida == fecha
        )
    ).scalars().all()
    novedades = sesion.execute(
        select(NovedadLaboral.tipo_novedad).where(
            NovedadLaboral.asignacion_id.in_([a.id for a in asignaciones] or [0])
        )
    ).scalars().all()
    derechos = consultas_derecho.derechos_del_dia(sesion, usuario_id, fecha)
    del_almuerzo = consultas_derecho.buscar_derecho(sesion, usuario_id, COMIDA_ID, fecha)
    return {
        "asignaciones": [
            {"turno_asignado_id": a.id, "fecha": a.fecha.isoformat(), "turno": a.turno,
             "duracion_horas": a.duracion_horas}
            for a in asignaciones
        ],
        "filas_v_comidas_por_turno": [
            {"turno_asignado_id": f.turno_asignado_id, "comida_id": f.comida_id,
             "duracion_horas": f.duracion_horas, "categoria": f.categoria}
            for f in filas_vista
        ],
        "novedades_v_novedades_laborales": sorted(novedades),
        "derechos_del_dia": [d.comida_id for d in derechos],
        "derecho_al_almuerzo": del_almuerzo is not None,
        "turno_asignado_que_lo_justifica": del_almuerzo.turno_asignado_id if del_almuerzo else None,
    }


def _contraste(fecha: date) -> dict:
    """La MISMA asignación, medida con las vistas y reglas reales sin y con la
    novedad impeditiva. La novedad vive solo dentro de una transacción que se
    revierte; al final se comprueba, con otra conexión, que no quedó."""
    from sqlalchemy.orm import Session

    from app.core.config import config
    from app.core.db import motor

    text = _text()
    asignacion = fila_asignacion(fecha, CONTRASTE_ID)
    novedad = fila_novedad(asignacion, NOVEDAD_IMPEDITIVA)
    with motor.connect() as conexion:
        transaccion = conexion.begin()
        try:
            with Session(bind=conexion) as sesion:
                sin = _derecho_de(sesion, CONTRASTE_ID, fecha)
                columnas = ", ".join(f"`{c}`" for c in novedad)
                conexion.execute(
                    text(
                        f"INSERT INTO `{config.db_name_turnos}`.`novedades_laborales` "
                        f"({columnas}) VALUES ({', '.join(':' + c for c in novedad)})"
                    ),
                    novedad,
                )
                con = _derecho_de(sesion, CONTRASTE_ID, fecha)
        finally:
            transaccion.rollback()
    with motor.connect() as conexion:
        persistida = conexion.execute(
            text(
                f"SELECT COUNT(*) FROM `{config.db_name_turnos}`.`novedades_laborales` "
                "WHERE asignacion_id = :a"
            ),
            {"a": asignacion["id"]},
        ).scalar_one()
    return {
        "usuario_id": CONTRASTE_ID,
        "turno_asignado_id": asignacion["id"],
        "tipo_novedad": NOVEDAD_IMPEDITIVA,
        "sin_novedad": sin,
        "con_novedad": con,
        "novedad_persistida_tras_revertir": persistida,
    }


def evidencia(fecha: date) -> dict:
    """El derecho calculado por la aplicación sobre MySQL: vistas v_* reales
    de --sim leyendo --demo, y app/consultas/derecho.py."""
    from sqlalchemy import func, select

    from app.consultas import derecho as consultas_derecho
    from app.consultas.horarios import ventanas_del_dia
    from app.core.config import config
    from app.core.db import SesionLocal
    from app.logica.marcacion import categoria_reporte_de, resolver_comida_en_curso
    from app.modelos.comedor import Asistencia, CategoriaReporte, LecturaBiometrica
    from app.modelos.heredados import Comensal
    from app.modelos.reglas import ReglaDerecho, ReglaDerechoNovedad
    from app.modelos.usuarios import UsuarioSistema

    with SesionLocal() as sesion:
        regla = sesion.execute(
            select(ReglaDerecho)
            .where(ReglaDerecho.vigente_desde <= fecha)
            .order_by(ReglaDerecho.vigente_desde.desc(), ReglaDerecho.id.desc())
            .limit(1)
        ).scalar_one()
        anulan = sorted(
            sesion.execute(
                select(ReglaDerechoNovedad.tipo_novedad).where(
                    ReglaDerechoNovedad.regla_id == regla.id
                )
            ).scalars()
        )
        casos = []
        for c in CASOS:
            comensal = sesion.execute(
                select(Comensal).where(Comensal.usuario_id == c["usuario_id"])
            ).scalar_one()
            medido = _derecho_de(sesion, c["usuario_id"], fecha)
            casos.append({
                "caso": c["caso"],
                "usuario_id": c["usuario_id"],
                "login": comensal.login,
                "categoria": comensal.categoria,
                "factor": c["factor"],
                "derecho_esperado": c["derecho"],
                **medido,
            })
        ventanas = next(
            (x.ventanas for x in ventanas_del_dia(sesion, fecha) if x.comida_id == COMIDA_ID), ()
        )
        en_curso = None
        if ventanas:
            medio = ventanas[0].inicio + (ventanas[0].fin - ventanas[0].inicio) / 2
            comida = resolver_comida_en_curso(sesion, medio)
            en_curso = {
                "momento": medio.isoformat(),
                "comida_id": comida.comida_id if comida else None,
                "fecha_comida": comida.fecha_comida.isoformat() if comida else None,
            }
        columna = sesion.execute(
            select(CategoriaReporte.codigo).where(
                CategoriaReporte.id == categoria_reporte_de(sesion, USUARIO_ID)
            )
        ).scalar_one()
        raciones = sesion.execute(
            select(func.count()).select_from(Asistencia).where(
                Asistencia.usuario_id == USUARIO_ID,
                Asistencia.fecha_comida == fecha,
                Asistencia.comida_id == COMIDA_ID,
            )
        ).scalar_one()
        lecturas = sesion.execute(
            select(func.count()).select_from(LecturaBiometrica).where(
                LecturaBiometrica.usuario_id == USUARIO_ID,
                LecturaBiometrica.fecha_hora >= datetime.combine(fecha, time.min),
                LecturaBiometrica.fecha_hora < datetime.combine(fecha + timedelta(days=1), time.min),
            )
        ).scalar_one()
        con_derecho = consultas_derecho.contar_personas_con_derecho(sesion, COMIDA_ID, fecha)
        cuentas = sesion.execute(
            select(UsuarioSistema).where(
                UsuarioSistema.username.in_([c["username"] for c in CUENTAS])
            ).order_by(UsuarioSistema.id)
        ).scalars().all()
        cuentas_de_comensales = sesion.execute(
            select(func.count()).select_from(UsuarioSistema).where(
                UsuarioSistema.usuario_turnos_id.in_([c["usuario_id"] for c in CASOS])
                | UsuarioSistema.username.in_([c["login"] for c in CASOS])
            )
        ).scalar_one()

    return {
        "bases": {"propia": config.db_name, "turnos": config.db_name_turnos},
        "fecha": fecha.isoformat(),
        "regla_vigente": {
            "id": regla.id,
            "vigente_desde": regla.vigente_desde.isoformat(),
            "duracion_minima_horas": regla.duracion_minima_horas,
            "excluir_enfermeria": bool(regla.excluir_enfermeria),
            "novedades_que_anulan": anulan,
        },
        "casos": casos,
        "contraste_novedad": _contraste(fecha),
        "personas_con_derecho_al_almuerzo": con_derecho,
        "ventanas_del_almuerzo": [[v.inicio.isoformat(), v.fin.isoformat()] for v in ventanas],
        "comida_en_curso_a_mitad_de_ventana": en_curso,
        "columna_del_informe_principal": columna,
        "raciones_principal": raciones,
        "lecturas_principal": lecturas,
        "cuentas": [
            {"id": c.id, "username": c.username, "rol": c.rol, "activo": bool(c.activo),
             "debe_cambiar": bool(c.debe_cambiar), "vinculo_padron": c.usuario_turnos_id}
            for c in cuentas
        ],
        "cuentas_de_comensales": cuentas_de_comensales,
    }


def problemas_de_evidencia(datos: dict) -> list[str]:
    """Lo que tiene que ser cierto para declarar el escenario listo (la ración
    principal se informa aparte)."""
    problemas = []
    for c in datos["casos"]:
        if c["derecho_al_almuerzo"] != c["derecho_esperado"]:
            problemas.append(
                f"{c['caso']}: derecho {c['derecho_al_almuerzo']}, se esperaba {c['derecho_esperado']}."
            )
    contraste = datos["contraste_novedad"]
    if not contraste["sin_novedad"]["derecho_al_almuerzo"]:
        problemas.append("contraste: sin novedad no hay derecho.")
    if contraste["con_novedad"]["derecho_al_almuerzo"]:
        problemas.append("contraste: con la novedad impeditiva sigue habiendo derecho.")
    if NOVEDAD_IMPEDITIVA not in contraste["con_novedad"]["novedades_v_novedades_laborales"]:
        problemas.append("contraste: la novedad no se vio por v_novedades_laborales.")
    if contraste["novedad_persistida_tras_revertir"]:
        problemas.append("contraste: la novedad quedó guardada.")
    if datos["cuentas_de_comensales"]:
        problemas.append("algún comensal del escenario tiene cuenta de acceso.")
    en_curso = datos["comida_en_curso_a_mitad_de_ventana"]
    if not en_curso or en_curso["comida_id"] != COMIDA_ID:
        problemas.append("ningún horario vigente resuelve el almuerzo en esa fecha.")
    esperadas = {(c["username"], c["rol"]) for c in CUENTAS}
    if {(c["username"], c["rol"]) for c in datos["cuentas"]} != esperadas:
        problemas.append("faltan cuentas del escenario o tienen otro rol.")
    for cuenta in datos["cuentas"]:
        if not cuenta["activo"] or cuenta["vinculo_padron"]:
            problemas.append(f"la cuenta {cuenta['username']} no quedó activa y sin vínculo.")
    return problemas


def armar_manifiesto(datos: dict, *, demo: str, sim: str, cabeza: str, mysql: str,
                     auditoria: list[dict], protegidas: dict, script_sha: str) -> dict:
    """Todo lo que A3 necesita, sin claves, hashes ni tokens."""
    principal = next(c for c in datos["casos"] if c["caso"] == "principal")
    turno = next(t for t in CATALOGO["turnos"] if t["id"] == TURNO_12H)
    categoria = next(x for x in CATALOGO["categorias"] if x["id"] == CATEGORIA_ADMIN)
    asignacion = next(
        (a for a in principal["asignaciones"] if a["fecha"] == datos["fecha"]), None
    )
    return {
        "escenario": MARCADOR_CLAVE,
        "version": MARCADOR_VERSION,
        "generado": datetime.now().isoformat(timespec="seconds"),
        "script_sha256": script_sha,
        "bases": {"turnos_sintetica": demo, "propia": sim, "alembic": cabeza, "mysql": mysql},
        "cuentas": datos["cuentas"],
        "comensal": {
            "usuario_id": USUARIO_ID,
            "login": USUARIO_LOGIN,
            "categoria": {"id": categoria["id"], "nombre": categoria["nombre"]},
            "columna_del_informe": datos["columna_del_informe_principal"],
            "cuentas_de_acceso": 0 if not datos["cuentas_de_comensales"] else "REVISAR",
            "identificacion_simulada": {
                "identificador": IDENTIFICADOR_SIMULADO,
                "tabla": f"{demo}.escenario_identificaciones",
                "contenido": "solo texto: sin imagen, huella ni plantilla",
                "uso_en_el_lector_simulado": f"POST /asistencias {{usuario_id: {USUARIO_ID}}} "
                                             "con ENTORNO=simulacion",
            },
        },
        "turno": {k: turno[k] for k in ("id", "nombre_turno", "duracion_horas", "hora_inicio", "hora_fin")},
        "asignacion": asignacion,
        "comida": {"id": COMIDA_ID, "codigo": COMIDA_CODIGO},
        "fecha": datos["fecha"],
        "ventana": datos["ventanas_del_almuerzo"],
        "regla_vigente": datos["regla_vigente"],
        "derecho_principal": {
            "derecho_al_almuerzo": principal["derecho_al_almuerzo"],
            "derechos_del_dia": principal["derechos_del_dia"],
            "fila_v_comidas_por_turno": principal["filas_v_comidas_por_turno"],
            "calculado_con": "vistas v_* de la base propia + app/consultas/derecho.py (MySQL)",
        },
        "racion_principal": {
            "raciones": datos["raciones_principal"],
            "lecturas": datos["lecturas_principal"],
            "disponible_para_cocina": datos["raciones_principal"] == 0,
        },
        "casos_negativos": [
            {k: c[k] for k in ("caso", "usuario_id", "login", "categoria", "factor",
                               "asignaciones", "filas_v_comidas_por_turno",
                               "novedades_v_novedades_laborales", "derecho_esperado",
                               "derecho_al_almuerzo")}
            for c in datos["casos"] if c["caso"].startswith("negativo_")
        ],
        "contraste_novedad": datos["contraste_novedad"],
        "personas_con_derecho_al_almuerzo": datos["personas_con_derecho_al_almuerzo"],
        "auditoria_escrituras": auditoria,
        "bases_protegidas_checksum": protegidas,
    }


# --- orquestación -------------------------------------------------------------------


def _argumentos(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo", default=DEMO_POR_DEFECTO, help="base de turnos sintética (*_demo)")
    parser.add_argument("--sim", default=SIM_POR_DEFECTO, help="bd_nutricion del escenario (*_sim)")
    parser.add_argument(
        "--fecha",
        type=date.fromisoformat,
        default=None,
        help="fecha del turno y del almuerzo (por defecto, hoy según el reloj real)",
    )
    parser.add_argument(
        "--solo-inventario",
        action="store_true",
        help="solo los pasos de lectura (0-2): no crea ni escribe nada",
    )
    parser.add_argument("--manifiesto", type=Path, default=None,
                        help="archivo JSON donde escribir el manifiesto (sin secretos)")
    parser.add_argument("--claves-sin-revelar", action="store_true",
                        help="claves al azar que nadie conoce; resetear con app.semillas.admin")
    parser.add_argument("--paso-interno", choices=PASOS[1:], help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    args.fecha_efectiva = args.fecha or date.today()
    return args


def _leer_registro(registro: Path) -> list[dict]:
    if not registro.exists():
        return []
    return [json.loads(linea) for linea in registro.read_text(encoding="utf-8").splitlines() if linea]


def _preparar(args: argparse.Namespace) -> int:
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    from app.core import seguridad
    from app.core.config import config

    fecha = args.fecha_efectiva
    protegidas = {config.db_name, config.db_name_turnos} | BASES_PROTEGIDAS
    errores = errores_de_nombres(args.demo, args.sim, protegidas)
    if errores:
        raise Abortado("\n  - ".join(["nombres no válidos:", *errores]))

    servidor = create_engine(config.url_servidor, future=True, isolation_level="AUTOCOMMIT")
    transaccional = create_engine(config.url_servidor, future=True)
    motor_sim = create_engine(make_url(config.url_base_datos).set(database=args.sim), future=True)
    registro = Path(tempfile.mkdtemp(prefix="escenario_")) / "auditoria.jsonl"
    quitar = instalar_auditor(paso="principal", demo=args.demo, sim=args.sim, registro=registro)
    try:
        with servidor.connect() as conexion:
            presentes = _protegidas_presentes(conexion, protegidas)
            antes = {b: _checksums(conexion, b) for b in presentes}
        _paso(0, f"Bases protegidas presentes (solo CHECKSUM): {', '.join(presentes) or 'ninguna'}")
        for base in presentes:
            print(f"      {base}: {_huella(antes[base])} ({len(antes[base])} tablas)")

        with servidor.connect() as conexion:
            estados = _inventario(conexion, args.demo, args.sim)
            cuentas = _cuentas_existentes(conexion, args.sim) if estados["sim"] == "propia" else {}
        _paso(1, f"Inventario: '{args.demo}' {estados['demo']}, '{args.sim}' {estados['sim']}.")
        errores = errores_de_cuentas(cuentas)
        if errores:
            raise Abortado("\n  - ".join(["cuentas en conflicto:", *errores]))

        with servidor.connect() as conexion:
            version_mysql = _mysql_compatible(conexion)
        cabeza = _cabeza_alembic()
        _paso(2, f"Dependencias: MySQL {version_mysql}, alembic head {cabeza}.")
        if args.solo_inventario:
            print("\n--solo-inventario: no se escribió nada.")
            return 0

        faltantes = [c for c in CUENTAS if c["username"] not in cuentas]
        claves = _pedir_claves(
            faltantes, seguridad.ajustes().largo_minimo_clave, args.claves_sin_revelar
        )

        conteo = _sembrar_demo(transaccional, args.demo, args.sim, estados["demo"], fecha)
        _paso(
            3,
            f"'{args.demo}': {conteo['creada']} filas creadas, {conteo['igual']} ya estaban "
            f"idénticas. Asignación principal {id_asignacion(fecha)} para {fecha}.",
        )

        _migrar_sim(servidor, args, estados["sim"], cabeza, registro)
        salida_semilla = _paso_interno("semilla", args, registro)
        _paso(4, f"'{args.sim}': alembic en {cabeza}, vistas sobre '{args.demo}', semilla corrida.")
        for linea in salida_semilla.strip().splitlines():
            print(f"      {linea}")

        creadas = _crear_cuentas(motor_sim, claves)
        claves.clear()
        existentes = sorted(set(cuentas) & {c["username"] for c in CUENTAS})
        _paso(
            5,
            f"Cuentas creadas: {', '.join(creadas) or 'ninguna'}; ya existían sin cambios: "
            f"{', '.join(existentes) or 'ninguna'}. Claves no mostradas.",
        )

        datos = json.loads(_paso_interno("evidencia", args, registro))
        _paso(6, "Derecho calculado en MySQL con las vistas v_* y app/consultas/derecho.py.")

        with servidor.connect() as conexion:
            despues = {b: _checksums(conexion, b) for b in presentes}
        cambiadas = sorted(b for b in presentes if antes[b] != despues[b])
        _paso(7, "CHECKSUM de las bases protegidas después: "
              + (", ".join(f"{b}={_huella(despues[b])}" for b in presentes) or "ninguna"))
    finally:
        quitar()
        servidor.dispose()
        transaccional.dispose()
        motor_sim.dispose()

    registros = _leer_registro(registro)
    problemas = problemas_de_auditoria(registros, args.demo, args.sim)
    problemas += problemas_de_evidencia(datos)
    if cambiadas:
        problemas.append(
            f"cambiaron durante la corrida: {cambiadas}. Este script no les escribe; "
            "¿había una API o un proceso trabajando sobre ellas?"
        )
    manifiesto = armar_manifiesto(
        datos, demo=args.demo, sim=args.sim, cabeza=cabeza, mysql=version_mysql,
        auditoria=resumir_auditoria(registros),
        protegidas={b: {"antes": _huella(antes[b]), "despues": _huella(despues[b])} for b in presentes},
        script_sha=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    )
    texto = json.dumps(manifiesto, ensure_ascii=False, indent=2)
    print(texto)
    if args.manifiesto:
        args.manifiesto.write_text(texto + "\n", encoding="utf-8")
        print(f"\nManifiesto: {args.manifiesto}")
    print(f"Registro de auditoría (SQL sin parámetros): {registro}")
    if problemas:
        raise Abortado("el escenario no quedó listo:\n  - " + "\n  - ".join(problemas))
    if datos["raciones_principal"]:
        print(
            f"\nEl almuerzo principal del {fecha} YA se registró ({datos['raciones_principal']}): "
            "no se borra. Para un escenario disponible, corra con otra --fecha.",
            file=sys.stderr,
        )
        return 3
    print(f"\nListo: almuerzo del {fecha} disponible para usuariosimulado ({USUARIO_ID}).")
    return 0


def _correr_paso_interno(args) -> int:
    _exigir_bases_del_escenario(args)
    registro = os.environ.get("ESCENARIO_AUDITORIA")
    quitar = instalar_auditor(
        paso=args.paso_interno, demo=args.demo, sim=args.sim,
        registro=Path(registro) if registro else None,
    )
    try:
        if args.paso_interno == "alembic":
            _correr_alembic()
        elif args.paso_interno == "semilla":
            _correr_semilla()
        else:
            print(json.dumps(evidencia(args.fecha_efectiva), ensure_ascii=False))
    finally:
        quitar()
    return 0


def main(argv: list[str] | None = None) -> int:
    _salida_utf8()
    args = _argumentos(argv)
    # Recién acá se toca el entorno del proceso: importar el script no hace
    # nada (ver tests/test_escenario_sintetico.py).
    os.chdir(RAIZ_BACK)
    if str(RAIZ_BACK) not in sys.path:
        sys.path.insert(0, str(RAIZ_BACK))
    try:
        if args.paso_interno:
            return _correr_paso_interno(args)
        return _preparar(args)
    except (Abortado, AuditoriaViolada) as error:
        print(f"ABORTADO: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
