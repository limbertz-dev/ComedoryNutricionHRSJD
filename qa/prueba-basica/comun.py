"""Infraestructura QA; importar este módulo no conecta ni carga configuración de app."""

import argparse
import hashlib
import json
import os
import re
import sys
from contextlib import contextmanager
from datetime import date, datetime
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
DISPOSITIVO = "lector-prueba-qa"
CUENTAS = ("cocinera2", "cocinera3")
CORRIDA = CARPETA / "corrida.json"
REQUERIDAS = ("DB_NAME", "DB_NAME_TURNOS", "DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD")


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
            if re.search(r"\b(INSERT|UPDATE|DELETE|REPLACE|CALL|INTO)\b", sin_bloqueo, re.I):
                raise Abortado("Auditor: SELECT no permitido")
        return
    if re.fullmatch(r"SHOW (?:VARIABLES LIKE '[a-z_]+'|COLLATION|FULL TABLES FROM " + IDENT + r")", sql, re.I):
        return
    if re.fullmatch(rf"CHECKSUM TABLE `{PROTEGIDA}`\.`[A-Za-z0-9_]+` EXTENDED", sql, re.I):
        return
    if re.fullmatch(r"(?:SAVEPOINT|RELEASE SAVEPOINT|ROLLBACK TO SAVEPOINT) sa_savepoint_\d+", sql, re.I):
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


def preflight(conexion):
    """Solo SELECT en conexión AUTOCOMMIT: antes de cualquier transacción DB."""
    validar_marcador(conexion.execute(text(
        f"SELECT clave, version, base_sim FROM `{DEMO}`.escenario_sintetico WHERE clave=:clave"
    ), {"clave": MARCADOR}).mappings().one_or_none())
    revision = conexion.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    if revision != "e1a7c3b9d5f2":
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
def entorno_seguro(permitidas=()):
    url = validar_entorno()  # Antes de crear motores o importar app.
    autorizadas = set()
    quitar = instalar_auditor(autorizadas)
    control = create_engine(url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    motor = None
    inicial = None
    try:
        with control.connect() as conn:
            servidor = preflight(conn)
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


def guardar_corrida(datos):
    temporal = CORRIDA.with_suffix('.json.tmp')
    with temporal.open('w', encoding='utf-8') as archivo:
        json.dump(datos, archivo, ensure_ascii=False, indent=2)
        archivo.write('\n')
        archivo.flush()
        os.fsync(archivo.fileno())
    os.replace(temporal, CORRIDA)


def leer_corrida(servidor):
    if not CORRIDA.exists():
        raise Abortado("Falta corrida.json; ejecutar primero comun.py --huella-base")
    datos = json.loads(CORRIDA.read_text(encoding='utf-8'))
    if (datos.get('version') != 1 or datos.get('servidor') != servidor
            or datos.get('bases') != [SIM, DEMO] or datos.get('usuario_id') != USUARIO
            or datos.get('asignacion_id') != ASIGNACION):
        raise Abortado("corrida.json no corresponde a este escenario/servidor")
    datetime.fromisoformat(datos['inicio'])
    for campo in ('fecha_original', 'fecha_destino'):
        if datos.get(campo):
            date.fromisoformat(datos[campo])
    if datos.get('lectura_id') is not None and (type(datos['lectura_id']) is not int or datos['lectura_id'] <= 0):
        raise Abortado("lectura_id inválido en corrida.json")
    return datos


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


def fila_asignacion(conn, bloquear=False):
    fila = conn.execute(text(
        f"SELECT id, usuario_id, fecha, turno_id FROM `{DEMO}`.turnos_asignados "
        "WHERE id=:id" + (" FOR UPDATE" if bloquear else '')
    ), {'id': ASIGNACION}).mappings().one_or_none()
    if not fila or fila['usuario_id'] != USUARIO or fila['turno_id'] != 9001:
        raise Abortado("Asignación sintética ausente o incompatible")
    return fila


def cambiar_fecha(conn, anterior, nueva):
    resultado = conn.execute(text(
        f"UPDATE `{DEMO}`.turnos_asignados SET fecha=:nueva "
        "WHERE id=:id AND usuario_id=:uid AND fecha=:anterior"
    ), {'nueva': nueva, 'id': ASIGNACION, 'uid': USUARIO, 'anterior': anterior})
    if resultado.rowcount != 1:
        raise Abortado("La asignación cambió concurrentemente")


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


def main():
    parser = argparse.ArgumentParser(description="Huella protegida y registro inicial/final")
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument('--huella-base', action='store_true')
    grupo.add_argument('--huella-final', action='store_true')
    args = parser.parse_args()
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
        with motor.connect() as conn:
            fila = fila_asignacion(conn)
            cuentas = conn.execute(text(
                "SELECT id, username, rol, usuario_turnos_id FROM usuarios_sistema "
                "WHERE username IN ('cocinera2','cocinera3')"
            )).mappings().all()
            if len(cuentas) != 2 or any(c['rol'] != 'cocinera' or c['usuario_turnos_id'] is not None for c in cuentas):
                raise Abortado("Se requieren las dos cocineras sintéticas existentes y sin vínculo")
            if conn.execute(text("SELECT COUNT(*) FROM lecturas_biometricas WHERE dispositivo=:d"),
                            {'d': DISPOSITIVO}).scalar_one():
                raise Abortado("Hay lecturas QA anteriores; recuperar su corrida antes de continuar")
            max_intento = (conn.execute(text("SELECT COALESCE(MAX(id),0) FROM intentos_login")).scalar_one()
                           if existe_tabla(conn, 'intentos_login') else None)
            sesiones = contrato_sesiones(conn)
            max_sesion = (conn.execute(text("SELECT COALESCE(MAX(id),0) FROM sesiones")).scalar_one()
                          if sesiones else None)
        guardar_corrida({'version': 1, 'servidor': servidor, 'bases': [SIM, DEMO],
                         'usuario_id': USUARIO, 'asignacion_id': ASIGNACION,
                         'inicio': datetime.now().replace(microsecond=0).isoformat(),
                         'fecha_original': fila['fecha'].isoformat(), 'fecha_destino': None,
                         'cuentas': {c['username']: c['id'] for c in cuentas},
                         'max_intento_inicial': max_intento,
                         'contrato_sesiones': sesiones, 'max_sesion_inicial': max_sesion,
                         'huella_base': huella, 'estado': 'iniciada', 'lectura_id': None})
        print("corrida.json creada antes de habilitar cuentas")


if __name__ == '__main__':
    ejecutar(main)
