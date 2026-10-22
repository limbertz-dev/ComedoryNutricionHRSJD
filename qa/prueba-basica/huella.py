"""Ejecución de marcaciones QA mediante `registrar_marcacion` real, sin endpoint ficticio.

Soporta:
- Escenario de tres comensales (`version=2` en `corrida.json`), ejecutando por separado:
  a) `--caso qa01` (alias `--normal`): registro biométrico normal reconocido (`usuario_id=900101`),
     que inserta 1 lectura aceptada y 1 asistencia biométrica.
  b) `--caso qa02` (alias `--no-reconocida`): lectura biométrica no reconocida (`usuario_id=None`),
     que conserva `usuario_id=None` en `lecturas_biometricas` y deja `comensal_previsto_id=900102`
     en el diario/manifiesto para que `cocinera2` lo identifique después en el frontend.
- Compatibilidad con diarios v1 de un solo comensal.
"""

import argparse
import json

from sqlalchemy import event, text
from sqlalchemy.orm import Session

import comun as c


def permisos_caso(caso=None):
    if caso == "qa01":
        return c.permisos(
            (c.SIM, "lecturas_biometricas", "INSERT"),
            (c.SIM, "asistencias", "INSERT"),
        )
    return c.permisos((c.SIM, "lecturas_biometricas", "INSERT"))


def _resolver_argumento_caso(args):
    if getattr(args, "normal", False):
        return "qa01"
    if getattr(args, "no_reconocida", False):
        return "qa02"
    return getattr(args, "caso", None)


def _leer_v1(motor, datos):
    with c.app_sin_dotenv(), c.reloj_laboratorio(datos) as reloj:
        from app.consultas.derecho import buscar_derecho
        from app.consultas.servicio import VentanasDelDia, evaluar_servicio
        from app.esquemas.marcacion import RespuestaMarcacion
        from app.logica.marcacion import registrar_marcacion, resolver_comida_en_curso, ya_comio
        from app.modelos.comedor import LecturaBiometrica

        fecha = c.fecha_para_operar(datos, reloj.ahora())
        with Session(motor, expire_on_commit=False) as sesion:
            if sesion.execute(
                text("SELECT COUNT(*) FROM lecturas_biometricas WHERE dispositivo=:d"),
                {"d": c.DISPOSITIVO},
            ).scalar_one():
                raise c.Abortado("Hay una lectura de una corrida anterior")
            momento = reloj.ahora()
            comida = resolver_comida_en_curso(sesion, momento)
            if comida is None or comida.comida_id != c.comida_corrida(datos):
                raise c.Abortado(
                    "El almuerzo ya no está en curso; limpiar y abrir una corrida nueva con otra ancla"
                )
            if comida.fecha_comida != fecha:
                raise c.Abortado("La asignación no corresponde al almuerzo actual")
            derecho = buscar_derecho(sesion, c.USUARIO, comida.comida_id, comida.fecha_comida)
            if (
                derecho is None
                or derecho.turno_asignado_id != c.ASIGNACION
                or ya_comio(sesion, c.USUARIO, comida)
            ):
                raise c.Abortado("Sin derecho por esta asignación o ración ya entregada")
            evaluacion = evaluar_servicio(sesion, VentanasDelDia(sesion), momento, momento)
            if evaluacion.motivo is not None:
                raise c.Abortado("Servicio efectivo no determinable")
            datos.update(estado="lectura_pendiente", momento_lectura=momento.isoformat())
            c.guardar_corrida(datos)

            def recordar_id(sesion_flush, _contexto):
                nuevas = [obj for obj in sesion_flush.new if isinstance(obj, LecturaBiometrica)]
                if len(nuevas) != 1:
                    raise c.Abortado("Se esperaba exactamente una lectura")
                datos["lectura_id"] = nuevas[0].id
                c.guardar_corrida(datos)

            event.listen(sesion, "after_flush", recordar_id)
            resultado = registrar_marcacion(
                sesion,
                usuario_id=None,
                momento=momento,
                dispositivo=c.DISPOSITIVO,
                metodo="biometrico",
            )
            cuerpo = RespuestaMarcacion(**vars(resultado)).model_dump(mode="json")
            datos.update(
                estado="lectura_creada",
                lectura_id=resultado.lectura_id,
                respuesta=cuerpo,
            )
            c.guardar_corrida(datos)
            print(f"lectura_id={resultado.lectura_id}")
            print(json.dumps(cuerpo, ensure_ascii=False, indent=2))


def _leer_caso_multi(motor, datos, caso):
    if caso == "qa03":
        raise c.Abortado("El comensal qa03 está en reserva y no tiene caso ejecutable")
    if caso not in c.CASOS_EJECUTABLES:
        raise c.Abortado(
            "Indicar explícitamente el caso a ejecutar: --caso qa01 (normal) o --caso qa02 (no reconocida)"
        )
    with c.app_sin_dotenv(), c.reloj_laboratorio(datos) as reloj:
        from app.consultas.derecho import buscar_derecho
        from app.consultas.servicio import VentanasDelDia, evaluar_servicio
        from app.esquemas.marcacion import RespuestaMarcacion
        from app.logica.marcacion import registrar_marcacion, resolver_comida_en_curso, ya_comio
        from app.modelos.comedor import Asistencia, LecturaBiometrica

        fecha = c.fecha_para_operar(datos, reloj.ahora(), caso=caso)
        info_caso = datos["casos"][caso]
        previsto_id = info_caso["comensal_previsto_id"]
        asignacion_id = info_caso["asignacion_id"]
        usuario_marcacion = info_caso["usuario_id"]

        with Session(motor, expire_on_commit=False) as sesion:
            ids_registrados = c.ids_casos_corrida(datos)
            filas_disp = sesion.execute(
                text("SELECT id FROM lecturas_biometricas WHERE dispositivo=:d"),
                {"d": c.DISPOSITIVO},
            ).scalars().all()
            if set(filas_disp) != ids_registrados:
                raise c.Abortado("Hay una lectura de una corrida anterior o ajena")

            momento = reloj.ahora()
            comida = resolver_comida_en_curso(sesion, momento)
            if comida is None or comida.comida_id != c.comida_corrida(datos):
                raise c.Abortado(
                    "El almuerzo ya no está en curso; limpiar y abrir una corrida nueva con otra ancla"
                )
            if comida.fecha_comida != fecha:
                raise c.Abortado("La asignación no corresponde al almuerzo actual")
            derecho = buscar_derecho(
                sesion, previsto_id, comida.comida_id, comida.fecha_comida
            )
            if (
                derecho is None
                or derecho.turno_asignado_id != asignacion_id
                or ya_comio(sesion, previsto_id, comida)
            ):
                raise c.Abortado("Sin derecho por esta asignación o ración ya entregada")
            evaluacion = evaluar_servicio(sesion, VentanasDelDia(sesion), momento, momento)
            if evaluacion.motivo is not None:
                raise c.Abortado("Servicio efectivo no determinable")

            info_caso["estado"] = "lectura_pendiente"
            info_caso["momento_lectura"] = momento.isoformat()
            c.guardar_corrida(datos)

            def recordar_ids(sesion_flush, _contexto):
                nuevas_lecturas = [
                    obj for obj in sesion_flush.new if isinstance(obj, LecturaBiometrica)
                ]
                nuevas_asistencias = [
                    obj for obj in sesion_flush.new if isinstance(obj, Asistencia)
                ]
                if len(nuevas_lecturas) > 1 or len(nuevas_asistencias) > 1:
                    raise c.Abortado("Se esperaba como máximo una lectura y una asistencia")
                if nuevas_lecturas:
                    if info_caso["lectura_id"] is not None:
                        raise c.Abortado("Se intentó crear más de una lectura en el mismo caso")
                    info_caso["lectura_id"] = nuevas_lecturas[0].id
                if nuevas_asistencias:
                    if caso != "qa01":
                        raise c.Abortado(
                            "La lectura no reconocida no debe crear asistencia directamente"
                        )
                    info_caso["asistencia_id"] = nuevas_asistencias[0].id
                if nuevas_lecturas or nuevas_asistencias:
                    c.guardar_corrida(datos)

            event.listen(sesion, "after_flush", recordar_ids)
            resultado = registrar_marcacion(
                sesion,
                usuario_id=usuario_marcacion,
                momento=momento,
                dispositivo=c.DISPOSITIVO,
                metodo="biometrico",
            )
            cuerpo = RespuestaMarcacion(**vars(resultado)).model_dump(mode="json")

            if caso == "qa01":
                if (
                    not resultado.valido
                    or resultado.motivo is not None
                    or resultado.usuario_id != previsto_id
                    or resultado.lectura_id is None
                    or resultado.asistencia_id is None
                ):
                    raise c.Abortado("El registro normal de QA 01 no produjo lectura y asistencia válidas")
                info_caso.update(
                    estado="completado",
                    lectura_id=resultado.lectura_id,
                    asistencia_id=resultado.asistencia_id,
                    respuesta=cuerpo,
                )
            else:
                if (
                    resultado.valido
                    or resultado.motivo != "no_identificado"
                    or resultado.usuario_id is not None
                    or resultado.lectura_id is None
                    or resultado.asistencia_id is not None
                ):
                    raise c.Abortado(
                        "La lectura de QA 02 debe quedar rechazada con motivo no_identificado y usuario_id=None"
                    )
                info_caso.update(
                    estado="lectura_creada",
                    lectura_id=resultado.lectura_id,
                    asistencia_id=None,
                    respuesta=cuerpo,
                )

            datos["estado"] = "lectura_creada"
            c.guardar_corrida(datos)
            if caso == "qa01":
                print(
                    f"caso=qa01 lectura_id={resultado.lectura_id} "
                    f"asistencia_id={resultado.asistencia_id} usuario_id={previsto_id}"
                )
            else:
                print(
                    f"caso=qa02 lectura_id={resultado.lectura_id} "
                    f"usuario_id=None comensal_previsto_id={previsto_id}"
                )
            print(json.dumps(cuerpo, ensure_ascii=False, indent=2))


def leer(motor, datos, caso=None):
    if c.es_corrida_multi(datos):
        _leer_caso_multi(motor, datos, caso)
    else:
        if caso is not None:
            raise c.Abortado(
                "El diario actual es de versión 1 (un solo comensal); "
                "cerrar, limpiar y abrir corrida nueva para ejecutar casos múltiples"
            )
        _leer_v1(motor, datos)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--referencia', help='Referencia simulada enrolada por el operador; obligatoria desde el laboratorio')
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument(
        "--caso",
        choices=("qa01", "qa02", "qa03"),
        help="Caso del escenario a ejecutar: qa01 (normal) o qa02 (no reconocida); qa03 está en reserva",
    )
    grupo.add_argument(
        "--normal",
        action="store_true",
        help="Atajo para --caso qa01 (registro normal reconocido de QA 01)",
    )
    grupo.add_argument(
        "--no-reconocida",
        action="store_true",
        help="Atajo para --caso qa02 (lectura no reconocida prevista para QA 02)",
    )
    args = parser.parse_args(argv)
    caso = _resolver_argumento_caso(args)
    if caso == "qa03":
        raise c.Abortado("El comensal qa03 está en reserva y no tiene caso ejecutable")
    if args.referencia is not None:
        import enrolamiento
        if caso not in c.CASOS_EJECUTABLES or enrolamiento.resolver(args.referencia) != c.COMENSALES_QA[caso]['usuario_id']:
            raise c.Abortado('La referencia de huella no esta registrada para la persona de este caso.')
    with c.bloqueo_corrida(), c.entorno_seguro(permisos_caso(caso)) as (motor, huella, servidor):
        datos = c.leer_corrida(servidor)
        c.comprobar_base(datos, huella)
        leer(motor, datos, caso=caso)


if __name__ == "__main__":
    c.ejecutar(main)
