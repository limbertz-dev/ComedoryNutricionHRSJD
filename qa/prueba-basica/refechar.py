"""Mueve únicamente las asignaciones sintéticas del escenario y confirma el derecho usando la app."""
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
        if c.es_corrida_multi(datos):
            c.validar_casos_diario(datos)
            if any(
                info['estado'] != 'pendiente' or info['lectura_id'] is not None
                for info in datos['casos'].values()
            ):
                raise c.Abortado("La corrida ya tiene casos iniciados; limpiar antes de refechar")
        if (c.CARPETA / 'api.activa').exists():
            raise c.Abortado("Detener API antes de refechar")
        with motor.begin() as conn:
            fila = c.filas_asignaciones_corrida(conn, datos, bloquear=not args.dry_run)
            if fila['fecha'].isoformat() != datos['fecha_original']:
                raise c.Abortado("Fecha actual distinta de la registrada al iniciar")
            if c.es_corrida_multi(datos):
                for codigo, spec in c.COMENSALES_QA.items():
                    print(
                        f"Asignación {spec['asignacion_id']} ({codigo}, usuario {spec['usuario_id']}): "
                        f"{fila['fecha']} -> {fecha}"
                    )
            else:
                print(f"Asignación {c.ASIGNACION}, usuario {c.USUARIO}: {fila['fecha']} -> {fecha}")
            if args.dry_run:
                print("Simulacro: sin UPDATE ni cambios en corrida.json; derecho destino se valida al aplicar")
                return
            datos.update(fecha_destino=fecha.isoformat(), estado='refechado_pendiente')
            c.guardar_corrida(datos)  # Diario previo al commit, incluso si este queda incierto.
            if fila['fecha'] != fecha:
                c.cambiar_fecha_corrida(conn, datos, fila['fecha'], fecha)
            with Session(bind=conn) as sesion:
                if c.es_corrida_multi(datos):
                    for codigo, spec in c.COMENSALES_QA.items():
                        derecho = buscar_derecho(sesion, spec['usuario_id'], c.comida_corrida(datos), fecha)
                        if derecho is None or derecho.turno_asignado_id != spec['asignacion_id']:
                            raise c.Abortado(
                                f"Sin derecho al almuerzo para {codigo}; UPDATE revertido"
                            )
                        print(
                            f"Derecho confirmado por buscar_derecho ({codigo}): "
                            f"comida_id={derecho.comida_id}"
                        )
                else:
                    derecho = buscar_derecho(sesion, c.USUARIO, c.comida_corrida(datos), fecha)
                    if derecho is None or derecho.turno_asignado_id != c.ASIGNACION:
                        raise c.Abortado("Sin derecho al almuerzo por esta asignación; UPDATE revertido")
                    print(f"Derecho confirmado por buscar_derecho: comida_id={derecho.comida_id}")
        datos['estado'] = 'refechada'
        c.guardar_corrida(datos)


if __name__ == '__main__':
    c.ejecutar(main)
