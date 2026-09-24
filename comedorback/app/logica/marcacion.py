"""La marcación: qué pasa cuando alguien apoya el dedo en el lector.

El orden de las validaciones no es arbitrario y no conviene cambiarlo:

  1. fuera_horario   primero por necesidad técnica: sin saber qué comida es,
                     no se puede comprobar nada más.
  2. duplicado       una persona no puede recibir dos raciones del mismo
                     tiempo de comida y fecha.
  3. sin_derecho     no le toca esa comida con el turno que tiene asignado.

Y una regla que no se ve en el código pero lo sostiene: el rechazo NO se
descarta, se guarda en `lecturas_biometricas`. Lo que se evita es la ración,
nunca el registro del intento. Si alguien reclama que marcó y no aparece,
tiene que haber con qué responderle.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.consultas.derecho import Derecho, buscar_derecho
from app.modelos.comedor import (
    Asistencia,
    CategoriaReporte,
    CategoriaReporteMap,
    HorarioComida,
    LecturaBiometrica,
)
from app.modelos.heredados import Comensal, Comida

CODIGO_SIN_CLASIFICAR = "sin_clasificar"


@dataclass(frozen=True)
class ComidaEnCurso:
    comida_id: int
    comida: str
    fecha_comida: date


@dataclass(frozen=True)
class Resultado:
    valido: bool
    motivo: str | None
    titulo: str
    detalle: str
    usuario_id: int | None = None
    nombre: str | None = None
    comida: str | None = None
    comida_id: int | None = None
    fecha_comida: date | None = None
    servicio_id: int | None = None
    lectura_id: int | None = None
    asistencia_id: int | None = None
    raciones_restantes: int | None = None


def resolver_comida_en_curso(sesion: Session, momento: datetime) -> ComidaEnCurso | None:
    """Qué tiempo de comida corresponde al reloj, según horarios_comida.

    Si la franja cruza la medianoche (hora_fin < hora_inicio) y la marcación cae
    en la madrugada, la ración pertenece al día ANTERIOR. Sin esto, alguien que
    marca el café nocturno a las 23:58 y otra vez a las 00:02 recibiría dos.
    """
    hoy = momento.date()
    hora = momento.time()

    cruza_medianoche = HorarioComida.hora_fin < HorarioComida.hora_inicio
    dentro_normal = and_(
        ~cruza_medianoche,
        HorarioComida.hora_inicio <= hora,
        HorarioComida.hora_fin > hora,
    )
    dentro_cruzada = and_(
        cruza_medianoche,
        or_(HorarioComida.hora_inicio <= hora, HorarioComida.hora_fin > hora),
    )

    consulta = (
        select(
            Comida.id,
            Comida.nombre,
            HorarioComida.hora_inicio,
            HorarioComida.hora_fin,
        )
        .join(Comida, Comida.id == HorarioComida.comida_id)
        .where(HorarioComida.activo == 1)
        .where(HorarioComida.vigente_desde <= hoy)
        .where(
            or_(
                HorarioComida.vigente_hasta.is_(None),
                HorarioComida.vigente_hasta >= hoy,
            )
        )
        .where(or_(dentro_normal, dentro_cruzada))
        .order_by(HorarioComida.vigente_desde.desc())
        .limit(1)
    )
    fila = sesion.execute(consulta).first()
    if fila is None:
        return None

    comida_id, nombre, inicio, fin = fila
    fecha = hoy
    if fin < inicio and hora < fin:
        # Madrugada: la ración es del día que terminó.
        fecha = hoy - timedelta(days=1)
    return ComidaEnCurso(comida_id=comida_id, comida=nombre, fecha_comida=fecha)


def _nombre_de(sesion: Session, usuario_id: int) -> str | None:
    consulta = select(Comensal.nombre_completo).where(
        Comensal.usuario_id == usuario_id
    )
    return sesion.execute(consulta).scalar_one_or_none()


def _categoria_reporte_de(sesion: Session, usuario_id: int) -> int:
    """La columna del informe que le toca a esta persona.

    Si su categoría todavía no está mapeada, cae en "Sin clasificar" en vez de
    rechazar la ración: no se le niega la comida a nadie porque el hospital no
    haya terminado de decidir el mapeo. El hueco queda visible en el informe.
    """
    consulta = (
        select(CategoriaReporteMap.categoria_reporte_id)
        .join(Comensal, Comensal.categoria_id == CategoriaReporteMap.categoria_id)
        .where(Comensal.usuario_id == usuario_id)
        .limit(1)
    )
    mapeada = sesion.execute(consulta).scalar_one_or_none()
    if mapeada is not None:
        return mapeada
    return sesion.execute(
        select(CategoriaReporte.id).where(
            CategoriaReporte.codigo == CODIGO_SIN_CLASIFICAR
        )
    ).scalar_one()


def _ya_comio(sesion: Session, usuario_id: int, comida: ComidaEnCurso) -> bool:
    return sesion.execute(
        select(Asistencia.id).where(
            Asistencia.usuario_id == usuario_id,
            Asistencia.fecha_comida == comida.fecha_comida,
            Asistencia.comida_id == comida.comida_id,
        )
    ).first() is not None


def _guardar_lectura(
    sesion: Session,
    usuario_id: int | None,
    momento: datetime,
    dispositivo: str,
    resultado: str,
    motivo: str | None,
) -> int:
    lectura = LecturaBiometrica(
        usuario_id=usuario_id,
        dispositivo=dispositivo,
        fecha_hora=momento,
        resultado=resultado,
        motivo=motivo,
    )
    sesion.add(lectura)
    sesion.flush()
    return lectura.id


def registrar_marcacion(
    sesion: Session,
    *,
    usuario_id: int | None,
    momento: datetime | None = None,
    dispositivo: str = "lector-comedor-01",
    metodo: str = "biometrico",
    registrado_por: int | None = None,
) -> Resultado:
    """Aplica las reglas y, si pasan todas, registra la ración."""
    momento = momento or datetime.now()
    nombre = _nombre_de(sesion, usuario_id) if usuario_id is not None else None
    es_biometrico = metodo == "biometrico"

    def rechazar(motivo: str, detalle: str, comida: ComidaEnCurso | None = None) -> Resultado:
        lectura_id = (
            _guardar_lectura(sesion, usuario_id, momento, dispositivo, "rechazada", motivo)
            if es_biometrico
            else None
        )
        sesion.commit()
        return Resultado(
            valido=False,
            motivo=motivo,
            titulo="Marcación rechazada",
            detalle=detalle,
            usuario_id=usuario_id,
            nombre=nombre,
            comida=comida.comida if comida else None,
            comida_id=comida.comida_id if comida else None,
            fecha_comida=comida.fecha_comida if comida else None,
            lectura_id=lectura_id,
        )

    comida = resolver_comida_en_curso(sesion, momento)
    if comida is None:
        return rechazar(
            "fuera_horario",
            "No hay un tiempo de comida vigente a esta hora",
        )

    if usuario_id is None:
        lectura_id = _guardar_lectura(
            sesion,
            usuario_id=None,
            momento=momento,
            dispositivo=dispositivo,
            resultado="rechazada",
            motivo="no_identificado",
        )
        sesion.commit()
        return Resultado(
            valido=False,
            motivo="no_identificado",
            titulo="Huella no reconocida",
            detalle=(
                "El lector no pudo identificar la huella dactilar. Verifique el "
                "padrón y proceda con registro manual si corresponde."
            ),
            usuario_id=None,
            nombre=None,
            comida=comida.comida,
            comida_id=comida.comida_id,
            fecha_comida=comida.fecha_comida,
            lectura_id=lectura_id,
        )

    if metodo == "manual":
        derecho: Derecho | None = buscar_derecho(
            sesion, usuario_id, comida.comida_id, comida.fecha_comida
        )
        if derecho is None:
            return rechazar(
                "sin_derecho",
                f"Su turno asignado no incluye {comida.comida.lower()} en esta fecha",
                comida,
            )
        if _ya_comio(sesion, usuario_id, comida):
            return rechazar(
                "duplicado",
                f"Ya recibió su {comida.comida.lower()} de hoy",
                comida,
            )
    else:
        if _ya_comio(sesion, usuario_id, comida):
            return rechazar(
                "duplicado",
                f"Ya recibió su {comida.comida.lower()} de hoy",
                comida,
            )
        derecho = buscar_derecho(
            sesion, usuario_id, comida.comida_id, comida.fecha_comida
        )
        if derecho is None:
            return rechazar(
                "sin_derecho",
                f"Su turno asignado no incluye {comida.comida.lower()} en esta fecha",
                comida,
            )

    lectura_id = (
        _guardar_lectura(sesion, usuario_id, momento, dispositivo, "aceptada", None)
        if es_biometrico
        else None
    )

    asistencia = Asistencia(
        usuario_id=usuario_id,
        fecha_comida=comida.fecha_comida,
        comida_id=comida.comida_id,
        categoria_reporte_id=_categoria_reporte_de(sesion, usuario_id),
        servicio_id=derecho.servicio_id,
        turno_asignado_id=derecho.turno_asignado_id,
        metodo=metodo,
        lectura_id=lectura_id,
        fecha_hora=momento,
        registrado_por=registrado_por,
    )
    sesion.add(asistencia)

    try:
        sesion.commit()
    except IntegrityError as error:
        # Dos lecturas en el mismo segundo pasan por el hueco entre la consulta
        # de duplicado y este INSERT. El índice único es la única defensa real;
        # el error 1062 se traduce al mismo rechazo de siempre.
        sesion.rollback()
        if _es_duplicado(error):
            return rechazar(
                "duplicado", f"Ya recibió su {comida.comida.lower()} de hoy", comida
            )
        raise

    return Resultado(
        valido=True,
        motivo=None,
        titulo="Ración manual habilitada" if metodo == "manual" else "Marcación válida",
        detalle=(
            "Ración autorizada manualmente — comensal registrado"
            if metodo == "manual"
            else "Ración habilitada — puede pasar al comedor"
        ),
        usuario_id=usuario_id,
        nombre=nombre,
        comida=comida.comida,
        comida_id=comida.comida_id,
        fecha_comida=comida.fecha_comida,
        servicio_id=derecho.servicio_id,
        lectura_id=lectura_id,
        asistencia_id=asistencia.id,
    )


def _es_duplicado(error: IntegrityError) -> bool:
    codigo = getattr(getattr(error, "orig", None), "args", [None])[0]
    return codigo == 1062
