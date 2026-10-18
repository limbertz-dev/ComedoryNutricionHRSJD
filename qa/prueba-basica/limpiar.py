"""Limpieza acotada a corrida.json. Simulacro por defecto; --aplicar confirma."""
import argparse
from datetime import date, datetime

from sqlalchemy import text

import comun as c


def objetivos(conn, datos, actuales=None):
    params = {'lectura': datos['lectura_id'], 'inicio': datetime.fromisoformat(datos['inicio']),
              'max_intento': datos['max_intento_inicial'], 'max_sesion': datos['max_sesion_inicial']}
    filtros = [('intervenciones_lectura', 'lectura_id=:lectura'),
               ('asistencias', 'lectura_id=:lectura'), ('lecturas_biometricas', 'id=:lectura')]
    if c.existe_tabla(conn, 'sesiones'):
        contrato = c.contrato_sesiones(conn)
        if contrato != datos['contrato_sesiones'] or params['max_sesion'] is None:
            raise c.Abortado("El contrato de sesiones cambió desde el inicio")
        cuenta, fecha = contrato['cuenta'], contrato['fecha']
        if cuenta == 'username':
            valores = list(c.CUENTAS)
        else:
            ids = list((actuales or datos['cuentas']).values())
            valores = ids + [ids[0]] * (4 - len(ids))
        params.update(cuenta1=valores[0], cuenta2=valores[1], cuenta3=valores[2], cuenta4=valores[3])
        filtros.append(('sesiones', f"`{cuenta}` IN (:cuenta1,:cuenta2,:cuenta3,:cuenta4) AND `{fecha}`>=:inicio AND id>:max_sesion"))
    if c.existe_tabla(conn, 'intentos_login'):
        if params['max_intento'] is None:
            raise c.Abortado("intentos_login apareció después del inicio")
        filtros.append((
            'intentos_login',
            "username IN ('cocinera1','cocinera2','cocinera3','jefa') AND fecha_hora>=:inicio AND id>:max_intento",
        ))
    return filtros, params


def contar(conn, filtros, params):
    return {tabla: {
        'de_corrida': c.normalizar_contador(
            conn.execute(text(f"SELECT COUNT(*) FROM `{tabla}` WHERE {filtro}"), params).scalar_one(),
            permitir_none=False,
        ),
        'total_tabla': c.normalizar_contador(
            conn.execute(text(f"SELECT COUNT(*) FROM `{tabla}`")).scalar_one(),
            permitir_none=False,
        ),
    } for tabla, filtro in filtros}


def comprobar_propiedad(conn, datos, aplicar):
    fila = c.fila_asignacion(conn, bloquear=aplicar)
    if fila['fecha'].isoformat() not in {datos['fecha_original'], datos['fecha_destino']}:
        raise c.Abortado("Fecha modificada fuera de la corrida: no se restaura")
    cuentas = conn.execute(text(
        "SELECT id, username, rol, usuario_turnos_id FROM usuarios_sistema "
        "WHERE username IN ('cocinera1','cocinera2','cocinera3','jefa')"
    )).mappings().all()
    actuales = c.validar_cuentas_limpieza(cuentas, datos.get('cuentas'))
    if not set(datos.get('verificacion_cuentas') or ()) <= set(actuales):
        raise c.Abortado("Las cuentas cambiaron de identidad")
    lecturas = conn.execute(text(
        "SELECT id, usuario_id, dispositivo, fecha_hora, resultado, motivo FROM lecturas_biometricas "
        "WHERE id=:id OR dispositivo=:d" + (' FOR UPDATE' if aplicar else '')
    ), {'id': datos['lectura_id'], 'd': c.DISPOSITIVO}).mappings().all()
    for lectura in lecturas:
        if (lectura['id'] != datos['lectura_id'] or lectura['dispositivo'] != c.DISPOSITIVO
                or lectura['usuario_id'] is not None or lectura['motivo'] != 'no_identificado'
                or lectura['resultado'] != 'rechazada'
                or lectura['fecha_hora'].isoformat() != datos.get('momento_lectura')):
            raise c.Abortado("Lectura ajena o alterada: no se borra")
    propias = set(actuales.values())
    intentos = conn.execute(text(
        "SELECT cuenta_id, usuario_id FROM intervenciones_lectura WHERE lectura_id=:id"
    ), {'id': datos['lectura_id']}).all()
    if any(cuenta not in propias or uid != c.USUARIO for cuenta, uid in intentos):
        raise c.Abortado("Intervenciones fuera del caso básico: revisar antes de limpiar")
    asistencias = conn.execute(text(
        "SELECT usuario_id, comida_id, turno_asignado_id, registrado_por_cuenta FROM asistencias WHERE lectura_id=:id"
    ), {'id': datos['lectura_id']}).all()
    if any(uid != c.USUARIO or comida != c.COMIDA or asignacion != c.ASIGNACION or cuenta not in propias
           for uid, comida, asignacion, cuenta in asistencias):
        raise c.Abortado("Asistencia ajena a la corrida")
    return fila['fecha'], actuales


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--aplicar', action='store_true')
    args = parser.parse_args()
    permitidas = c.permisos((c.DEMO, 'turnos_asignados', 'UPDATE'), *(
        (c.SIM, tabla, 'DELETE') for tabla in (
            'intervenciones_lectura', 'asistencias', 'lecturas_biometricas', 'sesiones', 'intentos_login')
    )) if args.aplicar else ()
    with c.bloqueo_corrida(), c.entorno_seguro(permitidas) as (motor, huella, servidor):
        if (c.CARPETA / 'api.activa').exists():
            raise c.Abortado("Detener la API QA antes de limpiar")
        datos = c.leer_corrida(servidor)
        c.comprobar_base(datos, huella)
        # Una conexión / UNA transacción cubre los DELETE y el UPDATE entre bases.
        with motor.begin() as conn:
            actual, actuales = comprobar_propiedad(conn, datos, args.aplicar)
            filtros, params = objetivos(conn, datos, actuales)
            antes = contar(conn, filtros, params)
            print(f"Conteos antes (selección y total): {antes}")
            print(f"Asignación {c.ASIGNACION}: {actual} -> {datos['fecha_original']}")
            if args.aplicar:
                datos['estado'] = 'limpieza_pendiente'
                c.guardar_corrida(datos)
                for tabla, filtro in filtros:
                    resultado = conn.execute(text(f"DELETE FROM `{tabla}` WHERE {filtro}"), params)
                    if resultado.rowcount != antes[tabla]['de_corrida']:
                        raise c.Abortado("Conteo cambió durante limpieza; rollback completo")
                original = date.fromisoformat(datos['fecha_original'])
                if actual != original:
                    c.cambiar_fecha(conn, actual, original)
            despues = contar(conn, filtros, params)
            print(f"Conteos después {'reales' if args.aplicar else '(simulacro, sin cambios)'}: {despues}")
            if args.aplicar and any(v['de_corrida'] for v in despues.values()):
                raise c.Abortado("Quedaron filas de la corrida; rollback completo")
            for tabla in antes:
                esperado = antes[tabla]['total_tabla'] - (antes[tabla]['de_corrida'] if args.aplicar else 0)
                if despues[tabla]['total_tabla'] != esperado:
                    raise c.Abortado("Cambió una fila ajena o hubo concurrencia; rollback completo")
        if args.aplicar:
            datos.update(estado='limpia', limpieza={'antes': antes, 'despues': despues},
                         fin=datetime.now().isoformat())
            c.guardar_corrida(datos)
            print("Limpieza confirmada. Cuentas existentes y sus claves se conservan.")
        else:
            print("Simulacro: no se emitieron DELETE/UPDATE ni se modificó corrida.json")


if __name__ == '__main__':
    c.ejecutar(main)
