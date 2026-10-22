"""Horario de referencia y conservacion de casos entre comidas, con SQL real."""
import copy
from datetime import datetime, date, time
from unittest.mock import patch
from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
import comun as c
from test_perfiles_lectura import circuito


@pytest.mark.parametrize('hora,comida,dia', [
    ('00:00',4,14), ('05:30',4,14), ('07:00',1,15), ('09:00',1,15), ('10:30',1,15),
    ('11:00',2,15), ('15:00',2,15), ('16:00',3,15), ('18:00',3,15),
    ('19:00',4,15), ('22:00',4,15), ('23:59',4,15),
])
def test_comida_vigente_o_ultima_cerrada(circuito, hora, comida, dia):
    motor, _ = circuito
    with c.app_sin_dotenv():
        from app.consultas.servicio import comida_de_referencia
        from app.consultas.pantalla import estado
        from app.logica.marcacion import resolver_comida_en_curso
        momento = datetime.fromisoformat(f'2026-10-15T{hora}:00')
        with Session(motor) as sesion:
            referencia = comida_de_referencia(sesion, momento)
            assert referencia.comida_id == comida and referencia.fecha_comida == date(2026,10,dia)
            pantalla = estado(sesion, momento=momento)
            assert pantalla.comida_id == comida and pantalla.fecha_comida == referencia.fecha_comida
            assert pantalla.fuera_de_horario == (resolver_comida_en_curso(sesion, momento) is None)


def test_referencia_cruce_medianoche_y_version_cerrada_hace_semanas(circuito):
    motor, _ = circuito
    with c.app_sin_dotenv():
        from app.consultas.servicio import comida_de_referencia
        from app.modelos.comedor import HorarioComida
        with Session(motor) as sesion:
            cena = sesion.get(HorarioComida,4)
            cena.hora_inicio, cena.hora_fin = time(22), time(2)
            sesion.commit()
            for hora in (1,3):
                referencia = comida_de_referencia(sesion,datetime(2026,10,15,hora))
                assert referencia.comida_id == 4 and referencia.fecha_comida == date(2026,10,14)
            for horario in sesion.query(HorarioComida):
                if horario.id != 4:
                    horario.activo = False
            cena.vigente_hasta = datetime(2026,10,1,12)
            sesion.commit()
            referencia = comida_de_referencia(sesion,datetime(2026,10,15,10))
            assert referencia.comida_id == 4 and referencia.fecha_comida == date(2026,9,30)


def test_cambiar_servicio_conserva_ids_y_revision_sin_aprobar_otro(circuito):
    datos = c.leer_corrida('srv')
    datos['casos']['qa02'].update(lectura_id=67,momento_lectura='2026-10-15T12:00:00',estado='lectura_creada')
    datos['revision_operador'] = {'qa02': {'resultado':'aprobado'}}
    c.seleccionar_servicio(datos,3)
    assert datos['casos']['qa02']['lectura_id'] is None and not datos['revision_operador']
    c.guardar_corrida(datos)
    datos = c.leer_corrida('srv')
    c.validar_casos_diario(datos)
    c.seleccionar_servicio(datos,4)
    c.guardar_corrida(datos)
    c.seleccionar_servicio(datos,2)
    assert datos['casos']['qa02']['lectura_id'] == 67
    assert datos['revision_operador']['qa02']['resultado'] == 'aprobado'
    assert c.ids_casos_corrida(datos) == {67}
    alterado = copy.deepcopy(datos)
    alterado['casos_por_comida']['3']['qa02'].update(lectura_id=67,estado='lectura_creada')
    with pytest.raises(c.Abortado,match='repetida'):
        c.validar_casos_diario(alterado)


def test_reinicio_api_en_otra_comida_con_casos_anteriores(circuito):
    datos = c.leer_corrida('srv')
    datos.update(estado='lectura_creada', fecha_original='2026-10-15')
    datos['casos']['qa02'].update(lectura_id=67, momento_lectura='2026-10-15T12:00:00', estado='lectura_creada')
    c.seleccionar_servicio(datos, 4)
    c.guardar_corrida(datos)
    datos = c.leer_corrida('srv')
    c.fecha_para_operar(datos, datetime(2026,10,15,19), permitir_lectura=True)
    assert datos['casos_por_comida']['2']['qa02']['lectura_id'] == 67


@pytest.mark.parametrize('duracion,permitido', [(8,False), (11,False), (12,True)])
def test_duracion_del_turno_no_se_elude_con_huella_o_cocinera(circuito, duracion, permitido):
    import enrolamiento, lector_enrolado
    motor, momento = circuito
    with c.app_sin_dotenv():
        from sqlalchemy import update
        from app.modelos.heredados import ComidaPorTurno
        from app.logica.marcacion import registrar_marcacion
        from app.logica.intervencion import identificar_lectura
        from app.core import reloj
        with Session(motor) as sesion:
            sesion.execute(update(ComidaPorTurno).where(ComidaPorTurno.usuario_id == 900101).values(duracion_horas=duracion))
            sesion.commit()
        referencia = enrolamiento.registrar(900101,2,str(uuid4()))['referencia']
        respuesta = lector_enrolado.procesar(motor,'srv',{},2,referencia,str(uuid4()))
        assert respuesta['valido'] is permitido
        assert respuesta['motivo'] == (None if permitido else 'sin_derecho')
        if permitido:
            return
        with Session(motor) as sesion:
            lectura = registrar_marcacion(sesion,usuario_id=None,momento=momento.valor)
            with patch.object(reloj,'ahora',return_value=momento.valor):
                manual = identificar_lectura(sesion,cuenta_id=2,lectura_id=lectura.lectura_id,usuario_id=900101,clave=str(uuid4()))
            assert not manual.valido and manual.motivo == 'sin_derecho'
            assert sesion.scalar(text('SELECT COUNT(*) FROM asistencias')) == 0
            assert sesion.scalar(text('SELECT resultado FROM intervenciones_lectura')) == 'rechazada'


def test_recuperacion_explicita_y_limpieza_multiservicio_no_borran_ajenos(circuito, monkeypatch):
    import enrolamiento, lector_enrolado, recuperar_diario_caso, limpiar
    motor, reloj_fixture = circuito
    referencia = enrolamiento.registrar(900101,2,str(uuid4()))['referencia']
    reloj_fixture.valor = datetime(2026,10,15,8)
    lector_enrolado.procesar(motor,'srv',{},2,referencia,str(uuid4()))
    with c.app_sin_dotenv():
        from app.logica.marcacion import registrar_marcacion
        from app.logica.intervencion import identificar_lectura
        from app.core import reloj
        with Session(motor) as sesion:
            momento = datetime(2026,10,15,12)
            lectura = registrar_marcacion(sesion,usuario_id=None,momento=momento,dispositivo=c.DISPOSITIVO)
            with patch.object(reloj,'ahora',return_value=momento):
                entrega = identificar_lectura(sesion,cuenta_id=2,lectura_id=lectura.lectura_id,usuario_id=900102,clave=str(uuid4()))
            assert entrega.valido
    datos = c.leer_corrida('srv')
    datos['fecha_original'] = '2026-10-15'
    c.seleccionar_servicio(datos,4)
    monkeypatch.setattr(c,'existe_tabla',lambda *_:False)
    with motor.begin() as conn:
        with pytest.raises(c.Abortado,match='ajena'):
            limpiar._comprobar_propiedad_multi(conn,datos,datos['cuentas'],False)
        recuperar_diario_caso.recuperar(conn,datos,lectura.lectura_id,2,momento)
        assert datos['casos_por_comida']['2']['qa02']['asistencia_id'] == entrega.asistencia_id
        c.guardar_corrida(datos)
        datos = c.leer_corrida('srv')
        limpiar._comprobar_propiedad_multi(conn,datos,datos['cuentas'],False)
        conn.execute(text("INSERT INTO lecturas_biometricas(id,usuario_id,dispositivo,fecha_hora,resultado,motivo) VALUES (999,777,'ajeno','2026-10-15 12:00:00','rechazada','sin_derecho')"))
        filtros,params = limpiar.objetivos(conn,datos)
        for tabla,filtro in filtros:
            conn.execute(text(f'DELETE FROM {tabla} WHERE {filtro}'),params)
        assert conn.scalar(text('SELECT COUNT(*) FROM asistencias')) == 0
        assert conn.scalar(text('SELECT id FROM lecturas_biometricas')) == 999
