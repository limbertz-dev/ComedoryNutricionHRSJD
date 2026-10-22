"""Caso QA «Policía»: una huella de policía leída por el lector, con la hora del laboratorio.

Usa la MISMA lógica que el lector real (app/logica/lector.registrar_lectura):
la huella `qa-policia` está vinculada como `tipo='policia'` (sin persona del
padrón) y cada lectura es una ración con vía libre en la columna Policías,
siempre que haya una comida en curso según el reloj del laboratorio.

    python -B qa/prueba-basica/policia_qa.py --leer       (una lectura)
    python -B qa/prueba-basica/policia_qa.py --limpiar    (borra las del laboratorio)

El vínculo `qa-policia` se crea la primera vez y se conserva entre ensayos,
como las huellas de QA 01 y QA 02. `--limpiar` borra solo las raciones y los
envíos de este lector de laboratorio; no toca nada del personal.
"""

import argparse
import json
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

import comun as c

DISPOSITIVO = "lector-laboratorio-qa"
IDENTIFICADOR = "qa-policia"


def permisos(limpiar: bool):
    if limpiar:
        return c.permisos((c.SIM, "raciones_policia", "DELETE"), (c.SIM, "solicitudes_lector", "DELETE"))
    return c.permisos((c.SIM, "vinculos_lector", "INSERT"), (c.SIM, "raciones_policia", "INSERT"),
                      (c.SIM, "solicitudes_lector", "INSERT"))


def asegurar_vinculo(conn) -> None:
    fila = conn.execute(text(
        "SELECT tipo, activo FROM vinculos_lector WHERE identificador=:i"), {"i": IDENTIFICADOR}).one_or_none()
    if fila is None:
        conn.execute(text(
            "INSERT INTO vinculos_lector (identificador, tipo, usuario_id, activo) "
            "VALUES (:i, 'policia', NULL, 1)"), {"i": IDENTIFICADOR})
    elif fila.tipo != "policia" or not fila.activo:
        raise c.Abortado("El identificador qa-policia existe pero no es una huella de policía activa.")


def leer(motor, datos) -> dict:
    with motor.begin() as conn:
        asegurar_vinculo(conn)
    with c.app_sin_dotenv(), c.reloj_laboratorio(datos):
        from app.logica import lector
        with Session(motor, expire_on_commit=False) as sesion:
            return lector.registrar_lectura(
                sesion, dispositivo=DISPOSITIVO, clave=str(uuid.uuid4()), identificador=IDENTIFICADOR
            ).cuerpo


def limpiar(motor) -> int:
    with motor.begin() as conn:
        borradas = conn.execute(text("DELETE FROM raciones_policia WHERE dispositivo=:d"),
                                {"d": DISPOSITIVO}).rowcount
        conn.execute(text("DELETE FROM solicitudes_lector WHERE dispositivo=:d"), {"d": DISPOSITIVO})
    return borradas


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--leer", action="store_true")
    grupo.add_argument("--limpiar", action="store_true")
    args = parser.parse_args(argv)
    with c.bloqueo_corrida(), c.entorno_seguro(permisos(args.limpiar)) as (motor, huella, servidor):
        datos = c.leer_corrida(servidor)
        c.comprobar_base(datos, huella)
        if args.limpiar:
            print(f"Raciones de policía del laboratorio borradas: {limpiar(motor)}")
        else:
            print(json.dumps(leer(motor, datos), ensure_ascii=False))


if __name__ == "__main__":
    c.ejecutar(main)
