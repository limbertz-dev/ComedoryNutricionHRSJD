"""Baja lógica y permisos con SQL real offline; no conecta a MySQL."""
from datetime import datetime

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

import comun as c
from test_perfiles_lectura import circuito


def preparar(motor):
    with c.app_sin_dotenv():
        from app.modelos.usuarios import UsuarioSistema
        with Session(motor) as sesion:
            sesion.add(UsuarioSistema(id=1, username='root', nombre='Operador', rol='sistemas',
                password_hash='fixture-no-autenticable', activo=True, debe_cambiar=False, version_token=0))
            sesion.add(UsuarioSistema(id=3, username='historia', nombre='Registro asociado', rol='jefa',
                creada_por_cuenta=2, password_hash='fixture-no-autenticable', activo=True,
                debe_cambiar=False, version_token=0))
            sesion.commit()


def test_desactivar_permite_reactivar_y_eliminar_oculta_sin_borrar(circuito):
    motor, _ = circuito
    preparar(motor)
    with c.app_sin_dotenv():
        from app.logica import cuentas
        from app.modelos.usuarios import UsuarioSistema
        from app.core.autorizacion import cargar_usuario, ErrorAuth
        with Session(motor) as sesion:
            root = sesion.get(UsuarioSistema, 1)
            cuentas.cambiar_activo(sesion, 2, False, root)
            assert any(f['id'] == 2 and not f['activo'] for f in cuentas.listar_cuentas(sesion))
            cuentas.cambiar_activo(sesion, 2, True, root)
            objetivo = sesion.get(UsuarioSistema, 2)
            version = objetivo.version_token
            cuentas.eliminar_cuenta(sesion, 2, root)
            assert all(f['id'] != 2 for f in cuentas.listar_cuentas(sesion))
            assert objetivo.username == 'cocinera2' and not objetivo.activo
            assert isinstance(objetivo.eliminada_en, datetime)
            assert objetivo.version_token == version + 1
            assert sesion.get(UsuarioSistema, 3).creada_por_cuenta == 2
            with pytest.raises(ErrorAuth) as error:
                cargar_usuario(sesion, {'sub': '2', 'ver': version})
            assert error.value.status_code == 401
            marca = objetivo.eliminada_en
            cuentas.eliminar_cuenta(sesion, 2, root)
            assert objetivo.eliminada_en == marca and objetivo.version_token == version + 1
            with pytest.raises(cuentas.ErrorCuenta, match='eliminada'):
                cuentas.cambiar_activo(sesion, 2, True, root)
        with Session(motor) as sesion:
            assert sesion.get(UsuarioSistema, 2) is not None
            assert all(f['id'] != 2 for f in cuentas.listar_cuentas(sesion))


def test_eliminar_protege_cuenta_propia_ultima_sistemas_e_inexistente(circuito):
    motor, _ = circuito
    preparar(motor)
    with c.app_sin_dotenv():
        from app.logica import cuentas
        from app.modelos.usuarios import UsuarioSistema
        with Session(motor) as sesion:
            root = sesion.get(UsuarioSistema, 1)
            for uid, solicitante, motivo in ((1, root, 'no_puede_desactivarse_a_si_misma'),
                    (1, sesion.get(UsuarioSistema, 2), 'ultima_cuenta_sistemas'),
                    (999, root, 'cuenta_inexistente')):
                with pytest.raises(cuentas.ErrorCuenta) as error:
                    cuentas.eliminar_cuenta(sesion, uid, solicitante)
                assert error.value.motivo == motivo
                sesion.rollback()
            assert root.activo and root.eliminada_en is None


def test_delete_http_solo_sistemas_y_sin_borrado_fisico(circuito):
    motor, _ = circuito
    preparar(motor)
    with c.app_sin_dotenv():
        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient
        from app.api import admin
        from app.core.autorizacion import usuario_actual, requiere_rol
        from app.core.db import obtener_sesion
        from app.modelos.usuarios import UsuarioSistema
        app = FastAPI()
        app.include_router(admin.router, dependencies=[Depends(requiere_rol('sistemas'))])
        with Session(motor) as sesion:
            actual = sesion.get(UsuarioSistema, 2)
            app.dependency_overrides[obtener_sesion] = lambda: sesion
            app.dependency_overrides[usuario_actual] = lambda: actual
            with TestClient(app) as cliente:
                assert cliente.delete('/admin/cuentas/3').status_code == 403
                actual = sesion.get(UsuarioSistema, 1)
                respuesta = cliente.delete('/admin/cuentas/2')
                assert respuesta.status_code == 204 and respuesta.content == b''
                assert cliente.delete('/admin/cuentas/2').status_code == 204
                assert all(f['id'] != 2 for f in cliente.get('/admin/cuentas').json())
                assert sesion.get(UsuarioSistema, 2) is not None
                app.dependency_overrides.pop(usuario_actual)
                assert cliente.delete('/admin/cuentas/3').status_code == 401


def test_permiso_migracion_no_habilita_ddl_general():
    permitidas = {(c.SIM, 'usuarios_sistema', 'ADD_ELIMINADA_EN')}
    sql = 'ALTER TABLE usuarios_sistema ADD eliminada_en DATETIME'
    c.revisar_sql(sql, c.SIM, permitidas)
    for sentencia, base, permisos in (
        (sql, c.SIM, ()), (sql, c.PROTEGIDA, permitidas),
        ('ALTER TABLE usuarios_sistema DROP COLUMN nombre', c.SIM, permitidas),
        ('ALTER TABLE usuarios_sistema ADD otra DATETIME', c.SIM, permitidas),
        ('ALTER TABLE asistencias ADD eliminada_en DATETIME', c.SIM, permitidas),
    ):
        with pytest.raises(c.Abortado):
            c.revisar_sql(sentencia, base, permisos)


def test_alta_http_real_bajo_auditor_qa_y_rechazo_de_otros_destinos(circuito):
    motor, _ = circuito
    preparar(motor)
    import ejecutar_app
    permitidas = ejecutar_app.permisos_modo('api', laboratorio=True)

    def auditar(conn, cursor, sentencia, parametros, contexto, multiples):
        c.revisar_sql(sentencia, c.SIM, permitidas)

    with c.app_sin_dotenv():
        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient
        from app.api import admin
        from app.core.autorizacion import usuario_actual, requiere_rol
        from app.core.db import obtener_sesion
        from app.modelos.usuarios import UsuarioSistema
        app = FastAPI()
        app.include_router(admin.router, dependencies=[Depends(requiere_rol('sistemas'))])
        event.listen(motor, 'before_cursor_execute', auditar)
        try:
            with Session(motor) as sesion:
                actual = sesion.get(UsuarioSistema, 1)
                app.dependency_overrides[obtener_sesion] = lambda: sesion
                app.dependency_overrides[usuario_actual] = lambda: actual
                with TestClient(app) as cliente:
                    respuesta = cliente.post('/admin/cuentas', json={
                        'username': 'cocinera4', 'nombre': 'Sandra Lima', 'rol': 'cocinera',
                        'password': 'clave-solo-fixture',
                    })
                    assert respuesta.status_code == 201, respuesta.text
                    nueva = respuesta.json()['cuenta']
                    assert nueva['nombre'] == 'Sandra Lima' and nueva['activo']
                    assert not nueva['debe_cambiar']
                    assert any(f['id'] == nueva['id'] for f in cliente.get('/admin/cuentas').json())
        finally:
            event.remove(motor, 'before_cursor_execute', auditar)
    for base, sql in ((c.PROTEGIDA, 'INSERT INTO usuarios_sistema (id) VALUES (1)'),
                      (c.SIM, 'DELETE FROM usuarios_sistema WHERE id=1'),
                      (c.SIM, 'INSERT INTO tabla_ajena (id) VALUES (1)')):
        with pytest.raises(c.Abortado):
            c.revisar_sql(sql, base, permitidas)


def test_bloqueo_auditor_responde_http_con_cors_sin_detalles_internos():
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.testclient import TestClient
    import ejecutar_app
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=['http://127.0.0.1:5173'])
    ejecutar_app.instalar_errores_auditor(app)

    @app.get('/bloqueada')
    def bloqueada():
        raise c.Abortado('detalle-interno-no-publicable')

    with TestClient(app) as cliente:
        respuesta = cliente.get('/bloqueada', headers={'Origin': 'http://127.0.0.1:5173'})
        assert respuesta.status_code == 500
        assert respuesta.headers['access-control-allow-origin'] == 'http://127.0.0.1:5173'
        assert respuesta.json()['motivo'] == 'operacion_bloqueada_qa'
        assert 'detalle-interno' not in respuesta.text


def test_editar_cuenta_http_con_auditor_permisos_validacion_e_historial(circuito):
    motor, _ = circuito
    preparar(motor)
    import ejecutar_app
    permitidas = ejecutar_app.permisos_modo('api', laboratorio=True)

    def auditar(conn, cursor, sentencia, parametros, contexto, multiples):
        c.revisar_sql(sentencia, c.SIM, permitidas)

    with c.app_sin_dotenv():
        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient
        from app.api import admin
        from app.core.autorizacion import usuario_actual, requiere_rol
        from app.core.db import obtener_sesion
        from app.modelos.usuarios import UsuarioSistema
        app = FastAPI()
        app.include_router(admin.router, dependencies=[Depends(requiere_rol('sistemas'))])
        event.listen(motor, 'before_cursor_execute', auditar)
        try:
            with Session(motor) as sesion:
                actual = sesion.get(UsuarioSistema, 1)
                cuenta = sesion.get(UsuarioSistema, 2)
                clave = cuenta.password_hash
                app.dependency_overrides[obtener_sesion] = lambda: sesion
                app.dependency_overrides[usuario_actual] = lambda: actual
                with TestClient(app) as cliente:
                    res = cliente.patch('/admin/cuentas/2', json={'nombre': '  Sandra Lima  '})
                    assert res.status_code == 200, res.text
                    assert res.json()['nombre'] == 'Sandra Lima'
                    assert cuenta.version_token == 0
                    res = cliente.patch('/admin/cuentas/2', json={'rol': 'jefa'})
                    assert res.status_code == 200 and res.json()['rol'] == 'jefa'
                    assert cuenta.version_token == 1
                    assert cuenta.username == 'cocinera2' and cuenta.password_hash == clave
                    assert sesion.get(UsuarioSistema, 3).creada_por_cuenta == 2
                    assert cliente.patch('/admin/cuentas/2', json={'rol': 'jefa'}).status_code == 200
                    assert cuenta.version_token == 1  # reenvío sin invalidar de nuevo
                    assert cliente.patch('/admin/cuentas/2', json={'nombre': 'Otro', 'rol': 'sistemas'}).status_code == 422
                    assert cuenta.nombre == 'Sandra Lima' and cuenta.rol == 'jefa'
                    assert cliente.patch('/admin/cuentas/1', json={'rol': 'jefa'}).status_code == 409
                    assert cliente.patch('/admin/cuentas/1', json={'nombre': 'Operador root'}).status_code == 200
                    assert actual.rol == 'sistemas'
                    for cuerpo in ({}, {'nombre': '   '}, {'nombre': None}, {'rol': None},
                                   {'nombre': 'a' * 101}, {'username': 'otro'}, {'activo': False}):
                        assert cliente.patch('/admin/cuentas/2', json=cuerpo).status_code == 422
                    assert cliente.patch('/admin/cuentas/999', json={'nombre': 'Otro'}).status_code == 404
                    cuenta.usuario_turnos_id = 900101
                    sesion.commit()
                    assert cliente.patch('/admin/cuentas/2', json={'nombre': 'Otro', 'rol': 'cocinera'}).status_code == 409
                    assert cuenta.nombre == 'Sandra Lima' and cuenta.rol == 'jefa'
                    assert cliente.delete('/admin/cuentas/2').status_code == 204
                    assert cliente.patch('/admin/cuentas/2', json={'rol': 'cocinera'}).status_code == 409
                    actual = sesion.get(UsuarioSistema, 3)
                    assert cliente.patch('/admin/cuentas/1', json={'nombre': 'Otro'}).status_code == 403
                    app.dependency_overrides.pop(usuario_actual)
                    assert cliente.patch('/admin/cuentas/1', json={'nombre': 'Otro'}).status_code == 401
        finally:
            event.remove(motor, 'before_cursor_execute', auditar)
