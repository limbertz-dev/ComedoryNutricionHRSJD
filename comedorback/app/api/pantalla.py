"""Estado de la pantalla en vivo del comedor."""

from dataclasses import asdict
from datetime import date, datetime, time
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.consultas import historial as consultas_historial
from app.consultas import pantalla as consultas
from app.core import reloj
from app.core.autorizacion import UsuarioActual, UsuarioIdentificador
from app.core.db import SesionDep
from app.esquemas.historial import ComensalDelDia, ComidaListada, HistorialDiario
from app.esquemas.marcacion import Checklist, PoliciaActivo
from app.logica import checklist as checklist_logica
from app.logica import policia as policia_logica
from app.esquemas.pantalla import (
    ComidasDelDia,
    EstadoPantalla,
    LecturasPorIdentificar,
    Marcacion,
)
from app.modelos.heredados import Comensal

router = APIRouter(prefix="/pantalla", tags=["pantalla en vivo"])


@router.get("/estado", response_model=EstadoPantalla, summary="Estado del comedor ahora")
def estado(
    sesion: SesionDep,
    fecha: Annotated[
        date | None,
        Query(description="Fecha a consultar. Por defecto, hoy."),
    ] = None,
    hora: Annotated[
        str | None,
        Query(description="Hora a consultar en formato HH:MM. Por defecto, la actual."),
    ] = None,
) -> EstadoPantalla:
    """Lo que la pantalla necesita para pintarse entera.

    Todo se calcula en el momento, sobre `asistencias` y `lecturas_biometricas`.
    No hay contadores acumulados: un contador que se incrementa se desincroniza
    tarde o temprano, y entonces la pantalla y el informe del mismo día dicen
    cosas distintas.
    """
    hora_consulta: time | None = None
    if hora is not None:
        try:
            hora_consulta = datetime.strptime(hora, "%H:%M").time()
        except ValueError as error:
            raise HTTPException(
                status_code=422,
                detail="hora debe tener el formato HH:MM",
            ) from error
    return EstadoPantalla(
        **asdict(consultas.estado(sesion, fecha=fecha, hora=hora_consulta))
    )


@router.get(
    "/ultimas-marcaciones",
    response_model=list[Marcacion],
    summary="Lo último que pasó en el lector",
)
def ultimas_marcaciones(
    sesion: SesionDep,
    usuario: UsuarioActual,
    fecha: Annotated[
        date | None,
        Query(description="Fecha a consultar. Por defecto hoy."),
    ] = None,
    comida_id: Annotated[
        int | None,
        Query(description="Filtrar por ID de comida"),
    ] = None,
    # 1000 cubre un día completo del comedor (≈450 lecturas con el padrón real).
    limite: Annotated[int, Query(ge=1, le=1000)] = 20,
) -> list[Marcacion]:
    """Incluye los rechazos: son justamente lo que la persona parada frente al
    lector necesita ver.

    Cada fila trae `origen` y `clave_evento` ('<origen>:<id>'): `id` se
    repite entre lecturas y asistencias manuales, la clave no. Es una ventana
    de lo más reciente (hasta 1000 filas), no un cursor: no garantiza entregar
    todos los eventos ocurridos entre dos consultas.

    Intervenciones de cocina: `decision_original` es lo que decidió el lector
    y no cambia; `estado_final` / `resultado_final` dicen si terminó en una
    ración. `intervencion.revision` sube cuando alguien registra una entrega
    de esa lectura (también otra cocinera): el front detecta el cambio
    comparando `revision`, aunque la `clave_evento` ya existiera. La cocinera
    no recibe datos de cuentas ajenas; la jefa ve quién registró; sistemas no
    recibe el bloque (`intervencion: null`).
    """
    return [
        Marcacion(**asdict(m))
        for m in consultas.ultimas_marcaciones(
            sesion,
            fecha=fecha,
            comida_id=comida_id,
            limite=limite,
            rol=usuario.rol,
            cuenta_id=usuario.id,
        )
    ]


@router.get(
    "/lecturas-por-identificar",
    response_model=LecturasPorIdentificar,
    summary="Las lecturas que la cocinera puede identificar ahora",
)
def lecturas_por_identificar(
    sesion: SesionDep, usuario: UsuarioIdentificador
) -> LecturasPorIdentificar:
    """Solo cocinera (jefa y sistemas: 403 `rol_no_autorizado`).

    `ultimas-marcaciones` se consulta por la FECHA de la lectura y corta en 100
    filas: una lectura de las 23:58 sigue siendo del servicio a las 00:30, pero
    ya es de "ayer" y la consulta de hoy no la trae. Esta lista parte del
    servicio actual (el mismo cómputo que el POST de identificación) y trae las
    lecturas no reconocidas pendientes de esa ventana, de ayer o de hoy, sin
    depender de la fecha ni de las 100 filas. Cada fila trae su `intervencion`
    (con `revision`) para seguirla. Una lectura que sale de la lista dejó de ser
    identificable: la resolvió alguien o terminó el servicio.
    """
    cuenta_id = usuario.id
    resultado = consultas.lecturas_por_identificar(sesion, cuenta_id)
    return LecturasPorIdentificar(**asdict(resultado))


@router.get(
    "/comidas-del-dia",
    response_model=ComidasDelDia,
    summary="Las comidas del día, con su avance",
)
def comidas_del_dia(
    sesion: SesionDep,
    fecha: Annotated[
        date | None,
        Query(description="Fecha a consultar. Por defecto hoy."),
    ] = None,
) -> ComidasDelDia:
    """Una fila por comida vigente: previstas, servidas, manuales y rechazos.

    Solo lectura, para la supervisión del día. El estado de cada franja sale
    del reloj del servidor: nunca se acepta hora del cliente.
    """
    return ComidasDelDia(**asdict(consultas.comidas_del_dia(sesion, fecha=fecha)))


@router.get(
    "/dia-personal",
    response_model=HistorialDiario,
    summary="Ficha del día de una persona",
)
def dia_personal(
    sesion: SesionDep,
    usuario: UsuarioActual,
    persona_id: Annotated[int, Query(gt=0, description="users.id, no personas.id")],
    fecha: Annotated[date | None, Query(description="Por defecto, hoy")] = None,
) -> HistorialDiario:
    """La tira del día que la pantalla muestra tras una marcación.

    Misma forma y mismas reglas que GET /historial/diario, acotada a una
    persona, para que la cocinera la vea sin abrir el historial completo.
    `datos` trae su ficha, o viene vacío si ese día no tenía derecho ni
    recibió ración (tampoco aparecería en el historial).
    """
    if sesion.get(Comensal, persona_id) is None:
        raise HTTPException(status_code=404, detail="No existe ese comensal")
    fecha = fecha or reloj.hoy()
    total, comidas, datos = consultas_historial.historial_diario(
        sesion, fecha, limite=1, usuario_id=persona_id
    )
    fichas = [ComensalDelDia(**asdict(d)) for d in datos]
    if usuario.rol == "cocinera":
        for ficha in fichas:
            ficha.carnet_identidad = None
    return HistorialDiario(
        fecha=fecha,
        total=total,
        limite=1,
        desplazamiento=0,
        comidas=[ComidaListada(**asdict(c)) for c in comidas],
        datos=fichas,
    )


@router.get(
    "/policias",
    response_model=list[PoliciaActivo],
    summary="Policías con huella activa",
)
def policias(sesion: SesionDep) -> list[PoliciaActivo]:
    """Para que cocina elija a un policía cuando el lector no reconoce su
    huella. Solo nombre y CI/placa; nunca plantillas."""
    return [PoliciaActivo(**p) for p in policia_logica.listar_activos(sesion)]


@router.get(
    "/checklist",
    response_model=Checklist,
    summary="Checklist de la comida en curso",
)
def checklist(sesion: SesionDep, usuario: UsuarioActual) -> Checklist:
    """Quiénes tienen derecho a la comida que está abierta (turno de 12 h o
    más, categorías permitidas, sin novedad) y si ya recibieron su ración.
    Fuera de horario: `fuera_de_horario=true` y lista vacía."""
    cuenta_id = usuario.id
    return Checklist(**asdict(checklist_logica.listar(sesion, cuenta_id)))
