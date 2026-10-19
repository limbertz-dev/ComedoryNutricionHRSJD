"""Comprobaciones de los casos del escenario de tres comensales QA.

Verifica en modo de solo lectura (sin DML permitido por el auditor):
1. Caso Normal (`qa01` — `900101`):
   - Exactamente 1 lectura biométrica reconocida (`usuario_id=900101`, `resultado='aceptada'`, `motivo=None`).
   - Exactamente 1 asistencia biométrica (`usuario_id=900101`, `metodo='biometrico'`, `lectura_id`, `registrado_por_cuenta=None`).
   - 0 intervenciones de cocina en `intervenciones_lectura`.
2. Caso Identificación (`qa02` — `900102`):
   - Exactamente 1 lectura biométrica originalmente rechazada que conserva `usuario_id=None`, `resultado='rechazada'`, `motivo='no_identificado'`.
   - Exactamente 1 asistencia vinculada a esa lectura (`usuario_id=900102`, `metodo='manual'`, `lectura_id`, `registrado_por_cuenta=cocinera2.id`).
   - Exactamente 1 intervención registrada en `intervenciones_lectura` (`resultado='registrada'`, `motivo_rechazo=None`, `usuario_id=900102`, `cuenta_id=cocinera2.id`, `asistencia_id`).
3. Consulta de Jefa (`GET /intervenciones-cocina` / `app.consultas.intervenciones.listar`):
   - Mismo comensal (`900102`, `QA 02 IDENTIFICACION`) y mismo `lectura_id`.
   - Decisión original conservada (`resultado='rechazada'`, `motivo='no_identificado'`).
   - Resultado final registrado (`resultado='registrada'`, `entrega_registrada=True`, `estado_actual_lectura='resuelta'`) atribuido a `cocinera2`.
   - Ausencia de intervenciones para `qa01` (`900101`) y `qa03` (`900103`).
4. Reserva (`qa03` — `900103`):
   - 0 lecturas, 0 asistencias y 0 intervenciones.
"""

import argparse
import json
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

import comun as c


def verificar_caso_normal(conn, datos, fecha: date):
    caso = datos["casos"]["qa01"]
    spec = c.COMENSALES_QA["qa01"]
    uid = spec["usuario_id"]
    aid_turno = spec["asignacion_id"]
    lid = caso.get("lectura_id")
    aid_asist = caso.get("asistencia_id")
    if lid is None or aid_asist is None:
        raise c.Abortado(
            "El caso qa01 aún no tiene lectura_id y asistencia_id en corrida.json; "
            "ejecutar primero `huella.py --caso qa01`"
        )

    lecturas = conn.execute(text(
        "SELECT id, usuario_id, dispositivo, fecha_hora, resultado, motivo "
        "FROM lecturas_biometricas WHERE id=:lid OR usuario_id=:uid"
    ), {"lid": lid, "uid": uid}).mappings().all()
    if len(lecturas) != 1:
        raise c.Abortado(
            f"QA 01 (normal): se esperaba 1 lectura biométrica y se encontraron {len(lecturas)}"
        )
    lectura = lecturas[0]
    if (
        lectura["id"] != lid
        or lectura["usuario_id"] != uid
        or lectura["dispositivo"] != c.DISPOSITIVO
        or lectura["resultado"] != "aceptada"
        or lectura["motivo"] is not None
        or lectura["fecha_hora"].isoformat() != caso.get("momento_lectura")
    ):
        raise c.Abortado("QA 01 (normal): la lectura biométrica no coincide con una marcación reconocida aceptada")

    asistencias = conn.execute(text(
        "SELECT id, usuario_id, fecha_comida, comida_id, servicio_id, turno_asignado_id, "
        "metodo, lectura_id, registrado_por_cuenta "
        "FROM asistencias WHERE id=:aid OR lectura_id=:lid OR usuario_id=:uid"
    ), {"aid": aid_asist, "lid": lid, "uid": uid}).mappings().all()
    if len(asistencias) != 1:
        raise c.Abortado(
            f"QA 01 (normal): se esperaba 1 asistencia y se encontraron {len(asistencias)}"
        )
    asistencia = asistencias[0]
    if (
        asistencia["id"] != aid_asist
        or asistencia["usuario_id"] != uid
        or asistencia["fecha_comida"] != fecha
        or asistencia["comida_id"] != c.COMIDA
        or asistencia["servicio_id"] != spec["servicio_id"]
        or asistencia["turno_asignado_id"] != aid_turno
        or asistencia["metodo"] != "biometrico"
        or asistencia["lectura_id"] != lid
        or asistencia["registrado_por_cuenta"] is not None
    ):
        raise c.Abortado("QA 01 (normal): la asistencia no coincide con el registro biométrico esperado")

    intervenciones = conn.execute(text(
        "SELECT COUNT(*) FROM intervenciones_lectura "
        "WHERE lectura_id=:lid OR usuario_id=:uid OR asistencia_id=:aid"
    ), {"lid": lid, "uid": uid, "aid": aid_asist}).scalar_one()
    if c.normalizar_contador(intervenciones, permitir_none=False) != 0:
        raise c.Abortado("QA 01 (normal): no debe existir ninguna intervención de cocina")

    caso["verificado"] = True
    return {
        "caso": "qa01",
        "usuario_id": uid,
        "lectura_id": lid,
        "asistencia_id": aid_asist,
        "lecturas": 1,
        "asistencias": 1,
        "intervenciones": 0,
        "resultado": "PASA",
    }


def verificar_caso_identificacion(conn, datos, fecha: date, cuentas_actuales: dict):
    caso = datos["casos"]["qa02"]
    spec = c.COMENSALES_QA["qa02"]
    uid = spec["usuario_id"]
    aid_turno = spec["asignacion_id"]
    lid = caso.get("lectura_id")
    if lid is None:
        raise c.Abortado(
            "El caso qa02 aún no tiene lectura_id en corrida.json; "
            "ejecutar primero `huella.py --caso qa02`"
        )
    if caso.get("usuario_id") is not None or caso.get("comensal_previsto_id") != uid:
        raise c.Abortado("QA 02: el diario debe conservar usuario_id=None y comensal_previsto_id=900102")
    cocinera2_id = cuentas_actuales.get("cocinera2")
    if cocinera2_id is None:
        raise c.Abortado("Falta cocinera2 en usuarios_sistema")

    lecturas = conn.execute(text(
        "SELECT id, usuario_id, dispositivo, fecha_hora, resultado, motivo "
        "FROM lecturas_biometricas WHERE id=:lid OR usuario_id=:uid"
    ), {"lid": lid, "uid": uid}).mappings().all()
    if len(lecturas) != 1:
        raise c.Abortado(
            f"QA 02 (identificación): se esperaba 1 lectura biométrica y se encontraron {len(lecturas)}"
        )
    lectura = lecturas[0]
    if (
        lectura["id"] != lid
        or lectura["usuario_id"] is not None
        or lectura["dispositivo"] != c.DISPOSITIVO
        or lectura["resultado"] != "rechazada"
        or lectura["motivo"] != "no_identificado"
        or lectura["fecha_hora"].isoformat() != caso.get("momento_lectura")
    ):
        raise c.Abortado(
            "QA 02 (identificación): la lectura original debe conservar usuario_id=None, "
            "resultado='rechazada' y motivo='no_identificado'"
        )

    asistencias = conn.execute(text(
        "SELECT id, usuario_id, fecha_comida, comida_id, servicio_id, turno_asignado_id, "
        "metodo, lectura_id, registrado_por_cuenta "
        "FROM asistencias WHERE lectura_id=:lid OR usuario_id=:uid"
    ), {"lid": lid, "uid": uid}).mappings().all()
    if len(asistencias) != 1:
        raise c.Abortado(
            "QA 02 (identificación): se esperaba 1 asistencia vinculada tras la confirmación de cocinera2 "
            f"y se encontraron {len(asistencias)}"
        )
    asistencia = asistencias[0]
    if (
        asistencia["usuario_id"] != uid
        or asistencia["fecha_comida"] != fecha
        or asistencia["comida_id"] != c.COMIDA
        or asistencia["servicio_id"] != spec["servicio_id"]
        or asistencia["turno_asignado_id"] != aid_turno
        or asistencia["metodo"] != "manual"
        or asistencia["lectura_id"] != lid
        or asistencia["registrado_por_cuenta"] != cocinera2_id
    ):
        raise c.Abortado(
            "QA 02 (identificación): la asistencia vinculada no coincide con la entrega de cocinera2 para 900102"
        )

    intervenciones = conn.execute(text(
        "SELECT id, lectura_id, usuario_id, cuenta_id, resultado, motivo_rechazo, "
        "causa, asistencia_id, comida_id, fecha_comida, nombre_comensal "
        "FROM intervenciones_lectura WHERE lectura_id=:lid OR usuario_id=:uid"
    ), {"lid": lid, "uid": uid}).mappings().all()
    if len(intervenciones) != 1:
        raise c.Abortado(
            f"QA 02 (identificación): se esperaba 1 intervención registrada y se encontraron {len(intervenciones)}"
        )
    interv = intervenciones[0]
    if (
        interv["lectura_id"] != lid
        or interv["usuario_id"] != uid
        or interv["cuenta_id"] != cocinera2_id
        or interv["resultado"] != "registrada"
        or interv["motivo_rechazo"] is not None
        or interv["causa"] != "identificacion_lectura_no_reconocida"
        or interv["asistencia_id"] != asistencia["id"]
        or interv["comida_id"] != c.COMIDA
        or interv["fecha_comida"] != fecha
        or interv["nombre_comensal"] != spec["nombre"]
    ):
        raise c.Abortado(
            "QA 02 (identificación): la intervención de cocina no coincide con la entrega registrada por cocinera2"
        )

    caso["asistencia_id"] = asistencia["id"]
    caso["intervencion_id"] = interv["id"]
    caso["estado"] = "completado"
    caso["verificado"] = True
    return {
        "caso": "qa02",
        "usuario_id": uid,
        "lectura_id": lid,
        "asistencia_id": asistencia["id"],
        "intervencion_id": interv["id"],
        "cuenta_id": cocinera2_id,
        "cuenta_usuario": "cocinera2",
        "lecturas": 1,
        "asistencias": 1,
        "intervenciones": 1,
        "resultado": "PASA",
    }


def verificar_consulta_jefa(conn, datos, fecha: date, cuentas_actuales: dict):
    """Comprobación interna del listado de intervenciones (contrato de consulta de cocina).

    Distinción metodológica importante:
    - Esta función ejecuta una comprobación interna directa sobre `consultas_intervenciones.listar()`
      y el serializador `_intervencion()`, validando el contrato SQL/ORM y la persistencia sin red.
    - Difiere de una petición HTTP autenticada (`GET /intervenciones-cocina` con Bearer token de jefa
      contra la API FastAPI).
    - Difiere de la visualización en navegador en el frontend, donde la jefa observa la tabla
      interactiva en la interfaz web.
    """
    caso = datos["casos"]["qa02"]
    spec_qa02 = c.COMENSALES_QA["qa02"]
    lid = caso.get("lectura_id")
    aid_asist = caso.get("asistencia_id")
    cocinera2_id = cuentas_actuales.get("cocinera2")

    with c.app_sin_dotenv(), c.reloj_laboratorio(datos), Session(bind=conn) as sesion:
        from app.api.intervenciones import _intervencion
        from app.consultas import intervenciones as consultas_intervenciones

        total, totales, filas = consultas_intervenciones.listar(
            sesion,
            consultas_intervenciones.Filtros(
                desde=fecha,
                hasta=fecha,
                usuario_id=spec_qa02["usuario_id"],
            ),
            limite=50,
            desplazamiento=0,
        )
        if total != 1 or totales != {"registradas": 1, "rechazadas": 0} or len(filas) != 1:
            raise c.Abortado(
                "Consulta de jefa: el listado de intervenciones para QA 02 no devolvió exactamente 1 entrega registrada"
            )
        vista = _intervencion(filas[0]).model_dump(mode="json")
        if (
            vista["comensal"] != {
                "usuario_id": spec_qa02["usuario_id"],
                "nombre": spec_qa02["nombre"],
                "categoria": "Administrativo",
            }
            or vista["decision_original"]["lectura_id"] != lid
            or vista["decision_original"]["resultado"] != "rechazada"
            or vista["decision_original"]["motivo"] != "no_identificado"
            or vista["decision_original"]["dispositivo"] != c.DISPOSITIVO
            or vista["resultado"] != "registrada"
            or vista["motivo_rechazo"] is not None
            or vista["resultado_final"] != {
                "entrega_registrada": True,
                "asistencia_id": aid_asist,
            }
            or vista["estado_actual_lectura"] != "resuelta"
            or vista["cuenta"]["id"] != cocinera2_id
            or vista["cuenta"]["usuario"] != "cocinera2"
        ):
            raise c.Abortado(
                "Consulta de jefa: la intervención expuesta no conserva la decisión original o no atribuye el registro a cocinera2"
            )

        for codigo_sin_interv in ("qa01", "qa03"):
            uid_otro = c.COMENSALES_QA[codigo_sin_interv]["usuario_id"]
            total_otro, _, _ = consultas_intervenciones.listar(
                sesion,
                consultas_intervenciones.Filtros(
                    desde=fecha,
                    hasta=fecha,
                    usuario_id=uid_otro,
                ),
                limite=50,
                desplazamiento=0,
            )
            if total_otro != 0:
                raise c.Abortado(
                    f"Consulta de jefa: el comensal {codigo_sin_interv} ({uid_otro}) no debe figurar con intervenciones"
                )

    return {
        "comensal_usuario_id": spec_qa02["usuario_id"],
        "comensal_nombre": spec_qa02["nombre"],
        "lectura_id": lid,
        "decision_original": {
            "resultado": "rechazada",
            "motivo": "no_identificado",
        },
        "resultado_final": {
            "resultado": "registrada",
            "entrega_registrada": True,
            "asistencia_id": aid_asist,
            "estado_actual_lectura": "resuelta",
            "cuenta_usuario": "cocinera2",
            "cuenta_id": cocinera2_id,
        },
        "resultado": "PASA",
    }


def verificar_reserva_qa03(conn):
    uid = c.COMENSALES_QA["qa03"]["usuario_id"]
    lecturas = c.normalizar_contador(
        conn.execute(
            text("SELECT COUNT(*) FROM lecturas_biometricas WHERE usuario_id=:uid"),
            {"uid": uid},
        ).scalar_one(),
        permitir_none=False,
    )
    asistencias = c.normalizar_contador(
        conn.execute(
            text("SELECT COUNT(*) FROM asistencias WHERE usuario_id=:uid"),
            {"uid": uid},
        ).scalar_one(),
        permitir_none=False,
    )
    intervenciones = c.normalizar_contador(
        conn.execute(
            text("SELECT COUNT(*) FROM intervenciones_lectura WHERE usuario_id=:uid"),
            {"uid": uid},
        ).scalar_one(),
        permitir_none=False,
    )
    if lecturas != 0 or asistencias != 0 or intervenciones != 0:
        raise c.Abortado("QA 03 (reserva): no debe tener lecturas, asistencias ni intervenciones")
    return {
        "caso": "qa03",
        "usuario_id": uid,
        "lecturas": 0,
        "asistencias": 0,
        "intervenciones": 0,
        "resultado": "PASA",
    }


def formatear_tabla_verificacion(resumen):
    lineas = [
        "| Bloque | Control | Esperado | Obtenido | PASA/FALLA |",
        "|---|---|---|---|---|",
    ]
    if "qa01" in resumen:
        r1 = resumen["qa01"]
        lineas.append(
            f"| QA 01 (Normal) | Lectura reconocida + asistencia biométrica + 0 intervenciones | "
            f"lecturas=1 (aceptada), asistencias=1 (biometrico), intervenciones=0 | "
            f"lectura_id={r1['lectura_id']}, asistencia_id={r1['asistencia_id']}, intervenciones={r1['intervenciones']} | "
            f"{r1['resultado']} |"
        )
    if "qa02" in resumen:
        r2 = resumen["qa02"]
        lineas.append(
            f"| QA 02 (Identificación) | Lectura rechazada (usuario_id=None) + asistencia vinculada + intervención cocinera2 | "
            f"lecturas=1 (no_identificado), asistencias=1, intervenciones=1 (cocinera2) | "
            f"lectura_id={r2['lectura_id']}, asistencia_id={r2['asistencia_id']}, intervencion_id={r2['intervencion_id']} ({r2['cuenta_usuario']}) | "
            f"{r2['resultado']} |"
        )
    if "consulta_jefa" in resumen:
        rj = resumen["consulta_jefa"]
        lineas.append(
            f"| Consulta de Jefa | Mismo comensal y lectura, decisión original conservada y resultado final registrado | "
            f"usuario_id=900102, original=rechazada/no_identificado, final=registrada por cocinera2 | "
            f"usuario_id={rj['comensal_usuario_id']}, lectura_id={rj['lectura_id']}, "
            f"original={rj['decision_original']['resultado']}/{rj['decision_original']['motivo']}, "
            f"final={rj['resultado_final']['resultado']} ({rj['resultado_final']['cuenta_usuario']}) | "
            f"{rj['resultado']} |"
        )
    if "qa03" in resumen:
        r3 = resumen["qa03"]
        lineas.append(
            f"| QA 03 (Reserva) | Comensal en reserva sin ejecuciones | "
            f"lecturas=0, asistencias=0, intervenciones=0 | "
            f"lecturas={r3['lecturas']}, asistencias={r3['asistencias']}, intervenciones={r3['intervenciones']} | "
            f"{r3['resultado']} |"
        )
    return "\n".join(lineas)


def ejecutar_comprobaciones(motor, datos, objetivo="todos"):
    if not c.es_corrida_multi(datos):
        raise c.Abortado(
            "verificar_casos.py requiere una corrida del escenario de tres comensales (version=2)"
        )
    c.validar_casos_diario(datos)
    fecha = date.fromisoformat(datos.get("fecha_destino") or datos["fecha_original"])
    resumen = dict(datos.get("verificacion_casos") or {})

    with motor.connect() as conn:
        filas_cuentas = conn.execute(text(
            "SELECT id, username, rol, usuario_turnos_id FROM usuarios_sistema "
            "WHERE username IN ('cocinera1','cocinera2','cocinera3','jefa')"
        )).mappings().all()
        cuentas_actuales = c.validar_cuentas_limpieza(filas_cuentas, datos.get("cuentas"))

        if objetivo in ("qa01", "todos"):
            resumen["qa01"] = verificar_caso_normal(conn, datos, fecha)
        if objetivo in ("qa02", "todos"):
            resumen["qa02"] = verificar_caso_identificacion(conn, datos, fecha, cuentas_actuales)
            resumen["consulta_jefa"] = verificar_consulta_jefa(conn, datos, fecha, cuentas_actuales)
        resumen["qa03"] = verificar_reserva_qa03(conn)

    datos["verificacion_casos"] = resumen
    if (
        datos["casos"]["qa01"].get("verificado") is True
        and datos["casos"]["qa02"].get("verificado") is True
    ):
        datos["estado"] = "casos_ejecutados"
    c.guardar_corrida(datos)
    print(formatear_tabla_verificacion(resumen))
    return resumen


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--caso",
        choices=("qa01", "qa02", "todos"),
        default="todos",
        help="Comprobar solo qa01, solo qa02 (con consulta de jefa) o todos (omisión: todos)",
    )
    args = parser.parse_args(argv)
    with c.bloqueo_corrida(), c.entorno_seguro(()) as (motor, huella, servidor):
        datos = c.leer_corrida(servidor)
        c.comprobar_base(datos, huella)
        ejecutar_comprobaciones(motor, datos, objetivo=args.caso)


if __name__ == "__main__":
    c.ejecutar(main)
