"""Enrolar huellas con el lector ZKTeco (ZK9500 / ZK4500) y vincularlas.

La jefatura entra con su cuenta, elige a la persona del padrón (o «policía»),
y la persona apoya el MISMO dedo tres veces. El SDK une las capturas en una
plantilla que se guarda en la API con su vínculo; el puente la carga solo
(cada minuto) o al reiniciarlo.

Cerrar el puente antes: el lector USB no se puede abrir desde dos programas.

    python enrolar.py --usuario jefa            (usa la url y clave de puente.ini)
"""

import argparse
import sys
import uuid
from pathlib import Path

import puente
import vincular

CAPTURAS = 3


def capturar_dedo(sdk, avisar=print, dormir=None) -> object:
    import time
    dormir = dormir or time.sleep
    while (plantilla := sdk.capturar()) is None:
        dormir(0.15)
    sdk.luz("green")
    avisar("    ✔ captura")
    # Esperar a que retire el dedo, para no tomar la misma imagen dos veces.
    while sdk.capturar() is not None:
        dormir(0.15)
    return plantilla


def enrolar(sdk, plantillas_actuales: list[dict], avisar=print, pedir=input, dormir=None) -> str | None:
    """Tres capturas del mismo dedo -> plantilla base64. None si se cancela o
    si ese dedo ya está enrolado."""
    sdk.cargar(plantillas_actuales)
    capturas = []
    while len(capturas) < CAPTURAS:
        avisar(f"  Apoyar el dedo ({len(capturas) + 1} de {CAPTURAS})…")
        plantilla = capturar_dedo(sdk, avisar, dormir)
        if not capturas and sdk.identificar(plantilla) is not None:
            sdk.luz("red")
            avisar("  Ese dedo ya está enrolado. Dar de baja su vínculo antes de volver a enrolarlo.")
            return None
        if capturas and not sdk.coinciden(capturas[0], plantilla):
            sdk.luz("red")
            avisar("  No coincide con la primera captura: hay que usar el mismo dedo. Se reinicia.")
            capturas = []
            if pedir("  ¿Reintentar? (s/n): ").strip().lower() != "s":
                return None
            continue
        capturas.append(plantilla)
    return sdk.unir(*capturas)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--usuario", required=True, help="cuenta de jefa o sistemas")
    parser.add_argument("--config", type=Path, default=puente.CARPETA / "puente.ini")
    args = parser.parse_args(argv)

    config = puente.Configuracion.leer(args.config)
    api_lector = puente.Api(config)
    sesion = vincular.Sesion(config.url)
    sesion.ingresar(args.usuario)

    from zkteco import SdkZK
    sdk = SdkZK()
    sdk.abrir()
    try:
        while True:
            opcion = input("\n1) Enrolar personal  2) Enrolar policía  0) Salir: ").strip()
            if opcion == "0":
                return 0
            if opcion not in ("1", "2"):
                continue
            usuario_id = None
            policia = {}
            if opcion == "2":
                policia = vincular.datos_policia()
                if policia is None:
                    continue
            if opcion == "1":
                usuario_id = vincular.buscar_persona(sesion)
                if usuario_id is None:
                    print("  Cancelado.")
                    continue
            plantilla = enrolar(sdk, api_lector.plantillas())
            if plantilla is None:
                continue
            cuerpo = {"identificador": f"zk-{uuid.uuid4().hex[:12]}", "plantilla": plantilla,
                      "tipo": "personal" if opcion == "1" else "policia"}
            if usuario_id is not None:
                cuerpo["usuario_id"] = usuario_id
            cuerpo.update(policia)
            codigo, datos = sesion.pedir("POST", "/lector/vinculos", cuerpo)
            if codigo == 201:
                print(f"  Listo: huella enrolada para {datos['nombre']}. El puente la toma en menos de un minuto.")
            else:
                print(f"  No se guardó ({codigo}): {vincular.detalle(datos)}")
    finally:
        sdk.cerrar()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print()
        sys.exit(0)
