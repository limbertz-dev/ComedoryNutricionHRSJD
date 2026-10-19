"""Parte A: preparación automática con claves temporales y verificación posterior de identidad y permisos.

Secuencia:
1. `cuentas.py --preparar` (o `ejecutar_app.py preparar`): crea/resetea las 4 cuentas con sus roles
   fijos mediante la semilla original, muestra cada clave temporal una sola vez en consola y la
   conserva solo en memoria, levanta la API QA mediante `ejecutar_app.py api`, comprueba
   automáticamente que el primer login de cada cuenta responde `428 cambio_password_pendiente`,
   guarda ese avance en `corrida.json` dejando la Parte A pendiente (`completa=false`) y mantiene
   disponible la API para que el operador cambie cada clave desde el frontend.
2. El operador ingresa al frontend con cada cuenta y cambia la clave temporal por su contraseña
   definitiva.
3. `cuentas.py` (opcionalmente `--solo <cuenta>`): solicita con `getpass` únicamente la contraseña
   definitiva elegida en el frontend y verifica login definitivo (`200 debe_cambiar=false`),
   `/auth/yo` y los permisos de cada rol.
"""

import argparse
import getpass
import json
import os
import socket
import subprocess
import sys
import time
from urllib import error, parse, request

import comun as c
import ejecutar_app

PUERTO_POR_DEFECTO = 8001
BASE_POR_DEFECTO = f"http://127.0.0.1:{PUERTO_POR_DEFECTO}"
REVISION_ESPERADA = "e1a7c3b9d5f2"
MOTIVOS_CONOCIDOS = frozenset({
    "cambio_password_pendiente",
    "credenciales_invalidas",
    "cuenta_bloqueada",
    "falta_token",
    "token_invalido",
    "token_expirado",
    "password_actual_requerida",
    "password_actual_incorrecta",
    "password_rechazada",
    "rol_no_autorizado",
    "metodo_no_autorizado",
    "biometrico_solo_lector",
    "clave_idempotencia_invalida",
})
ROLES_CONOCIDOS = frozenset({"cocinera", "jefa", "sistemas"})


def resolver_base_y_puerto(base=BASE_POR_DEFECTO, port=None):
    raiz = (base or BASE_POR_DEFECTO).rstrip("/")
    partes = parse.urlsplit(raiz)
    if partes.scheme not in {"http", "https"} or not partes.hostname:
        raise c.Abortado("URL base inválida para la API QA")
    puerto = port if port is not None else (partes.port or PUERTO_POR_DEFECTO)
    if type(puerto) is not int or not (1 <= puerto <= 65535):
        raise c.Abortado("Puerto inválido para la API QA")
    if port is not None:
        raiz = f"{partes.scheme}://{partes.hostname}:{puerto}"
    return raiz, puerto


def _puerto_ocupado(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


def verificar_sin_api_activa(port=PUERTO_POR_DEFECTO):
    if (c.CARPETA / "api.activa").exists() or _puerto_ocupado("127.0.0.1", port):
        raise c.Abortado(
            "Hay una API QA anterior activa; detenerla con Ctrl+C en su consola "
            "antes de ejecutar la preparación"
        )


def lanzar_api_qa(port=PUERTO_POR_DEFECTO):
    return subprocess.Popen(
        [sys.executable, "-B", str(c.CARPETA / "ejecutar_app.py"), "api", "--port", str(port)],
        cwd=str(c.RAIZ),
    )


def esperar_api_lista(proceso, solicitar, timeout=15.0, intervalo=0.1):
    limite = time.monotonic() + timeout
    ultimo_error = None
    while time.monotonic() < limite:
        if proceso.poll() is not None:
            raise c.Abortado("El proceso de la API QA terminó antes de quedar disponible")
        try:
            verificar_salud(solicitar)
            return
        except c.Abortado as exc:
            if "/salud" in str(exc):
                raise
            ultimo_error = exc
            time.sleep(intervalo)
    raise c.Abortado(
        "Tiempo agotado esperando a que la API QA responda en /salud"
    ) from ultimo_error


def detener_proceso_api(proceso, timeout=5.0, esperar_cierre=False):
    if proceso is None:
        return False
    marca = c.CARPETA / "api.activa"
    forzado = False
    error_detencion = None

    if esperar_cierre and proceso.poll() is None:
        try:
            proceso.wait(timeout=timeout)
        except Exception as exc:
            error_detencion = exc
            forzado = True

    if proceso.poll() is None:
        error_detencion = None
        try:
            proceso.terminate()
            proceso.wait(timeout=timeout)
        except Exception as exc:
            error_detencion = exc
            forzado = True

    if error_detencion is not None or proceso.poll() is None:
        forzado = True
        error_detencion = None
        try:
            proceso.kill()
            proceso.wait(timeout=timeout)
        except Exception as exc:
            error_detencion = exc

    estado_final = proceso.poll()
    if error_detencion is not None or estado_final is None:
        raise c.Abortado(
            "No se pudo detener el proceso de la API QA; se conserva api.activa"
        ) from error_detencion

    if marca.exists():
        try:
            marca.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise c.Abortado(
                "El proceso de la API QA terminó, pero no se pudo retirar api.activa"
            ) from exc

    if forzado or estado_final != 0:
        raise c.Abortado(
            "La API QA requirió detención forzada o cerró con error; "
            "no se confirmó la huella final"
        )
    return True


def mantener_api_activa(proceso, timeout_cierre=10.0):
    try:
        codigo = proceso.wait()
    except KeyboardInterrupt:
        detener_proceso_api(proceso, timeout=timeout_cierre, esperar_cierre=True)
        return
    if codigo is None:
        codigo = proceso.poll()
    if codigo != 0:
        detener_proceso_api(proceso)
        raise c.Abortado(
            f"La API QA finalizó con código {codigo}; no se confirmó la huella final"
        )
    if (c.CARPETA / "api.activa").exists() and proceso.poll() is not None:
        detener_proceso_api(proceso)


def cliente_http(base, timeout=10):
    raiz = base.rstrip("/")

    def solicitar(metodo, ruta, cuerpo=None, token=None):
        cabeceras = {"Accept": "application/json"}
        datos = None
        if cuerpo is not None:
            cabeceras["Content-Type"] = "application/json"
            datos = json.dumps(cuerpo).encode("utf-8")
        if token:
            cabeceras["Authorization"] = f"Bearer {token}"
        req = request.Request(f"{raiz}{ruta}", data=datos, headers=cabeceras, method=metodo)
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                texto = resp.read().decode("utf-8", errors="replace")
                return resp.status, (json.loads(texto) if texto else {})
        except error.HTTPError as fallo:
            texto = fallo.read().decode("utf-8", errors="replace")
            try:
                carga = json.loads(texto) if texto else {}
            except ValueError:
                carga = {}
            return fallo.code, carga
        except error.URLError as fallo:
            raise c.Abortado(f"No se pudo conectar con la API QA en {raiz}") from fallo

    return solicitar


def verificar_salud(solicitar):
    codigo, datos = solicitar("GET", "/salud")
    if (
        codigo != 200
        or not isinstance(datos, dict)
        or datos.get("estado") != "ok"
        or datos.get("entorno") != "desarrollo"
        or datos.get("base_datos") != c.SIM
        or datos.get("base_turnos") != c.DEMO
        or datos.get("revision_alembic") != REVISION_ESPERADA
    ):
        raise c.Abortado("La API no declara el escenario esperado en /salud")


def pedir_clave_definitiva(cuenta, lector=None):
    lector = getpass.getpass if lector is None else lector
    definitiva = lector(f"[{cuenta}] Clave definitiva: ")
    if not definitiva:
        raise c.Abortado(f"Se requiere la clave definitiva para {cuenta}")
    return definitiva


def _motivo_seguro(cuerpo):
    if not isinstance(cuerpo, dict):
        return None
    motivo = cuerpo.get("motivo")
    if isinstance(motivo, str) and motivo in MOTIVOS_CONOCIDOS:
        return motivo
    return None


def _resumen_obtenido(codigo, cuerpo, extra=None):
    if codigo is None:
        return "sin ejecutar (falta paso previo)"
    partes = [str(codigo)]
    if extra:
        partes.append(extra)
    else:
        motivo = _motivo_seguro(cuerpo)
        if motivo:
            partes.append(motivo)
    return " ".join(partes)


def _fila_control(control, esperado, codigo, cuerpo, pasa, extra=None):
    return {
        "control": control,
        "esperado": esperado,
        "codigo": codigo,
        "obtenido": _resumen_obtenido(codigo, cuerpo, extra),
        "resultado": "PASA" if pasa else "FALLA",
    }


def evaluar_login_temporal(cuenta, clave_temporal, solicitar):
    rol = c.rol_cuenta(cuenta)
    cod_temp, cuerpo_temp = solicitar(
        "POST", "/auth/login", {"username": cuenta, "password": clave_temporal}
    )
    token_temp = cuerpo_temp.get("temporal") if isinstance(cuerpo_temp, dict) else None
    pasa_temp = (
        cod_temp == 428
        and isinstance(cuerpo_temp, dict)
        and cuerpo_temp.get("motivo") == "cambio_password_pendiente"
        and isinstance(token_temp, str)
        and bool(token_temp)
    )
    fila = _fila_control(
        "POST /auth/login (temporal)",
        "428 cambio_password_pendiente",
        cod_temp,
        cuerpo_temp,
        pasa_temp,
    )
    return {
        "rol": rol,
        "temporal_verificada": pasa_temp,
        "cambio_frontend_completado": False,
        "resultado": "PENDIENTE" if pasa_temp else "FALLA",
        "controles": [fila],
    }


def verificar_logins_temporales(temporales, solicitar):
    verificar_salud(solicitar)
    resultados = {}
    for cuenta in c.CUENTAS:
        clave_temp = temporales.get(cuenta)
        if not isinstance(clave_temp, str) or not clave_temp:
            raise c.Abortado(f"Falta clave temporal en memoria para {cuenta}")
        resultados[cuenta] = evaluar_login_temporal(cuenta, clave_temp, solicitar)
    return resultados


def _control_temporal_previo(previos, cuenta):
    info = (previos or {}).get(cuenta)
    if not isinstance(info, dict) or info.get("temporal_verificada") is not True:
        raise c.Abortado(
            f"Falta la comprobación automática de clave temporal para {cuenta}; "
            "ejecutar primero `cuentas.py --preparar` y cambiar la clave en el frontend"
        )
    for fila in info.get("controles") or ():
        if (
            isinstance(fila, dict)
            and fila.get("control") == "POST /auth/login (temporal)"
            and fila.get("resultado") == "PASA"
        ):
            return dict(fila)
    raise c.Abortado(
        f"Registro de clave temporal incompleto para {cuenta}; "
        "ejecutar primero `cuentas.py --preparar`"
    )


def evaluar_cuenta(cuenta, clave_definitiva, solicitar, control_temporal=None):
    rol = c.rol_cuenta(cuenta)
    controles = []
    if control_temporal is not None:
        controles.append(dict(control_temporal))

    # No se cambia la clave desde Python: debe haberse cambiado previamente en el frontend.
    cod_login, cuerpo_login = solicitar(
        "POST", "/auth/login", {"username": cuenta, "password": clave_definitiva}
    )
    access_login = cuerpo_login.get("access") if isinstance(cuerpo_login, dict) else None
    debe_cambiar_login = (
        cuerpo_login.get("debe_cambiar") if isinstance(cuerpo_login, dict) else None
    )
    pasa_login = (
        cod_login == 200
        and isinstance(cuerpo_login, dict)
        and debe_cambiar_login is False
        and cuerpo_login.get("rol") == rol
        and isinstance(access_login, str)
        and bool(access_login)
    )
    controles.append(
        _fila_control(
            "POST /auth/login (definitiva)",
            "200 debe_cambiar=false",
            cod_login,
            cuerpo_login,
            pasa_login,
            extra=(
                f"debe_cambiar={'true' if debe_cambiar_login else 'false'}"
                if isinstance(debe_cambiar_login, bool)
                else None
            ),
        )
    )

    token_acceso = access_login if pasa_login else None

    if token_acceso:
        cod_yo, cuerpo_yo = solicitar("GET", "/auth/yo", token=token_acceso)
    else:
        cod_yo, cuerpo_yo = None, {}
    id_yo = cuerpo_yo.get("id") if isinstance(cuerpo_yo, dict) else None
    user_yo = cuerpo_yo.get("username") if isinstance(cuerpo_yo, dict) else None
    rol_yo = cuerpo_yo.get("rol") if isinstance(cuerpo_yo, dict) else None
    cambio_yo = cuerpo_yo.get("debe_cambiar") if isinstance(cuerpo_yo, dict) else None
    pasa_yo = (
        cod_yo == 200
        and isinstance(cuerpo_yo, dict)
        and type(id_yo) is int
        and id_yo > 0
        and user_yo == cuenta
        and rol_yo == rol
        and cambio_yo is False
    )
    partes_yo = []
    if user_yo in c.CUENTAS:
        partes_yo.append(user_yo)
    if rol_yo in ROLES_CONOCIDOS:
        partes_yo.append(f"rol={rol_yo}")
    if isinstance(cambio_yo, bool):
        partes_yo.append(f"debe_cambiar={'true' if cambio_yo else 'false'}")
    controles.append(
        _fila_control(
            "GET /auth/yo",
            f"200 {cuenta} rol={rol} debe_cambiar=false",
            cod_yo,
            cuerpo_yo,
            pasa_yo,
            extra=" ".join(partes_yo) if partes_yo else None,
        )
    )

    if rol == "cocinera":
        if token_acceso:
            cod_est, cuerpo_est = solicitar("GET", "/pantalla/estado", token=token_acceso)
        else:
            cod_est, cuerpo_est = None, {}
        controles.append(
            _fila_control(
                "GET /pantalla/estado",
                "200",
                cod_est,
                cuerpo_est,
                cod_est == 200 and isinstance(cuerpo_est, dict),
            )
        )

        if token_acceso:
            cod_man, cuerpo_man = solicitar(
                "POST",
                "/asistencias",
                {"usuario_id": c.USUARIO, "metodo": "manual"},
                token=token_acceso,
            )
        else:
            cod_man, cuerpo_man = None, {}
        pasa_man = (
            cod_man == 403
            and isinstance(cuerpo_man, dict)
            and cuerpo_man.get("motivo") == "metodo_no_autorizado"
        )
        controles.append(
            _fila_control(
                "POST /asistencias (manual)",
                "403 metodo_no_autorizado",
                cod_man,
                cuerpo_man,
                pasa_man,
            )
        )

        if token_acceso:
            cod_int, cuerpo_int = solicitar("GET", "/intervenciones-cocina", token=token_acceso)
        else:
            cod_int, cuerpo_int = None, {}
        controles.append(
            _fila_control(
                "GET /intervenciones-cocina",
                "403",
                cod_int,
                cuerpo_int,
                cod_int == 403,
            )
        )

        if token_acceso:
            cod_adm, cuerpo_adm = solicitar("GET", "/admin/cuentas", token=token_acceso)
        else:
            cod_adm, cuerpo_adm = None, {}
        controles.append(
            _fila_control(
                "GET /admin/cuentas",
                "403",
                cod_adm,
                cuerpo_adm,
                cod_adm == 403,
            )
        )
    else:
        if token_acceso:
            cod_int, cuerpo_int = solicitar("GET", "/intervenciones-cocina", token=token_acceso)
        else:
            cod_int, cuerpo_int = None, {}
        controles.append(
            _fila_control(
                "GET /intervenciones-cocina",
                "200",
                cod_int,
                cuerpo_int,
                cod_int == 200 and isinstance(cuerpo_int, dict),
            )
        )

        if token_acceso:
            cod_id, cuerpo_id = solicitar(
                "POST",
                "/asistencias/lecturas/1/identificar",
                {"usuario_id": c.USUARIO},
                token=token_acceso,
            )
        else:
            cod_id, cuerpo_id = None, {}
        pasa_id = (
            cod_id == 403
            and isinstance(cuerpo_id, dict)
            and cuerpo_id.get("motivo") == "rol_no_autorizado"
        )
        controles.append(
            _fila_control(
                "POST /asistencias/lecturas/1/identificar",
                "403 rol_no_autorizado",
                cod_id,
                cuerpo_id,
                pasa_id,
            )
        )

    todos_pasan = all(item["resultado"] == "PASA" for item in controles)
    return {
        "rol": rol,
        "temporal_verificada": True,
        "cambio_frontend_completado": todos_pasan,
        "resultado": "PASA" if todos_pasan else "FALLA",
        "controles": controles,
    }


def estado_inicial_preparacion_cuentas():
    return {
        cuenta: {
            "rol": c.rol_cuenta(cuenta),
            "temporal_verificada": False,
            "cambio_frontend_completado": False,
            "resultado": "PENDIENTE",
            "controles": [],
        }
        for cuenta in c.CUENTAS
    }


def estado_parte_a(verificacion_cuentas):
    if not isinstance(verificacion_cuentas, dict):
        return {"estado": "preparacion_pendiente", "completa": False}
    resumenes = [verificacion_cuentas.get(cuenta) for cuenta in c.CUENTAS]
    if any(isinstance(r, dict) and r.get("resultado") == "FALLA" for r in resumenes):
        return {"estado": "falla", "completa": False}
    if all(
        isinstance(r, dict)
        and r.get("temporal_verificada") is True
        and r.get("cambio_frontend_completado") is True
        and r.get("resultado") == "PASA"
        for r in resumenes
    ):
        return {"estado": "aprobada", "completa": True}
    if all(isinstance(r, dict) and r.get("temporal_verificada") is True for r in resumenes):
        return {"estado": "pendiente_cambio_frontend", "completa": False}
    return {"estado": "preparacion_pendiente", "completa": False}


def formatear_tabla(resultados):
    lineas = [
        "| Cuenta | Control | Esperado | Obtenido | PASA/FALLA |",
        "|---|---|---|---|---|",
    ]
    for cuenta, resumen in resultados.items():
        for fila in resumen["controles"]:
            lineas.append(
                f"| {cuenta} | {fila['control']} | {fila['esperado']} "
                f"| {fila['obtenido']} | {fila['resultado']} |"
            )
    return "\n".join(lineas)


def ejecutar_preparacion(base=BASE_POR_DEFECTO, port=None):
    if os.environ.get("ENTORNO") != "desarrollo":
        raise c.Abortado("ENTORNO")
    url_base, puerto = resolver_base_y_puerto(base=base, port=port)
    verificar_sin_api_activa(puerto)
    temporales = {}
    proceso = None
    try:
        with c.bloqueo_corrida(), c.entorno_seguro(
            ejecutar_app.permisos_modo("admin")
        ) as (motor, huella, servidor):
            datos = c.leer_corrida(servidor)
            c.comprobar_base(datos, huella)
            if datos.get("estado") not in {"iniciada", "refechada", "lectura_creada"}:
                raise c.Abortado("La corrida no está en un estado operativo para preparar cuentas")
            with c.app_sin_dotenv(), c.reloj_laboratorio(datos) as reloj:
                c.fecha_para_operar(datos, reloj.ahora(), permitir_lectura=True)
                inicial_cuentas = estado_inicial_preparacion_cuentas()
                datos["verificacion_cuentas"] = inicial_cuentas
                datos["parte_a"] = estado_parte_a(inicial_cuentas)
                c.guardar_corrida(datos)
                temporales = ejecutar_app.sembrar_cuentas_qa(motor, tuple(c.CUENTAS))

        verificar_sin_api_activa(puerto)
        proceso = lanzar_api_qa(puerto)
        try:
            solicitar = cliente_http(url_base)
            esperar_api_lista(proceso, solicitar)
            resultados = verificar_logins_temporales(temporales, solicitar)
            temporales.clear()

            with c.bloqueo_corrida():
                datos = c.leer_corrida_local()
                datos["verificacion_cuentas"] = resultados
                datos["parte_a"] = estado_parte_a(resultados)
                c.guardar_corrida(datos)

            print(formatear_tabla(resultados))
            if any(not r.get("temporal_verificada") for r in resultados.values()):
                raise c.Abortado("Uno o más controles de clave temporal fallaron")
            print(
                "Claves temporales verificadas (428 cambio_password_pendiente). "
                "Parte A PENDIENTE: ingresar al frontend, cambiar la clave de cada cuenta "
                "a su contraseña definitiva y luego ejecutar `cuentas.py` para verificar "
                "identidad y permisos."
            )
            print(f"API QA disponible en {url_base} (presionar Ctrl+C para detenerla al finalizar).")
        except BaseException as exc:
            try:
                detener_proceso_api(proceso)
            except c.Abortado as error_cierre:
                if isinstance(exc, c.Abortado) and str(error_cierre) not in str(exc):
                    raise c.Abortado(f"{exc}. Además: {error_cierre}") from exc
                raise
            raise
        mantener_api_activa(proceso)
    finally:
        temporales.clear()


def ejecutar_verificacion(cuentas_objetivo, solicitar, previos, lector=None):
    verificar_salud(solicitar)
    controles_temporales = {
        cuenta: _control_temporal_previo(previos, cuenta) for cuenta in cuentas_objetivo
    }
    resultados = {}
    for cuenta in cuentas_objetivo:
        definitiva = pedir_clave_definitiva(cuenta, lector=lector)
        resultados[cuenta] = evaluar_cuenta(
            cuenta,
            definitiva,
            solicitar,
            control_temporal=controles_temporales[cuenta],
        )
    return resultados


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preparar",
        action="store_true",
        help=(
            "Crear/resetear las 4 cuentas, generar y mostrar sus claves temporales una vez, "
            "levantar la API QA, comprobar 428 y mantener la API activa para el cambio en frontend"
        ),
    )
    parser.add_argument(
        "--base",
        default=BASE_POR_DEFECTO,
        help=f"URL base de la API QA (omisión: {BASE_POR_DEFECTO})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"Puerto de la API QA para --preparar (omisión: {PUERTO_POR_DEFECTO})",
    )
    parser.add_argument(
        "--solo",
        choices=c.CUENTAS,
        help="Verificar únicamente una cuenta tras haber cambiado su clave en el frontend",
    )
    args = parser.parse_args(argv)
    if args.preparar:
        if args.solo:
            parser.error("--solo no se usa con --preparar")
        ejecutar_preparacion(base=args.base, port=args.port)
        return

    url_base, _ = resolver_base_y_puerto(base=args.base, port=args.port)
    cuentas_objetivo = [args.solo] if args.solo else list(c.CUENTAS)
    solicitar = cliente_http(url_base)

    with c.bloqueo_corrida():
        datos = c.leer_corrida_local()
        previos = dict(datos.get("verificacion_cuentas") or {})
        resultados = ejecutar_verificacion(cuentas_objetivo, solicitar, previos)
        print(formatear_tabla(resultados))
        previos.update(resultados)
        datos["verificacion_cuentas"] = previos
        datos["parte_a"] = estado_parte_a(previos)
        c.guardar_corrida(datos)

    if any(r["resultado"] != "PASA" for r in resultados.values()):
        raise c.Abortado("Uno o más controles de cuentas fallaron")


if __name__ == "__main__":
    c.ejecutar(main)
