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

from sqlalchemy import and_, case, exists, func, literal, or_, select, union_all
from sqlalchemy.orm import Session, aliased

from app.consultas.derecho import (
    contar_personas_con_derecho,
    excluye_enfermeria_hoy,
    no_es_enfermeria,
)
from app.consultas.horarios import estado_en, rige_en, ventanas_del_dia
from app.consultas.intervenciones import cuentas_por_id
from app.consultas.servicio import Servicio, VentanasDelDia, evaluar_servicio, comida_de_referencia
from app.core import reloj
from app.consultas import raciones
from app.consultas.perfiles import categoria_permitida_sql
from app.logica import policia
from app.logica.marcacion import ComidaEnCurso, resolver_comida_en_curso
from app.modelos.comedor import (
    Asistencia,
    CategoriaReporte,
    HorarioComida,
    IntervencionLectura,
    LecturaBiometrica,
)
from app.modelos.heredados import Comensal, Comida
from app.modelos.lector import RacionPolicia, VinculoLector


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


# De qué tabla sale cada fila de `ultimas_marcaciones`. Lo pone la rama del
# UNION, nunca el cliente ni el dispositivo: `id` solo es único DENTRO de su
# tabla y una lectura y una asistencia manual pueden compartirlo.
ORIGEN_LECTURA = "lectura_biometrica"
ORIGEN_MANUAL = "asistencia_manual"
# Ración de policía por el lector: sin persona del padrón (app/logica/policia.py).
ORIGEN_POLICIA = "racion_policia"


def clave_evento(origen: str, id_: int) -> str:
    """'<origen>:<id>': identifica una fila sin ambigüedad entre las dos
    tablas. No es un cursor ni dice en qué orden se confirmaron las
    transacciones."""
    return f"{origen}:{id_}"


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
    origen: str
    clave_evento: str
    # Columnas crudas de la consulta (no salen en la API). Con valor por
    # omisión para que `_componer_ventana` siga aceptando ramas con solo las
    # once columnas de siempre.
    lectura_resultado: str | None = None
    lectura_motivo: str | None = None
    asistencia_id: int | None = None
    racion_usuario_id: int | None = None
    racion_nombre: str | None = None
    racion_fecha_comida: date | None = None
    racion_fecha_hora: datetime | None = None
    # Lo que calcula `_enriquecer`, según el rol.
    comida_origen: str | None = None
    decision_original: dict | None = None
    estado_final: str = "sin_racion"
    resultado_final: dict | None = None
    puede_identificar: bool = False
    motivo_no_identificable: str | None = None
    identificable_hasta: datetime | None = None
    intervencion: dict | None = None


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
    policias: int = 0


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
    r = raciones.fuente()
    conteos = dict(
        sesion.execute(
            select(r.c.categoria_reporte_id, func.count())
            .where(r.c.fecha_comida == fecha)
            .group_by(r.c.categoria_reporte_id)
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
    """Las raciones del día incluyen las de policías (app/consultas/raciones.py)."""
    r = raciones.fuente()
    servidas = sesion.execute(
        select(func.count()).select_from(r).where(r.c.fecha_comida == fecha_comida)
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
    """Estado de pantalla para una fecha u hora dadas.

    Si no se recibe una parte del reloj, se conserva esa parte del momento
    actual. `momento` se conserva como punto de inyección para consultas
    internas que necesiten controlar el reloj completo.
    """
    if momento is None:
        ahora = reloj.ahora()
        momento = datetime.combine(fecha or ahora.date(), hora or ahora.time())
    comida = resolver_comida_en_curso(sesion, momento)
    referencia = comida or comida_de_referencia(sesion, momento)
    fecha_comida = referencia.fecha_comida if referencia else momento.date()
    dia_totales = comida.fecha_comida if comida else momento.date()

    consulta_padron = select(func.count()).select_from(Comensal).where(categoria_permitida_sql(Comensal.categoria))
    if excluye_enfermeria_hoy(sesion):
        consulta_padron = consulta_padron.where(
            no_es_enfermeria(Comensal.categoria)
        )
    padron = sesion.execute(consulta_padron).scalar_one()

    return Estado(
        momento=momento,
        fecha_comida=fecha_comida,
        comida_id=referencia.comida_id if referencia else None,
        comida=referencia.comida if referencia else None,
        fuera_de_horario=comida is None,
        cupo=_cupo(sesion, referencia) if referencia else None,
        padron=padron,
        totales_del_dia=_totales(sesion, dia_totales, momento.date()),
        por_categoria=_por_categoria(sesion, dia_totales),
    )


def _franja_vigente(horario, momento):
    """El predicado que une una lectura con un horario que la cubre.

    `horario` son las columnas de un horario (`alias.c`); `momento`, la
    `fecha_hora` completa de la lectura. La versión cuenta si REGÍA en ese
    instante (`rige_en`), con microsegundos: un cambio de horario no
    reclasifica lo que ocurrió antes de guardarse. Solo dice si un horario es
    CANDIDATO: puede haber varios en datos heredados, y elegir entre ellos es
    cosa de `_comida_por_lectura`.
    """
    hora = func.time(momento)
    cruza_medianoche = horario.hora_fin < horario.hora_inicio
    dentro_normal = and_(
        ~cruza_medianoche,
        horario.hora_inicio <= hora,
        hora < horario.hora_fin,
    )
    dentro_cruzada = and_(
        cruza_medianoche,
        or_(
            horario.hora_inicio <= hora,
            hora < horario.hora_fin,
        ),
    )
    return and_(
        rige_en(horario, momento),
        or_(dentro_normal, dentro_cruzada),
    )


def _del_dia(columna, dia: date):
    """`DATE(columna) = dia` como rango: el mismo resultado sobre DATETIME,
    pero puede usar el índice de fecha_hora en vez de recorrer la tabla."""
    desde = datetime.combine(dia, time.min)
    return (columna >= desde, columna < desde + timedelta(days=1))


def _alias_lecturas(nombre: str):
    return LecturaBiometrica.__table__.alias(nombre)


def _alias_horarios(nombre: str):
    return HorarioComida.__table__.alias(nombre)


def _comida_por_lectura(
    dia: date, *, lecturas=_alias_lecturas, horarios=_alias_horarios
):
    """Subconsulta (lectura_id, comida_id): UNA fila por lectura del día que
    tenga al menos un horario candidato.

    Punto único de la resolución lectura→comida por horario: la usan
    `ultimas_marcaciones` y `comidas_del_dia`, así la lista y Supervisión
    dicen lo mismo. Entre los candidatos (`_franja_vigente`) cuentan solo los
    de mayor `vigente_desde`, el mismo orden que `resolver_comida_en_curso`:

      · si todos son de una comida, esa comida;
      · si empatan comidas distintas, NULL: la consulta no elige una al azar
        ni reconstruye la decisión de la marcación, que no quedó guardada en
        la lectura;
      · sin candidatos la lectura no aparece acá, y el LEFT JOIN de quien la
        usa la deja sin comida.

    Dos versiones de la misma comida no pueden empatar en `vigente_desde`
    (UNIQUE en horarios_comida). Solo se usa para lecturas SIN asistencia: la
    comida de una ración servida es la persistida (`_comida_de_la_lectura`).

    SQL: lecturas del día (rango sobre fecha_hora) JOIN horarios candidatos,
    NOT EXISTS de un candidato con vigencia más nueva, GROUP BY lectura. No
    está correlacionada con la consulta de afuera: se calcula una vez por
    petición. Coste esperado: lecturas del día × horarios × horarios, y la
    tabla de horarios tiene decenas de filas; no recorre otros días. No medido.

    `lecturas` y `horarios` fabrican alias con columnas `.c`: las pruebas
    pasan filas sintéticas por ahí.
    """
    lectura = lecturas("lectura_resuelta")
    candidato = horarios("horario_candidato")
    mas_nuevo = horarios("horario_mas_nuevo")
    momento = lectura.c.fecha_hora
    hay_uno_mas_nuevo = (
        select(mas_nuevo.c.id)
        .where(
            _franja_vigente(mas_nuevo.c, momento),
            mas_nuevo.c.vigente_desde > candidato.c.vigente_desde,
        )
        .exists()
    )
    return (
        select(
            lectura.c.id.label("lectura_id"),
            case(
                (
                    func.count(func.distinct(candidato.c.comida_id)) == 1,
                    func.min(candidato.c.comida_id),
                ),
                else_=None,
            ).label("comida_id"),
        )
        .select_from(lectura)
        .join(candidato, _franja_vigente(candidato.c, momento))
        .where(*_del_dia(lectura.c.fecha_hora, dia))
        .where(~hay_uno_mas_nuevo)
        .group_by(lectura.c.id)
        .subquery("comida_por_lectura")
    )


def _comida_de_la_lectura(resuelta):
    """La comida de una lectura: la persistida en su asistencia si la tiene
    (los horarios actuales no reclasifican una ración servida); si no, la
    resuelta por horario, que puede ser NULL."""
    return case(
        (Asistencia.id.is_not(None), Asistencia.comida_id),
        else_=resuelta.c.comida_id,
    )


def ultimas_marcaciones(
    sesion: Session,
    fecha: date | None = None,
    comida_id: int | None = None,
    limite: int = 50,
    rol: str | None = None,
    cuenta_id: int | None = None,
) -> list[Marcacion]:
    """El hilo de lo que va pasando en el lector, para la pantalla en vivo.

    Combina `lecturas_biometricas` con las asistencias manuales: la pantalla
    muestra los rechazos del lector y las raciones registradas por la
    jefatura en una sola secuencia cronológica. Una asistencia biométrica no
    entra por la rama manual: aparece una sola vez, como su lectura. Lo mismo
    una asistencia vinculada por una intervención de cocina: sale como su
    lectura, con la decisión original intacta y el resultado final aparte.

    Es una ventana de lo más reciente (`limite`, hasta 1000), no un cursor:
    entre dos consultas pueden pasar más eventos de los que caben.

    `rol` y `cuenta_id` deciden lo que se ve de las intervenciones (ver
    `_enriquecer`); sin rol, nada de ellas.
    """
    dia = fecha or reloj.hoy()
    comida_asistencia = aliased(Comida, name="comida_asistencia")
    comida_horario = aliased(Comida, name="comida_horario")
    comensal_racion = aliased(Comensal, name="comensal_racion")
    # Una fila por lectura ANTES de filtrar por comida y cortar el límite.
    resuelta = _comida_por_lectura(dia)
    comida_resuelta_id = _comida_de_la_lectura(resuelta)
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
            case(
                (Asistencia.id.is_not(None), comida_asistencia.nombre),
                else_=comida_horario.nombre,
            ).label("comida"),
            LecturaBiometrica.resultado,
            # El motivo GUARDADO. Antes toda lectura sin usuario se mostraba
            # como no_identificado, también la que se guardó como
            # fuera_horario, y eso la ofrecía como identificable.
            LecturaBiometrica.motivo.label("motivo"),
            case(
                (LecturaBiometrica.resultado == "aceptada", literal(True)),
                else_=literal(False),
            ).label("valido"),
            LecturaBiometrica.dispositivo,
            LecturaBiometrica.resultado.label("lectura_resultado"),
            LecturaBiometrica.motivo.label("lectura_motivo"),
            Asistencia.id.label("asistencia_id"),
            Asistencia.usuario_id.label("racion_usuario_id"),
            comensal_racion.nombre_completo.label("racion_nombre"),
            Asistencia.fecha_comida.label("racion_fecha_comida"),
            Asistencia.fecha_hora.label("racion_fecha_hora"),
        )
        .select_from(LecturaBiometrica)
        .outerjoin(Comensal, Comensal.usuario_id == LecturaBiometrica.usuario_id)
        .outerjoin(Asistencia, Asistencia.lectura_id == LecturaBiometrica.id)
        .outerjoin(comensal_racion, comensal_racion.usuario_id == Asistencia.usuario_id)
        .outerjoin(comida_asistencia, comida_asistencia.id == Asistencia.comida_id)
        .outerjoin(resuelta, resuelta.c.lectura_id == LecturaBiometrica.id)
        .outerjoin(comida_horario, comida_horario.id == resuelta.c.comida_id)
        .where(*_del_dia(LecturaBiometrica.fecha_hora, dia))
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
            case(
                (Asistencia.metodo == "checklist", literal("checklist-cocina")),
                else_=literal("registro-manual"),
            ).label("dispositivo"),
            literal(None).label("lectura_resultado"),
            literal(None).label("lectura_motivo"),
            Asistencia.id.label("asistencia_id"),
            Asistencia.usuario_id.label("racion_usuario_id"),
            Comensal.nombre_completo.label("racion_nombre"),
            Asistencia.fecha_comida.label("racion_fecha_comida"),
            Asistencia.fecha_hora.label("racion_fecha_hora"),
        )
        .select_from(Asistencia)
        .outerjoin(Comensal, Comensal.usuario_id == Asistencia.usuario_id)
        .outerjoin(Comida, Comida.id == Asistencia.comida_id)
        .where(
            # La rama sin lectura: manual de jefatura y checklist de cocina.
            Asistencia.metodo.in_(("manual", "checklist")),
            Asistencia.lectura_id.is_(None),
            func.date(Asistencia.fecha_hora) == dia,
        )
    )
    comida_policia = aliased(Comida, name="comida_policia")
    policias = (
        select(
            RacionPolicia.id.label("id"),
            literal(None).label("usuario_id"),
            RacionPolicia.fecha_hora,
            func.coalesce(RacionPolicia.nombre, VinculoLector.nombre, policia.NOMBRE).label("nombre"),
            literal("Policías").label("categoria"),
            RacionPolicia.comida_id,
            comida_policia.nombre.label("comida"),
            literal("aceptada").label("resultado"),
            literal(None).label("motivo"),
            literal(True).label("valido"),
            RacionPolicia.dispositivo,
            literal(None).label("lectura_resultado"),
            literal(None).label("lectura_motivo"),
            literal(None).label("asistencia_id"),
            literal(None).label("racion_usuario_id"),
            func.coalesce(RacionPolicia.nombre, VinculoLector.nombre, policia.NOMBRE).label("racion_nombre"),
            RacionPolicia.fecha_comida.label("racion_fecha_comida"),
            RacionPolicia.fecha_hora.label("racion_fecha_hora"),
        )
        .select_from(RacionPolicia)
        .outerjoin(VinculoLector, VinculoLector.id == RacionPolicia.vinculo_id)
        .outerjoin(comida_policia, comida_policia.id == RacionPolicia.comida_id)
        .where(
            func.date(RacionPolicia.fecha_hora) == dia,
            # El identificado por cocina sale como su lectura (huella no reconocida).
            RacionPolicia.lectura_id.is_(None),
        )
    )
    if comida_id is not None:
        lecturas = lecturas.where(comida_resuelta_id == comida_id)
        manuales = manuales.where(Asistencia.comida_id == comida_id)
        policias = policias.where(RacionPolicia.comida_id == comida_id)
    filas = _componer_ventana(sesion, lecturas, manuales, limite, policias)
    return _enriquecer(sesion, filas, rol, cuenta_id)


def _componer_ventana(
    sesion: Session, lecturas, manuales, limite: int, policias=None
) -> list[Marcacion]:
    """Une las tres ramas (lecturas, manuales y policías), ordena y corta la ventana.

    Cada rama agrega su `origen` como literal: sale de la consulta, nunca de
    una columna con datos. Orden: fecha_hora e id descendentes y, como último
    desempate, `origen` ascendente, para que dos filas con la misma fecha e
    id (una de cada tabla) salgan siempre en el mismo orden.
    """
    ramas = [
        lecturas.add_columns(literal(ORIGEN_LECTURA).label("origen")),
        manuales.add_columns(literal(ORIGEN_MANUAL).label("origen")),
    ]
    if policias is not None:
        ramas.append(policias.add_columns(literal(ORIGEN_POLICIA).label("origen")))
    consulta = union_all(*ramas).subquery("marcaciones")
    ordenadas = (
        select(consulta)
        .order_by(
            consulta.c.fecha_hora.desc(),
            consulta.c.id.desc(),
            consulta.c.origen.asc(),
        )
        .limit(limite)
    )
    return [
        Marcacion(**fila, clave_evento=clave_evento(fila["origen"], fila["id"]))
        for fila in sesion.execute(ordenadas).mappings().all()
    ]


def _es_rechazo_identificable(m: Marcacion) -> bool:
    """El rechazo ORIGINAL es de los que cocina puede identificar: valores
    GUARDADOS en la lectura, no lo que la pantalla presenta. No incluye si ya
    tiene ración: eso es otro caso (`lectura_ya_resuelta`)."""
    return (
        m.origen == ORIGEN_LECTURA
        and m.lectura_resultado == "rechazada"
        and m.lectura_motivo == "no_identificado"
        and m.usuario_id is None
    )


def _intervenciones_por_lectura(
    sesion: Session, ids: list[int]
) -> dict[int, list[tuple[int, str, datetime]]]:
    """(cuenta_id, resultado, momento) de cada intento, por lectura. Solo
    lectura: la tabla solo admite inserciones."""
    if not ids:
        return {}
    filas = sesion.execute(
        select(
            IntervencionLectura.lectura_id,
            IntervencionLectura.cuenta_id,
            IntervencionLectura.resultado,
            IntervencionLectura.momento,
        )
        .where(IntervencionLectura.lectura_id.in_(ids))
        .order_by(IntervencionLectura.id)
    ).all()
    por_lectura: dict[int, list[tuple[int, str, datetime]]] = {}
    for lectura_id, cuenta, resultado, momento in filas:
        por_lectura.setdefault(lectura_id, []).append((cuenta, resultado, momento))
    # Una huella que cocina identificó como policía: un intento registrado más.
    for lectura_id, cuenta, momento in sesion.execute(
        select(RacionPolicia.lectura_id, RacionPolicia.registrado_por_cuenta, RacionPolicia.fecha_hora)
        .where(RacionPolicia.lectura_id.in_(ids))
    ).all():
        por_lectura.setdefault(lectura_id, []).append((cuenta, "registrada", momento))
    return por_lectura


def _bloque_intervencion(
    rol: str | None,
    cuenta_id: int | None,
    intentos: list[tuple[int, str, datetime]],
    cuentas: dict[int, dict],
    resuelta: bool,
) -> dict | None:
    """Lo que cada rol ve de las intervenciones de una lectura.

    `revision` es la cantidad de filas de auditoría VISIBLES al rol. Como la
    tabla solo admite inserciones, el conjunto solo crece y `revision` nunca
    baja. Para la cocinera cuentan sus propios intentos y toda entrega
    registrada: cuando OTRA cocinera registra la entrega, sube exactamente 1,
    y un intento rechazado ajeno no cambia nada ni revela que existió. La
    cocinera no recibe ninguna cuenta ajena, solo `resuelta_por_mi`.
    """
    registrada = next((i for i in intentos if i[1] == "registrada"), None)
    if rol == "cocinera":
        visibles = [i for i in intentos if i[0] == cuenta_id or i[1] == "registrada"]
        return {
            "revision": len(visibles),
            "actualizado_en": max((i[2] for i in visibles), default=None),
            "resuelta": resuelta,
            "resuelta_por_mi": registrada is not None and registrada[0] == cuenta_id,
        }
    if rol == "jefa":
        return {
            "revision": len(intentos),
            "actualizado_en": max((i[2] for i in intentos), default=None),
            "resuelta": resuelta,
            "resuelta_por_mi": False,
            "registrada_por": cuentas.get(registrada[0]) if registrada else None,
            "intentos_rechazados": sum(1 for i in intentos if i[1] == "rechazada"),
        }
    return None  # sistemas, o sin rol: sin bloque ni datos de responsables


def _enriquecer(
    sesion: Session, filas: list[Marcacion], rol: str | None, cuenta_id: int | None
) -> list[Marcacion]:
    """Completa cada fila con la decisión original, el resultado final y lo
    que le toca ver a `rol` de las intervenciones.

    Cocinera: `puede_identificar` con el mismo predicado que usa el POST, en
    solo lectura (informativo: decide el POST). Jefa y sistemas nunca pueden
    identificar. La decisión original sale de los valores guardados de la
    lectura y no la sobrescribe ninguna intervención: el resultado final va
    aparte.
    """
    ids = [m.id for m in filas if _es_rechazo_identificable(m)]
    por_lectura = (
        _intervenciones_por_lectura(sesion, ids) if rol in ("cocinera", "jefa") else {}
    )
    cuentas: dict[int, dict] = {}
    if rol == "jefa":
        cuentas = cuentas_por_id(
            sesion,
            {i[0] for intentos in por_lectura.values() for i in intentos if i[1] == "registrada"},
        )
    ahora = reloj.ahora()
    ventanas: VentanasDelDia | None = None
    lecturas_ids = [m.id for m in filas if m.origen == ORIGEN_LECTURA and m.asistencia_id is None]
    policias_por_lectura = {
        f.lectura_id: f for f in sesion.execute(
            select(RacionPolicia.lectura_id, RacionPolicia.fecha_comida, RacionPolicia.fecha_hora,
                   Comida.nombre.label("comida"),
                   func.coalesce(RacionPolicia.nombre, VinculoLector.nombre, policia.NOMBRE).label("nombre"))
            .outerjoin(VinculoLector, VinculoLector.id == RacionPolicia.vinculo_id)
            .outerjoin(Comida, Comida.id == RacionPolicia.comida_id)
            .where(RacionPolicia.lectura_id.in_(lecturas_ids or [0]))
        ).all()
    }

    for m in filas:
        if m.origen == ORIGEN_POLICIA:
            # Vía libre: siempre una ración, sin lectura de personal que revisar.
            m.estado_final = "racion_servida"
            m.decision_original = None
            m.comida_origen = "persistida_en_asistencia"
            m.motivo_no_identificable = "no_aplica"
            m.resultado_final = {
                "via": "policia", "asistencia_id": None,
                "comensal": {"usuario_id": None, "nombre": m.racion_nombre or policia.NOMBRE},
                "comida": m.comida, "fecha_comida": m.racion_fecha_comida, "momento": m.racion_fecha_hora,
            }
            continue
        racion_policia = policias_por_lectura.get(m.id) if m.origen == ORIGEN_LECTURA else None
        con_racion = m.asistencia_id is not None or racion_policia is not None
        m.estado_final = "racion_servida" if con_racion else "sin_racion"
        es_lectura = m.origen == ORIGEN_LECTURA
        if es_lectura:
            m.decision_original = {
                "resultado": m.lectura_resultado,
                "motivo": m.lectura_motivo,
                "fecha_hora": m.fecha_hora,
                "dispositivo": m.dispositivo,
            }
            m.comida_origen = (
                "persistida_en_asistencia"
                if con_racion
                else "reconstruida_por_horario"
                if m.comida_id is not None
                else None
            )
        else:
            m.decision_original = None
            m.comida_origen = "persistida_en_asistencia"
            m.motivo_no_identificable = "no_aplica"

        if racion_policia is not None:
            m.resultado_final = {
                "via": "identificacion_policia", "asistencia_id": None,
                "comensal": {"usuario_id": None, "nombre": racion_policia.nombre},
                "comida": racion_policia.comida, "fecha_comida": racion_policia.fecha_comida,
                "momento": racion_policia.fecha_hora,
            }
        elif con_racion:
            if not es_lectura:
                via = "registro_manual"
            elif m.lectura_resultado == "aceptada":
                via = "lector"
            else:
                via = "identificacion_manual"
            m.resultado_final = {
                "via": via,
                "asistencia_id": m.asistencia_id,
                "comensal": {"usuario_id": m.racion_usuario_id, "nombre": m.racion_nombre},
                "comida": m.comida,
                "fecha_comida": m.racion_fecha_comida,
                "momento": m.racion_fecha_hora,
            }

        if not es_lectura:
            continue
        if not _es_rechazo_identificable(m):
            m.motivo_no_identificable = "lectura_no_resoluble"
            continue

        m.intervencion = _bloque_intervencion(
            rol, cuenta_id, por_lectura.get(m.id, []), cuentas, con_racion
        )
        if con_racion:
            m.motivo_no_identificable = "lectura_ya_resuelta"
            continue
        if rol != "cocinera":
            continue
        ventanas = ventanas or VentanasDelDia(sesion)
        evaluacion = evaluar_servicio(sesion, ventanas, m.fecha_hora, ahora)
        if evaluacion.motivo is not None:
            m.motivo_no_identificable = evaluacion.motivo
        else:
            m.puede_identificar = True
            m.identificable_hasta = evaluacion.servicio.fin
    return filas


# Tope de seguridad de `lecturas_por_identificar`. No es la ventana de 100 filas
# de `ultimas_marcaciones`: un servicio tiene muchas menos lecturas sin
# reconocer que esto, y si alguna vez se llega se avisa con `truncado`.
MAXIMO_POR_IDENTIFICAR = 500


@dataclass
class PorIdentificar:
    servicio: Servicio | None
    total: int
    truncado: bool
    lecturas: list[Marcacion]


def lecturas_por_identificar(sesion: Session, cuenta_id: int | None) -> PorIdentificar:
    """Las lecturas que la cocinera puede identificar AHORA, en el servicio
    actual, sin mirar la fecha ni la ventana de `ultimas_marcaciones`.

    `ultimas_marcaciones` se consulta por la fecha de la LECTURA y corta en
    100 filas. Un servicio que cruza la medianoche rompe las dos cosas: la
    lectura de las 23:58 sigue siendo del servicio a las 00:30, pero ya es de
    "ayer" y la fecha de hoy no la trae. Esta consulta parte del servicio
    actual (el mismo cómputo que el POST: `evaluar_servicio` con la hora de
    ahora en los dos extremos) y trae las lecturas `no_identificado`,
    pendientes, cuya hora cae dentro de la ventana efectiva, de ayer o de hoy.

    Cada fila pasa por `_enriquecer` con el rol de cocinera, así que repite el
    mismo predicado del POST (`puede_identificar`) y solo se devuelven las que
    de verdad se pueden identificar. Sin servicio determinable: lista vacía.
    """
    ahora = reloj.ahora()
    ventanas = VentanasDelDia(sesion)
    actual = evaluar_servicio(sesion, ventanas, ahora, ahora)
    if actual.motivo is not None or actual.servicio is None:
        return PorIdentificar(servicio=None, total=0, truncado=False, lecturas=[])
    servicio = actual.servicio

    sin_racion = and_(
        ~exists().where(Asistencia.lectura_id == LecturaBiometrica.id),
        ~exists().where(RacionPolicia.lectura_id == LecturaBiometrica.id),
    )
    filas = sesion.execute(
        select(
            LecturaBiometrica.id,
            LecturaBiometrica.fecha_hora,
            LecturaBiometrica.dispositivo,
        )
        .where(
            LecturaBiometrica.fecha_hora >= servicio.inicio,
            LecturaBiometrica.fecha_hora <= ahora,
            LecturaBiometrica.resultado == "rechazada",
            LecturaBiometrica.motivo == "no_identificado",
            LecturaBiometrica.usuario_id.is_(None),
            sin_racion,
        )
        .order_by(LecturaBiometrica.fecha_hora.desc(), LecturaBiometrica.id.desc())
        .limit(MAXIMO_POR_IDENTIFICAR)
    ).all()

    marcaciones = [
        Marcacion(
            id=id_,
            fecha_hora=fecha_hora,
            usuario_id=None,
            nombre="Huella no reconocida",
            categoria="Sin identificar",
            comida_id=servicio.comida_id,
            comida=servicio.comida,
            resultado="rechazada",
            motivo="no_identificado",
            valido=False,
            dispositivo=dispositivo,
            origen=ORIGEN_LECTURA,
            clave_evento=clave_evento(ORIGEN_LECTURA, id_),
            lectura_resultado="rechazada",
            lectura_motivo="no_identificado",
        )
        for id_, fecha_hora, dispositivo in filas
    ]
    enriquecidas = _enriquecer(sesion, marcaciones, "cocinera", cuenta_id)
    identificables = [m for m in enriquecidas if m.puede_identificar]
    return PorIdentificar(
        servicio=servicio,
        total=len(identificables),
        truncado=len(filas) >= MAXIMO_POR_IDENTIFICAR,
        lecturas=identificables,
    )


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
    Cada rechazo cuenta una sola vez: en su comida, o en rechazos_sin_comida
    si no tiene candidato o si empatan comidas distintas.
    """
    resuelta = _comida_por_lectura(dia)
    comida_resuelta_id = _comida_de_la_lectura(resuelta)
    # El motivo GUARDADO: una lectura sin usuario que se guardó como
    # fuera_horario ya no se cuenta como no_identificado. Las cifras por
    # comida no cambian (esa lectura no resuelve a ninguna y va a
    # rechazos_sin_comida), pero deja de rotularse mal.
    motivo_presentado = LecturaBiometrica.motivo
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
        .outerjoin(resuelta, resuelta.c.lectura_id == LecturaBiometrica.id)
        .where(*_del_dia(LecturaBiometrica.fecha_hora, dia))
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


def comidas_del_dia(
    sesion: Session, fecha: date | None = None
) -> ResumenComidas:
    """Una fila por comida con ventana efectiva ese día, para la supervisión.

    Solo lectura: previstas (derecho), servidas y manuales (asistencias por
    `fecha_comida`) y rechazos del día del reloj resueltos con la misma
    lógica de franja que `ultimas_marcaciones`, sin tope.

    El estado sale de las VENTANAS EFECTIVAS del día (app/consultas/horarios.py),
    no de la franja que hoy esté configurada: un horario guardado por la tarde
    no redefine un almuerzo que ya cerró por la mañana. `hora_inicio` y
    `hora_fin` son la franja de la versión de la última ventana.
    """
    dia = fecha or reloj.hoy()
    servidas, manuales = _servidas_por_comida(sesion, dia)
    policias = dict(sesion.execute(
        select(RacionPolicia.comida_id, func.count())
        .where(RacionPolicia.fecha_comida == dia)
        .group_by(RacionPolicia.comida_id)
    ).all())
    rechazos, sin_comida = _rechazos_por_comida(sesion, dia)
    ahora = reloj.ahora()
    comidas = [
        ComidaDelDia(
            comida_id=c.comida_id,
            comida=c.comida,
            hora_inicio=c.ultima.hora_inicio,
            hora_fin=c.ultima.hora_fin,
            estado=estado_en(c.ventanas, ahora),
            previstas=contar_personas_con_derecho(sesion, c.comida_id, dia),
            servidas=servidas.get(c.comida_id, 0),
            manuales=manuales.get(c.comida_id, 0),
            policias=policias.get(c.comida_id, 0),
            rechazos_por_motivo={
                motivo: rechazos.get((c.comida_id, motivo), 0)
                for motivo in MOTIVOS_POR_COMIDA
            },
        )
        for c in ventanas_del_dia(sesion, dia)
    ]
    return ResumenComidas(fecha=dia, comidas=comidas, rechazos_sin_comida=sin_comida)
