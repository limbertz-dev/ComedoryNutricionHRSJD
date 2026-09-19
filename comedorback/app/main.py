"""Punto de entrada de la API del Módulo Personal / Comensales."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import asistencias, historial, pantalla, personal, reportes
from app.core.config import config
from app.core.db import SesionDep

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

app.include_router(pantalla.router)
app.include_router(personal.router)
app.include_router(asistencias.router)
app.include_router(historial.router)
app.include_router(reportes.router)


@app.get("/salud", tags=["diagnóstico"])
def salud(sesion: SesionDep) -> dict:
    """Confirma que la API responde y que la base de datos contesta."""
    version = sesion.execute(text("SELECT VERSION()")).scalar_one()
    comensales = sesion.execute(text("SELECT COUNT(*) FROM personas")).scalar_one()
    return {
        "estado": "ok",
        "base_de_datos": "conectada",
        "entorno": config.entorno,
        "base_datos": config.db_name,
        "motor": f"MySQL {version}",
        "comensales_en_padron": comensales,
    }
