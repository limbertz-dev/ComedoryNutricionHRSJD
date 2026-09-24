"""vistas del contrato de lectura con la base de turnos

Revision ID: 0c294cd98c3a
Revises: ff4ddf3c8a18
Create Date: 2026-09-24

Crea en `bd_nutricion` las 9 vistas v_* que leen `bd_proyecto_backend`. Son
la ÚNICA superficie por la que este sistema toca la base del otro ingeniero:
si mañana él renombra una columna, se arregla en una migración nueva que
redefine la vista y ninguna consulta de app/consultas/ se entera.

Antes vivían en sql/vistas/contrato_turnos.sql, fuera del control de
versiones (el .gitignore de la raíz excluye todo *.sql, con razón: ahí van
los volcados con datos del hospital). Como migración quedan versionadas,
viajan con el esquema y `alembic downgrade` sabe quitarlas.

El nombre de la base de turnos NO está fijo: sale de DB_NAME_TURNOS. Estas
sentencias solo hacen CREATE/DROP VIEW dentro de `bd_nutricion`; sobre la
base de turnos no se ejecuta nada, solo se la nombra en los SELECT.

Tres reglas que no son cosméticas:

  1. SQL SECURITY INVOKER. Sin esto la vista corre con los permisos del que
     la creó (root) y no con los del usuario de la aplicación: la separación
     de privilegios quedaría decorativa.

  2. Siempre LEFT JOIN hacia `personas` y `categorias`. Un usuario sin ficha
     tiene que aparecer igual, con `tiene_ficha = 0`, para que el hueco sea
     visible. La vista vw_personal_comidas_externo del módulo heredado usa
     INNER JOIN y por eso esconde a esa gente; no la usamos.

  3. Ninguna vista aplica reglas de negocio. El derecho a comer (turno de
     12 h o más, sin novedad que lo anule, enfermería fuera) se deriva en
     app/consultas/derecho.py, que es el punto único de verdad.

Cambio respecto del .sql original: `v_comensales` ahora garantiza UNA fila
por users.id (toma la ficha de menor id si `personas.user_id` trajera
duplicados, porque esa columna no tiene índice único y no es nuestra para
agregárselo) y entrega el nombre con los espacios ya limpiados: el padrón
trae basura como "    JEREZ    DURAN    ALVARO". Las consultas hacían las dos
cosas cada una por su cuenta; ahora lo hace la vista una sola vez.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.core.config import config
from app.core.tablas_heredadas import VISTAS_CONTRATO

revision: str = "0c294cd98c3a"
down_revision: Union[str, Sequence[str], None] = "ff4ddf3c8a18"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _base_turnos() -> str:
    nombre = config.db_name_turnos
    if not nombre or "`" in nombre:
        raise ValueError(f"DB_NAME_TURNOS inválido: {nombre!r}")
    return f"`{nombre}`"


VISTAS = {
    # Padrón de comensales. El eje es users.id, nunca personas.id: las tablas
    # de turnos apuntan a users. El nombre sale SIEMPRE de
    # personas.nombre_completo, nunca de users.name, que es un login.
    "v_comensales": """
SELECT
    u.`id`                                                AS `usuario_id`,
    REGEXP_REPLACE(TRIM(p.`nombre_completo`), '[[:space:]]+', ' ')
                                                          AS `nombre_completo`,
    p.`carnet_identidad`                                  AS `carnet_identidad`,
    p.`tipo_trabajador`                                   AS `tipo_trabajador`,
    p.`numero_tipo_salario`                               AS `numero_item`,
    u.`categoria_id`                                      AS `categoria_id`,
    c.`nombre`                                            AS `categoria`,
    c.`nivel`                                             AS `categoria_nivel`,
    (p.`id` IS NOT NULL)                                  AS `tiene_ficha`
FROM {t}.`users` u
LEFT JOIN (
    SELECT `user_id`, MIN(`id`) AS `persona_id`
    FROM {t}.`personas`
    GROUP BY `user_id`
) fp ON fp.`user_id` = u.`id`
LEFT JOIN {t}.`personas`   p ON p.`id` = fp.`persona_id`
LEFT JOIN {t}.`categorias` c ON c.`id` = u.`categoria_id`
""",
    # Catálogos. Se exponen tal cual: son estables y este sistema solo los lee.
    "v_categorias": """
SELECT `id`, `nombre`, `nivel`, `descripcion`
FROM {t}.`categorias`
""",
    "v_servicios": """
SELECT `id`, `nombre`, `descripcion`, `cantidad_pacientes`
FROM {t}.`servicios`
""",
    # `estado` es el activo/inactivo del módulo de turnos. Se expone sin
    # filtrar: decidir qué comida cuenta es del lado del comedor.
    "v_comidas": """
SELECT `id`, `nombre`, `codigo`, `estado`
FROM {t}.`comidas`
""",
    "v_usuario_servicios": """
SELECT `id`, `usuario_id`, `servicio_id`, `estado`, `fecha_ingreso`
FROM {t}.`usuario_servicios`
""",
    # Turnos asignados con la duración ya resuelta. `duracion_horas` NO se
    # puede calcular de hora_inicio/hora_fin: el turno 90 dura 30 horas y
    # figura como 06:00-12:00. Es el dato que declara el hospital.
    "v_turnos_asignados": """
SELECT
    ta.`id`               AS `turno_asignado_id`,
    ta.`usuario_id`       AS `usuario_id`,
    ta.`servicio_id`      AS `servicio_id`,
    ta.`area_id`          AS `area_id`,
    ta.`fecha`            AS `fecha`,
    ta.`estado`           AS `estado`,
    ta.`es_intercambio`   AS `es_intercambio`,
    t.`id`                AS `turno_id`,
    t.`nombre_turno`      AS `turno`,
    t.`hora_inicio`       AS `hora_inicio`,
    t.`hora_fin`          AS `hora_fin`,
    t.`duracion_horas`    AS `duracion_horas`,
    t.`categoria_id`      AS `turno_categoria_id`
FROM {t}.`turnos_asignados` ta
JOIN {t}.`turnos` t ON t.`id` = ta.`turno_id`
""",
    # Qué comidas otorga cada turno y con cuántos días de corrimiento.
    # "La regla habilita, turno_comida otorga": un turno de 12 h sin filas acá
    # sigue sin dar derecho a nada.
    "v_turno_comida": """
SELECT `id`, `turno_id`, `comida_id`, `dia_relativo`
FROM {t}.`turno_comida`
""",
    # Se consultan, nunca se escriben. `devolucion_turno` NO anula el derecho;
    # el filtro se aplica en derecho.py, no acá.
    "v_novedades_laborales": """
SELECT
    `id`,
    `asignacion_id`,
    `tipo_novedad`,
    `usuario_solicitante_id`,
    `usuario_reemplazo_id`,
    `fecha_original`,
    `fecha_nueva`,
    `con_devolucion`
FROM {t}.`novedades_laborales`
""",
    # El cruce que da origen al derecho, sin las reglas aplicadas:
    #     fecha_comida = turnos_asignados.fecha + turno_comida.dia_relativo
    # Sale del derecho, nunca del reloj: así una guardia de 32 horas recibe
    # DOS desayunos en fechas distintas sin chocar con el índice único.
    "v_comidas_por_turno": """
SELECT
    ta.`id`                                       AS `turno_asignado_id`,
    ta.`usuario_id`                               AS `usuario_id`,
    ta.`servicio_id`                              AS `servicio_id`,
    ta.`fecha`                                    AS `fecha_turno`,
    tc.`dia_relativo`                             AS `dia_relativo`,
    (ta.`fecha` + INTERVAL tc.`dia_relativo` DAY) AS `fecha_comida`,
    co.`id`                                       AS `comida_id`,
    co.`nombre`                                   AS `comida`,
    t.`id`                                        AS `turno_id`,
    t.`nombre_turno`                              AS `turno`,
    t.`duracion_horas`                            AS `duracion_horas`,
    u.`categoria_id`                              AS `categoria_id`,
    cat.`nombre`                                  AS `categoria`
FROM {t}.`turnos_asignados` ta
JOIN {t}.`turnos`       t   ON t.`id`       = ta.`turno_id`
JOIN {t}.`turno_comida` tc  ON tc.`turno_id` = t.`id`
JOIN {t}.`comidas`      co  ON co.`id`      = tc.`comida_id`
JOIN {t}.`users`        u   ON u.`id`       = ta.`usuario_id`
LEFT JOIN {t}.`categorias` cat ON cat.`id` = u.`categoria_id`
""",
}

assert tuple(VISTAS) == VISTAS_CONTRATO, "VISTAS y VISTAS_CONTRATO deben coincidir"


def upgrade() -> None:
    base = _base_turnos()
    for nombre, cuerpo in VISTAS.items():
        sql = (
            f"CREATE OR REPLACE SQL SECURITY INVOKER VIEW `{nombre}` AS "
            + cuerpo.format(t=base)
        )
        # text() leería `[[:space:]]` como un parámetro `:spac...`. Ninguna
        # vista lleva parámetros, así que todo ':' se escapa como literal.
        op.execute(sa.text(sql.replace(":", r"\:")))


def downgrade() -> None:
    for nombre in reversed(VISTAS):
        op.execute(f"DROP VIEW IF EXISTS `{nombre}`")
