"""Consultas y operaciones sobre el catálogo de dietas.

Reglas del dominio:
  · `tipos_dieta` es la tabla que gobierna este catálogo. La captura usa solo
    los nombres oficiales de nutrición.
  · NPO (cuenta_racion = 0) queda registrada y no suma al total de raciones.
  · Desactivar una dieta (activo = 0) no borra sus registros históricos: lo ya
    servido sigue contando.
  · Eliminar una dieta es borrado LÓGICO (visible = 0): deja de listarse y de
    poder asignarse, pero la fila nunca se borra. NPO no se puede eliminar.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modelos.pacientes import ColumnaInformeDieta, TipoDieta


class DietaNoEncontrada(RuntimeError):
    """La dieta solicitada no existe."""


class ColumnaInformeInvalida(ValueError):
    """La columna del informe especificada no existe."""


class NombreDietaDuplicado(RuntimeError):
    """Ya existe una dieta con ese nombre o código."""


class DietaNoEliminable(ValueError):
    """La dieta existe pero no se puede eliminar (NPO)."""


def _es_npo(dieta: TipoDieta) -> bool:
    return dieta.codigo.lower() == "npo"


def _descripcion_duplicado(dieta: TipoDieta) -> str:
    """"una dieta" o "una dieta eliminada": el nombre de una eliminada sigue ocupado."""
    return "una dieta" if dieta.visible else "una dieta eliminada"


def _buscar_columna_informe(
    sesion: Session, identificador: str | int
) -> ColumnaInformeDieta:
    """Resuelve una ColumnaInformeDieta por ID numérico, código o nombre."""
    if isinstance(identificador, int) or (
        isinstance(identificador, str) and identificador.strip().isdigit()
    ):
        col = sesion.get(ColumnaInformeDieta, int(identificador))
        if col:
            return col

    texto = str(identificador).strip()
    col = sesion.execute(
        select(ColumnaInformeDieta).where(
            (func.lower(ColumnaInformeDieta.codigo) == texto.lower())
            | (func.lower(ColumnaInformeDieta.nombre) == texto.lower())
        )
    ).scalars().first()

    if not col:
        raise ColumnaInformeInvalida(
            f"La columna de informe '{identificador}' no existe."
        )
    return col


def _formatear_dieta(dieta: TipoDieta, columna_nombre: str) -> dict[str, Any]:
    cuenta = bool(dieta.cuenta_racion)
    es_ayuno = _es_npo(dieta)
    return {
        "id": dieta.id,
        "codigo": dieta.codigo,
        "nombre": dieta.nombre,
        "columna_informe_id": dieta.columna_informe_id,
        "columna_informe": columna_nombre,
        "columna_libro": columna_nombre,
        "cuenta_racion": cuenta,
        "suma_al_libro": cuenta,
        "no_suma": not cuenta,
        "es_ayuno": es_ayuno,
        "activo": bool(dieta.activo),
        "activa": bool(dieta.activo),
        "orden": dieta.orden,
    }


def listar_dietas(sesion: Session) -> list[dict[str, Any]]:
    """Devuelve el catálogo de dietas visibles con su columna de informe.

    Las eliminadas (visible = 0) no salen: para el frontend ya no existen.
    """
    stmt = (
        select(TipoDieta, ColumnaInformeDieta.nombre.label("columna_nombre"))
        .join(
            ColumnaInformeDieta,
            ColumnaInformeDieta.id == TipoDieta.columna_informe_id,
        )
        .where(TipoDieta.visible == 1)
        .order_by(TipoDieta.orden.asc(), TipoDieta.id.asc())
    )
    filas = sesion.execute(stmt).all()
    return [_formatear_dieta(tipo, col_nombre) for tipo, col_nombre in filas]


def crear_dieta(
    sesion: Session,
    nombre: str,
    columna_informe: str | int,
    codigo: str | None = None,
    cuenta_racion: bool = True,
    orden: int | None = None,
    activo: bool = True,
) -> dict[str, Any]:
    """Crea una nueva dieta en el catálogo verificando que la columna sea válida."""
    nombre_limpio = nombre.strip()
    if not nombre_limpio:
        raise ValueError("El nombre de la dieta no puede estar vacío.")

    # Validar unicidad de nombre
    duplicado = sesion.execute(
        select(TipoDieta).where(func.lower(TipoDieta.nombre) == nombre_limpio.lower())
    ).scalars().first()
    if duplicado:
        raise NombreDietaDuplicado(
            f"Ya existe {_descripcion_duplicado(duplicado)} con el nombre '{nombre_limpio}'."
        )

    # Validar columna de informe
    col = _buscar_columna_informe(sesion, columna_informe)

    # Generar código si no viene
    if not codigo or not codigo.strip():
        base_codigo = re.sub(r"[^a-z0-9_]", "", nombre_limpio.lower().replace(" ", "_"))
        codigo = base_codigo or "dieta"

    codigo_limpio = codigo.strip().lower()
    dup_codigo = sesion.execute(
        select(TipoDieta).where(func.lower(TipoDieta.codigo) == codigo_limpio)
    ).scalars().first()
    if dup_codigo:
        raise NombreDietaDuplicado(
            f"Ya existe {_descripcion_duplicado(dup_codigo)} con el código '{codigo_limpio}'."
        )

    # Asignar orden si no viene
    if orden is None:
        max_orden = sesion.execute(select(func.max(TipoDieta.orden))).scalar() or 0
        orden = max_orden + 1

    nueva = TipoDieta(
        nombre=nombre_limpio,
        codigo=codigo_limpio,
        columna_informe_id=col.id,
        cuenta_racion=cuenta_racion,
        orden=orden,
        activo=activo,
    )
    sesion.add(nueva)
    sesion.commit()
    sesion.refresh(nueva)

    return _formatear_dieta(nueva, col.nombre)


def editar_dieta(
    sesion: Session,
    dieta_id: int,
    nombre: str | None = None,
    activo: bool | None = None,
    columna_informe: str | int | None = None,
    cuenta_racion: bool | None = None,
    orden: int | None = None,
) -> dict[str, Any]:
    """Edita una dieta existente (renombrar, activar/desactivar, reordenar).

    Una dieta eliminada (visible = 0) no se edita: para la API ya no existe.
    """
    tipo = sesion.get(TipoDieta, dieta_id)
    if not tipo or not tipo.visible:
        raise DietaNoEncontrada(f"La dieta con ID {dieta_id} no existe.")

    if nombre is not None:
        nombre_limpio = nombre.strip()
        if not nombre_limpio:
            raise ValueError("El nombre de la dieta no puede estar vacío.")
        duplicado = sesion.execute(
            select(TipoDieta).where(
                func.lower(TipoDieta.nombre) == nombre_limpio.lower(),
                TipoDieta.id != dieta_id,
            )
        ).scalars().first()
        if duplicado:
            raise NombreDietaDuplicado(
                f"Ya existe {_descripcion_duplicado(duplicado).replace('una', 'otra', 1)} "
                f"con el nombre '{nombre_limpio}'."
            )
        tipo.nombre = nombre_limpio

    if activo is not None:
        tipo.activo = activo

    if cuenta_racion is not None:
        tipo.cuenta_racion = cuenta_racion

    if orden is not None:
        tipo.orden = orden

    if columna_informe is not None:
        col = _buscar_columna_informe(sesion, columna_informe)
        tipo.columna_informe_id = col.id

    sesion.commit()
    sesion.refresh(tipo)

    col = sesion.get(ColumnaInformeDieta, tipo.columna_informe_id)
    col_nombre = col.nombre if col else ""
    return _formatear_dieta(tipo, col_nombre)


def eliminar_dieta(sesion: Session, dieta_id: int) -> dict[str, Any]:
    """Borrado lógico: pone `visible = 0`. La fila NUNCA se borra.

    Los hechos de `dietas_cama` apuntan a esta dieta con una FK RESTRICT y
    los informes de meses pasados la siguen necesitando; por eso eliminar es
    un UPDATE y no un DELETE. Una dieta ya eliminada responde como
    inexistente (404), igual que una que nunca existió.

    NPO no se elimina: es la única forma de registrar "esta cama no come" y
    su `cuenta_racion = 0` es lo que la deja fuera de la suma.
    """
    tipo = sesion.get(TipoDieta, dieta_id)
    if not tipo or not tipo.visible:
        raise DietaNoEncontrada(f"La dieta con ID {dieta_id} no existe.")
    if _es_npo(tipo):
        raise DietaNoEliminable(
            "NPO es especial: registra que la cama no come y no se puede eliminar."
        )

    tipo.visible = False
    sesion.commit()
    return {"eliminado": True, "id": tipo.id}
