"""Mueve únicamente la asignación sintética y confirma el derecho usando la app."""
import argparse
from datetime import date

from sqlalchemy.orm import Session

import comun as c


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fecha', type=date.fromisoformat, help='Por omisión: fecha actual del laboratorio')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    permitidas = () if args.dry_run else c.permisos((c.DEMO, 'turnos_asignados', 'UPDATE'))
    with c.bloqueo_corrida(), c.entorno_seguro(permitidas) as (motor, huella, servidor):
        datos = c.leer_corrida(servidor)
        c.comprobar_base(datos, huella)
        refechar(motor, datos, args)


def refechar(motor, datos, args):
    with c.app_sin_dotenv(), c.reloj_laboratorio(datos) as reloj:
        from app.consultas.derecho import buscar_derecho
        fecha = args.fecha or reloj.hoy()
        if datos['estado'] != 'iniciada':
            raise c.Abortado("La corrida ya avanzó; limpiar antes de refechar de nuevo")
        if (c.CARPETA / 'api.activa').exists():
            raise c.Abortado("Detener API antes de refechar")
        with motor.begin() as conn:
            fila = c.fila_asignacion(conn, bloquear=not args.dry_run)
            if fila['fecha'].isoformat() != datos['fecha_original']:
                raise c.Abortado("Fecha actual distinta de la registrada al iniciar")
            print(f"Asignación {c.ASIGNACION}, usuario {c.USUARIO}: {fila['fecha']} -> {fecha}")
            if args.dry_run:
                print("Simulacro: sin UPDATE ni cambios en corrida.json; derecho destino se valida al aplicar")
                return
            datos.update(fecha_destino=fecha.isoformat(), estado='refechado_pendiente')
            c.guardar_corrida(datos)  # Diario previo al commit, incluso si este queda incierto.
            if fila['fecha'] != fecha:
                c.cambiar_fecha(conn, fila['fecha'], fecha)
            with Session(bind=conn) as sesion:
                derecho = buscar_derecho(sesion, c.USUARIO, c.COMIDA, fecha)
                if derecho is None or derecho.turno_asignado_id != c.ASIGNACION:
                    raise c.Abortado("Sin derecho al almuerzo por esta asignación; UPDATE revertido")
                print(f"Derecho confirmado por buscar_derecho: comida_id={derecho.comida_id}")
        datos['estado'] = 'refechada'
        c.guardar_corrida(datos)


if __name__ == '__main__':
    c.ejecutar(main)
