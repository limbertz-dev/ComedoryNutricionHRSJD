"""Preparador idempotente de los tres comensales sintéticos QA (QA 01, QA 02, QA 03).

Simulacro por defecto (sin DML); `--aplicar` inserta únicamente los comensales
faltantes en `bd_turnos_escenario_demo` y comprueba sus fichas en `v_comensales`
y su derecho al almuerzo mediante `buscar_derecho`.

Nunca emite UPDATE ni DELETE: ante cualquier colisión de ID, login, nombre,
carnet, legajo (`numero_tipo_salario`), asignación o identificador único,
aborta sin sobrescribir personas existentes.
"""

import argparse
import json
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

import comun as c

TABLAS_DEMO_INSERCION = (
    "users",
    "personas",
    "usuario_servicios",
    "turnos_asignados",
    "escenario_identificaciones",
)


def permisos_preparador(aplicar: bool):
    if not aplicar:
        return ()
    return c.permisos(*((c.DEMO, tabla, "INSERT") for tabla in TABLAS_DEMO_INSERCION))


def validar_catalogos_base(conn):
    categoria = conn.execute(text(
        f"SELECT id, nombre, nivel, descripcion FROM `{c.DEMO}`.categorias WHERE id=9001"
    )).mappings().one_or_none()
    if (
        not categoria
        or categoria["nombre"] != "Administrativo"
    ):
        raise c.Abortado(f"Catálogo base {c.DEMO}.categorias (9001) ausente o incompatible")

    servicio = conn.execute(text(
        f"SELECT id, nombre, descripcion, cantidad_pacientes FROM `{c.DEMO}`.servicios WHERE id=9001"
    )).mappings().one_or_none()
    if (
        not servicio
        or servicio["nombre"] != "Servicio simulado"
    ):
        raise c.Abortado(f"Catálogo base {c.DEMO}.servicios (9001) ausente o incompatible")

    turno = conn.execute(text(
        f"SELECT id, nombre_turno, hora_inicio, hora_fin, duracion_horas, categoria_id "
        f"FROM `{c.DEMO}`.turnos WHERE id=9001"
    )).mappings().one_or_none()
    if not turno or turno["duracion_horas"] < 12:
        raise c.Abortado(f"Catálogo base {c.DEMO}.turnos (9001) ausente o incompatible")

    comida = conn.execute(text(
        f"SELECT id, nombre, codigo, estado FROM `{c.DEMO}`.comidas WHERE id=:cid"
    ), {"cid": c.COMIDA}).mappings().one_or_none()
    if not comida or not bool(comida["estado"]):
        raise c.Abortado(f"Catálogo base {c.DEMO}.comidas ({c.COMIDA}) ausente o incompatible")

    turno_comida = conn.execute(text(
        f"SELECT id, turno_id, comida_id, dia_relativo FROM `{c.DEMO}`.turno_comida WHERE id=9001"
    )).mappings().one_or_none()
    if (
        not turno_comida
        or turno_comida["turno_id"] != 9001
        or turno_comida["comida_id"] != c.COMIDA
        or turno_comida["dia_relativo"] != 0
    ):
        raise c.Abortado(f"Catálogo base {c.DEMO}.turno_comida (9001) ausente o incompatible")


def _estado_tabla(filas, predicado, tabla, codigo):
    if not filas:
        return "ausente"
    if len(filas) == 1 and predicado(filas[0]):
        return "existente"
    raise c.Abortado(
        f"Colisión en {c.DEMO}.{tabla} para {codigo}; no se sobrescribe ni modifica"
    )


def inspeccionar_comensal(conn, spec):
    codigo = spec["codigo"]
    uid = spec["usuario_id"]
    aid = spec["asignacion_id"]
    fecha_base = date.fromisoformat(spec["fecha_base"])

    filas_users = conn.execute(text(
        f"SELECT id, name, categoria_id FROM `{c.DEMO}`.users "
        "WHERE id=:uid OR name=:name"
    ), {"uid": uid, "name": spec["login"]}).mappings().all()
    est_users = _estado_tabla(
        filas_users,
        lambda f: (
            f["id"] == uid
            and f["name"] == spec["login"]
            and f["categoria_id"] == spec["categoria_id"]
        ),
        "users",
        codigo,
    )

    filas_personas = conn.execute(text(
        f"SELECT id, user_id, nombre_completo, carnet_identidad, tipo_trabajador, "
        f"numero_tipo_salario FROM `{c.DEMO}`.personas "
        "WHERE id=:uid OR user_id=:uid OR carnet_identidad=:carnet "
        "OR numero_tipo_salario=:legajo OR nombre_completo=:nombre"
    ), {
        "uid": uid,
        "carnet": spec["carnet_identidad"],
        "legajo": spec["legajo"],
        "nombre": spec["nombre"],
    }).mappings().all()
    est_personas = _estado_tabla(
        filas_personas,
        lambda f: (
            f["id"] == uid
            and f["user_id"] == uid
            and f["nombre_completo"] == spec["nombre"]
            and f["carnet_identidad"] == spec["carnet_identidad"]
            and f["tipo_trabajador"] == spec["tipo_trabajador"]
            and f["numero_tipo_salario"] == spec["legajo"]
        ),
        "personas",
        codigo,
    )

    filas_servicios = conn.execute(text(
        f"SELECT id, usuario_id, servicio_id, estado, fecha_ingreso "
        f"FROM `{c.DEMO}`.usuario_servicios WHERE id=:uid OR usuario_id=:uid"
    ), {"uid": uid}).mappings().all()
    est_servicios = _estado_tabla(
        filas_servicios,
        lambda f: (
            f["id"] == uid
            and f["usuario_id"] == uid
            and f["servicio_id"] == spec["servicio_id"]
            and bool(f["estado"])
            and f["fecha_ingreso"] in (fecha_base, spec["fecha_base"])
        ),
        "usuario_servicios",
        codigo,
    )

    filas_turnos = conn.execute(text(
        f"SELECT id, usuario_id, servicio_id, area_id, fecha, estado, es_intercambio, turno_id "
        f"FROM `{c.DEMO}`.turnos_asignados "
        "WHERE id=:aid OR (usuario_id=:uid AND fecha=:fecha)"
    ), {"aid": aid, "uid": uid, "fecha": fecha_base}).mappings().all()
    est_turnos = _estado_tabla(
        filas_turnos,
        lambda f: (
            f["id"] == aid
            and f["usuario_id"] == uid
            and f["servicio_id"] == spec["servicio_id"]
            and f["fecha"] in (fecha_base, spec["fecha_base"])
            and f["turno_id"] == spec["turno_id"]
        ),
        "turnos_asignados",
        codigo,
    )

    filas_ident = conn.execute(text(
        f"SELECT identificador, usuario_id, origen, descripcion "
        f"FROM `{c.DEMO}`.escenario_identificaciones "
        "WHERE usuario_id=:uid OR identificador=:ident"
    ), {"uid": uid, "ident": spec["identificador_unico"]}).mappings().all()
    est_ident = _estado_tabla(
        filas_ident,
        lambda f: (
            f["identificador"] == spec["identificador_unico"]
            and f["usuario_id"] == uid
            and f["origen"] == "simulado"
        ),
        "escenario_identificaciones",
        codigo,
    )

    estados = {
        "users": est_users,
        "personas": est_personas,
        "usuario_servicios": est_servicios,
        "turnos_asignados": est_turnos,
        "escenario_identificaciones": est_ident,
    }
    valores = set(estados.values())
    if len(valores) != 1:
        raise c.Abortado(
            f"Estado parcial inconsistente en {c.DEMO} para {codigo}: {estados}"
        )
    unico = next(iter(valores))
    return "existente_idempotente" if unico == "existente" else "por_insertar"


def insertar_comensal(conn, spec):
    uid = spec["usuario_id"]
    aid = spec["asignacion_id"]
    fecha_base = date.fromisoformat(spec["fecha_base"])

    conn.execute(text(
        f"INSERT INTO `{c.DEMO}`.users (id, name, categoria_id) VALUES (:id, :name, :cat)"
    ), {"id": uid, "name": spec["login"], "cat": spec["categoria_id"]})

    conn.execute(text(
        f"INSERT INTO `{c.DEMO}`.personas "
        "(id, user_id, nombre_completo, carnet_identidad, tipo_trabajador, numero_tipo_salario) "
        "VALUES (:id, :uid, :nombre, :carnet, :tipo, :legajo)"
    ), {
        "id": uid,
        "uid": uid,
        "nombre": spec["nombre"],
        "carnet": spec["carnet_identidad"],
        "tipo": spec["tipo_trabajador"],
        "legajo": spec["legajo"],
    })

    conn.execute(text(
        f"INSERT INTO `{c.DEMO}`.usuario_servicios "
        "(id, usuario_id, servicio_id, estado, fecha_ingreso) "
        "VALUES (:id, :uid, :srv, 1, :fecha)"
    ), {
        "id": uid,
        "uid": uid,
        "srv": spec["servicio_id"],
        "fecha": fecha_base,
    })

    conn.execute(text(
        f"INSERT INTO `{c.DEMO}`.turnos_asignados "
        "(id, usuario_id, servicio_id, area_id, fecha, estado, es_intercambio, turno_id) "
        "VALUES (:id, :uid, :srv, NULL, :fecha, 'ACTIVO', 0, :turno)"
    ), {
        "id": aid,
        "uid": uid,
        "srv": spec["servicio_id"],
        "fecha": fecha_base,
        "turno": spec["turno_id"],
    })

    conn.execute(text(
        f"INSERT INTO `{c.DEMO}`.escenario_identificaciones (identificador, usuario_id, origen, descripcion) "
        "VALUES (:ident, :uid, :origen, :desc)"
    ), {
        "ident": spec["identificador_unico"],
        "uid": uid,
        "origen": "simulado",
        "desc": spec["nombre"],
    })


def verificar_comensales_en_app(conn):
    with c.app_sin_dotenv(), Session(bind=conn) as sesion:
        from sqlalchemy import select
        from app.consultas.derecho import buscar_derecho
        from app.modelos.heredados import Comensal, UsuarioServicio

        for codigo, spec in c.COMENSALES_QA.items():
            ficha = sesion.get(Comensal, spec["usuario_id"])
            if (
                ficha is None
                or ficha.nombre_completo != spec["nombre"]
                or ficha.numero_item != spec["legajo"]
                or ficha.carnet_identidad != spec["carnet_identidad"]
                or ficha.categoria != "Administrativo"
                or not bool(ficha.tiene_ficha)
            ):
                raise c.Abortado(
                    f"Comensal {codigo} no visible o incompatible en v_comensales tras preparar"
                )

            rel_servicio = sesion.execute(
                select(UsuarioServicio).where(
                    UsuarioServicio.usuario_id == spec["usuario_id"],
                    UsuarioServicio.servicio_id == spec["servicio_id"],
                    UsuarioServicio.estado == 1,
                )
            ).scalars().first()
            if rel_servicio is None:
                raise c.Abortado(
                    f"Comensal {codigo} sin relación activa con servicio {spec['servicio_id']}"
                )

            fecha_base = date.fromisoformat(spec["fecha_base"])
            derecho = buscar_derecho(sesion, spec["usuario_id"], c.COMIDA, fecha_base)
            if (
                derecho is None
                or derecho.turno_asignado_id != spec["asignacion_id"]
                or derecho.comida_id != c.COMIDA
                or derecho.servicio_id != spec["servicio_id"]
            ):
                raise c.Abortado(
                    f"Sin derecho al almuerzo confirmado por buscar_derecho para {codigo}"
                )


def preparar(motor, aplicar=False):
    if (c.CARPETA / "api.activa").exists():
        raise c.Abortado("Detener la API QA antes de preparar comensales")
    if c.CORRIDA.exists():
        raise c.Abortado(
            "Existe corrida.json; cerrar, limpiar y archivar la corrida actual antes de preparar comensales"
        )
    c.cargar_manifiesto_comensales()
    resumen = {}
    with motor.begin() as conn:
        validar_catalogos_base(conn)
        for codigo, spec in c.COMENSALES_QA.items():
            estado_actual = inspeccionar_comensal(conn, spec)
            if aplicar and estado_actual == "por_insertar":
                insertar_comensal(conn, spec)
                accion = "insertado"
            else:
                accion = estado_actual
            resumen[codigo] = {
                "usuario_id": spec["usuario_id"],
                "asignacion_id": spec["asignacion_id"],
                "nombre": spec["nombre"],
                "legajo": spec["legajo"],
                "identificador_unico": spec["identificador_unico"],
                "rol_escenario": spec["rol_escenario"],
                "estado": accion,
            }
        if aplicar or all(
            item["estado"] == "existente_idempotente" for item in resumen.values()
        ):
            verificar_comensales_en_app(conn)
    print(json.dumps(resumen, ensure_ascii=False, indent=2))
    if aplicar:
        print("Comensales QA verificados en bd_turnos_escenario_demo y v_comensales.")
    else:
        print("Simulacro: sin INSERT en bd_turnos_escenario_demo; usar --aplicar para confirmar.")
    return resumen


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--aplicar",
        action="store_true",
        help="Insertar los comensales faltantes en bd_turnos_escenario_demo y verificar derecho",
    )
    args = parser.parse_args(argv)
    permitidas = permisos_preparador(args.aplicar)
    with c.bloqueo_corrida(), c.entorno_seguro(permitidas) as (motor, _huella, _servidor):
        preparar(motor, aplicar=args.aplicar)


if __name__ == "__main__":
    c.ejecutar(main)
