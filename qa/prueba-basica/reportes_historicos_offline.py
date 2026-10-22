"""Comprobacion de informes con SQL real offline y datos sinteticos."""
import argparse
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import Integer, MetaData, create_engine, func, select
from sqlalchemy.orm import Session
import comun as c


@contextmanager
def escenario():
    with c.app_sin_dotenv():
        from app.core.db import Base, BaseContrato
        from app.modelos import comedor, heredados, reglas, usuarios
        metadata = MetaData()
        for original in [*Base.metadata.tables.values(), *BaseContrato.metadata.tables.values()]:
            tabla = original.to_metadata(metadata)
            for columna in tabla.columns:
                columna.type = columna.type.as_generic()
                if columna.primary_key and isinstance(columna.type, Integer):
                    columna.type = Integer()
        motor = create_engine('sqlite:///:memory:')
        metadata.create_all(motor)
        try:
            with Session(motor) as sesion:
                for cid, nombre in [(1, 'Medicos'), (2, 'Tecnicos'), (3, 'Sin clasificar'), (4, 'Categoria antigua')]:
                    sesion.add(comedor.CategoriaReporte(id=cid, nombre=nombre,
                        codigo='sin_clasificar' if cid == 3 else f'categoria_{cid}', orden=cid, activo=cid != 4))
                sesion.add(usuarios.UsuarioSistema(id=2, username='cocinera_offline', rol='cocinera',
                    password_hash='fixture-no-autenticable', debe_cambiar=False, activo=True))
                for cid, nombre, coef in [(1,'Desayuno',.5),(2,'Almuerzo',1),(3,'Te',.25),(4,'Cena',1)]:
                    sesion.add(heredados.Comida(id=cid, nombre=nombre, codigo=nombre.lower(), estado=True))
                    sesion.add(comedor.CoeficienteRacion(id=cid, comida_id=cid, coeficiente=coef,
                        vigente_desde=date(2000,1,1), vigente_hasta=date(2026,9,30) if cid == 2 else None))
                sesion.add(comedor.CoeficienteRacion(id=5, comida_id=2, coeficiente=1.2,
                    vigente_desde=date(2026,10,1)))
                filas = [('2026-09-01',1,1),('2026-09-01',2,1),('2026-09-01',2,2),
                         ('2026-09-15',2,1),('2026-09-15',3,3),('2026-09-15',4,2),
                         ('2026-10-02',2,1),('2026-10-02',4,2),('2025-09-03',2,4)]
                for aid, (dia, comida, categoria) in enumerate(filas, 1):
                    sesion.add(comedor.Asistencia(id=aid, usuario_id=900000+categoria,
                        fecha_comida=date.fromisoformat(dia), comida_id=comida, categoria_reporte_id=categoria,
                        servicio_id=9001, turno_asignado_id=9001, metodo='manual' if aid == 3 else 'biometrico',
                        registrado_por_cuenta=2 if aid == 3 else None, lectura_id=None,
                        fecha_hora=datetime.fromisoformat(dia+'T12:00:00')))
                sesion.add_all([
                    comedor.LecturaBiometrica(id=900, usuario_id=None, fecha_hora=datetime(2026,9,1,12),
                        resultado='rechazada', motivo='no_identificado', dispositivo='fixture-offline'),
                    comedor.LecturaBiometrica(id=901, usuario_id=900001, fecha_hora=datetime(2026,9,1,12),
                        resultado='rechazada', motivo='duplicado', dispositivo='fixture-offline'),
                ])
                sesion.commit()
                yield sesion
        finally:
            motor.dispose()


def informes(sesion):
    from app.consultas import informes as consultas
    from app.core import reloj
    with patch.object(reloj, 'hoy', return_value=date(2026,10,20)):
        return {nombre: asdict(valor) for nombre, valor in {
            'diario': consultas.registro_diario(sesion,2026,9),
            'mensual': consultas.informe_mensual(sesion,2026,9),
            'gestion': consultas.resumen_gestion(sesion,2026),
            'rango': consultas.informe_rango(sesion,date(2026,9,1),date(2026,9,30)),
            'mixto': consultas.informe_rango(sesion,date(2026,9,1),date(2026,10,31)),
        }.items()}


def generar():
    from app.modelos.comedor import CategoriaReporte, Asistencia
    from app.modelos.heredados import Comida
    with escenario() as sesion:
        antes = informes(sesion)
        sesion.get(CategoriaReporte,1).activo = False
        sesion.commit()
        categoria = informes(sesion)
        sesion.get(Comida,2).estado = False
        sesion.commit()
        ambos = informes(sesion)
        assert antes == categoria == ambos, 'Los informes cambiaron al desactivar catalogos usados.'
        for nombre, informe in antes.items():
            esperado = 8 if nombre in ('gestion','mixto') else 6
            assert informe['total_general'] == esperado
            assert sum(f['total'] for f in informe['filas']) == esperado
            assert sum(informe['totales_por_categoria']) == esperado
        assert antes['mensual']['total_equivalente'] == 4.75
        assert antes['mixto']['total_equivalente'] == 6.95
        assert sesion.scalar(select(func.count()).select_from(Asistencia)) == 9
        return {'origen': 'SQL real sobre SQLite en memoria; datos sinteticos; sin MySQL ni dotenv',
                'aprobado': True, 'antes': antes, 'categoria_inactiva': categoria, 'ambos_inactivos': ambos}


def guardar(destino):
    destino = Path(destino).resolve()
    destino.relative_to((c.CARPETA/'evidencias').resolve())
    destino.mkdir(parents=True, exist_ok=False)
    with c.app_sin_dotenv():
        resultado = generar()
    archivo = destino/'datos.json'
    archivo.write_text(json.dumps(resultado, default=lambda v: v.isoformat(), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return destino


def verificar(carpeta):
    carpeta = Path(carpeta).resolve()
    manifiesto = json.loads((carpeta/'sha256.json').read_text(encoding='utf-8'))
    if not manifiesto:
        raise c.Abortado('Manifiesto vacio.')
    for nombre, esperado in manifiesto.items():
        archivo = (carpeta/nombre).resolve()
        archivo.relative_to(carpeta)
        if hashlib.sha256(archivo.read_bytes()).hexdigest() != esperado:
            raise c.Abortado(f'Archivo modificado: {nombre}')
    return len(manifiesto)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--salida')
    parser.add_argument('--verificar')
    args = parser.parse_args()
    if args.verificar:
        print('Integridad correcta:',verificar(args.verificar),'archivos')
    else:
        carpeta = args.salida or c.CARPETA/'evidencias'/('reportes-offline-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        print(guardar(carpeta))


if __name__ == '__main__':
    main()
