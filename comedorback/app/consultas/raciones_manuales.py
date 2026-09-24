# LEGADO: Cargas manuales en dietas_cama (Hemodiálisis y Emergencias).
# Mantenido temporalmente sin uso activo; reemplazado por la matriz raciones_servicio_dia.

"""Raciones manuales: las que no salen del censo de camas.

Hemodiálisis no existe en el SIH y Emergencias se carga por cantidad
(`servicios_nutricion.modo = 'cantidad'`). Ninguna de las dos tiene cama.

No hay tabla propia ni columna `cantidad`, a propósito: una carga de N
raciones inserta N filas en `dietas_cama` con `cam_codigo` NULL. Cada fila
cuenta 1 en los reportes, sin la regla de la última por cama. Son ~23 y ~154
filas al mes: volumen trivial, y el esquema no cambia.

Igual que en el resto del módulo, solo se inserta. No hay borrado ni
edición.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.consultas.control import _tipo_activo
from app.consultas.reportes_pacientes import RangoInvalido
from app.modelos.pacientes import DietasCama, ServicioNutricion, TipoDieta

# Concepto -> (etiqueta, `servicios_nutricion.codigo` de la fila que lo lleva
# al reporte). El orden es el de la respuesta.
CONCEPTOS: dict[str, tuple[str, str]] = {
    "hemodialisis": ("Hemodiálisis", "hemodialisis"),
    "emergencias": ("Emergencias", "sih_216"),
}


class MapeoFaltante(RuntimeError):
    """No existe la fila de `servicios_nutricion` que lleva el concepto al reporte."""


@dataclass
class CargaManual:
    fecha: date
    concepto: str
    tipo_dieta_id: int
    cantidad: int
    dietas_cama_ids: list[int]


@dataclass
class FilaManual:
    fecha: date
    concepto: str
    tipo_dieta_id: int
    dieta: str
    cantidad: int


@dataclass
class RacionesManuales:
    desde: date
    hasta: date
    conceptos: list[dict]
    filas: list[FilaManual]


def _filas_de_mapeo(sesion: Session) -> dict[str, ServicioNutricion]:
    """Concepto -> su fila del mapeo, las que existan."""
    codigos = {mapeo: concepto for concepto, (_, mapeo) in CONCEPTOS.items()}
    filas = sesion.execute(
        select(ServicioNutricion).where(ServicioNutricion.codigo.in_(codigos))
    ).scalars()
    return {codigos[f.codigo]: f for f in filas}


def registrar(
    sesion: Session,
    fecha: date,
    concepto: str,
    tipo_dieta_id: int,
    cantidad: int,
    motivo: str | None = None,
    registrado_por: int | None = None,
) -> CargaManual:
    """Inserta `cantidad` filas, una por ración. Todo o nada.

    La dieta tiene que existir, estar activa, no estar eliminada y sumar
    ración: cargar NPO "por cantidad" no tiene sentido. Cualquiera de esas
    cosas es un 422.
    """
    if concepto not in CONCEPTOS:
        raise ValueError(f"El concepto '{concepto}' no existe.")
    if cantidad < 1:
        raise ValueError("La cantidad tiene que ser al menos 1.")

    mapeo = _filas_de_mapeo(sesion).get(concepto)
    if mapeo is None:
        raise MapeoFaltante(
            f"Falta la fila '{CONCEPTOS[concepto][1]}' en servicios_nutricion: "
            f"sin ella las raciones de {CONCEPTOS[concepto][0]} no llegan al reporte."
        )

    tipo = _tipo_activo(sesion, tipo_dieta_id)
    if not tipo.cuenta_racion:
        raise ValueError(f"'{tipo.nombre}' no suma ración: no se carga por cantidad.")

    # MySQL DATETIME guarda segundos: se descartan los microsegundos para que
    # lo que se responde sea lo que queda guardado.
    ahora = datetime.now().replace(microsecond=0)
    texto = (motivo or "").strip() or None
    filas = [
        DietasCama(
            fecha=fecha,
            momento=ahora,
            cam_codigo=None,
            sa_codigo=None,
            servicio_nutricion_id=mapeo.id,
            tipo_dieta_id=tipo.id,
            suspendida=0,
            motivo=texto,
            registrado_por=registrado_por,
        )
        for _ in range(cantidad)
    ]
    sesion.add_all(filas)
    sesion.commit()

    return CargaManual(
        fecha=fecha,
        concepto=concepto,
        tipo_dieta_id=tipo.id,
        cantidad=cantidad,
        dietas_cama_ids=[f.id for f in filas],
    )


def listar(sesion: Session, desde: date, hasta: date) -> RacionesManuales:
    """Lo cargado entre `desde` y `hasta`, agrupado por fecha, concepto y dieta."""
    if desde > hasta:
        raise RangoInvalido("La fecha inicial es posterior a la final.")

    conceptos = [{"codigo": c, "etiqueta": e} for c, (e, _) in CONCEPTOS.items()]
    concepto_de = {f.id: c for c, f in _filas_de_mapeo(sesion).items()}
    if not concepto_de:
        return RacionesManuales(desde=desde, hasta=hasta, conceptos=conceptos, filas=[])

    grupos = sesion.execute(
        select(
            DietasCama.fecha,
            DietasCama.servicio_nutricion_id,
            TipoDieta.id,
            TipoDieta.nombre,
            TipoDieta.orden,
            func.count(DietasCama.id),
        )
        .join(TipoDieta, TipoDieta.id == DietasCama.tipo_dieta_id)
        .where(
            DietasCama.fecha >= desde,
            DietasCama.fecha <= hasta,
            DietasCama.cam_codigo.is_(None),
            DietasCama.servicio_nutricion_id.in_(concepto_de),
        )
        .group_by(
            DietasCama.fecha, DietasCama.servicio_nutricion_id,
            TipoDieta.id, TipoDieta.nombre, TipoDieta.orden,
        )
    ).all()

    # Orden: fecha, concepto en el orden de CONCEPTOS, dieta en su orden del
    # catálogo. Nunca alfabético.
    orden_concepto = list(CONCEPTOS)
    grupos = sorted(
        grupos,
        key=lambda g: (g[0], orden_concepto.index(concepto_de[g[1]]), g[4], g[2]),
    )
    filas = [
        FilaManual(
            fecha=fecha,
            concepto=concepto_de[servicio_id],
            tipo_dieta_id=tipo_id,
            dieta=nombre,
            cantidad=int(cantidad),
        )
        for fecha, servicio_id, tipo_id, nombre, _orden, cantidad in grupos
    ]
    return RacionesManuales(desde=desde, hasta=hasta, conceptos=conceptos, filas=filas)
