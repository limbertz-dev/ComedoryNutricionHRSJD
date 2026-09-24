"""Estado de la pantalla en vivo del comedor.

Es la vista que mira la jefa de nutrición mientras la gente marca: qué tiempo
de comida está corriendo, cuántas raciones van, cuántas quedan y cómo se
reparten por categoría.

Todo se deriva de `asistencias` y `lecturas_biometricas` en el momento de
consultar. No hay contadores acumulados en ninguna tabla: un contador que se
incrementa se desincroniza tarde o temprano, y entonces la pantalla y el
informe dicen cosas distintas del mismo día.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time

from sqlalchemy import and_, case, func, literal, or_, select
from sqlalchemy.orm import Session, aliased

from app.consultas.derecho import contar_personas_con_derecho, no_es_enfermeria
from app.logica.marcacion import ComidaEnCurso, resolver_comida_en_curso
from app.modelos.comedor import (
    Asistencia,
    CategoriaReporte,
    HorarioComida,
    LecturaBiometrica,
)
from app.modelos.heredados import Comensal, Comida


@dataclass
class Cupo:
    previstas: int | None
    servidas: int
    restantes: int | None
    porcentaje: int | None


@dataclass
class ConsumoCategoria:
    categoria: str
    raciones: int


@dataclass
class TotalesDia:
    raciones_servidas: int
    lecturas: int
    aceptadas: int
    rechazadas: int


@dataclass
class Marcacion:
    id: int
    fecha_hora: datetime
    usuario_id: int | None
    nombre: str | None
    categoria: str | None
    comida_id: int | None
    comida: str | None
    resultado: str
    motivo: str | None
    valido: bool
    dispositivo: str


@dataclass
class Estado:
    momento: datetime
    fecha_comida: date | None
    comida_id: int | None
    comida: str | None
    fuera_de_horario: bool
    cupo: Cupo | None
    padron: int
    totales_del_dia: TotalesDia
    por_categoria: list[ConsumoCategoria] = field(default_factory=list)


def _cupo(sesion: Session, comida: ComidaEnCurso) -> Cupo:
    previstas = contar_personas_con_derecho(
        sesion, comida.comida_id, comida.fecha_comida
    )
    servidas = sesion.execute(
        select(func.count())
        .select_from(Asistencia)
        .where(
            Asistencia.fecha_comida == comida.fecha_comida,
            Asistencia.comida_id == comida.comida_id,
        )
    ).scalar_one()

    restantes = max(0, previstas - servidas)
    porcentaje = round(servidas / previstas * 100) if previstas else 0
    return Cupo(
        previstas=previstas,
        servidas=servidas,
        restantes=restantes,
        porcentaje=porcentaje,
    )


def _por_categoria(sesion: Session, fecha: date) -> list[ConsumoCategoria]:
    """Todas las raciones del día, abiertas por columna del formulario.

    Se listan también las columnas en cero: el gráfico necesita las seis
    barras siempre, o cambia de forma cada vez que alguien marca.
    """
    conteos = dict(
        sesion.execute(
            select(Asistencia.categoria_reporte_id, func.count())
            .where(Asistencia.fecha_comida == fecha)
            .group_by(Asistencia.categoria_reporte_id)
        ).all()
    )
    columnas = sesion.execute(
        select(CategoriaReporte.id, CategoriaReporte.nombre)
        .where(CategoriaReporte.activo == 1)
        .order_by(CategoriaReporte.orden)
    ).all()
    return [
        ConsumoCategoria(categoria=nombre, raciones=conteos.get(cid, 0))
        for cid, nombre in columnas
    ]


def _totales(sesion: Session, fecha_comida: date, dia: date) -> TotalesDia:
    servidas = sesion.execute(
        select(func.count())
        .select_from(Asistencia)
        .where(Asistencia.fecha_comida == fecha_comida)
    ).scalar_one()

    por_resultado = dict(
        sesion.execute(
            select(LecturaBiometrica.resultado, func.count())
            .where(func.date(LecturaBiometrica.fecha_hora) == dia)
            .group_by(LecturaBiometrica.resultado)
        ).all()
    )
    aceptadas = por_resultado.get("aceptada", 0)
    rechazadas = por_resultado.get("rechazada", 0)
    return TotalesDia(
        raciones_servidas=servidas,
        lecturas=aceptadas + rechazadas,
        aceptadas=aceptadas,
        rechazadas=rechazadas,
    )


def estado(
    sesion: Session,
    fecha: date | None = None,
    hora: time | None = None,
    momento: datetime | None = None,
) -> Estado:
    """Estado de pantalla para una fecha u hora simulada.

    Si no se recibe una parte del reloj, se conserva esa parte del momento
    actual. `momento` se conserva como punto de inyección para consultas
    internas que necesiten controlar el reloj completo.
    """
    if momento is None:
        ahora = datetime.now()
        momento = datetime.combine(fecha or ahora.date(), hora or ahora.time())
    comida = resolver_comida_en_curso(sesion, momento)
    fecha_comida = comida.fecha_comida if comida else momento.date()

    padron = sesion.execute(
        select(func.count())
        .select_from(Comensal)
        .where(no_es_enfermeria(Comensal.categoria))
    ).scalar_one()

    return Estado(
        momento=momento,
        fecha_comida=fecha_comida,
        comida_id=comida.comida_id if comida else None,
        comida=comida.comida if comida else None,
        fuera_de_horario=comida is None,
        cupo=_cupo(sesion, comida) if comida else None,
        padron=padron,
        totales_del_dia=_totales(sesion, fecha_comida, momento.date()),
        por_categoria=_por_categoria(sesion, fecha_comida),
    )


def ultimas_marcaciones(
    sesion: Session,
    fecha: date | None = None,
    comida_id: int | None = None,
    limite: int = 50,
) -> list[Marcacion]:
    """El hilo de lo que va pasando en el lector, para la pantalla en vivo.

    Combina `lecturas_biometricas` con las asistencias manuales: la pantalla
    muestra los rechazos del lector y las raciones registradas por la
    jefatura en una sola secuencia cronológica.
    """
    dia = fecha or datetime.now().date()
    comida_asistencia = aliased(Comida, name="comida_asistencia")
    comida_horario = aliased(Comida, name="comida_horario")
    hora_lectura = func.time(LecturaBiometrica.fecha_hora)
    cruza_medianoche = HorarioComida.hora_fin < HorarioComida.hora_inicio
    dentro_normal = and_(
        ~cruza_medianoche,
        HorarioComida.hora_inicio <= hora_lectura,
        hora_lectura < HorarioComida.hora_fin,
    )
    dentro_cruzada = and_(
        cruza_medianoche,
        or_(
            HorarioComida.hora_inicio <= hora_lectura,
            hora_lectura < HorarioComida.hora_fin,
        ),
    )
    comida_resuelta_id = func.coalesce(
        Asistencia.comida_id, HorarioComida.comida_id
    )
    lecturas = (
        select(
            LecturaBiometrica.id,
            LecturaBiometrica.usuario_id,
            LecturaBiometrica.fecha_hora,
            case(
                (
                    LecturaBiometrica.usuario_id.is_(None),
                    literal("Huella no reconocida"),
                ),
                else_=Comensal.nombre_completo,
            ).label("nombre"),
            case(
                (LecturaBiometrica.usuario_id.is_(None), literal("Sin identificar")),
                else_=Comensal.categoria,
            ).label("categoria"),
            comida_resuelta_id.label("comida_id"),
            func.coalesce(comida_asistencia.nombre, comida_horario.nombre).label(
                "comida"
            ),
            LecturaBiometrica.resultado,
            case(
                (LecturaBiometrica.usuario_id.is_(None), literal("no_identificado")),
                else_=LecturaBiometrica.motivo,
            ).label("motivo"),
            case(
                (LecturaBiometrica.usuario_id.is_(None), literal(False)),
                else_=LecturaBiometrica.resultado == "aceptada",
            ).label("valido"),
            LecturaBiometrica.dispositivo,
        )
        .select_from(LecturaBiometrica)
        .outerjoin(Comensal, Comensal.usuario_id == LecturaBiometrica.usuario_id)
        .outerjoin(Asistencia, Asistencia.lectura_id == LecturaBiometrica.id)
        .outerjoin(comida_asistencia, comida_asistencia.id == Asistencia.comida_id)
        .outerjoin(
            HorarioComida,
            and_(
                HorarioComida.activo == 1,
                HorarioComida.vigente_desde
                <= func.date(LecturaBiometrica.fecha_hora),
                or_(
                    HorarioComida.vigente_hasta.is_(None),
                    HorarioComida.vigente_hasta
                    >= func.date(LecturaBiometrica.fecha_hora),
                ),
                or_(dentro_normal, dentro_cruzada),
            ),
        )
        .outerjoin(comida_horario, comida_horario.id == HorarioComida.comida_id)
        .where(func.date(LecturaBiometrica.fecha_hora) == dia)
    )
    manuales = (
        select(
            Asistencia.id.label("id"),
            Asistencia.usuario_id,
            Asistencia.fecha_hora,
            Comensal.nombre_completo.label("nombre"),
            Comensal.categoria.label("categoria"),
            Asistencia.comida_id,
            Comida.nombre.label("comida"),
            literal("aceptada").label("resultado"),
            literal(None).label("motivo"),
            literal(True).label("valido"),
            literal("registro-manual").label("dispositivo"),
        )
        .select_from(Asistencia)
        .outerjoin(Comensal, Comensal.usuario_id == Asistencia.usuario_id)
        .outerjoin(Comida, Comida.id == Asistencia.comida_id)
        .where(
            Asistencia.metodo == "manual",
            Asistencia.lectura_id.is_(None),
            func.date(Asistencia.fecha_hora) == dia,
        )
    )
    if comida_id is not None:
        lecturas = lecturas.where(comida_resuelta_id == comida_id)
        manuales = manuales.where(Asistencia.comida_id == comida_id)
    consulta = lecturas.union_all(manuales).subquery("marcaciones")
    ordenadas = (
        select(consulta)
        .order_by(consulta.c.fecha_hora.desc(), consulta.c.id.desc())
        .limit(limite)
    )
    return [Marcacion(**fila) for fila in sesion.execute(ordenadas).mappings().all()]
