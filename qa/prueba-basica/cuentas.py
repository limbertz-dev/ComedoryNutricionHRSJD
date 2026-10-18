"""Parte A: pruebas de integración de las 4 cuentas y sus permisos contra la API QA.

Repetir el ciclo de clave temporal de una cuenta cuya clave ya fue cambiada exige
resetearla previamente con `ejecutar_app.py admin --username <cuenta>`.
"""

import argparse
import getpass
import json
from urllib import error, request

import comun as c

BASE_POR_DEFECTO = "http://127.0.0.1:8001"
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


def pedir_claves(cuenta, lector=None):
    lector = getpass.getpass if lector is None else lector
    temporal = lector(f"[{cuenta}] Clave temporal: ")
    nueva = lector(f"[{cuenta}] Clave nueva: ")
    if not temporal or not nueva:
        raise c.Abortado(f"Se requieren clave temporal y clave nueva para {cuenta}")
    return temporal, nueva


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


def evaluar_cuenta(cuenta, clave_temporal, clave_nueva, solicitar):
    rol = c.rol_cuenta(cuenta)
    controles = []

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
    controles.append(
        _fila_control(
            "POST /auth/login (temporal)",
            "428 cambio_password_pendiente",
            cod_temp,
            cuerpo_temp,
            pasa_temp,
        )
    )

    if pasa_temp:
        cod_cambio, cuerpo_cambio = solicitar(
            "POST",
            "/auth/cambio-password",
            {"password_nueva": clave_nueva},
            token=token_temp,
        )
    else:
        cod_cambio, cuerpo_cambio = None, {}
    access_cambio = cuerpo_cambio.get("access") if isinstance(cuerpo_cambio, dict) else None
    debe_cambiar_cambio = (
        cuerpo_cambio.get("debe_cambiar") if isinstance(cuerpo_cambio, dict) else None
    )
    pasa_cambio = (
        cod_cambio == 200
        and isinstance(cuerpo_cambio, dict)
        and debe_cambiar_cambio is False
        and cuerpo_cambio.get("rol") == rol
        and isinstance(access_cambio, str)
        and bool(access_cambio)
    )
    controles.append(
        _fila_control(
            "POST /auth/cambio-password",
            "200 debe_cambiar=false",
            cod_cambio,
            cuerpo_cambio,
            pasa_cambio,
            extra=(
                f"debe_cambiar={'true' if debe_cambiar_cambio else 'false'}"
                if isinstance(debe_cambiar_cambio, bool)
                else None
            ),
        )
    )

    # No reintentar login con la clave nueva si el ciclo temporal/cambio no pasó.
    if pasa_cambio:
        cod_login, cuerpo_login = solicitar(
            "POST", "/auth/login", {"username": cuenta, "password": clave_nueva}
        )
    else:
        cod_login, cuerpo_login = None, {}
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
            "POST /auth/login (nueva)",
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
        "resultado": "PASA" if todos_pasan else "FALLA",
        "controles": controles,
    }


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


def ejecutar_verificacion(cuentas_objetivo, solicitar, lector=None):
    verificar_salud(solicitar)
    resultados = {}
    for cuenta in cuentas_objetivo:
        temporal, nueva = pedir_claves(cuenta, lector=lector)
        resultados[cuenta] = evaluar_cuenta(cuenta, temporal, nueva, solicitar)
    return resultados


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default=BASE_POR_DEFECTO,
        help=f"URL base de la API QA (omisión: {BASE_POR_DEFECTO})",
    )
    parser.add_argument(
        "--solo",
        choices=c.CUENTAS,
        help="Verificar únicamente una cuenta (requiere resetearla antes si ya cambió clave)",
    )
    args = parser.parse_args(argv)
    cuentas_objetivo = [args.solo] if args.solo else list(c.CUENTAS)
    solicitar = cliente_http(args.base)

    with c.bloqueo_corrida():
        datos = c.leer_corrida_local()
        resultados = ejecutar_verificacion(cuentas_objetivo, solicitar)
        print(formatear_tabla(resultados))
        previos = dict(datos.get("verificacion_cuentas") or {})
        previos.update(resultados)
        datos["verificacion_cuentas"] = previos
        c.guardar_corrida(datos)

    if any(r["resultado"] != "PASA" for r in resultados.values()):
        raise c.Abortado("Uno o más controles de cuentas fallaron")


if __name__ == "__main__":
    c.ejecutar(main)
