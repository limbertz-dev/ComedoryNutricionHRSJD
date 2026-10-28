"""Carga qué columna del formulario le toca a cada categoría del hospital.

Es una decisión del hospital, no un dato fijo. Los valores de abajo son el
mapeo que tenía cargado la base de desarrollo al 2026-09-24; hay que
confirmarlos con la jefatura, sobre todo internos y residentes, que no tienen
columna propia en el formulario de papel.

Se resuelve por NOMBRE de categoría a través de v_categorias, no por id: el
id es de la base de turnos y puede cambiar entre copias. Una categoría que no
figura acá no se rechaza al marcar: su ración cae en "Sin clasificar" y queda
visible en el informe.

Enfermería no se mapea: está fuera del comedor (ver derecho.py). Tampoco
Administrativo ni Manual, Mantenimiento y Camillero: no comen en el comedor
(si sobra comida se les da sin registro) y sus columnas, Administrativo y
Servicio, están desactivadas (migraciones f4c6e8a0b2d4 y a7c9e1b3d5f6).

Idempotente: una categoría que ya tiene mapeo se omite, aunque apunte a otra
columna. Cambiar un mapeo es una decisión, no una recarga.

Ejecutar con:  python -m app.semillas.mapeo_categorias
"""

from sqlalchemy import select

from app.core.db import SesionLocal
from app.modelos.comedor import CategoriaReporte, CategoriaReporteMap
from app.modelos.heredados import Categoria

MAPEO = [
    ("Medicos", "medico"),
    ("Internos", "medico"),
    ("Residentes", "medico"),
    ("Internos-Medicina", "medico"),
    ("Tecnicos", "tecnicos"),
    ("Internos-Bioquimica", "tecnicos"),
    ("Internos-Imagenologia", "tecnicos"),
    ("Internos-Fisioterapia", "tecnicos"),
]


def sembrar() -> None:
    sesion = SesionLocal()
    creados = 0
    try:
        columnas = dict(
            sesion.execute(select(CategoriaReporte.codigo, CategoriaReporte.id)).all()
        )
        for nombre, codigo in MAPEO:
            categoria_id = sesion.execute(
                select(Categoria.id).where(Categoria.nombre == nombre)
            ).scalar_one_or_none()
            if categoria_id is None:
                print(f"  falta la categoría '{nombre}' en v_categorias — se omite")
                continue
            if codigo not in columnas:
                print(f"  falta la columna '{codigo}' en categorias_reporte — se omite")
                continue

            ya_existe = sesion.execute(
                select(CategoriaReporteMap.id).where(
                    CategoriaReporteMap.categoria_id == categoria_id
                )
            ).scalar_one_or_none()
            if ya_existe:
                print(f"  {nombre}: ya estaba mapeada")
                continue

            sesion.add(
                CategoriaReporteMap(
                    categoria_id=categoria_id,
                    categoria_reporte_id=columnas[codigo],
                )
            )
            creados += 1
            print(f"  {nombre} -> {codigo}")
        sesion.commit()
        print(f"Mapeos creados: {creados}")
    finally:
        sesion.close()


if __name__ == "__main__":
    sembrar()
