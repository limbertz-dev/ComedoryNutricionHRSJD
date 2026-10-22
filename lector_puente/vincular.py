"""Vincular huellas del lector con personas del padrón, desde la consola.

Mientras no exista la pantalla, la jefatura enrola la huella en el lector,
anota el número que muestra el aparato y lo vincula aquí con la persona.
Entra con una cuenta de jefa o sistemas (la contraseña se pide oculta).

    python vincular.py --api http://127.0.0.1:8000 --usuario jefa
"""

import argparse
import getpass
import json
import sys
from urllib import error, parse, request


class Sesion:
    def __init__(self, api: str):
        self.api = api.rstrip("/")
        self.token = None

    def pedir(self, metodo, ruta, cuerpo=None):
        cabeceras = {"Content-Type": "application/json"}
        if self.token:
            cabeceras["Authorization"] = f"Bearer {self.token}"
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        peticion = request.Request(self.api + ruta, data=datos, headers=cabeceras, method=metodo)
        try:
            with request.urlopen(peticion, timeout=15) as respuesta:
                return respuesta.status, json.loads(respuesta.read() or b"null")
        except error.HTTPError as fallo:
            try:
                return fallo.code, json.loads(fallo.read() or b"null")
            except ValueError:
                return fallo.code, {"detail": "Respuesta no válida"}

    def ingresar(self, usuario: str) -> None:
        clave = getpass.getpass(f"Contraseña de {usuario}: ")
        codigo, datos = self.pedir("POST", "/auth/login", {"username": usuario, "password": clave})
        if codigo != 200 or not datos.get("access"):
            raise SystemExit(f"No se pudo entrar ({codigo}): {datos.get('detail') if datos else ''}")
        self.token = datos["access"]


def detalle(datos) -> str:
    if isinstance(datos, dict):
        return str(datos.get("detail") or datos)
    return str(datos)


def buscar_persona(sesion: Sesion) -> int | None:
    texto = input("  Buscar persona (nombre, carnet o ítem; vacío = cancelar): ").strip()
    if not texto:
        return None
    codigo, pagina = sesion.pedir("GET", "/personal?" + parse.urlencode({"busqueda": texto, "limite": 15}))
    if codigo != 200:
        print(f"  No se pudo buscar ({codigo}): {detalle(pagina)}")
        return None
    personas = pagina["datos"]
    if not personas:
        print("  Nadie coincide con esa búsqueda (solo aparecen las categorías que comen).")
        return None
    for numero, p in enumerate(personas, 1):
        print(f"   {numero:>2}. {p['nombre_completo'] or '(sin ficha)'} · {p['categoria'] or '-'}"
              f" · CI {p['carnet_identidad'] or '-'} · id {p['usuario_id']}")
    eleccion = input("  Número de la lista (vacío = cancelar): ").strip()
    if not eleccion.isdigit() or not 1 <= int(eleccion) <= len(personas):
        return None
    return personas[int(eleccion) - 1]["usuario_id"]


def listar(sesion: Sesion) -> None:
    codigo, vinculos = sesion.pedir("GET", "/lector/vinculos")
    if codigo != 200:
        print(f"  No se pudo listar ({codigo}): {detalle(vinculos)}")
        return
    if not vinculos:
        print("  Todavía no hay huellas vinculadas.")
    for v in vinculos:
        print(f"   [{v['id']}] huella {v['identificador']} -> {v['nombre'] or '(fuera del padrón)'}"
              f" · {v['categoria'] or '-'}")


def vincular(sesion: Sesion) -> None:
    identificador = input("  Número que muestra el lector para esta huella: ").strip()
    if not identificador:
        return
    usuario_id = buscar_persona(sesion)
    if usuario_id is None:
        print("  Cancelado.")
        return
    codigo, datos = sesion.pedir("POST", "/lector/vinculos",
                                 {"identificador": identificador, "usuario_id": usuario_id})
    if codigo == 201:
        print(f"  Listo: huella {datos['identificador']} -> {datos['nombre']}.")
    else:
        print(f"  No se vinculó ({codigo}): {detalle(datos)}")


def dar_de_baja(sesion: Sesion) -> None:
    listar(sesion)
    vinculo = input("  [id] del vínculo a dar de baja (vacío = cancelar): ").strip()
    if not vinculo.isdigit():
        return
    codigo, datos = sesion.pedir("DELETE", f"/lector/vinculos/{vinculo}")
    print("  Dado de baja." if codigo == 200 else f"  No se pudo ({codigo}): {detalle(datos)}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--usuario", required=True, help="cuenta de jefa o sistemas")
    args = parser.parse_args(argv)
    sesion = Sesion(args.api)
    sesion.ingresar(args.usuario)
    acciones = {"1": vincular, "2": listar, "3": dar_de_baja}
    while True:
        opcion = input("\n1) Vincular huella  2) Ver vinculadas  3) Dar de baja  0) Salir: ").strip()
        if opcion == "0":
            return 0
        if opcion in acciones:
            acciones[opcion](sesion)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print()
        sys.exit(0)
