"""Punto de entrada de la API del Módulo Personal / Comensales."""

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

import app.modelos  # noqa: F401  registra las tablas propias en Base.metadata
from app.api import (
    admin,
    asistencias,
    auth,
    cuentas,
    historial,
    intervenciones,
    lector,
    monitoreo,
    pantalla,
    personal,
    policias,
    reglas,
    reportes,
)
from app.core.autorizacion import ErrorAuth, requiere_rol
from app.core.config import config
from app.core.db import Base, SesionDep
from app.core.entorno import EntornoDep, validar_entorno
from app.core.permisos import ACCESO
from app.core.tablas_heredadas import VISTAS_CONTRATO


def _error_auth(_: Request, error: ErrorAuth) -> JSONResponse:
    """Los errores de auth llevan `motivo` para que el front decida sin
    interpretar el texto (renovar el token, pedir el cambio de clave...)."""
    return JSONResponse(
        {"detail": error.detail, "motivo": error.motivo},
        status_code=error.status_code,
        headers=error.headers,
    )


diagnostico = APIRouter(tags=["diagnóstico"])


@diagnostico.get("/salud")
def salud(sesion: SesionDep, entorno: EntornoDep):
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
        "entorno": entorno,
        "base_datos": config.db_name,
        "base_turnos": config.db_name_turnos,
        "motor": f"MySQL {version}",
        "revision_alembic": revision,
        "tablas_propias": len(set(Base.metadata.tables) & tablas),
        "vistas_contrato": len(set(VISTAS_CONTRATO) & vistas),
        "faltan": faltan,
    }
    return JSONResponse(cuerpo, status_code=503 if faltan else 200)


def crear_app(entorno: str = config.entorno) -> FastAPI:
    """Arma la API para `entorno`. Los tests lo pasan explícito para probar
    los entornos en un mismo proceso.

    El entorno queda fijo en `app.state.entorno` y es la fuente del `entorno`
    que informan /salud y /monitoreo/estado (ver app/core/entorno.py).
    `config.entorno` es solo el valor por omisión de este argumento.
    """
    entorno = validar_entorno(entorno)
    app = FastAPI(title=config.nombre_app, version="0.1.0")
    app.state.entorno = entorno

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
    app.add_exception_handler(ErrorAuth, _error_auth)

    # Sin token solo responden /salud y /auth/login (y /auth/refresh, que trae el
    # suyo en el cuerpo). Cada router exige los roles de su fila en la matriz de
    # app/core/permisos.py: la política se lee y se cambia allá, no acá.
    app.include_router(auth.router)
    routers = [
        (pantalla, "pantalla"),
        (personal, "personal"),
        (asistencias, "asistencias"),
        (historial, "historial"),
        (reportes, "reportes"),
        (admin, "admin"),
        (reglas, "reglas"),
        (cuentas, "cuentas"),
        (monitoreo, "monitoreo"),
        (intervenciones, "intervenciones"),
        (lector.vinculos, "lector_vinculos"),
        (policias, "policias"),
    ]
    for modulo, recurso in routers:
        regla = ACCESO[recurso]
        app.include_router(
            modulo if isinstance(modulo, APIRouter) else modulo.router,
            dependencies=[Depends(requiere_rol(*regla.completo, lectura=regla.lectura))],
        )
    # El lector se autentica con su propia clave (X-Lector-Token), no con la
    # sesión de una persona: no pasa por requiere_rol.
    app.include_router(lector.router)
    app.include_router(diagnostico)
    return app


app = crear_app()
