"""Intervenciones de cocina: la consulta de la jefa.

CONTRATO con el front (no cambiar sin avisar):

    GET /intervenciones-cocina
        ?desde&hasta&resultado&motivo_rechazo&comida_id&cuenta_id&usuario_id
        &limite&desplazamiento

Solo jefa (ACCESO["intervenciones"]): la cocinera y sistemas reciben 403. La
jefa consulta; no aprueba ni ejecuta nada. Quien crea las intervenciones es la
cocinera, con POST /asistencias/lecturas/{id}/identificar.

`registrada` es una entrega; `rechazada` es un intento que no la tuvo. Los
registros manuales independientes de jefatura NO aparecen aquí.
"""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status

from app.consultas import intervenciones as consultas
from app.core import reloj
from app.core.autorizacion import ErrorAuth
from app.core.db import SesionDep
from app.esquemas.auth import ErrorConMotivo
from app.esquemas.intervenciones import (
    ComensalIntervenido,
    CuentaResponsable,
    DecisionOriginalLectura,
    Intervencion,
    PaginaIntervenciones,
    ResultadoDelIntento,
    ServicioUsado,
    TotalesIntervenciones,
)
router = APIRouter(prefix="/intervenciones-cocina", tags=["intervenciones de cocina"])

# Los mismos de modelos.comedor.MOTIVOS_RECHAZO_INTERVENCION; un Literal no
# acepta una tupla en tiempo de ejecución, así que se repiten (los cubre una
# prueba).
MotivoRechazo = Literal[
    "sin_derecho",
    "duplicado",
    "lectura_ya_resuelta",
    "lectura_no_resoluble",
    "servicio_distinto",
    "servicio_no_determinable",
    "reloj_inconsistente",
]


def _intervencion(fila: dict) -> Intervencion:
    servicio_conocido = fila["comida_id"] is not None
    return Intervencion(
        id=fila["id"],
        clave_evento=consultas.clave_evento(fila["id"]),
        resultado=fila["resultado"],
        motivo_rechazo=fila["motivo_rechazo"],
        causa=fila["causa"],
        momento=fila["momento"],
        decision_original=DecisionOriginalLectura(
            lectura_id=fila["lectura_id"],
            resultado=fila["lectura_resultado"],
            motivo=fila["lectura_motivo"],
            fecha_hora=fila["lectura_fecha_hora"],
            dispositivo=fila["lectura_dispositivo"],
        ),
        cuenta=CuentaResponsable(
            id=fila["cuenta_id"],
            usuario=fila["cuenta_usuario"],
            nombre=fila["cuenta_nombre"],
        ),
        comensal=ComensalIntervenido(
            usuario_id=fila["usuario_id"],
            nombre=fila["comensal_nombre"],
            categoria=fila["comensal_categoria"],
        ),
        servicio_usado=ServicioUsado(
            comida_id=fila["comida_id"],
            comida=fila["nombre_comida"],
            fecha_comida=fila["fecha_comida"],
            ventana_inicio=fila["ventana_inicio"],
            ventana_fin=fila["ventana_fin"],
            origen=fila["origen_servicio"] if servicio_conocido else None,
        ),
        resultado_final=ResultadoDelIntento(
            entrega_registrada=fila["resultado"] == "registrada",
            asistencia_id=fila["asistencia_id"],
        ),
        estado_actual_lectura="resuelta" if fila["lectura_resuelta"] else "pendiente",
    )


@router.get(
    "",
    response_model=PaginaIntervenciones,
    summary="Intervenciones de cocina",
    responses={403: {"model": ErrorConMotivo}, 422: {"model": ErrorConMotivo}},
)
def listar_intervenciones(
    sesion: SesionDep,
    desde: Annotated[
        date | None, Query(description="Primer día, por momento de la intervención. Por defecto, hoy.")
    ] = None,
    hasta: Annotated[
        date | None, Query(description="Último día, inclusive. Por defecto, hoy.")
    ] = None,
    resultado: Annotated[Literal["registrada", "rechazada"] | None, Query()] = None,
    motivo_rechazo: Annotated[MotivoRechazo | None, Query()] = None,
    comida_id: Annotated[int | None, Query(gt=0)] = None,
    cuenta_id: Annotated[int | None, Query(gt=0)] = None,
    usuario_id: Annotated[int | None, Query(gt=0)] = None,
    limite: Annotated[int, Query(ge=1, le=100)] = 50,
    desplazamiento: Annotated[int, Query(ge=0)] = 0,
) -> PaginaIntervenciones:
    """Las intervenciones del rango, la más reciente primero.

    `total` y `totales` cubren todo el filtro, no solo la página. Un rango de
    más de 31 días da 422 `rango_demasiado_largo`.
    """
    hoy = reloj.hoy()
    desde = desde or hoy
    hasta = hasta or hoy
    if desde > hasta:
        raise ErrorAuth(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "rango_invalido",
            "'desde' no puede ser posterior a 'hasta'.",
        )
    if (hasta - desde).days + 1 > consultas.MAXIMO_DIAS:
        raise ErrorAuth(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "rango_demasiado_largo",
            f"El rango no puede pasar de {consultas.MAXIMO_DIAS} días.",
        )

    filtros = consultas.Filtros(
        desde=desde,
        hasta=hasta,
        resultado=resultado,
        motivo_rechazo=motivo_rechazo,
        comida_id=comida_id,
        cuenta_id=cuenta_id,
        usuario_id=usuario_id,
    )
    total, totales, filas = consultas.listar(sesion, filtros, limite, desplazamiento)
    return PaginaIntervenciones(
        desde=desde,
        hasta=hasta,
        total=total,
        limite=limite,
        desplazamiento=desplazamiento,
        totales=TotalesIntervenciones(**totales),
        datos=[_intervencion(f) for f in filas],
    )
