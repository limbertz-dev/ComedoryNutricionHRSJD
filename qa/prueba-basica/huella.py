"""UNA lectura no reconocida, por registrar_marcacion; sin endpoint ficticio."""
import json

from sqlalchemy import event, text
from sqlalchemy.orm import Session

import comun as c


def main():
    with c.bloqueo_corrida(), c.entorno_seguro(c.permisos(
        (c.SIM, 'lecturas_biometricas', 'INSERT')
    )) as (motor, huella, servidor):
        datos = c.leer_corrida(servidor)
        c.comprobar_base(datos, huella)
        leer(motor, datos)


def leer(motor, datos):
    with c.app_sin_dotenv(), c.reloj_laboratorio(datos) as reloj:
        from app.consultas.derecho import buscar_derecho
        from app.consultas.servicio import VentanasDelDia, evaluar_servicio
        from app.esquemas.marcacion import RespuestaMarcacion
        from app.logica.marcacion import registrar_marcacion, resolver_comida_en_curso, ya_comio
        from app.modelos.comedor import LecturaBiometrica
        fecha = c.fecha_para_operar(datos, reloj.ahora())
        with Session(motor, expire_on_commit=False) as sesion:
            # Incluye lecturas resueltas: no se inicia otra corrida sin limpiar la anterior.
            if sesion.execute(text("SELECT COUNT(*) FROM lecturas_biometricas WHERE dispositivo=:d"),
                              {'d': c.DISPOSITIVO}).scalar_one():
                raise c.Abortado("Hay una lectura de una corrida anterior")
            momento = reloj.ahora()
            comida = resolver_comida_en_curso(sesion, momento)
            if comida is None or comida.comida_id != c.COMIDA:
                raise c.Abortado("El laboratorio está fuera del almuerzo; "
                                 "limpiar y abrir una corrida nueva con otra ancla")
            if comida.fecha_comida != fecha:
                raise c.Abortado("La asignación no corresponde al almuerzo actual")
            derecho = buscar_derecho(sesion, c.USUARIO, comida.comida_id, comida.fecha_comida)
            if derecho is None or derecho.turno_asignado_id != c.ASIGNACION or ya_comio(sesion, c.USUARIO, comida):
                raise c.Abortado("Sin derecho por esta asignación o ración ya entregada")
            evaluacion = evaluar_servicio(sesion, VentanasDelDia(sesion), momento, momento)
            if evaluacion.motivo is not None:
                raise c.Abortado("Servicio efectivo no determinable")
            datos.update(estado='lectura_pendiente', momento_lectura=momento.isoformat())
            c.guardar_corrida(datos)

            def recordar_id(sesion_flush, contexto):
                nuevas = [obj for obj in sesion_flush.new if isinstance(obj, LecturaBiometrica)]
                if len(nuevas) != 1:
                    raise c.Abortado("Se esperaba exactamente una lectura")
                datos['lectura_id'] = nuevas[0].id
                c.guardar_corrida(datos)  # Tras flush, ANTES del commit interno de la app.

            event.listen(sesion, 'after_flush', recordar_id)
            resultado = registrar_marcacion(sesion, usuario_id=None, momento=momento,
                                            dispositivo=c.DISPOSITIVO, metodo='biometrico')
            cuerpo = RespuestaMarcacion(**vars(resultado)).model_dump(mode='json')
            datos.update(estado='lectura_creada', lectura_id=resultado.lectura_id, respuesta=cuerpo)
            c.guardar_corrida(datos)
            print(f"lectura_id={resultado.lectura_id}")
            print(json.dumps(cuerpo, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    c.ejecutar(main)
