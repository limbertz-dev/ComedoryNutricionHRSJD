"""Ajuste idempotente de los tres perfiles sinteticos al catalogo del hospital."""
from datetime import datetime
from sqlalchemy import text
import comun as c
import configurar_reportes_qa


def permisos():
    return c.permisos((c.DEMO, 'categorias', 'INSERT'), (c.DEMO, 'servicios', 'INSERT'),
                      *((c.DEMO, t, 'UPDATE') for t in ('users', 'usuario_servicios', 'turnos_asignados')))


def preparar(conn):
    for uid, perfil in c.PERFILES_QA.items():
        spec = next(s for s in c.COMENSALES_QA.values() if s['usuario_id'] == uid)
        categoria = conn.execute(text(f'SELECT nombre FROM `{c.DEMO}`.categorias WHERE id=:id'), {'id': perfil['categoria_id']}).one_or_none()
        servicio = conn.execute(text(f'SELECT nombre FROM `{c.DEMO}`.servicios WHERE id=:id'), {'id': perfil['servicio_id']}).one_or_none()
        if categoria and categoria[0] != perfil['categoria'] or servicio and servicio[0] != perfil['servicio']:
            raise c.Abortado('Colision en los catalogos de perfiles QA; no se sobrescribe.')
        usuario = conn.execute(text(f'SELECT name,categoria_id FROM `{c.DEMO}`.users WHERE id=:uid'), {'uid': uid}).one_or_none()
        if usuario is None:
            raise c.Abortado('Preparar primero los tres comensales QA.')
        ficha = conn.execute(text(f'SELECT nombre_completo,numero_tipo_salario,carnet_identidad FROM `{c.DEMO}`.personas WHERE user_id=:uid'), {'uid': uid}).all()
        if (usuario[0] != spec['login'] or usuario[1] not in {9001, perfil['categoria_id']}
                or len(ficha) != 1 or tuple(ficha[0]) != (spec['nombre'], spec['legajo'], spec['carnet_identidad'])):
            raise c.Abortado('Identidad QA distinta; no se modifica el perfil.')
        for tabla, id_ in [('usuario_servicios', spec['usuario_id']), ('turnos_asignados', spec['asignacion_id'])]:
            fila = conn.execute(text(f'SELECT usuario_id,servicio_id FROM `{c.DEMO}`.`{tabla}` WHERE id=:id'), {'id': id_}).one_or_none()
            if not fila or fila[0] != uid or fila[1] not in {9001, perfil['servicio_id']}:
                raise c.Abortado('Relacion de servicio QA distinta; no se modifica.')
        if not categoria:
            conn.execute(text(f'INSERT INTO `{c.DEMO}`.categorias (id,nombre,nivel,descripcion) VALUES (:id,:nombre,1,:descripcion)'),
                         {'id': perfil['categoria_id'], 'nombre': perfil['categoria'], 'descripcion': 'Perfil sintetico del comedor QA'})
        if not servicio:
            conn.execute(text(f'INSERT INTO `{c.DEMO}`.servicios (id,nombre,descripcion,cantidad_pacientes) VALUES (:id,:nombre,:descripcion,0)'),
                         {'id': perfil['servicio_id'], 'nombre': perfil['servicio'], 'descripcion': 'Servicio sintetico para pruebas QA'})
        if usuario[1] == 9001:
            conn.execute(text(f'UPDATE `{c.DEMO}`.users SET categoria_id=:categoria WHERE id=:uid AND name=:nombre AND categoria_id=9001'),
                         {'uid': uid, 'nombre': spec['login'], 'categoria': perfil['categoria_id']})
        for tabla, id_ in [('usuario_servicios', spec['usuario_id']), ('turnos_asignados', spec['asignacion_id'])]:
            conn.execute(text(f'UPDATE `{c.DEMO}`.`{tabla}` SET servicio_id=:servicio WHERE id=:id AND usuario_id=:uid AND servicio_id=9001'),
                         {'id': id_, 'uid': uid, 'servicio': perfil['servicio_id']})


def main():
    if (c.CARPETA / 'api.activa').exists():
        raise c.Abortado('Detener la API QA antes de actualizar perfiles sinteticos.')
    with c.bloqueo_corrida(), c.entorno_seguro(permisos() | configurar_reportes_qa.permisos()) as (motor, huella, servidor):
        datos = c.leer_corrida(servidor)
        c.comprobar_base(datos, huella)
        with motor.begin() as conn:
            preparar(conn)
            configurar_reportes_qa.configurar(conn, aplicar=True)
        datos['perfiles_qa'] = {'version': 1, 'momento_real': datetime.now().isoformat(), 'usuarios': list(c.PERFILES_QA)}
        c.guardar_corrida(datos)
        print('QA 01 Medicos, QA 02 Tecnicos y QA 03 Internos; cuentas, huellas y entregas conservadas.')


if __name__ == '__main__':
    c.ejecutar(main)
