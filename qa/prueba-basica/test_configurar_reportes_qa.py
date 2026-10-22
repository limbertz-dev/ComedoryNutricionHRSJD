"""Cambio de columnas con SQL real offline y conservación del histórico."""
import pytest
from sqlalchemy import create_engine, text

import comun as c
import configurar_reportes_qa as configurador


@pytest.fixture
def conexion():
    motor = create_engine('sqlite:///:memory:')
    with motor.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE categorias_reporte (id INTEGER PRIMARY KEY, nombre TEXT UNIQUE, codigo TEXT UNIQUE, orden INTEGER, activo INTEGER)')
        conn.exec_driver_sql('CREATE TABLE categoria_reporte_map (id INTEGER PRIMARY KEY, categoria_id INTEGER UNIQUE, categoria_reporte_id INTEGER)')
        conn.exec_driver_sql('CREATE TABLE v_comensales (usuario_id INTEGER, categoria_id INTEGER)')
        conn.exec_driver_sql('CREATE TABLE asistencias (id INTEGER PRIMARY KEY, categoria_reporte_id INTEGER)')
        conn.exec_driver_sql("INSERT INTO categorias_reporte VALUES (1,'Medico','medico',1,1),(2,'Servicio','servicio',2,1),(3,'Administrativo','administrativo',3,1),(4,'Tecnicos','tecnicos',4,1),(5,'Policias','policias',5,1),(6,'Sin clasificar','sin_clasificar',99,1)")
        conn.exec_driver_sql('INSERT INTO v_comensales VALUES (900101,9003),(900102,9004),(900103,9005)')
        conn.exec_driver_sql('INSERT INTO asistencias VALUES (168,6),(169,6),(170,6)')
        yield conn
    motor.dispose()


def test_configurar_reportes_simulacro_idempotencia_y_preservacion(conexion):
    conn = conexion
    antes = conn.execute(text('SELECT * FROM categorias_reporte')).all()
    historico = conn.execute(text('SELECT * FROM asistencias')).all()
    assert len(configurador.configurar(conn)) == 6
    assert conn.execute(text('SELECT * FROM categorias_reporte')).all() == antes
    assert conn.scalar(text('SELECT COUNT(*) FROM categoria_reporte_map')) == 0
    configurador.configurar(conn, aplicar=True)
    assert not configurador.configurar(conn, aplicar=True)
    activas = conn.execute(text('SELECT codigo FROM categorias_reporte WHERE activo=1 ORDER BY orden')).scalars().all()
    assert activas == ['medico', 'internos', 'tecnicos', 'policias', 'sin_clasificar']
    destinos = dict(conn.execute(text('SELECT m.categoria_id,r.codigo FROM categoria_reporte_map m JOIN categorias_reporte r ON r.id=m.categoria_reporte_id')).all())
    assert destinos == {9003: 'medico', 9004: 'tecnicos', 9005: 'internos'}
    assert conn.execute(text('SELECT * FROM asistencias')).all() == historico
    assert conn.scalar(text('SELECT COUNT(*) FROM categorias_reporte')) == 7


def test_colision_de_mapeo_aborta_antes_de_cambiar_columnas(conexion):
    conn = conexion
    conn.exec_driver_sql('INSERT INTO categoria_reporte_map VALUES (1,9003,3)')
    antes = conn.execute(text('SELECT * FROM categorias_reporte')).all()
    with pytest.raises(c.Abortado, match='previa diferente'):
        configurador.configurar(conn, aplicar=True)
    assert conn.execute(text('SELECT * FROM categorias_reporte')).all() == antes


def test_permisos_no_modifican_raciones_ni_base_protegida():
    for base, sql in ((c.SIM, 'UPDATE asistencias SET categoria_reporte_id=1 WHERE id=168'),
                      (c.PROTEGIDA, 'UPDATE categorias_reporte SET activo=0 WHERE id=1'),
                      (c.SIM, 'DELETE FROM categorias_reporte WHERE id=3')):
        with pytest.raises(c.Abortado):
            c.revisar_sql(sql, base, configurador.permisos())
