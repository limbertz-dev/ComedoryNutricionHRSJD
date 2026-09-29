"""Endpoints del padrón de comensales."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query

from app.consultas import derecho as consultas_derecho
from app.consultas import personal as consultas
from app.consultas.personal import FiltrosPadron
from app.core import reloj
from app.core.autorizacion import UsuarioActual
from app.core.db import SesionDep
from app.esquemas.marcacion import DerechoComida
from app.esquemas.personal import Comensal, PaginaComensales

router = APIRouter(prefix="/personal", tags=["personal"])


@router.get("", response_model=PaginaComensales, summary="Padrón de comensales")
def listar_personal(
    sesion: SesionDep,
    usuario: UsuarioActual,
    busqueda: Annotated[
        str | None,
        Query(description="Busca en nombre completo, carnet o número de ítem"),
    ] = None,
    categoria_id: Annotated[int | None, Query(description="Categoría del hospital")] = None,
    servicio_id: Annotated[int | None, Query(description="Sala del hospital")] = None,
    solo_con_ficha: Annotated[
        bool, Query(description="Oculta los usuarios sin ficha en personas")
    ] = False,
    limite: Annotated[int, Query(ge=1, le=200)] = 50,
    desplazamiento: Annotated[int, Query(ge=0)] = 0,
) -> PaginaComensales:
    """Lista el padrón que consume la pantalla en vivo.

    El nombre sale de `personas`, nunca de `users.name`. Un usuario sin ficha
    aparece igual, con `tiene_ficha = false`, para que el hueco sea visible.
    """
    filtros = FiltrosPadron(
        busqueda=busqueda,
        categoria_id=categoria_id,
        servicio_id=servicio_id,
        solo_con_ficha=solo_con_ficha,
    )
    total = consultas.contar_comensales(sesion, filtros)
    datos = consultas.listar_comensales(sesion, filtros, limite, desplazamiento)

    comensales = [Comensal(**d) for d in datos]
    if usuario.rol == "cocinera":
        # La cocinera opera el lector: le alcanza el legajo (numero_item).
        # El carnet y el tipo de trabajador no salen de la jefatura.
        for comensal in comensales:
            comensal.carnet_identidad = None
            comensal.tipo_trabajador = None
    return PaginaComensales(
        total=total,
        limite=limite,
        desplazamiento=desplazamiento,
        sin_mapeo_de_categoria=sum(1 for d in datos if d["categoria_reporte"] is None),
        datos=comensales,
    )


@router.get("/{usuario_id}", response_model=Comensal, summary="Ficha de un comensal")
def obtener_personal(
    sesion: SesionDep,
    usuario: UsuarioActual,
    usuario_id: Annotated[int, Path(description="users.id, no personas.id")],
) -> Comensal:
    comensal = consultas.obtener_comensal(sesion, usuario_id)
    if comensal is None:
        raise HTTPException(status_code=404, detail="No existe ese comensal")
    ficha = Comensal(**comensal)
    if usuario.rol == "cocinera":
        ficha.carnet_identidad = None
        ficha.tipo_trabajador = None
    return ficha


@router.get(
    "/{usuario_id}/derecho",
    response_model=list[DerechoComida],
    summary="A qué comidas tiene derecho en una fecha",
)
def derecho_del_dia(
    sesion: SesionDep,
    usuario_id: Annotated[int, Path(description="users.id")],
    fecha: Annotated[
        date | None,
        Query(description="Fecha de la comida. Por defecto, hoy."),
    ] = None,
) -> list[DerechoComida]:
    """El derecho no está guardado en ninguna tabla: se deriva aquí.

    La fecha que se consulta es la de la COMIDA, no la del turno. Una guardia
    que empieza el lunes puede dar derecho a un desayuno del martes; ese
    desayuno aparece consultando el martes, no el lunes.
    """
    derechos = consultas_derecho.derechos_del_dia(
        sesion, usuario_id, fecha or reloj.hoy()
    )
    return [DerechoComida(**vars(d)) for d in derechos]
