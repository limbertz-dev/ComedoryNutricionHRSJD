"""Perfiles del comedor, basados en los nombres del catalogo del hospital.

Un servicio organiza el padron; no convierte una categoria excluida en elegible.
Solo comen estas categorias (regla del hospital, 22/10/2026): Administrativo,
Servicio, Enfermeria y las demas quedan fuera aunque una version de
reglas_derecho tenga excluir_enfermeria=0. Policias no tiene equivalencia
confirmada en los catalogos inspeccionados.
"""
import unicodedata

from sqlalchemy import func


CATEGORIAS_PERMITIDAS = (
    'Medicos', 'Tecnicos', 'Internos', 'Residentes', 'Internos-Medicina',
    'Internos-Bioquimica', 'Internos-Imagenologia', 'Internos-Fisioterapia',
)


def normalizar_categoria(valor):
    if not isinstance(valor, str):
        return ''
    return ''.join(c for c in unicodedata.normalize('NFD', valor.strip().casefold())
                   if unicodedata.category(c) != 'Mn')


_NOMBRES = tuple(normalizar_categoria(n) for n in CATEGORIAS_PERMITIDAS)


def categoria_permitida(valor):
    return normalizar_categoria(valor) in _NOMBRES


def categoria_permitida_sql(columna):
    nombre = func.lower(func.trim(columna))
    # SQLite no convierte mayusculas acentuadas; MySQL usa la misma expresion.
    for origen, destino in zip('áéíóúÁÉÍÓÚ', 'aeiouaeiou'):
        nombre = func.replace(nombre, origen, destino)
    return nombre.in_(_NOMBRES)
