"""Los objetos que NO administra este sistema, y las vistas que los leen.

Arquitectura de dos bases (ver app/core/config.py):

  · `bd_proyecto_backend` (DB_NAME_TURNOS) tiene las 36 tablas del módulo de
    turnos. Es del otro ingeniero y es de solo lectura sin excepciones: no se
    crea, no se altera, no se borra, no se le agrega ni una columna, y ninguna
    tabla nuestra le apunta con una FK (una FK entre bases también lo ata: le
    impediría borrar un usuario o migrar su propio esquema).

  · `bd_nutricion` (DB_NAME) es la nuestra: 6 tablas propias + las 9 vistas
    de VISTAS_CONTRATO, que son la ÚNICA superficie por la que se lee la base
    de turnos.

Alembic consulta estas listas en alembic/env.py para excluirlas de la
comparación. Las tablas heredadas ya no existen en `bd_nutricion`, pero el
filtro se conserva: si alguien apunta alembic a una copia vieja que todavía
las tenga, el autogenerate no debe proponer un DROP TABLE por cada una.
"""

TABLAS_HEREDADAS: frozenset[str] = frozenset(
    {
        "admin_authorizations",
        "areas",
        "cache",
        "cache_locks",
        "categoria_role",
        "categorias",
        "comidas",
        "configuraciones",
        "failed_jobs",
        "gestiones",
        "incidencias_tecnicas",
        "job_batches",
        "jobs",
        "kardex_vacaciones",
        "meses",
        "migrations",
        "novedades_laborales",
        "password_reset_tokens",
        "permission_role",
        "permissions",
        "personal_access_tokens",
        "personas",
        "role_servicio",
        "role_user",
        "roles",
        "roles_estados",
        "semanas",
        "servicio_turno",
        "servicios",
        "sessions",
        "turno_comida",
        "turnos",
        "turnos_asignados",
        "users",
        "usuario_servicios",
        "vacaciones",
    }
)

# Vista del módulo de turnos que NO usamos: hace INNER JOIN con personas y
# esconde a los usuarios sin ficha. Se lista solo para excluirla.
VISTAS_HEREDADAS: frozenset[str] = frozenset({"vw_personal_comidas_externo"})

# Las 9 vistas del contrato de lectura. Viven en bd_nutricion, las crea la
# migración 0c294cd98c3a y leen bd_proyecto_backend. Se mapean en
# app/modelos/heredados.py sobre una metadata aparte, así que alembic nunca
# las ve como tablas por crear.
VISTAS_CONTRATO: tuple[str, ...] = (
    "v_comensales",
    "v_categorias",
    "v_servicios",
    "v_comidas",
    "v_usuario_servicios",
    "v_turnos_asignados",
    "v_turno_comida",
    "v_novedades_laborales",
    "v_comidas_por_turno",
)
