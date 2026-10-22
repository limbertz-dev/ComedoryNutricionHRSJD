"""Formas del estado de la pantalla en vivo."""

from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Cupo(BaseModel):
    previstas: int | None = Field(
        description="null = no hay cupo cargado para esta fecha y comida: sin límite"
    )
    servidas: int
    restantes: int | None
    porcentaje: int | None


class ConsumoCategoria(BaseModel):
    categoria: str
    raciones: int


class TotalesDia(BaseModel):
    raciones_servidas: int
    lecturas: int = Field(description="Toques de dedo del día, válidos o no")
    aceptadas: int
    rechazadas: int


class EstadoPantalla(BaseModel):
    momento: datetime
    fecha_comida: date | None = Field(
        description="Fecha del servicio mostrado: vigente o ultimo cerrado si fuera_de_horario=true"
    )
    comida_id: int | None = None
    comida: str | None = Field(default=None, description="Comida vigente o ultima cerrada; no habilita entregas fuera de horario")
    fuera_de_horario: bool = Field(
        description="True si el reloj no cae en ninguna franja: nadie puede marcar"
    )
    cupo: Cupo | None = None
    padron: int
    totales_del_dia: TotalesDia
    por_categoria: list[ConsumoCategoria] = Field(
        description="Siempre las 6 columnas, incluso en cero, para que el gráfico no cambie de forma"
    )


class DecisionOriginal(BaseModel):
    """Lo que decidió el lector. Guardado e inmutable: una intervención no lo
    sobrescribe."""

    resultado: str
    motivo: str | None = None
    fecha_hora: datetime
    dispositivo: str


class ComensalRacion(BaseModel):
    usuario_id: int | None = None
    nombre: str | None = None


class ResultadoFinal(BaseModel):
    """La ración que quedó, si quedó una. Separado de `decision_original`."""

    via: Literal["lector", "identificacion_manual", "registro_manual"]
    asistencia_id: int
    comensal: ComensalRacion
    comida: str | None = None
    fecha_comida: date | None = None
    momento: datetime | None = None


class IntervencionPantalla(BaseModel):
    """Estado de las intervenciones de una lectura según el ROL.

    Cocinera: {revision, actualizado_en, resuelta, resuelta_por_mi}. Sin
    cuentas ajenas ni intentos ajenos. Jefa: lo mismo más `registrada_por`
    ({cuenta_id, usuario, nombre} o null) e `intentos_rechazados`; son campos
    extra que la cocinera no recibe. Sistemas: el bloque no existe (null).
    """

    model_config = ConfigDict(extra="allow")

    revision: int = Field(
        description=(
            "Filas de auditoría visibles al rol. Solo crece: sube cuando alguien "
            "registra una entrega, aunque sea otra cocinera."
        )
    )
    actualizado_en: datetime | None = None
    resuelta: bool
    resuelta_por_mi: bool


class Marcacion(BaseModel):
    id: int = Field(
        description=(
            "id en su tabla de origen. NO es único en la lista: una lectura y "
            "una asistencia manual pueden tener el mismo. Use clave_evento."
        )
    )
    fecha_hora: datetime
    usuario_id: int | None = None
    nombre: str | None = Field(
        default=None, description="null si el lector no reconoció la huella"
    )
    categoria: str | None = Field(
        default=None, description="Categoría del comensal o reporte"
    )
    comida_id: int | None = Field(
        default=None, description="ID de la comida asociada"
    )
    comida: str | None = Field(
        default=None,
        description="Nombre de la comida: Desayuno, Almuerzo, Cena, etc.",
    )
    resultado: str = Field(description="aceptada | rechazada")
    motivo: str | None = None
    valido: bool = Field(description="True si resultado == 'aceptada'")
    dispositivo: str
    origen: Literal["lectura_biometrica", "asistencia_manual"] = Field(
        description=(
            "Tabla de la que sale la fila, según la rama de la consulta; nunca "
            "del cliente ni del dispositivo. Una asistencia biométrica aparece "
            "solo como su lectura."
        )
    )
    clave_evento: str = Field(
        description=(
            "'<origen>:<id>'. Identifica la fila sin ambigüedad. No es un "
            "cursor ni refleja el orden de confirmación de las transacciones."
        ),
        examples=["lectura_biometrica:7", "asistencia_manual:7"],
    )
    comida_origen: Literal["persistida_en_asistencia", "reconstruida_por_horario"] | None = Field(
        default=None,
        description=(
            "De dónde sale `comida`. Una lectura sin asistencia no guarda comida: "
            "se reconstruye por horario y no es un dato histórico guardado."
        ),
    )
    decision_original: DecisionOriginal | None = Field(
        default=None,
        description="Guardada e inmutable. null en registros manuales independientes",
    )
    estado_final: Literal["racion_servida", "sin_racion"] = Field(
        default="sin_racion",
        description=(
            "Si la fila terminó en una ración. Separado de `valido`, que sigue "
            "siendo solo la decisión original del lector."
        ),
    )
    resultado_final: ResultadoFinal | None = None
    puede_identificar: bool = Field(
        default=False,
        description=(
            "Solo true para la cocinera y para una lectura pendiente del servicio "
            "actual. Es informativo: lo decide el POST de identificación."
        ),
    )
    motivo_no_identificable: str | None = Field(
        default=None,
        description=(
            "Por qué no se puede identificar: lectura_no_resoluble, "
            "lectura_ya_resuelta, servicio_distinto, servicio_no_determinable, "
            "reloj_inconsistente o no_aplica (registro manual). null si se puede, "
            "o si no es cocinera y la lectura sigue pendiente."
        ),
    )
    identificable_hasta: datetime | None = Field(
        default=None,
        description="Cierre de la ventana efectiva vigente. Informativo, no vinculante",
    )
    intervencion: IntervencionPantalla | None = Field(
        default=None,
        description="null para sistemas y para filas que no admiten intervención",
    )


class ServicioActual(BaseModel):
    """El servicio en curso: la comida, su fecha_comida y la ventana efectiva."""

    comida_id: int
    comida: str
    fecha_comida: date
    inicio: datetime
    fin: datetime


class LecturasPorIdentificar(BaseModel):
    servicio: ServicioActual | None = Field(
        description="null si ahora no hay un servicio determinable: la lista va vacía"
    )
    total: int = Field(description="Cuántas lecturas se pueden identificar ahora")
    truncado: bool = Field(
        description="True si se llegó al tope de seguridad y puede haber más"
    )
    lecturas: list[Marcacion] = Field(
        description=(
            "Misma forma que ultimas-marcaciones, siempre con puede_identificar=true. "
            "Más reciente primero. Incluye lecturas de ayer si el servicio cruza la medianoche"
        )
    )


class ComidaDelDia(BaseModel):
    comida_id: int
    comida: str
    hora_inicio: time
    hora_fin: time
    estado: Literal["pendiente", "en_curso", "cerrada"] = Field(
        description="Dónde está la franja respecto al reloj del servidor"
    )
    previstas: int = Field(description="Personas distintas con derecho, según aplicar_reglas")
    servidas: int = Field(description="Raciones por fecha_comida, todos los métodos")
    manuales: int = Field(description="De las servidas, las registradas a mano")
    rechazos_por_motivo: dict[str, int] = Field(
        description="Siempre no_identificado, sin_derecho y duplicado, en 0 si no hay casos"
    )


class ComidasDelDia(BaseModel):
    fecha: date = Field(
        description="Día consultado. Las raciones suman por fecha_comida; los rechazos, por día del reloj"
    )
    comidas: list[ComidaDelDia] = Field(
        description="Una fila por comida vigente, en orden cronológico"
    )
    rechazos_sin_comida: int = Field(
        description="Rechazos del día que no resuelven a ninguna comida (fuera_horario, no_identificado fuera de franja)"
    )
