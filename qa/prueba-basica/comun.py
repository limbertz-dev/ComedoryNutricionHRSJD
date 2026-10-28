"""Infraestructura QA; importar este módulo no conecta ni carga configuración de app."""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine, URL

CARPETA = Path(__file__).resolve().parent
RAIZ = CARPETA.parents[1]
SIM = "bd_nutricion_escenario_sim"
DEMO = "bd_turnos_escenario_demo"
PROTEGIDA = "bd_proyecto_backend"
MARCADOR = "comedor-escenario-sintetico"
USUARIO = 900001
ASIGNACION = 91739904
COMIDA = 2
COMIDAS_LABORATORIO = {
    1: {'id': 1, 'nombre': 'Desayuno', 'codigo': 'desayuno', 'hora': '08:00:00'},
    2: {'id': 2, 'nombre': 'Almuerzo', 'codigo': 'almuerzo', 'hora': '12:00:00'},
    3: {'id': 3, 'nombre': 'Té', 'codigo': 'te', 'hora': '16:00:00'},
    4: {'id': 4, 'nombre': 'Cena', 'codigo': 'cena', 'hora': '19:00:00'},
}
TURNO_LABORATORIO = 900101
DISPOSITIVO = "lector-prueba-qa"
MANIFIESTO_COMENSALES = CARPETA / "manifiesto_comensales_qa.json"
USUARIOS_HISTORICOS = frozenset(range(900001, 900008))
CASOS_EJECUTABLES = ("qa01", "qa02")
PERFILES_QA = {
    900101: {'categoria_id': 9003, 'categoria': 'Medicos', 'servicio_id': 9003, 'servicio': 'MEDICINA INTERNA'},
    900102: {'categoria_id': 9004, 'categoria': 'Tecnicos', 'servicio_id': 9004, 'servicio': 'LABORATORIO'},
    900103: {'categoria_id': 9005, 'categoria': 'Internos', 'servicio_id': 9005, 'servicio': 'IMAGENOLOGIA'},
}
COMENSALES_QA = {
    "qa01": {
        "codigo": "qa01",
        "etiqueta": "QA 01",
        "rol_escenario": "registro_normal",
        "usuario_id": 900101,
        "asignacion_id": 191739904,
        "login": "qa01_normal",
        "nombre": "QA 01 NORMAL",
        "legajo": "LEG-QA01",
        "carnet_identidad": "SIM-900101",
        "identificador_unico": "SIM-ID-900101",
        "tipo_trabajador": "Eventual",
        "categoria_id": 9001,
        "servicio_id": 9001,
        "turno_id": 9001,
        "fecha_base": "2026-10-15",
        "comida_id": COMIDA,
        "ejecutable": True,
        "modo_marcacion": "reconocida",
        "cuenta_identificadora": None,
    },
    "qa02": {
        "codigo": "qa02",
        "etiqueta": "QA 02",
        "rol_escenario": "identificacion",
        "usuario_id": 900102,
        "asignacion_id": 192739904,
        "login": "qa02_identificacion",
        "nombre": "QA 02 IDENTIFICACION",
        "legajo": "LEG-QA02",
        "carnet_identidad": "SIM-900102",
        "identificador_unico": "SIM-ID-900102",
        "tipo_trabajador": "Eventual",
        "categoria_id": 9001,
        "servicio_id": 9001,
        "turno_id": 9001,
        "fecha_base": "2026-10-15",
        "comida_id": COMIDA,
        "ejecutable": True,
        "modo_marcacion": "no_reconocida",
        "cuenta_identificadora": "cocinera2",
    },
    "qa03": {
        "codigo": "qa03",
        "etiqueta": "QA 03",
        "rol_escenario": "reserva",
        "usuario_id": 900103,
        "asignacion_id": 193739904,
        "login": "qa03_reserva",
        "nombre": "QA 03 RESERVA",
        "legajo": "LEG-QA03",
        "carnet_identidad": "SIM-900103",
        "identificador_unico": "SIM-ID-900103",
        "tipo_trabajador": "Eventual",
        "categoria_id": 9001,
        "servicio_id": 9001,
        "turno_id": 9001,
        "fecha_base": "2026-10-15",
        "comida_id": COMIDA,
        "ejecutable": False,
        "modo_marcacion": "reserva",
        "cuenta_identificadora": None,
    },
}
CUENTAS = {
    "cocinera1": "cocinera",
    "cocinera2": "cocinera",
    "cocinera3": "cocinera",
    "jefa": "jefa",
}
CUENTAS_BASE = ("cocinera2", "cocinera3")
CAMPOS_SECRETOS = frozenset({
    "password", "password_nueva", "password_actual", "password_hash",
    "clave", "clave_temporal", "clave_nueva", "access", "refresh", "temporal", "token",
})
CONTADORES_DIARIO = ("max_intento_inicial", "max_sesion_inicial")
CORRIDA = CARPETA / "corrida.json"
REQUERIDAS = ("DB_NAME", "DB_NAME_TURNOS", "DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD")
RELOJ_POR_DEFECTO = "2026-10-15T11:30:00"


class Abortado(RuntimeError):
    """Mensaje seguro para el operador: nunca contiene SQL, parámetros o secretos."""


def validar_entorno(entorno=None):
    entorno = os.environ if entorno is None else entorno
    sin_clave = entorno.get("QA_DB_SIN_CLAVE") == "1"
    for nombre in REQUERIDAS:
        if nombre == "DB_PASSWORD" and nombre not in entorno and sin_clave:
            continue
        if nombre not in entorno or (nombre != "DB_PASSWORD" and not entorno[nombre]):
            raise Abortado(nombre)
    if sin_clave and entorno.get("DB_PASSWORD"):
        raise Abortado("DB_PASSWORD y QA_DB_SIN_CLAVE: configuración ambigua")
    for nombre, esperado in (("DB_NAME", SIM), ("DB_NAME_TURNOS", DEMO)):
        if entorno[nombre] != esperado:
            raise Abortado(nombre)
    try:
        puerto = int(entorno["DB_PORT"])
        if not 1 <= puerto <= 65535:
            raise ValueError
    except ValueError:
        raise Abortado("DB_PORT") from None
    return URL.create("mysql+pymysql", username=entorno["DB_USER"],
                      password=entorno.get("DB_PASSWORD", ""), host=entorno["DB_HOST"],
                      port=puerto, database=SIM, query={"charset": "utf8mb4"})


def validar_marcador(fila):
    if not fila or dict(fila) != {"clave": MARCADOR, "version": 2, "base_sim": SIM}:
        raise Abortado("Marcador del escenario ausente o incompatible")


IDENT = r"`?[A-Za-z_][A-Za-z0-9_]*`?"
DESTINO = rf"(?P<objeto>{IDENT}(?:\s*\.\s*{IDENT})?)"
PATRONES = {
    "INSERT": re.compile(rf"^INSERT\s+INTO\s+{DESTINO}\s*\(", re.I),
    "UPDATE": re.compile(rf"^UPDATE\s+{DESTINO}\s+SET\s+", re.I),
    "DELETE": re.compile(rf"^DELETE\s+FROM\s+{DESTINO}\s+WHERE\s+", re.I),
}


def revisar_sql(sentencia, base, permitidas):
    """Lista cerrada para SQL emitido por este circuito, NO parser SQL general.

    Corta comentarios (incluidos ejecutables MySQL), múltiples sentencias,
    CTE/DML multitabla, procedimientos, DDL, USE y destinos no autorizados.
    Los valores se pasan ligados, nunca interpolados.
    """
    sql = sentencia.strip()
    if not sql or any(x in sql for x in (";", "/*", "*/", "--", "#", ":=")):
        raise Abortado("Auditor: sintaxis no autorizada")
    # Quita literales únicamente para analizar palabras, no identificadores.
    palabras = re.sub(r"'(?:''|[^'])*'", "''", sql)
    if re.search(r"\b(INTO\s+(OUTFILE|DUMPFILE)|LOAD_FILE|GET_LOCK|RELEASE_LOCK)\b", palabras, re.I):
        raise Abortado("Auditor: operación no autorizada")
    if re.match(r"^SELECT\b", sql, re.I):
        if re.search(r"\b(INSERT|UPDATE|DELETE|REPLACE|CALL|INTO)\b", palabras, re.I):
            # El bloqueo de filas propia es necesario para la intervención.
            sin_bloqueo = re.sub(r"\bFOR UPDATE\b", "", palabras, flags=re.I)
            # REPLACE(...) es una funcion de texto de solo lectura. REPLACE INTO
            # sigue prohibido, igual que todo DML dentro de SELECT.
            sin_bloqueo = re.sub(r"\bREPLACE(?=\s*\()", "FUNCION_TEXTO", sin_bloqueo, flags=re.I)
            if re.search(r"\b(INSERT|UPDATE|DELETE|REPLACE|CALL|INTO)\b", sin_bloqueo, re.I):
                raise Abortado("Auditor: SELECT no permitido")
        return
    if re.fullmatch(r"SHOW (?:VARIABLES LIKE '[a-z_]+'|COLLATION|FULL TABLES FROM " + IDENT + r")", sql, re.I):
        return
    if re.fullmatch(rf"CHECKSUM TABLE `{PROTEGIDA}`\.`[A-Za-z0-9_]+` EXTENDED", sql, re.I):
        return
    if re.fullmatch(r"(?:SAVEPOINT|RELEASE SAVEPOINT|ROLLBACK TO SAVEPOINT) sa_savepoint_\d+", sql, re.I):
        return
    # Excepción cerrada para la migración aditiva de bajas lógicas, nunca DDL general.
    if (base == SIM and (SIM, "usuarios_sistema", "ADD_ELIMINADA_EN") in permitidas
            and re.fullmatch(r"ALTER TABLE `?usuarios_sistema`? ADD (?:COLUMN )?`?eliminada_en`? DATETIME(?: NULL)?", sql, re.I)):
        return
    for verbo, patron in PATRONES.items():
        m = patron.match(sql)
        if not m:
            continue
        partes = [p.strip().strip('`').lower() for p in m['objeto'].split('.')]
        destino = (partes[0], partes[1]) if len(partes) == 2 else ((base or '').lower(), partes[0])
        if (*destino, verbo) not in permitidas:
            raise Abortado("Auditor: escritura fuera de la lista permitida")
        cola = palabras[m.end():]
        if re.search(r"\b(SELECT|JOIN|UNION|FROM|USING|CALL|INTO)\b", cola, re.I):
            raise Abortado("Auditor: escritura compleja no permitida")
        if verbo == "UPDATE" and not re.search(r"\bWHERE\b", cola, re.I):
            raise Abortado("Auditor: UPDATE sin filtro")
        return
    raise Abortado("Auditor: sentencia no reconocida")


def instalar_auditor(permitidas, objetivo=Engine):
    def antes(conexion, cursor, sentencia, parametros, contexto, multiples):
        revisar_sql(sentencia, conexion.engine.url.database, permitidas)
    event.listen(objetivo, "before_cursor_execute", antes)
    return lambda: event.remove(objetivo, "before_cursor_execute", antes)


def permisos(*entradas):
    return {(base, tabla, verbo) for base, tabla, verbo in entradas}


def huella_protegida(conexion):
    tablas = conexion.execute(text(
        "SELECT TABLE_NAME FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA=:base AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME"
    ), {"base": PROTEGIDA}).scalars().all()
    if not tablas:
        raise Abortado("No se puede medir la base protegida")
    valores = {}
    for tabla in tablas:
        if not re.fullmatch(r"[A-Za-z0-9_]+", tabla):
            raise Abortado("Nombre de tabla no soportado para CHECKSUM")
        fila = conexion.execute(text(f"CHECKSUM TABLE `{PROTEGIDA}`.`{tabla}` EXTENDED")).one()
        if fila[1] is None:
            raise Abortado("CHECKSUM no disponible; no se admite una huella parcial")
        valores[tabla] = int(fila[1])
    digest = hashlib.sha256(json.dumps(valores, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {"sha256": digest, "tablas": valores}


def mostrar_huella(etiqueta, huella):
    print(f"{PROTEGIDA} {etiqueta}: {huella['sha256']} ({len(huella['tablas'])} tablas)")


# La revisión de Alembic de la app que el laboratorio exige en la base QA.
# Al agregar una migración, se cambia SOLO aquí (y se migra la base QA).
REVISION_APP = "d9f1b3c5e7a9"


def preflight(conexion, revisiones=(REVISION_APP,)):
    """Solo SELECT en conexión AUTOCOMMIT: antes de cualquier transacción DB."""
    validar_marcador(conexion.execute(text(
        f"SELECT clave, version, base_sim FROM `{DEMO}`.escenario_sintetico WHERE clave=:clave"
    ), {"clave": MARCADOR}).mappings().one_or_none())
    revision = conexion.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    if revision not in revisiones:
        raise Abortado("Revisión Alembic incompatible")
    tablas = conexion.execute(text(
        "SELECT TABLE_SCHEMA, TABLE_NAME, ENGINE FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA IN (:sim,:demo) AND TABLE_TYPE='BASE TABLE'"
    ), {"sim": SIM, "demo": DEMO}).all()
    if any(engine != "InnoDB" for _, _, engine in tablas):
        raise Abortado("El escenario requiere tablas InnoDB para rollback atómico")
    if conexion.execute(text(
        "SELECT COUNT(*) FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA IN (:sim,:demo)"
    ), {"sim": SIM, "demo": DEMO}).scalar_one():
        raise Abortado("Escenario con triggers: no se pueden auditar efectos indirectos")
    if conexion.execute(text(
        "SELECT COUNT(*) FROM information_schema.REFERENTIAL_CONSTRAINTS "
        "WHERE REFERENCED_TABLE_NAME IS NOT NULL AND UNIQUE_CONSTRAINT_SCHEMA IN (:sim,:demo) "
        "AND CONSTRAINT_SCHEMA NOT IN (:sim,:demo)"
    ), {"sim": SIM, "demo": DEMO}).scalar_one():
        raise Abortado("FK externa al escenario")
    usos = conexion.execute(text(
        "SELECT VIEW_NAME, TABLE_SCHEMA FROM information_schema.VIEW_TABLE_USAGE WHERE VIEW_SCHEMA=:sim"
    ), {"sim": SIM}).all()
    if len({v for v, _ in usos}) != 9 or any(b != DEMO for _, b in usos):
        raise Abortado("Las nueve vistas deben leer únicamente la demo")
    return conexion.execute(text("SELECT @@server_uuid")).scalar_one()


@contextmanager
def entorno_seguro(permitidas=(), *, revisiones=None):
    url = validar_entorno()  # Antes de crear motores o importar app.
    autorizadas = set()
    quitar = instalar_auditor(autorizadas)
    control = create_engine(url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    motor = None
    inicial = None
    try:
        with control.connect() as conn:
            servidor = preflight(conn) if revisiones is None else preflight(conn, revisiones)
            inicial = huella_protegida(conn)
        mostrar_huella("antes", inicial)
        autorizadas.update(permitidas)
        motor = create_engine(url, hide_parameters=True)
        yield motor, inicial, servidor
    finally:
        error_original = sys.exc_info()[1]
        try:
            if inicial is not None:
                with control.connect() as conn:
                    final = huella_protegida(conn)
                mostrar_huella("después", final)
                if inicial != final:
                    mensaje = "La huella protegida cambió; detener la prueba"
                    if error_original is not None:
                        # Solo Abortado garantiza texto sin SQL/credenciales.
                        detalle = (str(error_original) if isinstance(error_original, Abortado)
                                   else f"{type(error_original).__name__} (detalle omitido por seguridad)")
                        raise Abortado(f"Error original: {detalle}. Además: {mensaje}") from error_original
                    raise Abortado(mensaje)
        finally:
            if motor is not None:
                motor.dispose()
            control.dispose()
            quitar()


@contextmanager
def app_sin_dotenv():
    """Deshabilita la FUENTE dotenv antes de construir Configuracion/AjustesSeguridad."""
    from pydantic_settings.sources import DotEnvSettingsSource
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(RAIZ / "comedorback"))
    with patch.object(DotEnvSettingsSource, "_read_env_files", return_value={}):
        yield


def retirar_marca_api_huerfana(puerto=8001, gracia=120):
    """Quita api.activa si quedó de una API cerrada a la fuerza (ventana cerrada sin Ctrl+C).

    Solo con el puerto libre y la marca más vieja que `gracia` segundos: una API
    que está arrancando crea la marca antes de escuchar y no se confunde con una huérfana.
    """
    import socket
    marca = CARPETA / 'api.activa'
    if not marca.exists():
        return False
    with socket.socket() as conexion:
        conexion.settimeout(.5)
        if conexion.connect_ex(('127.0.0.1', puerto)) == 0:
            return False
    if time.time() - marca.stat().st_mtime < gracia:
        return False
    marca.unlink()
    print('Se retiró api.activa de una API anterior que se cerró sin Ctrl+C (puerto libre).', flush=True)
    return True


@contextmanager
def bloqueo_corrida():
    ruta = CARPETA / "corrida.lock"
    try:
        fd = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise Abortado("corrida.lock existe: otra herramienta corre o hubo interrupción; revisar GUION") from None
    try:
        os.close(fd)
        yield
    finally:
        ruta.unlink()


def _sin_secretos(valor):
    if isinstance(valor, dict):
        for clave, contenido in valor.items():
            if str(clave).lower() in CAMPOS_SECRETOS:
                raise Abortado("Prohibido guardar claves o tokens en corrida.json")
            _sin_secretos(contenido)
    elif isinstance(valor, list):
        for item in valor:
            _sin_secretos(item)


def normalizar_contador(valor, *, permitir_none=True):
    if valor is None:
        if permitir_none:
            return None
        raise Abortado("Contador del diario ausente")
    if type(valor) is int:
        if valor < 0:
            raise Abortado("Contador del diario negativo")
        return valor
    if isinstance(valor, Decimal):
        if not valor.is_finite() or valor < 0 or valor != int(valor):
            raise Abortado("Contador Decimal inválido para el diario")
        return int(valor)
    raise Abortado("Tipo de contador inválido para el diario")


def guardar_corrida(datos):
    if not isinstance(datos, dict):
        raise Abortado("El diario debe ser un objeto JSON")
    _sin_secretos(datos)
    if 'casos_por_comida' in datos:
        import copy
        if not isinstance(datos['casos_por_comida'], dict):
            raise Abortado('Historial de casos por comida invalido')
        clave = str(comida_corrida(datos))
        datos['casos_por_comida'][clave] = copy.deepcopy(datos['casos'])
        datos.setdefault('revisiones_por_comida', {})[clave] = copy.deepcopy(datos.get('revision_operador', {}))
    normalizados = {
        campo: normalizar_contador(datos[campo], permitir_none=True)
        for campo in CONTADORES_DIARIO
        if campo in datos
    }
    documento = {**datos, **normalizados}
    contenido = json.dumps(documento, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    json.loads(contenido)
    datos.update(normalizados)
    temporal = CORRIDA.with_suffix('.json.tmp')
    with temporal.open('w', encoding='utf-8') as archivo:
        archivo.write(contenido)
        archivo.flush()
        os.fsync(archivo.fileno())
    # Windows puede negar el reemplazo mientras otro proceso lee el reloj.
    # Se conserva el temporal completo y el diario anterior; no se trunca el destino.
    for intento in range(40):
        try:
            os.replace(temporal, CORRIDA)
            break
        except PermissionError as error:
            if getattr(error, 'winerror', None) not in (5, 32, 33) or intento == 39:
                raise
            time.sleep(.025)


def cargar_manifiesto_comensales(ruta=None):
    objetivo = Path(ruta) if ruta is not None else MANIFIESTO_COMENSALES
    if not objetivo.exists():
        raise Abortado("Falta manifiesto_comensales_qa.json en qa/prueba-basica/")
    try:
        manifiesto = json.loads(objetivo.read_text(encoding="utf-8"))
    except Exception:
        raise Abortado("manifiesto_comensales_qa.json inválido") from None
    if (
        not isinstance(manifiesto, dict)
        or manifiesto.get("version") != 1
        or manifiesto.get("escenario") != "tres_comensales_qa"
        or manifiesto.get("bases") != {"nutricion": SIM, "turnos": DEMO, "protegida": PROTEGIDA}
    ):
        raise Abortado("Encabezado incompatible en manifiesto_comensales_qa.json")
    comensales = manifiesto.get("comensales")
    if not isinstance(comensales, dict) or tuple(comensales) != tuple(COMENSALES_QA):
        raise Abortado("El manifiesto debe definir exactamente qa01, qa02 y qa03")
    vistos = {
        "usuario_id": set(),
        "asignacion_id": set(),
        "login": set(),
        "nombre": set(),
        "legajo": set(),
        "carnet_identidad": set(),
        "identificador_unico": set(),
    }
    for codigo, esperado in COMENSALES_QA.items():
        actual = comensales.get(codigo)
        if not isinstance(actual, dict):
            raise Abortado(f"Comensal inválido en manifiesto: {codigo}")
        if actual.get("usuario_id") in USUARIOS_HISTORICOS:
            raise Abortado(f"Colisión con comensales históricos en manifiesto: {codigo}")
        for campo in (
            "etiqueta",
            "rol_escenario",
            "usuario_id",
            "asignacion_id",
            "login",
            "nombre",
            "legajo",
            "carnet_identidad",
            "identificador_unico",
            "tipo_trabajador",
            "categoria_id",
            "servicio_id",
            "turno_id",
            "fecha_base",
            "comida_id",
            "ejecutable",
        ):
            if actual.get(campo) != esperado[campo]:
                raise Abortado(f"Atributo {campo} incompatible en manifiesto para {codigo}")
        for campo_unico, conjunto in vistos.items():
            valor = actual[campo_unico]
            if valor in conjunto:
                raise Abortado(f"Valor duplicado en manifiesto ({campo_unico}): {valor}")
            conjunto.add(valor)
    return manifiesto


def resumen_comensales_diario():
    return {
        codigo: {
            "codigo": info["codigo"],
            "etiqueta": info["etiqueta"],
            "rol_escenario": info["rol_escenario"],
            "usuario_id": info["usuario_id"],
            "asignacion_id": info["asignacion_id"],
            "login": info["login"],
            "nombre": info["nombre"],
            "legajo": info["legajo"],
            "carnet_identidad": info["carnet_identidad"],
            "identificador_unico": info["identificador_unico"],
            "comida_id": info["comida_id"],
            "ejecutable": info["ejecutable"],
        }
        for codigo, info in COMENSALES_QA.items()
    }


def comida_corrida(datos):
    comida = datos.get('comida_ensayo', COMIDA)
    if type(comida) is not int or comida not in COMIDAS_LABORATORIO:
        raise Abortado('Comida del ensayo inválida en corrida.json')
    return comida


def casos_iniciales_diario(comida=None):
    qa01 = COMENSALES_QA["qa01"]
    qa02 = COMENSALES_QA["qa02"]
    return {
        "qa01": {
            "tipo": "registro_normal",
            "usuario_id": qa01["usuario_id"],
            "comensal_previsto_id": qa01["usuario_id"],
            "asignacion_id": qa01["asignacion_id"],
            "comida_id": comida if comida is not None else qa01["comida_id"],
            "modo_marcacion": "reconocida",
            "cuenta_identificadora": None,
            "estado": "pendiente",
            "momento_lectura": None,
            "lectura_id": None,
            "asistencia_id": None,
            "intervencion_id": None,
            "respuesta": None,
            "verificado": False,
        },
        "qa02": {
            "tipo": "identificacion",
            "usuario_id": None,
            "comensal_previsto_id": qa02["usuario_id"],
            "asignacion_id": qa02["asignacion_id"],
            "comida_id": comida if comida is not None else qa02["comida_id"],
            "modo_marcacion": "no_reconocida",
            "cuenta_identificadora": qa02["cuenta_identificadora"],
            "estado": "pendiente",
            "momento_lectura": None,
            "lectura_id": None,
            "asistencia_id": None,
            "intervencion_id": None,
            "respuesta": None,
            "verificado": False,
        },
    }


def vistas_servicios(datos):
    """Proyecciones del diario por comida; conservan las referencias a sus casos."""
    servicios = dict(datos.get('casos_por_comida', {}))
    servicios[str(comida_corrida(datos))] = datos['casos']
    for clave, casos in servicios.items():
        vista = {**datos, 'comida_ensayo': int(clave), 'casos': casos}
        vista.pop('casos_por_comida', None)
        yield vista


def ids_casos_corrida(datos):
    return {caso['lectura_id'] for vista in vistas_servicios(datos)
            for caso in vista['casos'].values() if caso.get('lectura_id') is not None}


def seleccionar_servicio(datos, comida):
    """Cambiar el servicio visible no descarta lecturas ni aprobaciones de otro."""
    import copy
    if type(comida) is not int or comida not in COMIDAS_LABORATORIO:
        raise Abortado('Comida del ensayo invalida')
    validar_casos_diario(datos)
    anterior = str(comida_corrida(datos))
    servicios = datos.setdefault('casos_por_comida', {})
    revisiones = datos.setdefault('revisiones_por_comida', {})
    servicios[anterior] = copy.deepcopy(datos['casos'])
    revisiones[anterior] = copy.deepcopy(datos.get('revision_operador', {}))
    clave = str(comida)
    datos['comida_ensayo'] = comida
    datos['casos'] = copy.deepcopy(servicios.setdefault(clave, casos_iniciales_diario(comida)))
    datos['revision_operador'] = copy.deepcopy(revisiones.get(clave, {}))
    if any(info.get('lectura_id') is not None for info in datos['casos'].values()):
        datos['estado'] = 'lectura_creada'
    else:
        datos['estado'] = 'refechada' if datos.get('fecha_destino') else 'iniciada'


def es_corrida_multi(datos):
    return bool(isinstance(datos, dict) and "casos" in datos and "comensales" in datos)


def _validar_id_opcional(valor, nombre_campo):
    if valor is not None and (type(valor) is not int or valor <= 0):
        raise Abortado(f"{nombre_campo} inválido en corrida.json")


def validar_casos_diario(datos):
    if datos.get("escenario") != "tres_comensales_qa":
        raise Abortado("corrida.json no corresponde al escenario de tres comensales")
    if datos.get("comensales") != resumen_comensales_diario():
        raise Abortado("Definición de comensales alterada en corrida.json")
    if 'casos_por_comida' in datos:
        servicios = datos['casos_por_comida']
        if (not isinstance(servicios, dict) or not servicios
                or any(k not in {'1', '2', '3', '4'} for k in servicios)
                or servicios.get(str(comida_corrida(datos))) != datos['casos']):
            raise Abortado('Historial de casos por comida incompatible')
        vistos = set()
        for vista in vistas_servicios(datos):
            validar_casos_diario(vista)
            ids = {f['lectura_id'] for f in vista['casos'].values() if f.get('lectura_id') is not None}
            if vistos & ids:
                raise Abortado('Una lectura esta repetida entre comidas del diario')
            vistos |= ids
        return
    casos = datos.get("casos")
    plantilla = casos_iniciales_diario(comida_corrida(datos))
    if not isinstance(casos, dict) or set(casos) != set(plantilla):
        raise Abortado("Estructura de casos inválida en corrida.json")
    lecturas_vistas = set()
    for codigo, base in plantilla.items():
        actual = casos.get(codigo)
        if not isinstance(actual, dict):
            raise Abortado(f"Caso {codigo} inválido en corrida.json")
        for fijo in (
            "tipo",
            "usuario_id",
            "comensal_previsto_id",
            "asignacion_id",
            "comida_id",
            "modo_marcacion",
            "cuenta_identificadora",
        ):
            if actual.get(fijo) != base[fijo]:
                raise Abortado(f"Atributo fijo {fijo} alterado en caso {codigo} de corrida.json")
        if actual.get("estado") not in {
            "pendiente",
            "lectura_pendiente",
            "lectura_creada",
            "completado",
        }:
            raise Abortado(f"Estado inválido en caso {codigo} de corrida.json")
        if actual.get("momento_lectura") is not None:
            datetime.fromisoformat(actual["momento_lectura"])
        for campo_id in ("lectura_id", "asistencia_id", "intervencion_id"):
            _validar_id_opcional(actual.get(campo_id), f"{codigo}.{campo_id}")
        lid = actual.get("lectura_id")
        if lid is not None:
            if lid in lecturas_vistas:
                raise Abortado("lectura_id duplicado entre casos en corrida.json")
            lecturas_vistas.add(lid)


def _validar_cabecera_corrida(datos, servidor=None):
    if not isinstance(datos, dict) or datos.get("bases") != [SIM, DEMO]:
        raise Abortado(
            "corrida.json no corresponde a este escenario/servidor"
            if servidor is not None
            else "corrida.json no corresponde a este escenario"
        )
    if servidor is not None and datos.get("servidor") != servidor:
        raise Abortado("corrida.json no corresponde a este escenario/servidor")
    if servidor is None and not datos.get("servidor"):
        raise Abortado("corrida.json no corresponde a este escenario")
    if es_corrida_multi(datos):
        if datos.get("version") not in (1, 2):
            raise Abortado("Versión de corrida.json no soportada")
        validar_casos_diario(datos)
    else:
        if (
            datos.get("version") != 1
            or datos.get("usuario_id") != USUARIO
            or datos.get("asignacion_id") != ASIGNACION
        ):
            raise Abortado(
                "corrida.json no corresponde a este escenario/servidor"
                if servidor is not None
                else "corrida.json no corresponde a este escenario"
            )
        _validar_id_opcional(datos.get("lectura_id"), "lectura_id")
    datetime.fromisoformat(datos["inicio"])
    for campo in ("fecha_original", "fecha_destino"):
        if datos.get(campo):
            date.fromisoformat(datos[campo])


def leer_corrida(servidor):
    if not CORRIDA.exists():
        raise Abortado("Falta corrida.json; ejecutar primero comun.py --huella-base")
    datos = json.loads(CORRIDA.read_text(encoding='utf-8'))
    _validar_cabecera_corrida(datos, servidor=servidor)
    return datos


def leer_corrida_local():
    if not CORRIDA.exists():
        raise Abortado("Falta corrida.json; ejecutar primero comun.py --huella-base")
    datos = json.loads(CORRIDA.read_text(encoding='utf-8'))
    _validar_cabecera_corrida(datos, servidor=None)
    if datos.get('estado') not in {
        'iniciada', 'refechada', 'lectura_creada', 'en_curso', 'casos_ejecutados'
    }:
        raise Abortado("La corrida no está en un estado operativo para verificar cuentas")
    return datos


def rol_cuenta(username):
    rol = CUENTAS.get(username)
    if rol not in {"cocinera", "jefa"}:
        raise Abortado(f"Cuenta fuera del escenario QA: {username}")
    return rol


def validar_cuentas_iniciales(filas):
    por_nombre = {}
    for c in filas:
        nombre = c['username']
        if (nombre not in CUENTAS or nombre in por_nombre
                or c['rol'] != CUENTAS[nombre] or c['usuario_turnos_id'] is not None
                or type(c['id']) is not int or c['id'] <= 0):
            raise Abortado("Cuenta del escenario con rol, vínculo o identidad incompatible")
        por_nombre[nombre] = c['id']
    if not set(CUENTAS_BASE) <= set(por_nombre):
        raise Abortado("Se requieren las dos cocineras sintéticas existentes y sin vínculo")
    return por_nombre


def validar_cuenta_admin(conn, username):
    esperado = rol_cuenta(username)
    fila = conn.execute(text(
        "SELECT id, username, rol, usuario_turnos_id FROM usuarios_sistema "
        "WHERE username=:username"
    ), {'username': username}).mappings().one_or_none()
    if fila is not None and (fila['rol'] != esperado or fila['usuario_turnos_id'] is not None):
        raise Abortado(f"La cuenta {username} existe con otro rol o con vínculo")
    return esperado


def validar_cuentas_limpieza(filas, iniciales):
    if (not isinstance(iniciales, dict)
            or not set(CUENTAS_BASE) <= set(iniciales)
            or not set(iniciales) <= set(CUENTAS)):
        raise Abortado("Las cuentas cambiaron de identidad")
    actuales = {}
    for r in filas:
        nombre = r['username']
        if (nombre not in CUENTAS or nombre in actuales
                or r['rol'] != CUENTAS[nombre] or r['usuario_turnos_id'] is not None
                or type(r['id']) is not int or r['id'] <= 0):
            raise Abortado("Las cuentas cambiaron de identidad")
        actuales[nombre] = r['id']
    if any(actuales.get(nombre) != id_inicial for nombre, id_inicial in iniciales.items()):
        raise Abortado("Las cuentas cambiaron de identidad")
    return actuales


def comprobar_base(datos, huella):
    if datos['huella_base'] != huella:
        raise Abortado("La huella protegida difiere del inicio de la corrida")


def existe_tabla(conn, tabla):
    return bool(conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=:base "
        "AND TABLE_NAME=:tabla AND TABLE_TYPE='BASE TABLE'"
    ), {'base': SIM, 'tabla': tabla}).scalar_one())


def contrato_sesiones(conn):
    """HEAD no tiene sesiones. Si aparecen, exige un contrato inequívoco o aborta."""
    if not existe_tabla(conn, 'sesiones'):
        return None
    columnas = set(conn.execute(text(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=:base AND TABLE_NAME='sesiones'"
    ), {'base': SIM}).scalars())
    cuenta = next((n for n in ('username', 'cuenta_id', 'usuario_sistema_id') if n in columnas), None)
    fecha = next((n for n in ('fecha_hora', 'created_at', 'creada_en') if n in columnas), None)
    if 'id' not in columnas or cuenta is None or fecha is None:
        raise Abortado("Tabla sesiones desconocida: se requiere id, cuenta inequívoca y fecha; no se borra nada")
    return {'cuenta': cuenta, 'fecha': fecha}


def fila_asignacion_v1(conn, bloquear=False):
    fila = conn.execute(text(
        f"SELECT id, usuario_id, fecha, turno_id FROM `{DEMO}`.turnos_asignados "
        "WHERE id=:id" + (" FOR UPDATE" if bloquear else '')
    ), {'id': ASIGNACION}).mappings().one_or_none()
    if not fila or fila['usuario_id'] != USUARIO or fila['turno_id'] != 9001:
        raise Abortado("Asignación sintética ausente o incompatible")
    return fila


def filas_asignaciones_qa(conn, bloquear=False, turno_laboratorio=None):
    cargar_manifiesto_comensales()
    filas = conn.execute(text(
        f"SELECT id, usuario_id, fecha, turno_id FROM `{DEMO}`.turnos_asignados "
        "WHERE id IN (:id1, :id2, :id3) ORDER BY id" + (" FOR UPDATE" if bloquear else "")
    ), {
        "id1": COMENSALES_QA["qa01"]["asignacion_id"],
        "id2": COMENSALES_QA["qa02"]["asignacion_id"],
        "id3": COMENSALES_QA["qa03"]["asignacion_id"],
    }).mappings().all()
    if len(filas) != 3:
        raise Abortado(
            "Asignaciones sintéticas QA ausentes o incompletas; "
            "ejecutar primero preparar_comensales.py --aplicar"
        )
    por_id = {f["id"]: dict(f) for f in filas}
    fechas = set()
    por_codigo = {}
    turnos_permitidos = None
    if turno_laboratorio is not None:
        if (turno_laboratorio.get('id') != TURNO_LABORATORIO
                or turno_laboratorio.get('original') != 9001):
            raise Abortado('Definición del turno de laboratorio alterada')
        turnos_permitidos = {TURNO_LABORATORIO}
        if turno_laboratorio.get('preparando') is True:
            turnos_permitidos.add(9001)
    for codigo, spec in COMENSALES_QA.items():
        fila = por_id.get(spec["asignacion_id"])
        if (
            not fila
            or fila["usuario_id"] != spec["usuario_id"]
            or fila["turno_id"] not in (turnos_permitidos or {spec["turno_id"]})
        ):
            raise Abortado(f"Asignación sintética incompatible para {codigo}")
        fechas.add(fila["fecha"])
        por_codigo[codigo] = fila
    if len(fechas) != 1:
        raise Abortado("Las asignaciones de los tres comensales QA tienen fechas distintas")
    if len({f['turno_id'] for f in filas}) != 1:
        raise Abortado('Los tres comensales QA deben conservar el mismo turno')
    if not bloquear:
        padron = conn.execute(text(
            "SELECT usuario_id, nombre_completo, numero_item, carnet_identidad, "
            "categoria, tiene_ficha FROM v_comensales "
            "WHERE usuario_id IN (:u1, :u2, :u3) ORDER BY usuario_id"
        ), {
            "u1": COMENSALES_QA["qa01"]["usuario_id"],
            "u2": COMENSALES_QA["qa02"]["usuario_id"],
            "u3": COMENSALES_QA["qa03"]["usuario_id"],
        }).mappings().all()
        por_uid = {f["usuario_id"]: dict(f) for f in padron}
        for codigo, spec in COMENSALES_QA.items():
            ficha = por_uid.get(spec["usuario_id"])
            if (
                not ficha
                or ficha["nombre_completo"] != spec["nombre"]
                or ficha["numero_item"] != spec["legajo"]
                or ficha["carnet_identidad"] != spec["carnet_identidad"]
                or ficha["categoria"] not in {"Administrativo", PERFILES_QA[spec['usuario_id']]['categoria']}
                or not bool(ficha["tiene_ficha"])
            ):
                raise Abortado(
                    f"Comensal {codigo} ausente o incompatible en v_comensales; "
                    "ejecutar preparar_comensales.py --aplicar"
                )
    return {"fecha": next(iter(fechas)), "asignaciones": por_codigo}


def fila_asignacion(conn, bloquear=False):
    return filas_asignaciones_qa(conn, bloquear=bloquear)


_FILA_ASIGNACION_ORIGINAL = fila_asignacion


def filas_asignaciones_corrida(conn, datos, bloquear=False):
    if es_corrida_multi(datos) and datos.get('turno_laboratorio'):
        return filas_asignaciones_qa(conn, bloquear=bloquear, turno_laboratorio=datos['turno_laboratorio'])
    if es_corrida_multi(datos) or fila_asignacion is not _FILA_ASIGNACION_ORIGINAL:
        return fila_asignacion(conn, bloquear=bloquear)
    return fila_asignacion_v1(conn, bloquear=bloquear)


def restaurar_turno_laboratorio(conn, datos):
    if not datos.get('turno_laboratorio'):
        return
    filas = filas_asignaciones_qa(conn, bloquear=True, turno_laboratorio=datos['turno_laboratorio'])
    if all(f['turno_id'] == 9001 for f in filas['asignaciones'].values()):
        return
    for spec in COMENSALES_QA.values():
        resultado = conn.execute(text(
            f'UPDATE `{DEMO}`.turnos_asignados SET turno_id=:original '
            'WHERE id=:id AND usuario_id=:uid AND turno_id=:laboratorio'
        ), {'original': 9001, 'id': spec['asignacion_id'], 'uid': spec['usuario_id'],
            'laboratorio': TURNO_LABORATORIO})
        if resultado.rowcount != 1:
            raise Abortado('La asignación QA cambió al restaurar su turno')


def cambiar_fecha_v1(conn, anterior, nueva):
    resultado = conn.execute(text(
        f"UPDATE `{DEMO}`.turnos_asignados SET fecha=:nueva "
        "WHERE id=:id AND usuario_id=:uid AND fecha=:anterior"
    ), {'nueva': nueva, 'id': ASIGNACION, 'uid': USUARIO, 'anterior': anterior})
    if resultado.rowcount != 1:
        raise Abortado("La asignación cambió concurrentemente")


def cambiar_fechas_qa(conn, anterior, nueva):
    for spec in COMENSALES_QA.values():
        resultado = conn.execute(text(
            f"UPDATE `{DEMO}`.turnos_asignados SET fecha=:nueva "
            "WHERE id=:id AND usuario_id=:uid AND fecha=:anterior"
        ), {
            "nueva": nueva,
            "id": spec["asignacion_id"],
            "uid": spec["usuario_id"],
            "anterior": anterior,
        })
        if resultado.rowcount != 1:
            raise Abortado("La asignación cambió concurrentemente")


def cambiar_fecha(conn, anterior, nueva):
    cambiar_fechas_qa(conn, anterior, nueva)


_CAMBIAR_FECHA_ORIGINAL = cambiar_fecha


def cambiar_fecha_corrida(conn, datos, anterior, nueva):
    if es_corrida_multi(datos) or cambiar_fecha is not _CAMBIAR_FECHA_ORIGINAL:
        cambiar_fecha(conn, anterior, nueva)
    else:
        cambiar_fecha_v1(conn, anterior, nueva)


def heredar_parte_a_aprobada(conn, ruta_archivo, cuentas_actuales, servidor):
    ruta = Path(ruta_archivo)
    if not ruta.exists():
        raise Abortado(f"No existe el archivo de evidencia de Parte A: {ruta}")
    try:
        previa = json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:
        raise Abortado("El archivo de evidencia de Parte A no es un JSON válido") from None
    if (
        not isinstance(previa, dict)
        or previa.get("servidor") != servidor
        or previa.get("bases") != [SIM, DEMO]
        or previa.get("parte_a") != {"estado": "aprobada", "completa": True}
    ):
        raise Abortado("La evidencia indicada no contiene una Parte A aprobada de este escenario/servidor")
    verif = previa.get("verificacion_cuentas")
    if not isinstance(verif, dict) or set(verif) != set(CUENTAS):
        raise Abortado("La evidencia indicada no tiene las 4 cuentas verificadas")
    for nombre, rol_esperado in CUENTAS.items():
        resumen = verif.get(nombre)
        if (
            not isinstance(resumen, dict)
            or resumen.get("rol") != rol_esperado
            or resumen.get("temporal_verificada") is not True
            or resumen.get("cambio_frontend_completado") is not True
            or resumen.get("resultado") != "PASA"
            or not isinstance(resumen.get("controles"), list)
            or not resumen["controles"]
        ):
            raise Abortado(f"Evidencia de Parte A incompleta o no aprobada para {nombre}")
    if set(cuentas_actuales) != set(CUENTAS):
        raise Abortado("Las 4 cuentas deben existir en usuarios_sistema para conservar Parte A")
    cuentas_previas = previa.get("cuentas") or {}
    for nombre, id_previo in cuentas_previas.items():
        if cuentas_actuales.get(nombre) != id_previo:
            raise Abortado("El id de una cuenta en usuarios_sistema cambió respecto a la evidencia")
    estados_db = conn.execute(text(
        "SELECT username, debe_cambiar, activo FROM usuarios_sistema "
        "WHERE username IN ('cocinera1','cocinera2','cocinera3','jefa')"
    )).mappings().all()
    if len(estados_db) != 4 or any(
        bool(f["debe_cambiar"]) or not bool(f["activo"]) for f in estados_db
    ):
        raise Abortado(
            "Las cuentas en usuarios_sistema requieren cambio de clave o están inactivas; "
            "no se puede heredar Parte A sin claves definitivas vigentes"
        )
    return verif, {"estado": "aprobada", "completa": True}


def ejecutar(main):
    try:
        main()
    except Abortado as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
    except Exception as error:
        # DBAPI/ValidationError pueden incluir credenciales, SQL o parámetros.
        print(f"ABORTADO ({type(error).__name__}); no se muestran parámetros. Conservar corrida.json.", file=sys.stderr)
        raise SystemExit(1) from None


def argumento_reloj(valor):
    """Hora de pared local, sin zona: el mismo contrato que app.core.reloj."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", valor):
        raise argparse.ArgumentTypeError("Usar AAAA-MM-DDTHH:MM:SS, sin zona horaria")
    try:
        return datetime.fromisoformat(valor)
    except ValueError:
        raise argparse.ArgumentTypeError("Fecha u hora de laboratorio inválida") from None


def crear_ancla_reloj(lab):
    return {'lab': lab.isoformat(), 'real': datetime.now().isoformat()}


def desfase_reloj(datos):
    try:
        ancla = datos['reloj']
        lab = datetime.fromisoformat(ancla['lab'])
        real = datetime.fromisoformat(ancla['real'])
        if lab.tzinfo is not None or real.tzinfo is not None:
            raise ValueError
        return lab - real
    except (KeyError, TypeError, ValueError):
        raise Abortado("Ancla de laboratorio ausente o inválida; limpiar y abrir una corrida nueva") from None


def mostrar_reloj(lab, real):
    print(f"Reloj de laboratorio: {lab.isoformat()} (real: {real.isoformat()})")


def momento_laboratorio(datos, real=None):
    """Hora de negocio; el modo fijo permite al operador probar sin que venza la ventana."""
    desfase = desfase_reloj(datos)
    modo = datos['reloj'].get('modo', 'continuo')
    if modo not in ('continuo', 'fijo'):
        raise Abortado("Modo de reloj de laboratorio inválido")
    if modo == 'fijo':
        return datetime.fromisoformat(datos['reloj']['lab'])
    return (real if real is not None else datetime.now()) + desfase


@contextmanager
def reloj_laboratorio(datos, *, interactivo=False):
    """Usar dentro de app_sin_dotenv. Solo cambia ahora, durante este proceso.

    El desfase sale SIEMPRE del diario; arrancar otro proceso no reinicia la
    ventana. real/real_utc, tokens e inicio real de la corrida quedan intactos.
    """
    from app.core import reloj
    real = reloj.real()
    mostrar_reloj(momento_laboratorio(datos, real), real)

    def ahora_laboratorio():
        actual = leer_corrida_local() if interactivo else datos
        if interactivo and actual['inicio'] != datos['inicio']:
            raise Abortado("La corrida cambió con la API activa; reiniciar desde el laboratorio")
        return momento_laboratorio(actual, reloj.real())

    with patch.object(reloj, 'ahora', ahora_laboratorio):
        yield reloj


def fecha_para_operar(datos, momento, *, permitir_lectura=False, caso=None):
    """Valida el estado sin adelantarlo: habilitar cuentas/API no crea lectura."""
    estado = datos['estado']
    if es_corrida_multi(datos):
        validar_casos_diario(datos)
        casos = datos['casos']
        for info in casos.values():
            if info['estado'] == 'lectura_pendiente':
                raise Abortado("Corrida pendiente/anterior: no repetir lectura; limpiar primero")
            if (info['estado'] == 'pendiente') != (info['lectura_id'] is None):
                raise Abortado("Corrida pendiente/anterior: no repetir lectura; limpiar primero")
        alguna_lectura = any(info['lectura_id'] is not None for info in casos.values())
        permitidos = {'iniciada', 'refechada'}
        if permitir_lectura or caso is not None:
            permitidos |= {'lectura_creada', 'en_curso', 'casos_ejecutados'}
        if (
            estado not in permitidos
            or (estado in {'iniciada', 'refechada'} and alguna_lectura)
            or (estado in {'lectura_creada', 'en_curso', 'casos_ejecutados'} and not alguna_lectura)
        ):
            raise Abortado("Corrida pendiente/anterior: no repetir lectura; limpiar primero")
        if caso is not None:
            if caso == 'qa03':
                raise Abortado("El comensal qa03 está en reserva y no tiene caso ejecutable")
            if caso not in casos:
                raise Abortado(f"Caso desconocido: {caso}")
            if casos[caso]['estado'] != 'pendiente' or casos[caso]['lectura_id'] is not None:
                raise Abortado("Corrida pendiente/anterior: no repetir lectura; limpiar primero")
    else:
        if caso is not None:
            raise Abortado(
                "El diario actual es de versión 1 (un solo comensal); "
                "cerrar, limpiar y abrir corrida nueva para ejecutar casos múltiples"
            )
        permitidos = {'iniciada', 'refechada'}
        if permitir_lectura:
            permitidos.add('lectura_creada')
        if (estado not in permitidos
                or (estado != 'lectura_creada' and datos.get('lectura_id') is not None)
                or (estado == 'lectura_creada' and datos.get('lectura_id') is None)):
            raise Abortado("Corrida pendiente/anterior: no repetir lectura; limpiar primero")
    destino = datos.get('fecha_destino')
    if (estado == 'iniciada' and destino is not None) or (estado == 'refechada' and destino is None):
        raise Abortado("Estado/fecha destino incoherentes en corrida.json")
    fecha = date.fromisoformat(destino or datos['fecha_original'])
    if momento.date() != fecha:
        raise Abortado("Fecha del laboratorio distinta de la asignación: refechar si está iniciada; "
                       "si la corrida venció, limpiar y abrir una corrida nueva con otra ancla")
    return fecha


def main():
    parser = argparse.ArgumentParser(description="Huella protegida y registro inicial/final")
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument('--huella-base', action='store_true')
    grupo.add_argument('--huella-final', action='store_true')
    parser.add_argument('--reloj', type=argumento_reloj,
                        help=f"Ancla local de negocio para --huella-base (omisión: {RELOJ_POR_DEFECTO})")
    parser.add_argument(
        '--conservar-cuentas-de',
        metavar='ARCHIVO',
        help=(
            'Ruta al corrida.json archivado cuya Parte A aprobada se conserva '
            'en la nueva corrida sin resetear contraseñas definitivas'
        ),
    )
    args = parser.parse_args()
    if args.huella_final and (args.reloj is not None or args.conservar_cuentas_de is not None):
        parser.error('--reloj y --conservar-cuentas-de solo se usan con --huella-base')
    with bloqueo_corrida(), entorno_seguro() as (motor, huella, servidor):
        if args.huella_final:
            datos = leer_corrida(servidor)
            comprobar_base(datos, huella)
            if datos.get('estado') != 'limpia':
                raise Abortado("La corrida todavía no está limpia")
            print("Huella final idéntica a la base")
            return
        if CORRIDA.exists():
            raise Abortado("Ya existe corrida.json; conservar la evidencia y revisar GUION")
        herencia = None
        with motor.connect() as conn:
            fila = fila_asignacion(conn)
            cuentas = validar_cuentas_iniciales(conn.execute(text(
                "SELECT id, username, rol, usuario_turnos_id FROM usuarios_sistema "
                "WHERE username IN ('cocinera1','cocinera2','cocinera3','jefa')"
            )).mappings().all())
            if args.conservar_cuentas_de:
                herencia = heredar_parte_a_aprobada(
                    conn, args.conservar_cuentas_de, cuentas, servidor
                )
            if conn.execute(text("SELECT COUNT(*) FROM lecturas_biometricas WHERE dispositivo=:d"),
                            {'d': DISPOSITIVO}).scalar_one():
                raise Abortado("Hay lecturas QA anteriores; recuperar su corrida antes de continuar")
            max_intento = (
                normalizar_contador(
                    conn.execute(text("SELECT COALESCE(MAX(id),0) FROM intentos_login")).scalar_one(),
                    permitir_none=False,
                )
                if existe_tabla(conn, 'intentos_login')
                else None
            )
            sesiones = contrato_sesiones(conn)
            max_sesion = (
                normalizar_contador(
                    conn.execute(text("SELECT COALESCE(MAX(id),0) FROM sesiones")).scalar_one(),
                    permitir_none=False,
                )
                if sesiones
                else None
            )
        ancla = crear_ancla_reloj(args.reloj or argumento_reloj(RELOJ_POR_DEFECTO))
        mostrar_reloj(datetime.fromisoformat(ancla['lab']), datetime.fromisoformat(ancla['real']))
        documento = {
            'version': 2,
            'escenario': 'tres_comensales_qa',
            'servidor': servidor,
            'bases': [SIM, DEMO],
            'reloj': ancla,
            'inicio': datetime.now().replace(microsecond=0).isoformat(),
            'fecha_original': fila['fecha'].isoformat(),
            'fecha_destino': None,
            'cuentas': cuentas,
            'comensales': resumen_comensales_diario(),
            'casos': casos_iniciales_diario(),
            'max_intento_inicial': max_intento,
            'contrato_sesiones': sesiones,
            'max_sesion_inicial': max_sesion,
            'huella_base': huella,
            'estado': 'iniciada',
        }
        if herencia is not None:
            verif_cuentas, parte_a = herencia
            documento['verificacion_cuentas'] = verif_cuentas
            documento['parte_a'] = parte_a
            documento['parte_a_conservada_de'] = Path(args.conservar_cuentas_de).name
        guardar_corrida(documento)
        if herencia is not None:
            print(
                f"corrida.json creada con tres comensales QA y Parte A aprobada "
                f"conservada desde {Path(args.conservar_cuentas_de).name}"
            )
        else:
            print("corrida.json creada antes de habilitar cuentas")


if __name__ == '__main__':
    ejecutar(main)
