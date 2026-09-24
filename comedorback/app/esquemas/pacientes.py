"""Esquemas del Módulo Pacientes: diagnóstico del SIH, Control de Dietas y
catálogo de dietas.

Los de informes se agregan en su etapa.
"""

from datetime import date, datetime, time
from typing import Annotated, Literal

from fastapi import Query
from pydantic import BaseModel, Field, StringConstraints


class DivergenciaVistaOut(BaseModel):
    """Un grupo de camas que nuestra consulta ve y `ListaInternados` no.

    Se abre por los dos VGRUCODIGO en juego porque la causa siempre es la
    misma: un código de servicio que no está cargado en `VGRUPOSI`. Tener el
    código a la vista es lo que permite ir a pedirle al hospital que lo
    cargue, en vez de solo saber que "falta una cama".
    """

    cod_servicio_cama: int | None = Field(
        description="VGRUCODIGO de la SALA donde está la cama. Es el eje del informe."
    )
    servicio_cama: str | None = Field(
        description="Su nombre en VGRUPOSI. None = el código no existe ahí."
    )
    cod_servicio_internacion: int | None = Field(
        description="VGRUCODIGO con el que se internó al paciente. No siempre coincide."
    )
    servicio_internacion: str | None = None
    camas: int


class SaludSih(BaseModel):
    """Diagnóstico de la conexión al SIH y de su divergencia con la vista.

    El frontend lo usa para decidir si ofrece traer el censo o si arranca en
    carga manual; la licenciada lo usa para auditar por qué su informe y el
    del hospital no dan el mismo número.
    """

    configurado: bool = Field(description="Hay SIH_HOST, SIH_DATABASE y SIH_USER en .env.")
    conectado: bool
    mensaje: str

    filas_censo: int | None = Field(
        default=None, description="Camas vigentes que ve ESTE sistema (ORATDET_EST = 'V')."
    )
    filas_vista: int | None = Field(
        default=None,
        description=(
            "Filas de dbo.ListaInternados, la vista oficial del hospital. "
            "None si la vista no existe o no se pudo leer."
        ),
    )
    historias_distintas: int | None = Field(
        default=None,
        description=(
            "Historias clínicas distintas entre esas camas. Puede ser menor que "
            "filas_censo: una historia puede ocupar dos camas. La unidad del "
            "módulo es la cama."
        ),
    )
    descartadas_por_la_vista: list[DivergenciaVistaOut] = Field(
        default_factory=list,
        description=(
            "Camas que nosotros vemos y la vista descarta por sus INNER JOIN "
            "contra VGRUPOSI. Nosotros las mostramos en 'Sin clasificar'."
        ),
    )
    solo_en_la_vista: int | None = Field(
        default=None,
        description=(
            "Filas que la vista tiene y nosotros no. Con los JOIN actuales "
            "debería ser 0: si no lo es, alguien cambió ListaInternados."
        ),
    )


# ==========================================================================
# Control de Dietas
#
# Todo lo que describe la cama —paciente, sexo, sala, pieza, servicio— viaja
# de SALIDA nada mas. Los esquemas de entrada piden `cam_codigo` y la
# decision de nutricion, y punto: el servidor resuelve el resto leyendo el
# censo. Si el cliente pudiera mandar el nombre del paciente o el servicio,
# podria guardar una racion a nombre de quien no esta en esa cama.
# ==========================================================================


class MarcaOut(BaseModel):
    """El `{hora, motivo}` de la línea chica de la pantalla.

    Campos separados y no un texto ya armado: quien decide cómo se lee es el
    front, que lo muestra de una forma en la tabla y de otra en el detalle.
    """

    hora: time
    motivo: str | None = None


class DietaVigenteOut(BaseModel):
    """La dieta que rige para una cama en este momento."""

    dietas_cama_id: int = Field(description="La fila de dietas_cama que manda hoy.")
    tipo_dieta_id: int
    codigo: str
    nombre: str
    cuenta_racion: bool = Field(
        description="False en NPO: queda registrada la decision y no suma racion."
    )
    prescripcion_texto: str | None = None
    momento: datetime = Field(description="Hora del hecho que dejo esta dieta vigente.")


class FilaControlOut(BaseModel):
    """Una cama ocupada con su dieta vigente.

    Todo lo de la cama es de SOLO LECTURA: lo administra el hospital en su
    propio sistema. Esta API no tiene forma de dar de alta, mover ni quitar
    una cama, y no debe tenerla.
    """

    cam_codigo: int = Field(description="SE_CAMA.CAM_CODIGO. La unidad del modulo.")
    cama_texto: str
    sa_codigo: int | None = None
    sala_texto: str
    pieza_texto: str = Field(description="La columna PIEZA del parte de papel.")

    nro_historia: int | None = None
    nombre_paciente: str | None = None
    sexo: str | None = Field(default=None, description="'M', 'F' o null si el SIH no lo tiene.")

    servicio_nutricion_id: int | None = None
    hoja_informe: str | None = None
    grupo_informe: str | None = None
    servicio_cama_texto: str | None = Field(
        default=None, description="Nombre del servicio en VGRUPOSI, para detectar renombres."
    )
    por_sala: bool = Field(
        description="La cama entro por una fila de sala y no por la del servicio (Infectologia)."
    )
    sin_clasificar: bool = Field(
        description=(
            "Sin servicio mapeado, o mapeado a una fila sin hoja_informe. Las "
            "dos cosas terminan en la fila 'Sin clasificar' del libro, y las "
            "dos tienen que poder verse: el hueco se muestra, no se esconde."
        )
    )

    dieta: DietaVigenteOut | None = Field(
        default=None, description="null = a esta cama todavia no se le cargo dieta hoy."
    )
    suspendida: bool
    cambio: MarcaOut | None = Field(
        default=None,
        description="Presente solo si hubo mas de un hecho en el dia: la primera dieta no es un cambio.",
    )
    suspension: MarcaOut | None = None
    hechos_hoy: int = Field(
        description="Cuantas filas de dietas_cama tiene esta cama hoy. Mayor a 1 = cambio."
    )
    en_censo: bool = Field(
        description=(
            "False = la cama ya no figura ocupada en el SIH. Pasa cuando dieron "
            "de alta despues de servir: la racion existio y sigue contando."
        )
    )


# Filtros de `GET /pacientes/control`, todos opcionales y combinables (AND).
# Van como parámetros sueltos y no como un modelo de query porque conviven con
# `fecha`, y FastAPI no mezcla un modelo de query con otros parámetros.
#
# La sala va por su CÓDIGO del SIH y nunca por el texto: el texto se repite
# (4 "CV", 6 "TRM"), tiene tipeos y hay salas sin nombre. Los nombres de los
# parámetros no cambian cuando el módulo pase a trabajar por sala.
SalaFiltro = Annotated[
    int | None,
    Query(gt=0, description="SE_SALA.SA_CODIGO: solo las camas de esa sala."),
]
HojaFiltro = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=60),
    Query(description="Solo las camas de esa hoja del libro. Una hoja que no existe da lista vacía."),
]
SinClasificarFiltro = Annotated[
    bool,
    Query(description="true: solo las camas con `sin_clasificar` (sin hoja del libro)."),
]


class ControlDelDiaOut(BaseModel):
    """La pantalla de Control de Dietas de una fecha, con sus totales."""

    fecha: date
    es_hoy: bool = Field(
        description=(
            "False = fecha pasada. El SIH no guarda historia de ocupacion, asi "
            "que esas filas salen solo de lo congelado."
        )
    )
    sih_disponible: bool
    sih_mensaje: str
    leido_en: datetime | None = Field(
        default=None, description="Cuando se leyo el censo. El SIH no tiene fecha: es el ahora."
    )

    total_camas: int
    con_dieta: int
    sin_dieta: int
    suspendidas: int
    sin_clasificar: int
    raciones: int = Field(
        description="Lo que hoy sumaria al libro: ni suspendidas ni NPO."
    )

    filas: list[FilaControlOut]


class AsignarDietaIn(BaseModel):
    """Asignar o cambiar la dieta de una cama.

    Es deliberadamente corto. El servidor resuelve sala, pieza, paciente,
    sexo y servicio leyendo el censo en ese mismo instante y los congela.
    """

    cam_codigo: int = Field(gt=0, description="SE_CAMA.CAM_CODIGO. Nada mas identifica la cama.")
    tipo_dieta_id: int = Field(gt=0)
    prescripcion_texto: str | None = Field(
        default=None,
        max_length=65535,
        description="Texto libre. CUALQUIER dieta puede llevarlo, no solo sondas y licuadas.",
    )
    motivo: str | None = Field(
        default=None,
        max_length=200,
        description="Opcional, también en un cambio. Si viene, se guarda con el hecho.",
    )


class CambioEstadoIn(BaseModel):
    """Suspender o reanudar. La cama sigue con la dieta que ya tenía."""

    cam_codigo: int = Field(gt=0, description="SE_CAMA.CAM_CODIGO. Nada mas identifica la cama.")
    motivo: str | None = Field(
        default=None, max_length=200, description="Opcional. Si viene, se guarda con el hecho."
    )


class HechoRegistradoOut(BaseModel):
    """La fila recién insertada. Confirma que fue un INSERT y no un UPDATE."""

    dietas_cama_id: int
    fecha: date
    momento: datetime
    cam_codigo: int
    tipo_dieta_id: int
    suspendida: bool
    motivo: str | None = None
    servicio_nutricion_id: int | None = None
    nombre_paciente: str | None = None


# ==========================================================================
# Catálogo de Dietas
# ==========================================================================


class DietaOut(BaseModel):
    """Una dieta del catálogo con su columna de informe."""

    id: int
    codigo: str
    nombre: str
    columna_informe_id: int
    columna_informe: str = Field(
        description="Nombre de la columna del informe mensual a la que suma."
    )
    columna_libro: str = Field(
        description="Mismo valor que columna_informe, con el nombre que usa el frontend."
    )
    cuenta_racion: bool = Field(
        description="False en NPO: queda registrada y no suma al total."
    )
    suma_al_libro: bool = Field(
        description="Mismo valor que cuenta_racion, con el nombre que usa el frontend."
    )
    no_suma: bool = Field(
        description="True para dietas que no suman ración al libro (NPO)."
    )
    es_ayuno: bool = Field(
        default=False, description="True si la dieta es NPO / ayuno."
    )
    activo: bool
    activa: bool = Field(
        description="Mismo valor que activo, con el nombre que usa el frontend."
    )
    orden: int


class CrearDietaIn(BaseModel):
    """Datos para crear una nueva dieta en el catálogo."""

    nombre: str = Field(
        min_length=1, max_length=80, description="Nombre de la dieta."
    )
    codigo: str | None = Field(
        default=None,
        max_length=40,
        description="Código único. Si se omite, se genera a partir del nombre.",
    )
    columna_informe: str | int = Field(
        description="ID, código o nombre de la columna del informe a la que suma."
    )
    cuenta_racion: bool = Field(
        default=True,
        description="Si suma al informe de raciones (False para NPO).",
    )
    orden: int | None = Field(
        default=None, description="Orden de visualización."
    )
    activo: bool = Field(default=True)


class EditarDietaIn(BaseModel):
    """Datos editables de una dieta: renombrar, activar/desactivar, reordenar."""

    nombre: str | None = Field(default=None, min_length=1, max_length=80)
    activo: bool | None = None
    activa: bool | None = None
    columna_informe: str | int | None = None
    cuenta_racion: bool | None = None
    orden: int | None = None


class EliminarDietaOut(BaseModel):
    """Respuesta del borrado lógico: la fila sigue en la base con visible = 0."""

    eliminado: bool
    id: int


# ==========================================================================
# Matriz diaria de raciones por servicio (raciones_servicio_dia)
# ==========================================================================


class CeldaRacionIn(BaseModel):
    """Una celda a registrar o actualizar en la matriz del día."""

    fila: str = Field(description="Código de la fila de FILAS_DISTRIBUCION (ej: 'pediatria_gral').")
    columna: str = Field(description="Código de la columna de COLUMNAS_DISTRIBUCION (ej: 'corriente').")
    cantidad: int = Field(ge=0, description="Cantidad de raciones servidas (entero >= 0).")


class RacionesDiaIn(BaseModel):
    """Cuerpo para guardar/actualizar celdas de la matriz del día."""

    fecha: date = Field(description="Día al que corresponden las raciones (no futuro).")
    celdas: list[CeldaRacionIn] = Field(default_factory=list, description="Celdas a actualizar.")


class ColumnaMatrizOut(BaseModel):
    codigo: str
    etiqueta: str


class FilaMatrizOut(BaseModel):
    codigo: str
    etiqueta: str
    celdas: list[int] = Field(description="9 enteros correspondientes a las columnas de la planilla.")
    total: int


class TotalMatrizOut(BaseModel):
    celdas: list[int] = Field(description="Total por columna (9 enteros).")
    total: int


class MatrizRacionesDiaOut(BaseModel):
    """La matriz completa de raciones servicios × tipos de dieta para una fecha."""

    fecha: date
    columnas: list[ColumnaMatrizOut]
    filas: list[FilaMatrizOut]
    total: TotalMatrizOut
    actualizado: datetime | None = Field(
        default=None, description="Momento del hecho más reciente registrado ese día, o null si no hay registros."
    )


# ==========================================================================
# Reportes de pacientes: Distribución (servicios × tipos de dieta)
#
# Filas y columnas en el orden fijo de las planillas del hospital (16 filas).
# ==========================================================================


class ColumnaReporteOut(BaseModel):
    codigo: str = Field(description="Estable: la etiqueta puede cambiar, el codigo no.")
    etiqueta: str


class FilaDistribucionOut(BaseModel):
    codigo: str
    etiqueta: str
    valores: list[int] = Field(description="Alineados con `columnas`, en su mismo orden.")
    total: int


class TotalDistribucionOut(BaseModel):
    valores: list[int] = Field(description="Total por columna, alineado con `columnas`.")
    total: int


class CriterioReporteOut(BaseModel):
    """Con qué base se contó. Describe la fuente raciones_servicio_dia."""

    fuente: str = Field(default="raciones_servicio_dia", description="Tabla fuente del reporte.")
    ultima_del_dia_manda: bool = Field(default=True, description="La última celda registrada del día es la que manda.")
    pendiente_confirmar: list[int] = Field(
        default_factory=list,
        description="Números de pregunta de docs/contexto-modulo-pacientes-dietas.md, sección 7.",
    )


class ReporteDistribucionOut(BaseModel):
    """Servicios × tipos de dieta: el informe mensual de raciones a pacientes."""

    desde: date
    hasta: date
    dias: int = Field(description="Días del rango, inclusive.")
    titulo: str
    columnas: list[ColumnaReporteOut]
    filas: list[FilaDistribucionOut]
    total: TotalDistribucionOut
    criterio: CriterioReporteOut


# ==========================================================================
# Raciones manuales: Hemodiálisis y Emergencias, sin cama
# ==========================================================================


class RacionManualIn(BaseModel):
    """Una carga de N raciones de un concepto, un día y una dieta.

    El servidor inserta N filas en `dietas_cama`, una por ración.
    """

    fecha: date = Field(description="Día al que corresponden las raciones.")
    concepto: Literal["hemodialisis", "emergencias"]
    tipo_dieta_id: int = Field(gt=0)
    cantidad: int = Field(ge=1, le=200, description="Raciones a registrar. Una fila por unidad.")
    motivo: str | None = Field(default=None, max_length=200, description="Opcional.")


class RacionManualCreadaOut(BaseModel):
    fecha: date
    concepto: str
    tipo_dieta_id: int
    cantidad: int
    dietas_cama_ids: list[int] = Field(description="Las filas insertadas, una por ración.")


class ConceptoManualOut(BaseModel):
    codigo: str
    etiqueta: str


class FilaRacionManualOut(BaseModel):
    fecha: date
    concepto: str
    tipo_dieta_id: int
    dieta: str
    cantidad: int


class RacionesManualesOut(BaseModel):
    """Lo cargado en el rango, agrupado por fecha, concepto y dieta."""

    desde: date
    hasta: date
    conceptos: list[ConceptoManualOut]
    filas: list[FilaRacionManualOut]
