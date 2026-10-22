"""Turno exclusivo para probar las cuatro comidas con los tres comensales QA."""
import argparse
from datetime import date, time, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

import comun as c


NOMBRE_TURNO = 'QA laboratorio cuatro comidas 24 h'


def segundos(valor):
    if isinstance(valor, timedelta):
        return valor.total_seconds()
    if isinstance(valor, time):
        return valor.hour * 3600 + valor.minute * 60 + valor.second
    partes = str(valor).split(':')
    return int(partes[0]) * 3600 + int(partes[1]) * 60 + float(partes[2])


def preparar(conn, datos):
    if any(info.get('lectura_id') is not None for info in datos['casos'].values()):
        raise c.Abortado('Archivar el ensayo actual antes de preparar otro servicio.')
    if (c.CARPETA / 'api.activa').exists():
        raise c.Abortado('Detener la API propia antes de preparar los servicios.')
    c.filas_asignaciones_corrida(conn, datos, bloquear=True)
    turno = conn.execute(text(
        f'SELECT id,nombre_turno,hora_inicio,hora_fin,duracion_horas,categoria_id '
        f'FROM `{c.DEMO}`.turnos WHERE id=:id OR nombre_turno=:nombre'
    ), {'id': c.TURNO_LABORATORIO, 'nombre': NOMBRE_TURNO}).mappings().all()
    if turno and (len(turno) != 1 or turno[0]['id'] != c.TURNO_LABORATORIO
                  or turno[0]['nombre_turno'] != NOMBRE_TURNO
                  or segundos(turno[0]['hora_inicio']) != 0
                  or segundos(turno[0]['hora_fin']) != 86399
                  or turno[0]['duracion_horas'] != 24 or turno[0]['categoria_id'] != 9001):
        raise c.Abortado('Colisión en el turno exclusivo del laboratorio; no se sobrescribe.')
    filas = conn.execute(text(
        f'SELECT id,turno_id,comida_id,dia_relativo FROM `{c.DEMO}`.turno_comida '
        'WHERE turno_id=:turno OR id IN (90010101,90010102,90010103,90010104)'
    ), {'turno': c.TURNO_LABORATORIO}).mappings().all()
    for fila in filas:
        cid = fila['comida_id']
        if (cid not in c.COMIDAS_LABORATORIO or fila['id'] != 90010100 + cid
                or fila['turno_id'] != c.TURNO_LABORATORIO or fila['dia_relativo'] != 0):
            raise c.Abortado('Colisión en el mapeo de comidas del laboratorio; no se sobrescribe.')
    if len({f['comida_id'] for f in filas}) != len(filas):
        raise c.Abortado('Mapeo duplicado de comidas del laboratorio.')
    for cid, comida in c.COMIDAS_LABORATORIO.items():
        catalogo = conn.execute(text(
            f'SELECT codigo,estado FROM `{c.DEMO}`.comidas WHERE id=:id'
        ), {'id': cid}).mappings().one_or_none()
        if not catalogo or catalogo['codigo'] != comida['codigo'] or not catalogo['estado']:
            raise c.Abortado('El catálogo de comidas QA es incompatible.')
    # El diario previo permite limpiar una preparación interrumpida tanto tras rollback como commit.
    datos['turno_laboratorio'] = {'id': c.TURNO_LABORATORIO, 'original': 9001, 'preparando': True}
    c.guardar_corrida(datos)
    if not turno:
        conn.execute(text(
            f'INSERT INTO `{c.DEMO}`.turnos '
            '(id,nombre_turno,hora_inicio,hora_fin,duracion_horas,categoria_id) '
            'VALUES (:id,:nombre,:inicio,:fin,24,9001)'
        ), {'id': c.TURNO_LABORATORIO, 'nombre': NOMBRE_TURNO,
            'inicio': '00:00:00', 'fin': '23:59:59'})
    existentes = {f['comida_id'] for f in filas}
    for cid in c.COMIDAS_LABORATORIO:
        if cid not in existentes:
            conn.execute(text(
                f'INSERT INTO `{c.DEMO}`.turno_comida (id,turno_id,comida_id,dia_relativo) '
                'VALUES (:id,:turno,:comida,0)'
            ), {'id': 90010100 + cid, 'turno': c.TURNO_LABORATORIO, 'comida': cid})
    for spec in c.COMENSALES_QA.values():
        fila = conn.execute(text(
            f'SELECT turno_id FROM `{c.DEMO}`.turnos_asignados '
            'WHERE id=:id AND usuario_id=:uid FOR UPDATE'
        ), {'id': spec['asignacion_id'], 'uid': spec['usuario_id']}).one()
        if fila[0] == c.TURNO_LABORATORIO:
            continue
        if fila[0] != spec['turno_id']:
            raise c.Abortado('La asignación QA cambió fuera del laboratorio.')
        cambio = conn.execute(text(
            f'UPDATE `{c.DEMO}`.turnos_asignados SET turno_id=:turno '
            'WHERE id=:id AND usuario_id=:uid AND turno_id=:original'
        ), {'turno': c.TURNO_LABORATORIO, 'id': spec['asignacion_id'],
            'uid': spec['usuario_id'], 'original': spec['turno_id']})
        if cambio.rowcount != 1:
            raise c.Abortado('La asignación QA cambió durante la preparación.')
    with c.app_sin_dotenv(), Session(bind=conn) as sesion:
        from app.consultas.derecho import buscar_derecho
        fecha = date.fromisoformat(datos.get('fecha_destino') or datos['fecha_original'])
        for spec in c.COMENSALES_QA.values():
            for cid in c.COMIDAS_LABORATORIO:
                derecho = buscar_derecho(sesion, spec['usuario_id'], cid, fecha)
                if derecho is None or derecho.turno_asignado_id != spec['asignacion_id']:
                    raise c.Abortado('No se confirmó el derecho QA a las cuatro comidas; rollback.')


def main():
    permitidas = c.permisos((c.DEMO, 'turnos', 'INSERT'), (c.DEMO, 'turno_comida', 'INSERT'),
                           (c.DEMO, 'turnos_asignados', 'UPDATE'))
    with c.bloqueo_corrida(), c.entorno_seguro(permitidas) as (motor, huella, servidor):
        datos = c.leer_corrida(servidor)
        c.comprobar_base(datos, huella)
        with motor.begin() as conn:
            preparar(conn, datos)
        datos['turno_laboratorio']['preparando'] = False
        c.guardar_corrida(datos)
        print('Tres comensales QA con derecho verificado a Desayuno, Almuerzo, Té y Cena.')


if __name__ == '__main__':
    c.ejecutar(main)
