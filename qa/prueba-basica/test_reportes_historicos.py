"""Regresiones de historial: catalogos desactivados, clasificacion y periodos."""
from datetime import date
import json

import pytest
from reportes_historicos_offline import escenario, informes, generar, verificar
import comun as c


def test_los_cuatro_reportes_conservan_historia_con_categoria_y_comida_inactivas():
    with c.app_sin_dotenv():
        datos = generar()
        assert datos['aprobado']
        mixto = next(g for g in datos['antes']['mixto']['grupos'] if g['grupo'] == 'Almuerzo')
        assert mixto['coeficientes_mixtos'] and mixto['servidas'] == 4 and mixto['equivalente'] == 4.2


def test_no_arrastra_categorias_inactivas_de_otros_periodos_y_conserva_clasificacion():
    with c.app_sin_dotenv():
        from app.modelos.comedor import CategoriaReporte, CategoriaReporteMap
        from app.consultas import informes as consultas
        with escenario() as sesion:
            inicial = informes(sesion)
            assert 'Categoria antigua' not in inicial['diario']['categorias']
            pasado = consultas.registro_diario(sesion,2025,9)
            assert pasado.total_general == 1 and 'Categoria antigua' in pasado.categorias
            sesion.add(CategoriaReporteMap(categoria_id=9001, categoria_reporte_id=2))
            sesion.get(CategoriaReporte,1).activo = False
            sesion.commit()
            assert inicial == informes(sesion)


def test_reactivar_tampoco_duplica_raciones_y_rango_vacio_no_inventa_historia():
    with c.app_sin_dotenv():
        from app.modelos.comedor import CategoriaReporte
        from app.modelos.heredados import Comida
        from app.consultas import informes as consultas
        with escenario() as sesion:
            inicial = informes(sesion)
            for activo in (False,True,False,True):
                sesion.get(CategoriaReporte,1).activo = activo
                sesion.get(Comida,2).estado = activo
                sesion.commit()
                assert inicial == informes(sesion)
            assert consultas.informe_rango(sesion,date(2024,1,1),date(2024,1,31)).total_general == 0


def test_verificacion_detecta_archivo_editado(tmp_path):
    import hashlib
    archivo = tmp_path/'reporte.json'
    archivo.write_text('{"total":6}')
    (tmp_path/'sha256.json').write_text(json.dumps({'reporte.json':hashlib.sha256(archivo.read_bytes()).hexdigest()}))
    assert verificar(tmp_path) == 1
    archivo.write_text('{"total":0}')
    with pytest.raises(c.Abortado,match='modificado'):
        verificar(tmp_path)
