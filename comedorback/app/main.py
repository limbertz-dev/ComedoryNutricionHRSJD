"""Punto de entrada de la API del Módulo Personal / Comensales."""

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

import app.modelos  # noqa: F401  registra las tablas propias en Base.metadata
from app.api import asistencias, auth, historial, pantalla, personal, reportes
from app.core.autorizacion import ErrorAuth, requiere_rol
from app.core.config import config
from app.core.db import Base, SesionDep
from app.core.permisos import ACCESO
from app.core.tablas_heredadas import VISTAS_CONTRATO

app = FastAPI(title=config.nombre_app, version="0.1.0")

# El front corre en otro puerto que la API, así que para el navegador son dos
# sitios distintos y bloquea las peticiones salvo que la API diga quién puede
# llamarla. Sin esto no funciona ni una pantalla.
#
# Los orígenes se listan uno por uno en .env, nunca con "*": con comodín el
# navegador rechaza las peticiones con credenciales, y el día que exista el
# login eso rompería la sesión.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.origenes,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ErrorAuth)
def _error_auth(_: Request, error: ErrorAuth) -> JSONResponse:
    """Los errores de auth llevan `motivo` para que el front decida sin
    interpretar el texto (renovar el token, pedir el cambio de clave...)."""
    return JSONResponse(
        {"detail": error.detail, "motivo": error.motivo},
        status_code=error.status_code,
        headers=error.headers,
    )


# Sin token solo responden /salud y /auth/login (y /auth/refresh, que trae el
# suyo en el cuerpo). Cada router exige los roles de su fila en la matriz de
# app/core/permisos.py: la política se lee y se cambia allá, no acá.
app.include_router(auth.router)
for modulo, recurso in (
    (pantalla, "pantalla"),
    (personal, "personal"),
    (asistencias, "asistencias"),
    (historial, "historial"),
    (reportes, "reportes"),
):
    regla = ACCESO[recurso]
    app.include_router(
        modulo.router,
        dependencies=[Depends(requiere_rol(*regla.completo, lectura=regla.lectura))],
    )


@app.get("/salud", tags=["diagnóstico"])
def salud(sesion: SesionDep):
    """Confirma que la API responde y que `bd_nutricion` está completa.

    Solo mira objetos de `bd_nutricion`: su catálogo y `alembic_version`. No
    lee ninguna vista v_* ni la base de turnos: un problema allá no tiene que
    tumbar el diagnóstico de acá, y en una base recién recreada tiene que
    responder igual. Responde 503 si falta alguna tabla o vista.
    """
    version = sesion.execute(text("SELECT VERSION()")).scalar_one()
    objetos = sesion.execute(
        text(
            "SELECT TABLE_NAME, TABLE_TYPE FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE()"
        )
    ).all()
    tablas = {nombre for nombre, tipo in objetos if tipo == "BASE TABLE"}
    vistas = {nombre for nombre, tipo in objetos if tipo == "VIEW"}

    revision = None
    if "alembic_version" in tablas:
        revision = sesion.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()

    faltan = sorted(
        (set(Base.metadata.tables) - tablas) | (set(VISTAS_CONTRATO) - vistas)
    )
    cuerpo = {
        "estado": "incompleta" if faltan else "ok",
        "base_de_datos": "conectada",
        "entorno": config.entorno,
        "base_datos": config.db_name,
        "base_turnos": config.db_name_turnos,
        "motor": f"MySQL {version}",
        "revision_alembic": revision,
        "tablas_propias": len(set(Base.metadata.tables) & tablas),
        "vistas_contrato": len(set(VISTAS_CONTRATO) & vistas),
        "faltan": faltan,
    }
    return JSONResponse(cuerpo, status_code=503 if faltan else 200)
