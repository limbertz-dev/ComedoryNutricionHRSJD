"""Politica y circuito de huella registrada con SQL real offline, sin MySQL."""
from contextlib import contextmanager
from datetime import date, datetime, time
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import Integer, MetaData, create_engine, select, func, text
from sqlalchemy.orm import Session

import comun as c
import enrolamiento
import lector_enrolado


@pytest.fixture
def circuito(tmp_path, monkeypatch):
    with c.app_sin_dotenv():
        from app.core.db import Base, BaseContrato
        from app.modelos import comedor, heredados, reglas, usuarios
        metadata = MetaData()
        for original in [*Base.metadata.tables.values(), *BaseContrato.metadata.tables.values()]:
            tabla = original.to_metadata(metadata)
            for col in tabla.columns:
                col.type = col.type.as_generic()
                if col.primary_key and isinstance(col.type, Integer):
                    col.type = Integer()
        motor = create_engine('sqlite:///' + (tmp_path / 'circuito.sqlite').as_posix(), connect_args={'check_same_thread': False})
        metadata.create_all(motor)
        dia = date(2026, 10, 15)
        with Session(motor) as sesion:
            sesion.add_all([
                heredados.Servicio(id=1, nombre='MEDICINA INTERNA', cantidad_pacientes=0),
                comedor.CategoriaReporte(id=1, nombre='Medicos', codigo='medicos', orden=1, activo=True),
                comedor.CategoriaReporte(id=2, nombre='Sin clasificar', codigo='sin_clasificar', orden=2, activo=True),
                comedor.CategoriaReporteMap(id=1, categoria_id=1, categoria_reporte_id=1),
                reglas.ReglaDerecho(id=1, vigente_desde=date(2000, 1, 1), duracion_minima_horas=12,
                                    excluir_enfermeria=False, motivo='Fixture offline', creada_por_cuenta=None),
                usuarios.UsuarioSistema(id=2, username='cocinera2', password_hash='fixture-no-autenticable',
                                        rol='cocinera', debe_cambiar=False, activo=True, version_token=0),
            ])
            for perfil in c.PERFILES_QA.values():
                sesion.add(heredados.Servicio(id=perfil['servicio_id'], nombre=perfil['servicio'], cantidad_pacientes=0))
            for cid, nombre, inicio, fin in [(1, 'Desayuno', 7, 9), (2, 'Almuerzo', 11, 15),
                                             (3, 'Te', 16, 18), (4, 'Cena', 19, 22)]:
                sesion.add(heredados.Comida(id=cid, nombre=nombre, codigo=nombre.lower(), estado=True))
                sesion.add(comedor.CoeficienteRacion(id=cid, comida_id=cid, coeficiente=1,
                                                   vigente_desde=date(2000, 1, 1)))
                sesion.add(comedor.HorarioComida(id=cid, comida_id=cid, hora_inicio=time(inicio),
                    hora_fin=time(fin), vigente_desde=datetime(2000, 1, 1), activo=True))
            for uid, categoria in [(900101, 'Medicos'), (900102, 'Tecnicos'), (900103, 'Internos'),
                                    (900001, 'Administrativo'), (900004, 'Interno-Enfermeria')]:
                nombre = next((s['nombre'] for s in c.COMENSALES_QA.values() if s['usuario_id'] == uid), f'Persona {uid}')
                legajo = next((s['legajo'] for s in c.COMENSALES_QA.values() if s['usuario_id'] == uid), f'LEG-{uid}')
                sesion.add(heredados.Comensal(usuario_id=uid, nombre_completo=nombre, numero_item=legajo,
                    categoria_id=1, categoria=categoria, tiene_ficha=True))
                servicio_id = c.PERFILES_QA.get(uid, {}).get('servicio_id', 1)
                asignacion_id = next((s['asignacion_id'] for s in c.COMENSALES_QA.values() if s['usuario_id'] == uid), uid)
                sesion.add(heredados.UsuarioServicio(id=uid, usuario_id=uid, servicio_id=servicio_id, estado=True, fecha_ingreso=dia))
                for cid, nombre in [(1, 'Desayuno'), (2, 'Almuerzo'), (3, 'Te'), (4, 'Cena')]:
                    sesion.add(heredados.ComidaPorTurno(turno_asignado_id=asignacion_id, comida_id=cid, usuario_id=uid,
                        servicio_id=servicio_id, fecha_turno=dia, dia_relativo=0, fecha_comida=dia,
                        comida=nombre, turno_id=1, turno='Guardia', duracion_horas=24,
                        categoria_id=1, categoria=categoria))
            sesion.commit()

        monkeypatch.setattr(c, 'CARPETA', tmp_path)
        monkeypatch.setattr(c, 'CORRIDA', tmp_path / 'corrida.json')
        datos = {'cuentas': {'cocinera2': 2}, 'casos': c.casos_iniciales_diario(),
                 'comensales': c.resumen_comensales_diario(), 'escenario': 'tres_comensales_qa',
                 'parte_a': {'completa': True}, 'inicio': '2026-10-19T00:00:00', 'max_intento_inicial': 0, 'max_sesion_inicial': None}
        c.guardar_corrida(datos)
        monkeypatch.setattr(c, 'leer_corrida', lambda *_: json.loads(c.CORRIDA.read_text(encoding='utf-8')))
        monkeypatch.setattr(c, 'comprobar_base', lambda *_: None)
        momento = SimpleNamespace(valor=datetime(2026, 10, 15, 12))

        @contextmanager
        def reloj(_):
            yield SimpleNamespace(ahora=lambda: momento.valor)

        monkeypatch.setattr(c, 'reloj_laboratorio', reloj)
        yield motor, momento
        motor.dispose()


@pytest.mark.parametrize('categoria,esperado', [
    ('Medicos', True), (' MÉDICOS ', True), ('Tecnicos', True), ('TÉCNICOS', True),
    ('Internos', True), ('Residentes', True), ('Internos-Medicina', True),
    ('Internos-Bioquimica', True), ('Internos-Imagenologia', True), ('Internos-Fisioterapia', True),
    ('Enfermera', False), ('Aux. Enfermeria', False), ('Interno-Enfermeria', False),
    ('Enfermería', False), ('Administrativo', False), ('Manual', False), ('Mantenimiento', False),
    ('Camillero', False), ('nombre desconocido', False), (None, False),
])
def test_politica_python_y_sql_coinciden(categoria, esperado):
    with c.app_sin_dotenv():
        from app.consultas.perfiles import categoria_permitida, categoria_permitida_sql
        from sqlalchemy import literal
        assert categoria_permitida(categoria) == esperado
        motor = create_engine('sqlite:///:memory:')
        quitar = c.instalar_auditor((), objetivo=motor)
        try:
            with motor.connect() as conn:
                obtenido = conn.scalar(select(literal(1)).where(categoria_permitida_sql(literal(categoria))))
        finally:
            quitar()
            motor.dispose()
        assert (obtenido == 1) == esperado


def test_auditor_admite_replace_de_texto_pero_no_dml():
    c.revisar_sql("SELECT REPLACE(categoria,'a','e') FROM v_comensales", c.SIM, ())
    for sql in ["SELECT 1 REPLACE INTO usuarios_sistema (id) VALUES (1)",
                "REPLACE INTO usuarios_sistema (id) VALUES (1)",
                "SELECT REPLACE('a','a','b'), CALL procedimiento()",
                "SELECT REPLACE('a','a','b'); DELETE FROM asistencias WHERE id=1"]:
        with pytest.raises(c.Abortado):
            c.revisar_sql(sql, c.SIM, ())


def test_referencia_reconocida_reenvio_y_nueva_lectura_duplicada(circuito):
    motor, _ = circuito
    referencia = enrolamiento.registrar(900101, 2, str(uuid4()))['referencia']
    clave = str(uuid4())
    primero = lector_enrolado.procesar(motor, 'srv', {}, 2, referencia, clave)
    assert primero['valido'] and primero['usuario_id'] == 900101
    assert lector_enrolado.procesar(motor, 'srv', {}, 2, referencia, clave) == primero
    segundo = lector_enrolado.procesar(motor, 'srv', {}, 2, referencia, str(uuid4()))
    assert not segundo['valido'] and segundo['motivo'] == 'duplicado'
    with motor.connect() as conn:
        assert conn.scalar(text('SELECT COUNT(*) FROM asistencias')) == 1
        assert conn.scalar(text('SELECT COUNT(*) FROM lecturas_biometricas')) == 2
        assert len(lector_enrolado.validar(conn, c.leer_corrida('srv'))) == 2


@pytest.mark.parametrize('uid', [900001, 900004])
def test_huella_preexistente_no_habilita_categoria_excluida(circuito, uid):
    motor, _ = circuito
    # Representa un vinculo antiguo: conocer la identidad no concede derecho.
    referencia = enrolamiento.registrar(uid, 2, str(uuid4()))['referencia']
    respuesta = lector_enrolado.procesar(motor, 'srv', {}, 2, referencia, str(uuid4()))
    assert not respuesta['valido'] and respuesta['motivo'] == 'sin_derecho'
    with motor.connect() as conn:
        assert conn.scalar(text('SELECT COUNT(*) FROM asistencias')) == 0
        lector_enrolado.validar(conn, c.leer_corrida('srv'))


def test_cocina_no_puede_eludir_exclusion_de_categoria(circuito):
    from unittest.mock import patch
    motor, momento = circuito
    with c.app_sin_dotenv():
        from app.logica.marcacion import registrar_marcacion
        from app.logica.intervencion import identificar_lectura
        from app.core import reloj
        with Session(motor) as sesion:
            lectura = registrar_marcacion(sesion, usuario_id=None, momento=momento.valor)
            with patch.object(reloj, 'ahora', return_value=momento.valor):
                respuesta = identificar_lectura(sesion, cuenta_id=2, lectura_id=lectura.lectura_id,
                    usuario_id=900004, clave=str(uuid4()))
            assert not respuesta.valido and respuesta.motivo == 'sin_derecho'
            assert sesion.scalar(text('SELECT COUNT(*) FROM asistencias')) == 0
            assert sesion.scalar(text('SELECT resultado FROM intervenciones_lectura')) == 'rechazada'


def test_huella_permite_cuatro_comidas_y_limpieza_exacta(circuito, monkeypatch):
    import limpiar
    motor, momento = circuito
    referencia = enrolamiento.registrar(900103, 2, str(uuid4()))['referencia']
    for hora, comida in [(8, 'Desayuno'), (12, 'Almuerzo'), (17, 'Te'), (20, 'Cena')]:
        momento.valor = datetime(2026, 10, 15, hora)
        resultado = lector_enrolado.procesar(motor, 'srv', {}, 2, referencia, str(uuid4()))
        assert resultado['valido'] and resultado['comida'] == comida
    monkeypatch.setattr(c, 'existe_tabla', lambda *_: False)
    with motor.begin() as conn:
        datos = c.leer_corrida('srv')
        limpiar._comprobar_propiedad_multi(conn, datos, {'cocinera2': 2}, False)
        filtros, params = limpiar.objetivos(conn, datos)
        for tabla, filtro in filtros:
            conn.execute(text(f'DELETE FROM {tabla} WHERE {filtro}'), params)
        assert conn.scalar(text('SELECT COUNT(*) FROM asistencias')) == 0
        assert conn.scalar(text('SELECT COUNT(*) FROM lecturas_biometricas')) == 0
    assert enrolamiento.resolver(referencia) == 900103


def test_referencia_distinta_no_puede_reusar_solicitud(circuito):
    motor, _ = circuito
    a = enrolamiento.registrar(900101, 2, str(uuid4()))['referencia']
    b = enrolamiento.registrar(900102, 2, str(uuid4()))['referencia']
    clave = str(uuid4())
    lector_enrolado.procesar(motor, 'srv', {}, 2, a, clave)
    with pytest.raises(c.Abortado, match='otra persona'):
        lector_enrolado.procesar(motor, 'srv', {}, 2, b, clave)
    with motor.begin() as conn:
        conn.execute(text("UPDATE lecturas_biometricas SET dispositivo='ajeno'"))
    with motor.connect() as conn, pytest.raises(c.Abortado, match='ajena'):
        lector_enrolado.validar(conn, c.leer_corrida('srv'))


def test_migracion_perfiles_sql_idempotente_conserva_personas_ajenas():
    import preparar_perfiles
    motor = create_engine('sqlite:///:memory:')
    with motor.begin() as conn:
        conn.exec_driver_sql(f"ATTACH DATABASE ':memory:' AS {c.DEMO}")
        for tabla, columnas in {
            'categorias': 'id INTEGER PRIMARY KEY,nombre TEXT,nivel INTEGER,descripcion TEXT',
            'servicios': 'id INTEGER PRIMARY KEY,nombre TEXT,descripcion TEXT,cantidad_pacientes INTEGER',
            'users': 'id INTEGER PRIMARY KEY,name TEXT,categoria_id INTEGER',
            'personas': 'user_id INTEGER,nombre_completo TEXT,numero_tipo_salario TEXT,carnet_identidad TEXT',
            'usuario_servicios': 'id INTEGER PRIMARY KEY,usuario_id INTEGER,servicio_id INTEGER',
            'turnos_asignados': 'id INTEGER PRIMARY KEY,usuario_id INTEGER,servicio_id INTEGER',
        }.items():
            conn.exec_driver_sql(f'CREATE TABLE {c.DEMO}.{tabla} ({columnas})')
        for spec in c.COMENSALES_QA.values():
            uid = spec['usuario_id']
            conn.execute(text(f'INSERT INTO {c.DEMO}.users VALUES (:uid,:nombre,9001)'), {'uid': uid, 'nombre': spec['login']})
            conn.execute(text(f'INSERT INTO {c.DEMO}.personas VALUES (:uid,:nombre,:legajo,:ci)'),
                         {'uid': uid, 'nombre': spec['nombre'], 'legajo': spec['legajo'], 'ci': spec['carnet_identidad']})
            for tabla, id_ in [('usuario_servicios', uid), ('turnos_asignados', spec['asignacion_id'])]:
                conn.execute(text(f'INSERT INTO {c.DEMO}.{tabla} VALUES (:id,:uid,9001)'), {'id': id_, 'uid': uid})
        conn.exec_driver_sql(f"INSERT INTO {c.DEMO}.users VALUES (900001,'historico',9001)")
        preparar_perfiles.preparar(conn)
        primera = conn.execute(text(f'SELECT * FROM {c.DEMO}.users ORDER BY id')).all()
        preparar_perfiles.preparar(conn)
        assert primera == conn.execute(text(f'SELECT * FROM {c.DEMO}.users ORDER BY id')).all()
        assert primera[0] == (900001, 'historico', 9001)
        assert dict(conn.execute(text(f'SELECT id,nombre FROM {c.DEMO}.categorias')).all()) == {
            p['categoria_id']: p['categoria'] for p in c.PERFILES_QA.values()}
        conn.exec_driver_sql(f"UPDATE {c.DEMO}.users SET name='persona_ajena' WHERE id=900101")
        with pytest.raises(c.Abortado, match='Identidad QA distinta'):
            preparar_perfiles.preparar(conn)
        conn.exec_driver_sql(f"UPDATE {c.DEMO}.categorias SET nombre='Enfermera' WHERE id=9003")
        with pytest.raises(c.Abortado, match='Colision'):
            preparar_perfiles.preparar(conn)
    motor.dispose()


def test_recupera_commit_si_se_perdio_respuesta_final_y_rechaza_relacion_cruzada(circuito):
    motor, _ = circuito
    referencia = enrolamiento.registrar(900101, 2, str(uuid4()))['referencia']
    clave = str(uuid4())
    respuesta = lector_enrolado.procesar(motor, 'srv', {}, 2, referencia, clave)
    datos = c.leer_corrida('srv')
    datos['lecturas_enroladas'][0]['respuesta'] = None
    c.guardar_corrida(datos)
    recuperada = lector_enrolado.procesar(motor, 'srv', {}, 2, referencia, clave)
    assert recuperada['valido'] and recuperada['asistencia_id'] == respuesta['asistencia_id']
    with motor.begin() as conn:
        assert conn.scalar(text('SELECT COUNT(*) FROM asistencias')) == 1
        conn.execute(text('UPDATE asistencias SET usuario_id=900102'))
    with motor.connect() as conn, pytest.raises(c.Abortado, match='relaciones incompatibles'):
        lector_enrolado.validar(conn, c.leer_corrida('srv'))


def test_modal_distingue_huella_de_cada_caso_aunque_qa03_este_registrado(circuito, monkeypatch):
    from unittest.mock import Mock
    import laboratorio
    motor, _ = circuito
    datos = c.leer_corrida('srv')
    datos.update(fecha_original='2026-10-15', reloj={
        'lab': '2026-10-15T12:00:00', 'real': '2026-10-19T12:00:00', 'modo': 'fijo'})
    monkeypatch.setattr(c, 'validar_cuentas_limpieza', lambda *_: {'cocinera2': 2})
    control = laboratorio.Laboratorio(motor, 'srv', {})
    control.diario = Mock(return_value=datos)
    enrolamiento.registrar(900103, 2, str(uuid4()))
    estado = control.estado()
    assert not estado['casos']['qa01']['huella_registrada']
    assert not estado['casos']['qa02']['huella_registrada']
    assert estado['casos']['qa01']['usuario_id'] == 900101
    assert estado['casos']['qa02']['nombre'] == 'QA 02 IDENTIFICACION'
    enrolamiento.registrar(900101, 2, str(uuid4()))
    estado = control.estado()
    assert estado['casos']['qa01']['huella_registrada']
    assert not estado['casos']['qa02']['huella_registrada']
