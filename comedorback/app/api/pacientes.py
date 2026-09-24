"""API del Módulo Pacientes: dietas de internados.

Endpoints de diagnóstico, Control de Dietas (la vista del día y las tres
escrituras: asignar, suspender y reanudar), los dos reportes de pacientes,
las raciones manuales sin cama y Catálogo de Dietas.

Lo que esta API NO hace: no da de alta camas, ni salas, ni pacientes,
ni traslados. Todo eso lo administra el hospital en el SIH y acá se LEE.
"""

from dataclasses import asdict
from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.consultas import control as consultas_control
from app.consultas import dietas as consultas_dietas
from app.consultas import raciones_manuales as consultas_manuales
from app.consultas import reportes_pacientes as consultas_reportes
from app.core.db import SesionDep
from app.core.db_sih import estado_sih
from app.esquemas.pacientes import (
    AsignarDietaIn,
    CambioEstadoIn,
    ControlDelDiaOut,
    CrearDietaIn,
    DietaOut,
    EditarDietaIn,
    EliminarDietaOut,
    HechoRegistradoOut,
    HojaFiltro,
    MatrizRacionesDiaOut,
    RacionesDiaIn,
    RacionManualCreadaOut,
    RacionManualIn,
    RacionesManualesOut,
    ReporteDistribucionOut,
    SalaFiltro,
    SaludSih,
    SinClasificarFiltro,
)

router = APIRouter(prefix="/pacientes", tags=["pacientes"])

Fecha = Annotated[
    date | None,
    Query(description="Día a mostrar. Por defecto, hoy."),
]


# ==========================================================================
# Matriz diaria de raciones por servicio (raciones_servicio_dia)
# ==========================================================================


@router.get(
    "/raciones-dia",
    response_model=MatrizRacionesDiaOut,
    summary="Matriz de raciones por servicio y tipo de dieta del día",
)
def raciones_dia(sesion: SesionDep, fecha: Fecha = None) -> MatrizRacionesDiaOut:
    """La matriz de 16 servicios × 9 columnas del informe para una fecha.

    Una celda sin registro vale 0. Por defecto muestra hoy.
    """
    matriz = consultas_reportes.obtener_matriz_dia(sesion, fecha or date.today())
    return MatrizRacionesDiaOut(**asdict(matriz))


@router.put(
    "/raciones-dia",
    response_model=MatrizRacionesDiaOut,
    summary="Actualizar celdas de la matriz de raciones del día",
)
def guardar_raciones_dia(
    sesion: SesionDep, cuerpo: RacionesDiaIn
) -> MatrizRacionesDiaOut:
    """Inserta una fila por celda cuyo valor cambió respecto del vigente.

    Valida que la fecha no sea futura, que las filas y columnas existan en
    la planilla oficial y que las cantidades sean enteros >= 0. Celdas con
    el mismo valor no insertan nada (solo INSERT, nunca UPDATE).
    """
    try:
        matriz = consultas_reportes.guardar_matriz_dia(
            sesion,
            fecha=cuerpo.fecha,
            celdas_input=cuerpo.celdas,
        )
    except ValueError as err:
        raise HTTPException(422, str(err)) from err
    return MatrizRacionesDiaOut(**asdict(matriz))


# ==========================================================================
# LEGADO: Diagnóstico y Control de Dietas por cama (dietas_cama sin uso activo)
# ==========================================================================


@router.get(
    "/salud-sih",
    response_model=SaludSih,
    summary="Estado de la conexión al SIH y divergencia con ListaInternados",
)
def salud_sih() -> SaludSih:
    """Dice si el SIH contesta y cuánto difiere de la vista del hospital.

    Devuelve 200 aunque el SIH esté caído, a propósito: esto es un
    diagnóstico, y un 503 obligaría al frontend a tratar "no hay SIH" como
    un error de la API en vez de como el estado normal que es. El detalle
    viaja en `conectado` y `mensaje`.

    No toca MySQL: no necesita sesión.
    """
    estado = estado_sih()
    return SaludSih(**asdict(estado))


@router.get(
    "/control",
    response_model=ControlDelDiaOut,
    summary="Control de Dietas: una fila por cama ocupada con su dieta vigente",
)
def control(
    sesion: SesionDep,
    fecha: Fecha = None,
    sala: SalaFiltro = None,
    hoja: HojaFiltro = None,
    sin_clasificar: SinClasificarFiltro = False,
) -> ControlDelDiaOut:
    """El censo del día cruzado con la última dieta de cada cama.

    Devuelve 200 aunque el SIH no conteste: `sih_disponible` y `sih_mensaje`
    llevan el detalle y las filas ya cargadas siguen viéndose.

    `?sala=<sa_codigo>`, `?hoja=<texto>` y `?sin_clasificar=true` recortan las
    filas y se combinan entre sí (AND). Una sala u hoja sin camas da lista
    vacía, no error; una sala que no es entero > 0 da 422.
    """
    dia = consultas_control.control_del_dia(
        sesion,
        fecha or date.today(),
        consultas_control.FiltroControl(sala=sala, hoja=hoja, sin_clasificar=sin_clasificar),
    )
    return ControlDelDiaOut(
        fecha=dia.fecha,
        es_hoy=dia.es_hoy,
        sih_disponible=dia.sih_disponible,
        sih_mensaje=dia.sih_mensaje,
        leido_en=dia.leido_en,
        total_camas=dia.total_camas,
        con_dieta=dia.con_dieta,
        sin_dieta=dia.sin_dieta,
        suspendidas=dia.suspendidas,
        sin_clasificar=dia.sin_clasificar,
        raciones=dia.raciones,
        filas=[asdict(f) for f in dia.filas],
    )


# ==========================================================================
# Control de Dietas: escritura. Siempre INSERT, nunca UPDATE.
# ==========================================================================


def _registrar(accion, **datos) -> HechoRegistradoOut:
    """Corre una escritura de `consultas/control.py` y traduce sus errores.

    Las tres rutas terminan igual: una fila nueva en `dietas_cama` o un error
    del negocio con su código HTTP.
    """
    try:
        fila = accion(**datos)
    except consultas_control.CamaFueraDelCenso as err:
        raise HTTPException(status.HTTP_409_CONFLICT, str(err)) from err
    except consultas_control.SinDietaVigente as err:
        raise HTTPException(status.HTTP_409_CONFLICT, str(err)) from err
    except consultas_control.SihNoDisponible as err:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(err)) from err
    except ValueError as err:
        # Dieta inexistente, eliminada (visible = 0) o dada de baja.
        raise HTTPException(422, str(err)) from err
    return HechoRegistradoOut(
        dietas_cama_id=fila.id,
        fecha=fila.fecha,
        momento=fila.momento,
        cam_codigo=fila.cam_codigo,
        tipo_dieta_id=fila.tipo_dieta_id,
        suspendida=bool(fila.suspendida),
        motivo=fila.motivo,
        servicio_nutricion_id=fila.servicio_nutricion_id,
        nombre_paciente=fila.nombre_paciente,
    )


@router.post(
    "/control",
    response_model=HechoRegistradoOut,
    status_code=status.HTTP_201_CREATED,
    summary="Asignar o cambiar la dieta de una cama",
)
def asignar_dieta(sesion: SesionDep, cuerpo: AsignarDietaIn) -> HechoRegistradoOut:
    """Inserta un hecho nuevo con la dieta elegida. Nunca actualiza el anterior.

    El paciente, la sala y la pieza salen del censo del SIH leído en este
    momento, no del cuerpo. Cama que el SIH no da por ocupada: 409. Dieta
    inexistente, eliminada o dada de baja: 422. SIH caído: 503.
    """
    return _registrar(
        consultas_control.asignar_dieta,
        sesion=sesion,
        cam_codigo=cuerpo.cam_codigo,
        tipo_dieta_id=cuerpo.tipo_dieta_id,
        motivo=cuerpo.motivo,
        prescripcion_texto=cuerpo.prescripcion_texto,
    )


@router.post(
    "/control/suspender",
    response_model=HechoRegistradoOut,
    status_code=status.HTTP_201_CREATED,
    summary="Suspender la comida de una cama sin perder su dieta",
)
def suspender_dieta(sesion: SesionDep, cuerpo: CambioEstadoIn) -> HechoRegistradoOut:
    """Inserta un hecho con `suspendida = 1` y la misma dieta vigente.

    Sin dieta hoy o ya suspendida: 409. Cama fuera del censo: 409.
    """
    return _registrar(
        consultas_control.suspender,
        sesion=sesion,
        cam_codigo=cuerpo.cam_codigo,
        motivo=cuerpo.motivo,
    )


@router.post(
    "/control/reanudar",
    response_model=HechoRegistradoOut,
    status_code=status.HTTP_201_CREATED,
    summary="Reanudar la comida de una cama suspendida",
)
def reanudar_dieta(sesion: SesionDep, cuerpo: CambioEstadoIn) -> HechoRegistradoOut:
    """Inserta un hecho con `suspendida = 0` y la misma dieta que tenía.

    Si la cama no está suspendida: 409. Cama fuera del censo: 409.
    """
    return _registrar(
        consultas_control.reanudar,
        sesion=sesion,
        cam_codigo=cuerpo.cam_codigo,
        motivo=cuerpo.motivo,
    )


# ==========================================================================
# Reportes de pacientes. Solo lectura de bd_nutricion; el SIH no se toca.
# ==========================================================================

Desde = Annotated[date, Query(description="Primer día del rango, inclusive.")]
Hasta = Annotated[date, Query(description="Último día del rango, inclusive.")]


@router.get(
    "/reporte-distribucion",
    response_model=ReporteDistribucionOut,
    summary="Raciones servidas a pacientes: servicios × tipos de dieta",
)
def reporte_distribucion(sesion: SesionDep, desde: Desde, hasta: Hasta) -> ReporteDistribucionOut:
    """La matriz del informe mensual para cualquier rango de fechas.

    `valores` de cada fila va alineado con `columnas`. Las filas vienen todas,
    en el orden de la planilla, aunque valgan 0. `desde` posterior a `hasta`:
    422.
    """
    try:
        reporte = consultas_reportes.reporte_distribucion(sesion, desde, hasta)
    except consultas_reportes.RangoInvalido as err:
        raise HTTPException(422, str(err)) from err
    return ReporteDistribucionOut(**asdict(reporte))


# ==========================================================================
# LEGADO: Raciones manuales sin cama a dietas_cama (mantenido temporalmente)
# ==========================================================================



@router.post(
    "/raciones-manuales",
    response_model=RacionManualCreadaOut,
    status_code=status.HTTP_201_CREATED,
    summary="Cargar N raciones sin cama (Hemodiálisis o Emergencias)",
)
def registrar_raciones_manuales(
    sesion: SesionDep, cuerpo: RacionManualIn
) -> RacionManualCreadaOut:
    """Inserta `cantidad` filas en `dietas_cama`, una por ración, sin cama.

    Concepto desconocido, cantidad fuera de 1..200, o dieta inexistente,
    eliminada, dada de baja o NPO: 422. No hay borrado ni edición.
    """
    try:
        carga = consultas_manuales.registrar(
            sesion,
            fecha=cuerpo.fecha,
            concepto=cuerpo.concepto,
            tipo_dieta_id=cuerpo.tipo_dieta_id,
            cantidad=cuerpo.cantidad,
            motivo=cuerpo.motivo,
        )
    except consultas_manuales.MapeoFaltante as err:
        raise HTTPException(status.HTTP_409_CONFLICT, str(err)) from err
    except ValueError as err:
        raise HTTPException(422, str(err)) from err
    return RacionManualCreadaOut(**asdict(carga))


@router.get(
    "/raciones-manuales",
    response_model=RacionesManualesOut,
    summary="Raciones sin cama cargadas en un rango de fechas",
)
def listar_raciones_manuales(
    sesion: SesionDep, desde: Desde, hasta: Hasta
) -> RacionesManualesOut:
    """Lo cargado entre `desde` y `hasta`, agrupado por fecha, concepto y dieta.

    `desde` posterior a `hasta`: 422.
    """
    try:
        resultado = consultas_manuales.listar(sesion, desde, hasta)
    except consultas_reportes.RangoInvalido as err:
        raise HTTPException(422, str(err)) from err
    return RacionesManualesOut(**asdict(resultado))


# ==========================================================================
# Catálogo de Dietas
# ==========================================================================


@router.get(
    "/dietas",
    response_model=list[DietaOut],
    summary="Catálogo de tipos de dieta con su columna de informe",
)
def listar_dietas(sesion: SesionDep) -> list[DietaOut]:
    """Devuelve las dietas con nombre, código, columna del libro, cuenta_racion y activa.

    NPO va señalada con cuenta_racion = False y no_suma = True («no suma»).
    """
    filas = consultas_dietas.listar_dietas(sesion)
    return [DietaOut(**f) for f in filas]


@router.post(
    "/dietas",
    response_model=DietaOut,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una nueva dieta en el catálogo",
)
def crear_dieta(sesion: SesionDep, cuerpo: CrearDietaIn) -> DietaOut:
    """Crea una nueva dieta en el catálogo.

    Valida que `columna_informe` apunte a una columna existente; de lo contrario
    devuelve 422. Si el nombre o código ya existen devuelve 409.
    """
    try:
        nueva = consultas_dietas.crear_dieta(
            sesion,
            nombre=cuerpo.nombre,
            columna_informe=cuerpo.columna_informe,
            codigo=cuerpo.codigo,
            cuenta_racion=cuerpo.cuenta_racion,
            orden=cuerpo.orden,
            activo=cuerpo.activo,
        )
        return DietaOut(**nueva)
    except consultas_dietas.ColumnaInformeInvalida as err:
        raise HTTPException(422, str(err)) from err
    except consultas_dietas.NombreDietaDuplicado as err:
        raise HTTPException(status.HTTP_409_CONFLICT, str(err)) from err
    except ValueError as err:
        raise HTTPException(422, str(err)) from err


# ==========================================================================
# Edición de Dietas
# ==========================================================================


@router.put(
    "/dietas/{id}",
    response_model=DietaOut,
    summary="Editar dieta: renombrar o activar/desactivar",
)
def editar_dieta(sesion: SesionDep, id: int, cuerpo: EditarDietaIn) -> DietaOut:
    """Renombra o activa/desactiva una dieta.

    Desactivar (activo = False) no borra: lo ya servido sigue contando en los informes.
    """
    activo_final = cuerpo.activo if cuerpo.activo is not None else cuerpo.activa
    try:
        actualizada = consultas_dietas.editar_dieta(
            sesion,
            dieta_id=id,
            nombre=cuerpo.nombre,
            activo=activo_final,
            columna_informe=cuerpo.columna_informe,
            cuenta_racion=cuerpo.cuenta_racion,
            orden=cuerpo.orden,
        )
        return DietaOut(**actualizada)
    except consultas_dietas.DietaNoEncontrada as err:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(err)) from err
    except consultas_dietas.NombreDietaDuplicado as err:
        raise HTTPException(status.HTTP_409_CONFLICT, str(err)) from err
    except consultas_dietas.ColumnaInformeInvalida as err:
        raise HTTPException(422, str(err)) from err
    except ValueError as err:
        raise HTTPException(422, str(err)) from err


@router.delete(
    "/dietas/{id}",
    response_model=EliminarDietaOut,
    summary="Eliminar dieta: borrado lógico (visible = 0), nunca DELETE real",
)
def eliminar_dieta(sesion: SesionDep, id: int) -> EliminarDietaOut:
    """Oculta la dieta del catálogo y de la captura; la fila queda en la base.

    404 si no existe o ya estaba eliminada. 422 si es NPO: "NPO es especial".
    """
    try:
        return EliminarDietaOut(**consultas_dietas.eliminar_dieta(sesion, dieta_id=id))
    except consultas_dietas.DietaNoEncontrada as err:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(err)) from err
    except consultas_dietas.DietaNoEliminable as err:
        raise HTTPException(422, str(err)) from err
