"""Columnas y clasificación QA: Internos sustituye a Servicio, sin borrar historia."""
import argparse

from sqlalchemy import text

import comun as c


def permisos():
    return c.permisos(
        (c.SIM, 'categorias_reporte', 'INSERT'),
        (c.SIM, 'categorias_reporte', 'UPDATE'),
        (c.SIM, 'categoria_reporte_map', 'INSERT'),
    )


def configurar(conn, aplicar=False):
    columnas = {f['codigo']: dict(f) for f in conn.execute(text(
        'SELECT id,nombre,codigo,orden,activo FROM categorias_reporte'
    )).mappings()}
    if not {'medico', 'tecnicos', 'sin_clasificar'}.issubset(columnas):
        raise c.Abortado('Faltan columnas base del informe QA; no se cambia el catálogo.')
    if any(f['nombre'] == 'Internos' and f['codigo'] != 'internos' for f in columnas.values()):
        raise c.Abortado('Existe una columna Internos con otro código; revisar antes de cambiarla.')
    perfiles = dict(conn.execute(text(
        'SELECT usuario_id,categoria_id FROM v_comensales WHERE usuario_id IN (900101,900102,900103)'
    )).all())
    destinos = {900101: 'medico', 900102: 'tecnicos', 900103: 'internos'}
    pendientes = []
    for uid, codigo in destinos.items():
        cid = c.PERFILES_QA[uid]['categoria_id']
        if perfiles.get(uid) != cid:
            raise c.Abortado('Preparar primero los perfiles QA; su categoría no coincide.')
        mapeo = conn.execute(text(
            'SELECT categoria_reporte_id FROM categoria_reporte_map WHERE categoria_id=:cid'
        ), {'cid': cid}).scalar_one_or_none()
        esperado = columnas.get(codigo, {}).get('id')
        if mapeo is not None and mapeo != esperado:
            raise c.Abortado('Clasificación QA previa diferente; no se sobrescribe.')
        if mapeo is None:
            pendientes.append((cid, codigo))
    acciones = []
    if 'internos' not in columnas:
        acciones.append('Crear columna Internos')
    elif not columnas['internos']['activo']:
        acciones.append('Activar columna Internos')
    for codigo in ('servicio', 'administrativo'):
        if columnas.get(codigo, {}).get('activo'):
            acciones.append('Desactivar columna ' + columnas[codigo]['nombre'])
    acciones.extend('Relacionar categoría QA ' + str(cid) + ' con ' + codigo for cid, codigo in pendientes)
    if not aplicar:
        return acciones
    if 'internos' not in columnas:
        resultado = conn.execute(text(
            'INSERT INTO categorias_reporte (nombre,codigo,orden,activo) VALUES (:nombre,:codigo,:orden,1)'
        ), {'nombre': 'Internos', 'codigo': 'internos', 'orden': columnas.get('servicio', {}).get('orden', 2)})
        columnas['internos'] = {'id': resultado.lastrowid, 'activo': 1}
    elif not columnas['internos']['activo']:
        conn.execute(text('UPDATE categorias_reporte SET activo=1 WHERE id=:id'), {'id': columnas['internos']['id']})
    for codigo in ('servicio', 'administrativo'):
        if columnas.get(codigo, {}).get('activo'):
            conn.execute(text('UPDATE categorias_reporte SET activo=0 WHERE id=:id'), {'id': columnas[codigo]['id']})
    for cid, codigo in pendientes:
        conn.execute(text(
            'INSERT INTO categoria_reporte_map (categoria_id,categoria_reporte_id) VALUES (:cid,:destino)'
        ), {'cid': cid, 'destino': columnas[codigo]['id']})
    return acciones


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--aplicar', action='store_true')
    args = parser.parse_args()
    with c.bloqueo_corrida(), c.entorno_seguro(permisos()) as (motor, _, _):
        with motor.begin() as conn:
            acciones = configurar(conn, aplicar=args.aplicar)
        for accion in acciones:
            print(('Aplicado: ' if args.aplicar else 'Simulacro: ') + accion)
        if not acciones:
            print('El informe QA ya está configurado.')
        print('Las raciones y sus clasificaciones históricas se conservan.')


if __name__ == '__main__':
    c.ejecutar(main)
