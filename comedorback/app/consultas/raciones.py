"""Todas las raciones que cuentan: las del personal y las de los policías.

Se guardan en tablas separadas (`asistencias` y `raciones_policia`) y no se
mezclan nunca al escribir. Los conteos de informes, resumen y supervisión leen
esta unión, de solo lectura, con las columnas que tienen en común. Sin
raciones de policía, la unión da exactamente lo mismo que `asistencias`.
"""

from sqlalchemy import literal, select, union_all

from app.modelos.comedor import Asistencia
from app.modelos.lector import RacionPolicia


def fuente(nombre: str = "raciones"):
    """Subconsulta con `fecha_comida`, `comida_id`, `categoria_reporte_id` y
    `origen` ('personal' | 'policia') por ración."""
    personal = select(
        Asistencia.fecha_comida.label("fecha_comida"),
        Asistencia.comida_id.label("comida_id"),
        Asistencia.categoria_reporte_id.label("categoria_reporte_id"),
        Asistencia.metodo.label("metodo"),
        literal("personal").label("origen"),
    )
    policia = select(
        RacionPolicia.fecha_comida,
        RacionPolicia.comida_id,
        RacionPolicia.categoria_reporte_id,
        literal("policia"),
        literal("policia"),
    )
    return union_all(personal, policia).subquery(nombre)
