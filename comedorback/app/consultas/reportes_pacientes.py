"""Reporte de distribución de pacientes (servicios × tipos de dieta) y matriz del día.

Lee exclusivamente `bd_nutricion` de la tabla `raciones_servicio_dia`.
Cada ración cuenta 1, sin coeficientes: en pacientes no se pondera por tiempo
de comida (contexto, sección 2.4).

Filas y columnas salen en un orden FIJO, el de las planillas del hospital:
- 16 filas fijas (`FILAS_DISTRIBUCION`, de H. CIRUGIA MUJERES a H. ONCOLOGIA).
- 9 columnas del informe (`COLUMNAS_DISTRIBUCION`, de CORRIENTE a OTROS).

La celda vigente para un (día, fila, columna) es siempre la última registrada
(por `momento`, y a igual momento por `id`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modelos.pacientes import ColumnaInformeDieta, RacionServicioDia

# --------------------------------------------------------------------------
# Orden fijo de las planillas
# --------------------------------------------------------------------------

# Códigos y etiquetas de `columnas_informe_dieta`. SONDAS y LIQUIDAS son hijas
# de SONDAS Y LIQUIDAS (`agrupa_en_id`) y se suman ahí; papilla y otros ya
# apuntan a OTROS.
COLUMNAS_DISTRIBUCION: list[tuple[str, str]] = [
    ("corriente", "CORRIENTE"),
    ("blanda", "BLANDA"),
    ("hiposodica", "HIPOSODICA"),
    ("hiposograsa", "HIPOSOGRASA"),
    ("diabetico", "DIABETICO"),
    ("licuadas", "LICUADAS"),
    ("quimioterapias", "QUIMIOTERAPIAS"),
    ("sondas_liquidas", "SONDAS Y LIQUIDAS"),
    ("otros", "OTROS"),
]

CODIGOS_COLUMNAS = [c for c, _ in COLUMNAS_DISTRIBUCION]


@dataclass(frozen=True)
class FilaFija:
    """Una fila de planilla fija."""

    codigo: str
    etiqueta: str
    grupo: str
    hoja: str | None = None


FILAS_DISTRIBUCION: list[FilaFija] = [
    FilaFija("cirugia_mujeres", "H. CIRUGIA MUJERES", "H. CIRUGIA GENERAL", "CIRUGIA MUJERES"),
    FilaFija("cirugia_varones", "H. CIRUGIA VARONES", "H. CIRUGIA GENERAL", "CIRUGIA VARONES"),
    FilaFija("ginecologia", "H. GINECOLOGIA", "H. GINECOLOGIA"),
    FilaFija("infectologia", "H. INFECTOLOGIA", "H. INFECTOLOGIA"),
    FilaFija("medicina_mujeres", "H. MEDICINA MUJERES", "H. MEDICINA INTERNA", "MEDICINA MUJERES"),
    FilaFija("medicina_varones", "H. MEDICINA VARONES", "H. MEDICINA INTERNA", "MEDICINA VARONES"),
    FilaFija("obstetricia", "H. OBSTETRICIA", "H. OBSTETRICIA"),
    FilaFija("hemodialisis", "H. HEMODIALISIS", "H. HEMODIALISIS"),
    FilaFija("neonatologia_ucin", "H. NEONATOLOGIA UCIN", "H. NEONATOLOGIA UTI"),
    FilaFija("uti", "H. U.T.I.", "H. U.T.I."),
    FilaFija("traumatologia", "H. TRAUMATOLOGIA", "H. TRAUMATOLOGIA"),
    FilaFija("quemados", "H. QUEMADOS", "H. QUEMADOS"),
    FilaFija("emergencias", "H. EMERGENCIAS", "EMERGENCIAS"),
    FilaFija("pediatria_uci", "H. PEDIATRIA UCI", "H. PEDIATRIA UCI"),
    FilaFija("pediatria_gral", "H. PEDIATRIA GRAL.", "H. PEDIATRIA GRAL."),
    FilaFija("oncologia", "H. ONCOLOGIA", "H. ONCOLOGIA"),
]

CODIGOS_FILAS = [f.codigo for f in FILAS_DISTRIBUCION]


# --------------------------------------------------------------------------
# Dataclasses de resultados
# --------------------------------------------------------------------------


@dataclass
class FilaDistribucion:
    codigo: str
    etiqueta: str
    valores: list[int]
    total: int


@dataclass
class ReporteDistribucion:
    desde: date
    hasta: date
    dias: int
    titulo: str
    columnas: list[dict]
    filas: list[FilaDistribucion]
    total: dict
    criterio: dict


@dataclass
class ColumnaMatriz:
    codigo: str
    etiqueta: str


@dataclass
class FilaMatriz:
    codigo: str
    etiqueta: str
    celdas: list[int]
    total: int


@dataclass
class TotalMatriz:
    celdas: list[int]
    total: int


@dataclass
class MatrizRacionesDia:
    fecha: date
    columnas: list[ColumnaMatriz]
    filas: list[FilaMatriz]
    total: TotalMatriz
    actualizado: datetime | None


class RangoInvalido(ValueError):
    """`desde` es posterior a `hasta`."""


# --------------------------------------------------------------------------
# Funciones auxiliares
# --------------------------------------------------------------------------


def _columna_raiz(sesion: Session) -> dict[int, str]:
    """`columnas_informe_dieta.id` -> código de la columna del informe.

    Una hija (`agrupa_en_id`) se resuelve al código de la madre: SONDAS y
    LIQUIDAS terminan en SONDAS Y LIQUIDAS ('sondas_liquidas').
    """
    columnas = {c.id: c for c in sesion.execute(select(ColumnaInformeDieta)).scalars()}
    raiz: dict[int, str] = {}
    for col_id, col in columnas.items():
        madre = columnas.get(col.agrupa_en_id) if col.agrupa_en_id else None
        raiz[col_id] = (madre or col).codigo
    return raiz


def _mapa_columnas_raiz(sesion: Session) -> dict[str, int]:
    """Código de columna raíz ('corriente', ..., 'otros') -> id en `columnas_informe_dieta`."""
    columnas = sesion.execute(
        select(ColumnaInformeDieta).where(ColumnaInformeDieta.agrupa_en_id.is_(None))
    ).scalars()
    return {c.codigo: c.id for c in columnas}


# --------------------------------------------------------------------------
# Matriz diaria (raciones_servicio_dia)
# --------------------------------------------------------------------------


def obtener_matriz_dia(sesion: Session, fecha: date) -> MatrizRacionesDia:
    """La matriz completa de raciones servicios × tipos de dieta para una fecha.

    Una celda sin registro vale 0. La celda vigente es la última por momento.
    """
    filas_db = sesion.execute(
        select(RacionServicioDia)
        .where(RacionServicioDia.fecha == fecha)
        .order_by(RacionServicioDia.momento.asc(), RacionServicioDia.id.asc())
    ).scalars().all()

    raiz = _columna_raiz(sesion)
    celdas: dict[tuple[str, str], int] = {}
    actualizado: datetime | None = None

    for r in filas_db:
        col_cod = raiz.get(r.columna_informe_id)
        if col_cod:
            celdas[(r.fila_informe, col_cod)] = r.cantidad
        if actualizado is None or r.momento > actualizado:
            actualizado = r.momento

    filas_out: list[FilaMatriz] = []
    totales_por_col = [0] * len(CODIGOS_COLUMNAS)

    for fila in FILAS_DISTRIBUCION:
        valores_fila = [celdas.get((fila.codigo, col_cod), 0) for col_cod in CODIGOS_COLUMNAS]
        total_fila = sum(valores_fila)
        filas_out.append(FilaMatriz(
            codigo=fila.codigo,
            etiqueta=fila.etiqueta,
            celdas=valores_fila,
            total=total_fila,
        ))
        for i, val in enumerate(valores_fila):
            totales_por_col[i] += val

    columnas_out = [ColumnaMatriz(codigo=c, etiqueta=e) for c, e in COLUMNAS_DISTRIBUCION]
    total_out = TotalMatriz(celdas=totales_por_col, total=sum(totales_por_col))

    return MatrizRacionesDia(
        fecha=fecha,
        columnas=columnas_out,
        filas=filas_out,
        total=total_out,
        actualizado=actualizado,
    )


def guardar_matriz_dia(
    sesion: Session,
    fecha: date,
    celdas_input: list,
    registrado_por: int | None = None,
) -> MatrizRacionesDia:
    """Inserta una fila por celda cuyo valor cambió respecto del vigente.

    Valida:
    - `fecha`: no futura (<= date.today()).
    - `fila`: debe existir en `FILAS_DISTRIBUCION`.
    - `columna`: debe existir en `COLUMNAS_DISTRIBUCION`.
    - `cantidad`: entero >= 0.

    Si el valor enviado coincide con el vigente actual, no inserta nada.
    """
    if fecha > date.today():
        raise ValueError("La fecha no puede ser futura.")

    # Validar formato y valores de las celdas
    for item in celdas_input:
        fila = getattr(item, "fila", None) or item.get("fila")
        columna = getattr(item, "columna", None) or item.get("columna")
        cantidad = getattr(item, "cantidad", None)
        if cantidad is None and isinstance(item, dict):
            cantidad = item.get("cantidad")

        if fila not in CODIGOS_FILAS:
            raise ValueError(f"Fila de distribución inválida: '{fila}'.")
        if columna not in CODIGOS_COLUMNAS:
            raise ValueError(f"Columna de distribución inválida: '{columna}'.")
        if cantidad is None or not isinstance(cantidad, int) or cantidad < 0:
            raise ValueError("La cantidad debe ser un entero mayor o igual a 0.")

    # Obtener valores vigentes actuales para la fecha
    filas_db = sesion.execute(
        select(RacionServicioDia)
        .where(RacionServicioDia.fecha == fecha)
        .order_by(RacionServicioDia.momento.asc(), RacionServicioDia.id.asc())
    ).scalars().all()

    raiz = _columna_raiz(sesion)
    vigentes: dict[tuple[str, str], int] = {}
    for r in filas_db:
        col_cod = raiz.get(r.columna_informe_id)
        if col_cod:
            vigentes[(r.fila_informe, col_cod)] = r.cantidad

    mapa_col_id = _mapa_columnas_raiz(sesion)
    ahora = datetime.now()

    for item in celdas_input:
        fila = getattr(item, "fila", None) or item["fila"]
        columna = getattr(item, "columna", None) or item["columna"]
        cantidad = getattr(item, "cantidad", None)
        if cantidad is None and isinstance(item, dict):
            cantidad = item["cantidad"]

        val_vigente = vigentes.get((fila, columna), 0)
        if cantidad != val_vigente:
            col_id = mapa_col_id.get(columna)
            if not col_id:
                raise ValueError(f"Columna de informe no encontrada en base de datos: '{columna}'.")
            sesion.add(RacionServicioDia(
                fecha=fecha,
                fila_informe=fila,
                columna_informe_id=col_id,
                cantidad=cantidad,
                momento=ahora,
                registrado_por=registrado_por,
            ))
            vigentes[(fila, columna)] = cantidad

    sesion.commit()
    return obtener_matriz_dia(sesion, fecha)


# --------------------------------------------------------------------------
# Reporte de distribución por rango de fechas
# --------------------------------------------------------------------------


def reporte_distribucion(sesion: Session, desde: date, hasta: date) -> ReporteDistribucion:
    """Servicios × tipos de dieta consolidado para cualquier rango de fechas.

    Lee exclusivamente de `raciones_servicio_dia`. Para cada día del rango,
    la cantidad vigente de cada celda es la última registrada (o 0 si no se registró).
    """
    if desde > hasta:
        raise RangoInvalido("La fecha inicial es posterior a la final.")

    filas_db = sesion.execute(
        select(RacionServicioDia)
        .where(RacionServicioDia.fecha >= desde, RacionServicioDia.fecha <= hasta)
        .order_by(RacionServicioDia.fecha.asc(), RacionServicioDia.momento.asc(), RacionServicioDia.id.asc())
    ).scalars().all()

    raiz = _columna_raiz(sesion)

    # Última cantidad registrada por (fecha, fila, columna_raiz)
    ultima_por_dia_celda: dict[tuple[date, str, str], int] = {}
    for r in filas_db:
        col_cod = raiz.get(r.columna_informe_id)
        if col_cod:
            ultima_por_dia_celda[(r.fecha, r.fila_informe, col_cod)] = r.cantidad

    # Sumar las cantidades vigentes a lo largo del período
    totales_celda: dict[tuple[str, str], int] = {}
    for (_, fila_cod, col_cod), cant in ultima_por_dia_celda.items():
        if cant > 0:
            totales_celda[(fila_cod, col_cod)] = totales_celda.get((fila_cod, col_cod), 0) + cant

    filas_out: list[FilaDistribucion] = []
    totales_por_col = [0] * len(CODIGOS_COLUMNAS)

    for fila in FILAS_DISTRIBUCION:
        valores_fila = [totales_celda.get((fila.codigo, col_cod), 0) for col_cod in CODIGOS_COLUMNAS]
        total_fila = sum(valores_fila)
        filas_out.append(FilaDistribucion(
            codigo=fila.codigo,
            etiqueta=fila.etiqueta,
            valores=valores_fila,
            total=total_fila,
        ))
        for i, val in enumerate(valores_fila):
            totales_por_col[i] += val

    criterio = {
        "fuente": "raciones_servicio_dia",
        "ultima_del_dia_manda": True,
        "pendiente_confirmar": [],
    }

    return ReporteDistribucion(
        desde=desde,
        hasta=hasta,
        dias=(hasta - desde).days + 1,
        titulo="INFORME MENSUAL DE RACIONES SERVIDAS A PACIENTES",
        columnas=[{"codigo": c, "etiqueta": e} for c, e in COLUMNAS_DISTRIBUCION],
        filas=filas_out,
        total={"valores": totales_por_col, "total": sum(totales_por_col)},
        criterio=criterio,
    )
