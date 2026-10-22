"""Recupera una referencia perdida usando ID y momento explicitos; nunca borra filas."""
import argparse
from datetime import datetime
from sqlalchemy import text
import comun as c
import limpiar


def recuperar(conn, datos, lectura_id, comida_id, momento):
    lectura = conn.execute(text('SELECT id,usuario_id,dispositivo,fecha_hora,resultado,motivo FROM lecturas_biometricas WHERE id=:id'), {'id': lectura_id}).mappings().one_or_none()
    if (lectura is None or lectura['usuario_id'] is not None or lectura['dispositivo'] != c.DISPOSITIVO
            or lectura['resultado'] != 'rechazada' or lectura['motivo'] != 'no_identificado'
            or datetime.fromisoformat(str(lectura['fecha_hora'])) != momento
            or momento.date().isoformat() != (datos.get('fecha_destino') or datos['fecha_original'])):
        raise c.Abortado('La lectura explicita no corresponde al caso QA 02 esperado; diario intacto.')
    with c.app_sin_dotenv():
        from sqlalchemy.orm import Session
        from app.logica.marcacion import resolver_comida_en_curso
        with Session(bind=conn) as sesion:
            servicio = resolver_comida_en_curso(sesion, momento)
            if servicio is None or servicio.comida_id != comida_id:
                raise c.Abortado('La comida indicada no corresponde al horario de la lectura.')
    c.seleccionar_servicio(datos, c.comida_corrida(datos))
    casos = datos['casos_por_comida'].setdefault(str(comida_id), c.casos_iniciales_diario(comida_id))
    info = casos['qa02']
    if info.get('lectura_id') not in {None, lectura_id}:
        raise c.Abortado('El caso ya tiene otra lectura; no se reemplaza.')
    info.update(lectura_id=lectura_id, momento_lectura=momento.isoformat(), estado='lectura_creada')
    asistencias = conn.execute(text('SELECT id FROM asistencias WHERE lectura_id=:id'), {'id': lectura_id}).all()
    if len(asistencias) == 1:
        info.update(asistencia_id=asistencias[0][0], estado='completado')
    if comida_id == c.comida_corrida(datos):
        datos['casos'] = casos
    # Comprueba todas las lecturas, asistencias e intervenciones de la corrida,
    # incluyendo atribucion, comida, turno, duplicados y filas ajenas.
    limpiar._comprobar_propiedad_multi(conn, datos, datos['cuentas'], False)
    datos.setdefault('recuperaciones_diario', []).append({
        'caso': 'qa02', 'lectura_id': lectura_id, 'comida_id': comida_id,
        'momento_lectura': momento.isoformat(), 'momento_real': datetime.now().isoformat(),
        'motivo': 'referencia_perdida_al_cambiar_servicio',
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lectura', type=int, required=True)
    parser.add_argument('--comida', type=int, choices=[1, 2, 3, 4], required=True)
    parser.add_argument('--momento', type=datetime.fromisoformat, required=True)
    parser.add_argument('--aplicar', action='store_true')
    args = parser.parse_args()
    if (c.CARPETA / 'api.activa').exists():
        raise c.Abortado('Detener la API QA antes de recuperar el diario.')
    with c.bloqueo_corrida(), c.entorno_seguro() as (motor, huella, servidor):
        datos = c.leer_corrida(servidor)
        c.comprobar_base(datos, huella)
        with motor.connect() as conn:
            recuperar(conn, datos, args.lectura, args.comida, args.momento)
        if args.aplicar:
            respaldo = c.CARPETA / 'evidencias' / (datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '-diario-antes-recuperacion.json')
            respaldo.parent.mkdir(exist_ok=True)
            respaldo.write_bytes(c.CORRIDA.read_bytes())
            c.guardar_corrida(datos)
        print('Diario recuperado; filas de base intactas.' if args.aplicar else 'Simulacro: propiedad comprobada; diario y base intactos.')


if __name__ == '__main__':
    c.ejecutar(main)
