"""Las 36 tablas que ya existen en la base del módulo de turnos.

Este sistema las lee y las referencia, pero NO las administra: no crea,
no altera y no borra ninguna. Son de solo lectura sin excepciones: ni
siquiera se les agrega una columna. Lo que este sistema necesita saber
de ellas vive en tablas propias que las referencian por FK.

Alembic consulta esta lista en alembic/env.py para excluirlas de la
comparación. Sin ese filtro, el primer `revision --autogenerate` generaría
un DROP TABLE por cada tabla del otro ingeniero.
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

VISTAS_HEREDADAS: frozenset[str] = frozenset({"vw_personal_comidas_externo"})
