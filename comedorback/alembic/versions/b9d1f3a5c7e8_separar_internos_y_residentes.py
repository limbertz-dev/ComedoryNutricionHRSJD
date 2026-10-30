"""separar internos y residentes

Revision ID: b9d1f3a5c7e8
Revises: a7c9e1b3d5f6
Create Date: 2026-10-29

El informe juntaba internos y residentes en la columna «Médico», pero en el
rol de turnos del personal de salud son grupos distintos y son los que más
comen. La jefatura los quiere separados. Las columnas quedan en el orden
de su hoja, más Técnicos, que sigue comiendo:

    Internos · Residentes · Policías · Médicos · Técnicos · Sin clasificar

Mapeo nuevo (solo para las categorías que existan en v_categorias):
  · Internos, Internos-Medicina, -Bioquimica, -Imagenologia, -Fisioterapia
    -> internos (antes medico o tecnicos)
  · Residentes -> residentes (antes medico)

Las raciones ya servidas NO se reclasifican: su columna se congeló al
servirlas (asistencias.categoria_reporte_id), como cualquier otro cambio de
mapeo. Solo las raciones nuevas caen en las columnas nuevas.

El downgrade devuelve el mapeo anterior y desactiva las dos columnas (no
las borra: un período con raciones en ellas las sigue mostrando).
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'b9d1f3a5c7e8'
down_revision: Union[str, Sequence[str], None] = 'a7c9e1b3d5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INTERNOS = (
    'Internos', 'Internos-Medicina', 'Internos-Bioquimica',
    'Internos-Imagenologia', 'Internos-Fisioterapia',
)
RESIDENTES = ('Residentes',)

ORDEN_NUEVO = {
    'internos': 1, 'residentes': 2, 'policias': 3, 'medico': 4,
    'tecnicos': 5, 'servicio': 6, 'administrativo': 7,
}
ORDEN_VIEJO = {
    'medico': 1, 'servicio': 2, 'administrativo': 3, 'tecnicos': 4,
    'policias': 5, 'internos': 6, 'residentes': 7,
}
MAPEO_VIEJO = {
    'medico': ('Internos', 'Internos-Medicina', 'Residentes'),
    'tecnicos': ('Internos-Bioquimica', 'Internos-Imagenologia', 'Internos-Fisioterapia'),
}


def _lista(nombres) -> str:
    return ", ".join("'%s'" % n for n in nombres)


def _mapear(nombres, codigo: str) -> None:
    """Apunta esas categorías a la columna `codigo`; las que no tenían mapeo
    se agregan. Las que no existen en v_categorias se ignoran."""
    columna = f"(SELECT id FROM categorias_reporte WHERE codigo = '{codigo}')"
    categorias = f"SELECT id FROM v_categorias WHERE nombre IN ({_lista(nombres)})"
    op.execute(
        f"UPDATE categoria_reporte_map SET categoria_reporte_id = {columna} "
        f"WHERE categoria_id IN ({categorias})"
    )
    op.execute(
        f"INSERT INTO categoria_reporte_map (categoria_id, categoria_reporte_id) "
        f"SELECT v.id, {columna} FROM v_categorias v "
        f"WHERE v.nombre IN ({_lista(nombres)}) "
        f"AND v.id NOT IN (SELECT categoria_id FROM categoria_reporte_map)"
    )


def _ordenar(orden: dict) -> None:
    for codigo, numero in orden.items():
        op.execute(f"UPDATE categorias_reporte SET orden = {numero} WHERE codigo = '{codigo}'")


def upgrade() -> None:
    """Upgrade schema."""
    for nombre, codigo in (('Internos', 'internos'), ('Residentes', 'residentes')):
        op.execute(
            f"INSERT INTO categorias_reporte (nombre, codigo, orden, activo) "
            f"SELECT '{nombre}', '{codigo}', 0, 1 FROM DUAL "
            f"WHERE NOT EXISTS (SELECT 1 FROM categorias_reporte WHERE codigo = '{codigo}')"
        )
        op.execute(f"UPDATE categorias_reporte SET activo = 1 WHERE codigo = '{codigo}'")
    op.execute("UPDATE categorias_reporte SET nombre = 'Médicos' WHERE codigo = 'medico'")
    _ordenar(ORDEN_NUEVO)
    _mapear(INTERNOS, 'internos')
    _mapear(RESIDENTES, 'residentes')


def downgrade() -> None:
    """Downgrade schema."""
    for codigo, nombres in MAPEO_VIEJO.items():
        _mapear(nombres, codigo)
    op.execute(
        "UPDATE categorias_reporte SET activo = 0 WHERE codigo IN ('internos', 'residentes')"
    )
    op.execute("UPDATE categorias_reporte SET nombre = 'Médico' WHERE codigo = 'medico'")
    _ordenar(ORDEN_VIEJO)
