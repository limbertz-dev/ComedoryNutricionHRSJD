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
from datetime import date, datetime, time, timedelta

from sqlalchemy import and_, case, func, literal, or_, select
from sqlalchemy.orm import Session, aliased

from app.consultas.derecho import (
    contar_personas_con_derecho,
    excluye_enfermeria_hoy,
    no_es_enfermeria,
)
from app.core import reloj
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


# Motivos que una lectura rechazada puede traer ya resuelta a una comida.
# Van siempre los tres, en cero si no hay casos: el front no adivina claves.
MOTIVOS_POR_COMIDA: tuple[str, ...] = (
    "no_identificado",
    "sin_derecho",
    "duplicado",
)


@dataclass
class ComidaDelDia:
    comida_id: int
    comida: str
    hora_inicio: time
    hora_fin: time
    estado: str
    previstas: int
    servidas: int
    manuales: int
    rechazos_por_motivo: dict[str, int]


@dataclass
class ResumenComidas:
    fecha: date
    comidas: list[ComidaDelDia]
    rechazos_sin_comida: int


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
        ahora = reloj.ahora()
        momento = datetime.combine(fecha or ahora.date(), hora or ahora.time())
    comida = resolver_comida_en_curso(sesion, momento)
    fecha_comida = comida.fecha_comida if comida else momento.date()

    consulta_padron = select(func.count()).select_from(Comensal)
    if excluye_enfermeria_hoy(sesion):
        consulta_padron = consulta_padron.where(
            no_es_enfermeria(Comensal.categoria)
        )
    padron = sesion.execute(consulta_padron).scalar_one()

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


def _franja_vigente(hora, dia):
    """El predicado que une una lectura con el horario que la cubre.

    Punto único: lo usan tanto `ultimas_marcaciones` como `comidas_del_dia`,
    así la resolución lectura→comida es la misma en los dos lados.
    `hora` y `dia` son expresiones sobre la marca temporal de la lectura.
    """
    cruza_medianoche = HorarioComida.hora_fin < HorarioComida.hora_inicio
    dentro_normal = and_(
        ~cruza_medianoche,
        HorarioComida.hora_inicio <= hora,
        hora < HorarioComida.hora_fin,
    )
    dentro_cruzada = and_(
        cruza_medianoche,
        or_(
            HorarioComida.hora_inicio <= hora,
            hora < HorarioComida.hora_fin,
        ),
    )
    return and_(
        HorarioComida.activo == 1,
        HorarioComida.vigente_desde <= dia,
        or_(
            HorarioComida.vigente_hasta.is_(None),
            HorarioComida.vigente_hasta >= dia,
        ),
        or_(dentro_normal, dentro_cruzada),
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
    dia = fecha or reloj.hoy()
    comida_asistencia = aliased(Comida, name="comida_asistencia")
    comida_horario = aliased(Comida, name="comida_horario")
    hora_lectura = func.time(LecturaBiometrica.fecha_hora)
    dia_lectura = func.date(LecturaBiometrica.fecha_hora)
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
            _franja_vigente(hora_lectura, dia_lectura),
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


def _horarios_vigentes(
    sesion: Session, dia: date
) -> list[tuple[int, str, time, time]]:
    """Una fila por comida que rige ese día, en orden cronológico.

    Si una comida tiene más de un horario vigente, el de `vigente_desde` más
    reciente (la misma regla que `resolver_comida_en_curso`).
    """
    filas = sesion.execute(
        select(
            HorarioComida.comida_id,
            Comida.nombre,
            HorarioComida.hora_inicio,
            HorarioComida.hora_fin,
        )
        .join(Comida, Comida.id == HorarioComida.comida_id)
        .where(HorarioComida.activo == 1)
        .where(HorarioComida.vigente_desde <= dia)
        .where(
            or_(
                HorarioComida.vigente_hasta.is_(None),
                HorarioComida.vigente_hasta >= dia,
            )
        )
        .order_by(HorarioComida.vigente_desde.desc())
    ).all()
    vigentes: dict[int, tuple[int, str, time, time]] = {}
    for comida_id, nombre, inicio, fin in filas:
        vigentes.setdefault(comida_id, (comida_id, nombre, inicio, fin))
    return sorted(vigentes.values(), key=lambda fila: (fila[2], fila[0]))


def _servidas_por_comida(
    sesion: Session, dia: date
) -> tuple[dict[int, int], dict[int, int]]:
    """Raciones y manuales por comida, por `fecha_comida`, todos los métodos."""
    servidas: dict[int, int] = {}
    manuales: dict[int, int] = {}
    for comida_id, total, a_mano in sesion.execute(
        select(
            Asistencia.comida_id,
            func.count(),
            func.sum(case((Asistencia.metodo == "manual", 1), else_=0)),
        )
        .where(Asistencia.fecha_comida == dia)
        .group_by(Asistencia.comida_id)
    ).all():
        servidas[comida_id] = total
        manuales[comida_id] = int(a_mano or 0)
    return servidas, manuales


def _rechazos_por_comida(
    sesion: Session, dia: date
) -> tuple[dict[tuple[int, str], int], int]:
    """Rechazos del día del reloj, resueltos a comida como `ultimas_marcaciones`.

    Devuelve ((comida_id, motivo) → cantidad, rechazos_sin_comida). Sin tope.
    """
    hora_lectura = func.time(LecturaBiometrica.fecha_hora)
    dia_lectura = func.date(LecturaBiometrica.fecha_hora)
    comida_resuelta_id = func.coalesce(
        Asistencia.comida_id, HorarioComida.comida_id
    )
    motivo_presentado = case(
        (LecturaBiometrica.usuario_id.is_(None), literal("no_identificado")),
        else_=LecturaBiometrica.motivo,
    )
    rechazos: dict[tuple[int, str], int] = {}
    sin_comida = 0
    for comida_id, motivo, cantidad in sesion.execute(
        select(
            comida_resuelta_id.label("comida_id"),
            motivo_presentado.label("motivo"),
            func.count(func.distinct(LecturaBiometrica.id)),
        )
        .select_from(LecturaBiometrica)
        .outerjoin(Asistencia, Asistencia.lectura_id == LecturaBiometrica.id)
        .outerjoin(HorarioComida, _franja_vigente(hora_lectura, dia_lectura))
        .where(func.date(LecturaBiometrica.fecha_hora) == dia)
        .where(LecturaBiometrica.resultado == "rechazada")
        .group_by(comida_resuelta_id, motivo_presentado)
    ).all():
        if comida_id is None or motivo not in MOTIVOS_POR_COMIDA:
            # `fuera_horario` no resuelve por construcción. Un motivo fuera
            # del trío con comida solo aparece si un horario se vigenteó
            # hacia atrás; igual se mide, acá, en vez de esconderse.
            sin_comida += cantidad
        else:
            clave = (comida_id, motivo)
            rechazos[clave] = rechazos.get(clave, 0) + cantidad
    return rechazos, sin_comida


def _estado_franja(dia: date, inicio: time, fin: time, ahora: datetime) -> str:
    """Dónde está la franja respecto al reloj: pendiente | en_curso | cerrada."""
    abre = datetime.combine(dia, inicio)
    cierra = datetime.combine(dia, fin)
    if fin < inicio:
        cierra += timedelta(days=1)
    if ahora < abre:
        return "pendiente"
    if ahora < cierra:
        return "en_curso"
    return "cerrada"


def comidas_del_dia(
    sesion: Session, fecha: date | None = None
) -> ResumenComidas:
    """Una fila por comida vigente del día, para la supervisión.

    Solo lectura: previstas (derecho), servidas y manuales (asistencias por
    `fecha_comida`) y rechazos del día del reloj resueltos con la misma
    lógica de franja que `ultimas_marcaciones`, sin tope.
    """
    dia = fecha or reloj.hoy()
    servidas, manuales = _servidas_por_comida(sesion, dia)
    rechazos, sin_comida = _rechazos_por_comida(sesion, dia)
    ahora = reloj.ahora()
    comidas = [
        ComidaDelDia(
            comida_id=comida_id,
            comida=nombre,
            hora_inicio=inicio,
            hora_fin=fin,
            estado=_estado_franja(dia, inicio, fin, ahora),
            previstas=contar_personas_con_derecho(sesion, comida_id, dia),
            servidas=servidas.get(comida_id, 0),
            manuales=manuales.get(comida_id, 0),
            rechazos_por_motivo={
                motivo: rechazos.get((comida_id, motivo), 0)
                for motivo in MOTIVOS_POR_COMIDA
            },
        )
        for comida_id, nombre, inicio, fin in _horarios_vigentes(sesion, dia)
    ]
    return ResumenComidas(fecha=dia, comidas=comidas, rechazos_sin_comida=sin_comida)
