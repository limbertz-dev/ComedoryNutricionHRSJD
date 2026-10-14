"""Reglas de derecho (solo lectura) y horarios inmediatos, solo para root.

HORARIOS. Guardar un horario cierra la versión abierta de la comida y abre otra
desde el instante del servidor (`reloj.ahora()`, con microsegundos), dentro de
una transacción que empieza tomando el cerrojo `horarios_comida` (tabla
`cerrojos`). No hay fecha de vigencia, programación futura ni motivo escrito
por el usuario; la auditoría es automática: cuenta del token y `created_at`.
Nunca se borra ni se reescribe una versión: solo se cierra la abierta.

  · base_horario_id  la versión abierta que el cliente editó. Si ya no es esa,
                     409 version_desactualizada: otro cambio se coló.
  · instante         si el reloj no es posterior a toda `vigente_desde` de las
                     versiones EFECTIVAS (activo=1), 409 instante_no_posterior.
                     No se avanza el reloj ni se pisa una versión: se informa.
                     Una fila inactiva, aunque sea futura, no cuenta.
  · solape           contra la versión abierta de cada OTRA comida, serializado
                     por el cerrojo (también con `horarios_comida` vacía).

DERECHO. Solo lectura: sus versiones se resuelven en SQL por `fecha_turno`
(app/consultas/derecho.py) y esta capa ya no crea ni borra ninguna.
"""

from datetime import date, datetime, time

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.consultas.horarios import rige_en, version_rige_en
from app.core import reloj
from app.modelos.comedor import CERROJO_HORARIOS, Cerrojo, HorarioComida
from app.modelos.heredados import Comida
from app.modelos.reglas import ReglaDerecho, ReglaDerechoNovedad
from app.modelos.usuarios import UsuarioSistema

DIA = 24 * 3600

# Errores de MySQL que significan "otro cambio tiene el cerrojo" y no un fallo.
ESPERA_AGOTADA = 1205
INTERBLOQUEO = 1213


class ErrorRegla(Exception):
    """Un error con motivo. El endpoint la traduce a ErrorAuth."""

    def __init__(self, status_code: int, motivo: str, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.motivo = motivo
        self.detail = detail


def _codigo_mysql(error: Exception) -> int | None:
    return getattr(getattr(error, "orig", None), "args", [None])[0]


def _es_duplicado(error: IntegrityError) -> bool:
    return _codigo_mysql(error) == 1062


def _novedades_por_regla(sesion: Session, ids: list[int]) -> dict[int, list[str]]:
    if not ids:
        return {}
    filas = sesion.execute(
        select(ReglaDerechoNovedad.regla_id, ReglaDerechoNovedad.tipo_novedad)
        .where(ReglaDerechoNovedad.regla_id.in_(ids))
        .order_by(ReglaDerechoNovedad.tipo_novedad)
    ).all()
    agrupadas: dict[int, list[str]] = {i: [] for i in ids}
    for regla_id, tipo in filas:
        agrupadas[regla_id].append(tipo)
    return agrupadas


def _usernames(sesion: Session, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    filas = sesion.execute(
        select(UsuarioSistema.id, UsuarioSistema.username).where(
            UsuarioSistema.id.in_(sorted(ids))
        )
    ).all()
    return {i: u for i, u in filas}


# --- derecho (solo lectura) ----------------------------------------------------


def _estado(version: ReglaDerecho, vigente_id: int | None, hoy: date) -> str:
    if version.vigente_desde > hoy:
        return "programada"
    if vigente_id is not None and version.id == vigente_id:
        return "vigente"
    return "anterior"


def _version_para_respuesta(
    version: ReglaDerecho,
    novedades: list[str],
    creada_por: str | None,
    estado: str,
) -> dict:
    return {
        "id": version.id,
        "vigente_desde": version.vigente_desde,
        "duracion_minima_horas": version.duracion_minima_horas,
        "novedades_que_anulan": list(novedades),
        "excluir_enfermeria": bool(version.excluir_enfermeria),
        "motivo": version.motivo,
        "creada_por": creada_por,
        "creada": version.created_at,
        "estado": estado,
    }


def listar_derecho(sesion: Session) -> dict:
    hoy = reloj.hoy()
    versiones = (
        sesion.execute(
            select(ReglaDerecho).order_by(
                ReglaDerecho.vigente_desde.desc(), ReglaDerecho.id.desc()
            )
        )
        .scalars()
        .all()
    )
    vigente = next((v for v in versiones if v.vigente_desde <= hoy), None)
    vigente_id = vigente.id if vigente else None
    novedades = _novedades_por_regla(sesion, [v.id for v in versiones])
    nombres = _usernames(
        sesion, {v.creada_por_cuenta for v in versiones if v.creada_por_cuenta}
    )
    items = [
        _version_para_respuesta(
            v,
            novedades.get(v.id, []),
            nombres.get(v.creada_por_cuenta) if v.creada_por_cuenta else None,
            _estado(v, vigente_id, hoy),
        )
        for v in versiones
    ]
    vigente_item = next((i for i in items if i["id"] == vigente_id), None)
    if vigente_item is None:
        raise ErrorRegla(404, "version_inexistente", "No hay versión vigente.")
    return {"vigente": vigente_item, "versiones": items}


# --- horarios: solape y respuesta ----------------------------------------------


def _a_segundos(momento: time) -> int:
    return momento.hour * 3600 + momento.minute * 60 + momento.second


def _segmentos(inicio: time, fin: time) -> list[tuple[int, int]]:
    ini, out = _a_segundos(inicio), _a_segundos(fin)
    if out < ini:
        return [(ini, DIA), (0, out)]
    return [(ini, out)]


def franjas_se_solapan(a_ini: time, a_fin: time, b_ini: time, b_fin: time) -> bool:
    """Dos franjas diarias [inicio, fin) se superponen. La que cruza la
    medianoche (fin < inicio) cuenta como dos tramos."""
    for s1, e1 in _segmentos(a_ini, a_fin):
        for s2, e2 in _segmentos(b_ini, b_fin):
            if max(s1, s2) < min(e1, e2):
                return True
    return False


def _nombres_comidas(sesion: Session, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    filas = sesion.execute(
        select(Comida.id, Comida.nombre).where(Comida.id.in_(sorted(ids)))
    ).all()
    return {i: n for i, n in filas}


def _estado_horario(horario: HorarioComida) -> str:
    """vigente = la versión abierta; anterior = cerrada; inactiva = fila con
    activo=0, que nunca se aplica (no la crea este código)."""
    if not horario.activo:
        return "inactiva"
    return "vigente" if horario.vigente_hasta is None else "anterior"


def _horario_para_respuesta(
    horario: HorarioComida, comida: str | None, creada_por: str | None
) -> dict:
    return {
        "horario_id": horario.id,
        "comida_id": horario.comida_id,
        "comida": comida,
        "hora_inicio": horario.hora_inicio,
        "hora_fin": horario.hora_fin,
        "cruza_medianoche": horario.hora_fin < horario.hora_inicio,
        "vigente_desde": horario.vigente_desde,
        "vigente_hasta": horario.vigente_hasta,
        "motivo": horario.motivo,
        "creada_por": creada_por,
        "creada": horario.created_at,
        "estado": _estado_horario(horario),
    }


def listar_horarios(sesion: Session, momento: datetime) -> list[dict]:
    """La versión de cada comida que regía en el instante `momento`."""
    filas = (
        sesion.execute(
            select(HorarioComida)
            .where(rige_en(HorarioComida, momento))
            .order_by(HorarioComida.vigente_desde.desc(), HorarioComida.id.desc())
        )
        .scalars()
        .all()
    )
    vigentes: dict[int, HorarioComida] = {}
    for fila in filas:
        vigentes.setdefault(fila.comida_id, fila)
    nombres = _nombres_comidas(sesion, set(vigentes))
    autores = _usernames(
        sesion, {h.creada_por_cuenta for h in vigentes.values() if h.creada_por_cuenta}
    )
    items = [
        _horario_para_respuesta(
            h,
            nombres.get(h.comida_id),
            autores.get(h.creada_por_cuenta) if h.creada_por_cuenta else None,
        )
        for h in vigentes.values()
    ]
    return sorted(items, key=lambda i: (i["hora_inicio"], i["comida_id"]))


def historial_horarios(sesion: Session, comida_id: int) -> list[dict]:
    nombre = sesion.execute(
        select(Comida.nombre).where(Comida.id == comida_id)
    ).scalar_one_or_none()
    if nombre is None:
        raise ErrorRegla(404, "comida_inexistente", "No existe esa comida.")
    filas = (
        sesion.execute(
            select(HorarioComida)
            .where(HorarioComida.comida_id == comida_id)
            .order_by(HorarioComida.vigente_desde.desc(), HorarioComida.id.desc())
        )
        .scalars()
        .all()
    )
    autores = _usernames(
        sesion, {h.creada_por_cuenta for h in filas if h.creada_por_cuenta}
    )
    return [
        _horario_para_respuesta(
            h, nombre, autores.get(h.creada_por_cuenta) if h.creada_por_cuenta else None
        )
        for h in filas
    ]


# --- horarios: guardar ---------------------------------------------------------


def guardar_horario(
    sesion: Session,
    comida_id: int,
    hora_inicio: time,
    hora_fin: time,
    base_horario_id: int | None,
    cuenta_id: int,
    autor: str,
) -> dict:
    """Guarda el horario de una comida con efecto inmediato.

    `cuenta_id` y `autor` llegan como valores simples, copiados por el
    endpoint ANTES de entrar aquí: el rollback de abajo expira los objetos
    ORM de la sesión, y leer `usuario.id` después abriría una lectura nueva
    antes de tener el cerrojo.
    """
    if hora_inicio == hora_fin:
        raise ErrorRegla(
            422, "horario_invalido", "La hora de inicio y la de fin no coinciden."
        )
    # La autenticación dejó abierta una transacción de solo lectura, con su
    # snapshot de REPEATABLE READ. Se termina ahora para que lo que se lea
    # después del cerrojo sea lo último confirmado, no una foto vieja. Solo
    # hubo SELECT: no se pierde ninguna escritura.
    sesion.rollback()
    try:
        nuevo, nombre = _guardar_bajo_cerrojo(
            sesion, comida_id, hora_inicio, hora_fin, base_horario_id, cuenta_id
        )
        sesion.commit()
    except OperationalError as error:
        sesion.rollback()
        if _codigo_mysql(error) in (ESPERA_AGOTADA, INTERBLOQUEO):
            raise ErrorRegla(
                409,
                "cambio_en_curso",
                "Hay otro cambio de horarios en curso. Vuelva a intentarlo.",
            ) from error
        raise
    except IntegrityError as error:
        sesion.rollback()
        if _es_duplicado(error):
            raise ErrorRegla(
                409,
                "instante_no_posterior",
                "Ya hay una versión de esta comida desde ese mismo instante.",
            ) from error
        raise
    except BaseException:
        # Suelta el cerrojo, que dura lo que la transacción.
        sesion.rollback()
        raise
    sesion.refresh(nuevo)
    return _horario_para_respuesta(nuevo, nombre, autor)


def _guardar_bajo_cerrojo(
    sesion: Session,
    comida_id: int,
    hora_inicio: time,
    hora_fin: time,
    base_horario_id: int | None,
    cuenta_id: int,
) -> tuple[HorarioComida, str]:
    # 1. Primera sentencia de la transacción: el cerrojo. Bloqueo de registro
    #    sobre una fila que siempre existe, exclusivo en cualquier aislamiento.
    cerrojo = sesion.execute(
        select(Cerrojo.nombre)
        .where(Cerrojo.nombre == CERROJO_HORARIOS)
        .with_for_update()
    ).scalar_one_or_none()
    if cerrojo is None:
        raise ErrorRegla(
            500,
            "cerrojo_ausente",
            "Falta el cerrojo de horarios: aplique las migraciones.",
        )

    nombre = sesion.execute(
        select(Comida.nombre).where(Comida.id == comida_id)
    ).scalar_one_or_none()
    if nombre is None:
        raise ErrorRegla(404, "comida_inexistente", "No existe esa comida.")

    # 2. Todas las versiones, con lectura actual (FOR UPDATE): son decenas de
    #    filas y ningún otro escritor puede estar aquí.
    versiones = (
        sesion.execute(
            select(HorarioComida)
            .order_by(HorarioComida.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        .scalars()
        .all()
    )

    abiertas = [
        v
        for v in versiones
        if v.comida_id == comida_id and v.activo and v.vigente_hasta is None
    ]
    if len(abiertas) > 1:
        raise ErrorRegla(
            409,
            "versiones_abiertas_multiples",
            "La comida tiene más de una versión abierta: corrija los datos antes de guardar.",
        )
    abierta = abiertas[0] if abiertas else None

    if base_horario_id != (abierta.id if abierta else None):
        raise ErrorRegla(
            409,
            "version_desactualizada",
            "El horario cambió desde que lo abrió: recárguelo y vuelva a guardar.",
        )
    if (
        abierta is not None
        and abierta.hora_inicio == hora_inicio
        and abierta.hora_fin == hora_fin
    ):
        raise ErrorRegla(409, "sin_cambios", "El horario guardado ya es ese.")

    # 3. El instante. Se lee ya con el cerrojo en la mano, justo antes del
    #    INSERT, así el orden de los instantes es el de las confirmaciones.
    #    Sin avanzar el reloj ni tocar versiones históricas: si no es
    #    estrictamente posterior a toda versión EFECTIVA, se informa. Una fila
    #    inactiva (activo=0) nunca se aplica, aunque tenga una fecha futura:
    #    no cuenta como retroceso ni bloquea los guardados. Tampoco se borra
    #    ni se reactiva: simplemente no es parte de la historia efectiva.
    ahora = reloj.ahora()
    ultimo = max((v.vigente_desde for v in versiones if v.activo), default=None)
    if ultimo is not None and ahora <= ultimo:
        raise ErrorRegla(
            409,
            "instante_no_posterior",
            (
                f"El reloj ({ahora.isoformat()}) no es posterior a la última versión "
                f"efectiva ({ultimo.isoformat()}); no se guardó nada."
            ),
        )

    # 4. Solape contra la versión que rige AHORA en cada otra comida.
    for otra in versiones:
        if (
            otra.comida_id != comida_id
            and version_rige_en(otra, ahora)
            and franjas_se_solapan(
                hora_inicio, hora_fin, otra.hora_inicio, otra.hora_fin
            )
        ):
            raise ErrorRegla(
                409,
                "solapa_con_otra_comida",
                "La franja se superpone con la de otra comida vigente.",
            )

    if abierta is not None:
        abierta.vigente_hasta = ahora
    nuevo = HorarioComida(
        comida_id=comida_id,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
        vigente_desde=ahora,
        vigente_hasta=None,
        activo=1,
        motivo=None,
        creada_por_cuenta=cuenta_id,
    )
    sesion.add(nuevo)
    sesion.flush()
    return nuevo, nombre
