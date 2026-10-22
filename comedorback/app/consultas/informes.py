"""Los tres informes: registro diario, informe mensual y resumen de gestión.

Los tres salen de la MISMA tabla, `asistencias`, con distinto agrupamiento.
Ninguna cifra se guarda dos veces, y por eso el total del registro diario
tiene que dar exactamente igual al del informe mensual: son la misma suma
abierta por criterios distintos.

    registro diario   una fila por día del mes
    informe mensual   una fila por tiempo de comida, más la reducción a
                      ración completa con los coeficientes
    resumen gestión   una fila por mes del año

Dos números que los tres informes exponen a propósito, porque miden lo que
falta en vez de esconderlo:

    sin_clasificar    raciones cuya categoría todavía no está mapeada a una
                      columna del formulario
    sin_coeficiente   raciones de un tiempo de comida sin grupo asignado, que
                      por lo tanto no suman al equivalente en raciones completas
"""

import calendar
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.consultas import raciones
from app.core import reloj
from app.modelos.comedor import (
    CategoriaReporte,
    CoeficienteRacion,
)
from app.modelos.heredados import Comida

CODIGO_SIN_CLASIFICAR = "sin_clasificar"

MESES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


@dataclass(frozen=True)
class Columna:
    id: int
    nombre: str
    codigo: str


@dataclass
class Fila:
    etiqueta: str
    celdas: list[int]
    total: int = 0
    registrado: bool = True

    def cerrar(self) -> None:
        self.total = sum(self.celdas)


@dataclass
class Grupo:
    grupo: str
    servidas: int
    coeficiente: float
    equivalente: float
    coeficientes_mixtos: bool = False


@dataclass
class Informe:
    tipo: str
    gestion: int
    mes: int | None
    mes_nombre: str | None
    desde: date
    hasta: date
    situacion: str
    cerrado: bool
    categorias: list[str]
    filas: list[Fila]
    totales_por_categoria: list[int]
    total_general: int
    sin_clasificar: int
    sin_coeficiente: int
    grupos: list[Grupo] = field(default_factory=list)
    total_equivalente: float | None = None


def _columnas(sesion: Session, desde: date, hasta: date) -> list[Columna]:
    """El estado actual no puede ocultar la clasificacion de una racion servida."""
    r = raciones.fuente()
    utilizadas = select(r.c.categoria_reporte_id).where(r.c.fecha_comida.between(desde, hasta))
    consulta = (
        select(CategoriaReporte.id, CategoriaReporte.nombre, CategoriaReporte.codigo)
        .where(or_(CategoriaReporte.activo == 1, CategoriaReporte.id.in_(utilizadas)))
        .order_by(CategoriaReporte.orden, CategoriaReporte.id)
    )
    return [Columna(*fila) for fila in sesion.execute(consulta).all()]


def _comidas(sesion: Session, desde: date, hasta: date) -> list[tuple]:
    """Conservar comidas con entregas del periodo aunque hoy esten desactivadas."""
    r = raciones.fuente()
    utilizadas = select(r.c.comida_id).where(r.c.fecha_comida.between(desde, hasta))
    return sesion.execute(
        select(Comida.id, Comida.nombre)
        .where(or_(Comida.estado == 1, Comida.id.in_(utilizadas)))
        .order_by(Comida.id)
    ).all()


def _situacion(gestion: int, mes: int | None, hoy: date) -> str:
    if mes is None:
        if gestion < hoy.year:
            return "cerrado"
        return "curso" if gestion == hoy.year else "futuro"
    pedido = gestion * 12 + mes
    actual = hoy.year * 12 + hoy.month
    if pedido < actual:
        return "cerrado"
    return "curso" if pedido == actual else "futuro"


def _rango(gestion: int, mes: int | None) -> tuple[date, date]:
    if mes is None:
        return date(gestion, 1, 1), date(gestion, 12, 31)
    ultimo = calendar.monthrange(gestion, mes)[1]
    return date(gestion, mes, 1), date(gestion, mes, ultimo)


def _conteos(sesion: Session, desde: date, hasta: date) -> list[tuple]:
    """(fecha_comida, comida_id, categoria_reporte_id, cantidad) del período.
    Personal y policías: ver app/consultas/raciones.py."""
    r = raciones.fuente()
    consulta = (
        select(
            r.c.fecha_comida,
            r.c.comida_id,
            r.c.categoria_reporte_id,
            func.count().label("cantidad"),
        )
        .where(r.c.fecha_comida.between(desde, hasta))
        .group_by(r.c.fecha_comida, r.c.comida_id, r.c.categoria_reporte_id)
    )
    return sesion.execute(consulta).all()


def _totales_de_columna(filas: list[Fila], cantidad: int) -> list[int]:
    return [sum(f.celdas[i] for f in filas) for i in range(cantidad)]


def _sin_clasificar(sesion: Session, desde: date, hasta: date) -> int:
    r = raciones.fuente()
    consulta = (
        select(func.count())
        .select_from(r)
        .join(CategoriaReporte, CategoriaReporte.id == r.c.categoria_reporte_id)
        .where(
            r.c.fecha_comida.between(desde, hasta),
            CategoriaReporte.codigo == CODIGO_SIN_CLASIFICAR,
        )
    )
    return sesion.execute(consulta).scalar_one()


def _sin_coeficiente(sesion: Session, desde: date, hasta: date) -> int:
    """Raciones sin coeficiente vigente ese día: no suman al equivalente."""
    r = raciones.fuente()
    consulta = (
        select(func.count())
        .select_from(r)
        .outerjoin(
            CoeficienteRacion,
            and_(
                CoeficienteRacion.comida_id == r.c.comida_id,
                CoeficienteRacion.vigente_desde <= r.c.fecha_comida,
                or_(
                    CoeficienteRacion.vigente_hasta.is_(None),
                    CoeficienteRacion.vigente_hasta >= r.c.fecha_comida,
                ),
            ),
        )
        .where(
            r.c.fecha_comida.between(desde, hasta),
            CoeficienteRacion.id.is_(None),
        )
    )
    return sesion.execute(consulta).scalar_one()


def _grupos(sesion: Session, desde: date, hasta: date) -> list[Grupo]:
    """Reducción a ración completa, con el coeficiente vigente en cada día.

    El coeficiente se resuelve por (comida_id, fecha_comida), no por una
    clave foránea desde `comidas` a una versión concreta. Si la jefatura lo
    cambia a mitad de año, cada día del informe usa el que estaba vigente ese
    día y los meses ya firmados siguen dando el mismo número.
    """
    r = raciones.fuente()
    por_dia = (
        select(
            r.c.fecha_comida.label("fecha_comida"),
            r.c.comida_id.label("comida_id"),
            func.count().label("cantidad"),
        )
        .where(r.c.fecha_comida.between(desde, hasta))
        .group_by(r.c.fecha_comida, r.c.comida_id)
        .subquery("por_dia")
    )

    consulta = (
        select(
            Comida.nombre.label("grupo"),
            func.sum(por_dia.c.cantidad).label("servidas"),
            func.sum(por_dia.c.cantidad * CoeficienteRacion.coeficiente).label(
                "equivalente"
            ),
            func.min(CoeficienteRacion.coeficiente).label("coef_min"),
            func.max(CoeficienteRacion.coeficiente).label("coef_max"),
        )
        .select_from(por_dia)
        .join(
            CoeficienteRacion,
            and_(
                CoeficienteRacion.comida_id == por_dia.c.comida_id,
                CoeficienteRacion.vigente_desde <= por_dia.c.fecha_comida,
                or_(
                    CoeficienteRacion.vigente_hasta.is_(None),
                    CoeficienteRacion.vigente_hasta >= por_dia.c.fecha_comida,
                ),
            ),
        )
        .join(Comida, Comida.id == por_dia.c.comida_id)
        .group_by(Comida.id, Comida.nombre)
        .order_by(Comida.id)
    )

    grupos = []
    for grupo, servidas, equivalente, coef_min, coef_max in sesion.execute(consulta):
        # Si el coeficiente cambió dentro del período, no hay un valor único que
        # mostrar; el equivalente ya está bien calculado día por día.
        coeficiente = float(coef_min) if coef_min == coef_max else float(coef_max)
        grupos.append(
            Grupo(
                grupo=grupo,
                servidas=int(servidas),
                coeficiente=coeficiente,
                equivalente=round(float(equivalente), 2),
                coeficientes_mixtos=coef_min != coef_max,
            )
        )
    return grupos


def _armar(
    sesion: Session,
    tipo: str,
    gestion: int,
    mes: int | None,
    filas: list[Fila],
    columnas: list[Columna],
    desde: date,
    hasta: date,
) -> Informe:
    for fila in filas:
        fila.cerrar()
    totales = _totales_de_columna(filas, len(columnas))
    situacion = _situacion(gestion, mes, reloj.hoy())
    return Informe(
        tipo=tipo,
        gestion=gestion,
        mes=mes,
        mes_nombre=MESES[mes - 1] if mes else None,
        desde=desde,
        hasta=hasta,
        situacion=situacion,
        cerrado=situacion == "cerrado",
        categorias=[c.nombre for c in columnas],
        filas=filas,
        totales_por_categoria=totales,
        total_general=sum(totales),
        sin_clasificar=_sin_clasificar(sesion, desde, hasta),
        sin_coeficiente=_sin_coeficiente(sesion, desde, hasta),
    )


def registro_diario(sesion: Session, gestion: int, mes: int) -> Informe:
    """La planilla del cuaderno: una fila por día del mes."""
    desde, hasta = _rango(gestion, mes)
    columnas = _columnas(sesion, desde, hasta)
    indice = {c.id: i for i, c in enumerate(columnas)}
    hoy = reloj.hoy()

    filas = [
        Fila(etiqueta=str(dia), celdas=[0] * len(columnas), registrado=date(gestion, mes, dia) <= hoy)
        for dia in range(1, hasta.day + 1)
    ]
    for fecha, _comida, categoria, cantidad in _conteos(sesion, desde, hasta):
        columna = indice.get(categoria)
        if columna is not None:
            filas[fecha.day - 1].celdas[columna] += cantidad

    return _armar(sesion, "registro_diario", gestion, mes, filas, columnas, desde, hasta)


def informe_mensual(sesion: Session, gestion: int, mes: int) -> Informe:
    """El formulario de Estadística: tiempos de comida × categorías."""
    desde, hasta = _rango(gestion, mes)
    columnas = _columnas(sesion, desde, hasta)
    indice = {c.id: i for i, c in enumerate(columnas)}
    comidas = _comidas(sesion, desde, hasta)
    posicion = {cid: i for i, (cid, _) in enumerate(comidas)}

    filas = [Fila(etiqueta=nombre, celdas=[0] * len(columnas)) for _, nombre in comidas]
    for _fecha, comida_id, categoria, cantidad in _conteos(sesion, desde, hasta):
        fila = posicion.get(comida_id)
        columna = indice.get(categoria)
        if fila is not None and columna is not None:
            filas[fila].celdas[columna] += cantidad

    informe = _armar(sesion, "mensual", gestion, mes, filas, columnas, desde, hasta)
    informe.grupos = _grupos(sesion, desde, hasta)
    informe.total_equivalente = round(sum(g.equivalente for g in informe.grupos), 2)
    return informe


def informe_rango(sesion: Session, desde: date, hasta: date) -> Informe:
    """El formulario de Estadística para un rango de fechas arbitrario.

    Igual que `informe_mensual` (tiempos de comida × categorías, con
    reducción a ración completa), pero sin atarse a un mes calendario: sirve
    tanto para "Hoy" como para 7 días, una quincena o un rango elegido a mano.
    """
    if desde > hasta:
        raise ValueError("'desde' no puede ser posterior a 'hasta'")

    columnas = _columnas(sesion, desde, hasta)
    indice = {c.id: i for i, c in enumerate(columnas)}

    comidas = _comidas(sesion, desde, hasta)
    posicion = {cid: i for i, (cid, _) in enumerate(comidas)}

    filas = [Fila(etiqueta=nombre, celdas=[0] * len(columnas)) for _, nombre in comidas]
    for _fecha, comida_id, categoria, cantidad in _conteos(sesion, desde, hasta):
        fila = posicion.get(comida_id)
        columna = indice.get(categoria)
        if fila is not None and columna is not None:
            filas[fila].celdas[columna] += cantidad

    for fila in filas:
        fila.cerrar()
    totales = _totales_de_columna(filas, len(columnas))
    grupos = _grupos(sesion, desde, hasta)
    situacion = "curso" if hasta >= reloj.hoy() else "cerrado"

    return Informe(
        tipo="informe",
        gestion=hasta.year,
        mes=hasta.month,
        mes_nombre=MESES[hasta.month - 1],
        desde=desde,
        hasta=hasta,
        situacion=situacion,
        cerrado=situacion == "cerrado",
        categorias=[c.nombre for c in columnas],
        filas=filas,
        totales_por_categoria=totales,
        total_general=sum(totales),
        sin_clasificar=_sin_clasificar(sesion, desde, hasta),
        sin_coeficiente=_sin_coeficiente(sesion, desde, hasta),
        grupos=grupos,
        total_equivalente=round(sum(g.equivalente for g in grupos), 2),
    )


def resumen_gestion(sesion: Session, gestion: int) -> Informe:
    """El año entero, un mes por fila."""
    desde, hasta = _rango(gestion, None)
    columnas = _columnas(sesion, desde, hasta)
    indice = {c.id: i for i, c in enumerate(columnas)}
    hoy = reloj.hoy()

    filas = [
        Fila(
            etiqueta=nombre,
            celdas=[0] * len(columnas),
            registrado=_situacion(gestion, i + 1, hoy) != "futuro",
        )
        for i, nombre in enumerate(MESES)
    ]
    for fecha, _comida, categoria, cantidad in _conteos(sesion, desde, hasta):
        columna = indice.get(categoria)
        if columna is not None:
            filas[fecha.month - 1].celdas[columna] += cantidad

    return _armar(sesion, "gestion", gestion, None, filas, columnas, desde, hasta)
