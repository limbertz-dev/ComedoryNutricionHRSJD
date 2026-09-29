"""Reglas versionadas de derecho y horarios, solo para root.

Todo cambio es una versión nueva con `vigente_desde` hoy o futuro; nunca
se edita ni se borra una vigente o pasada. Solo se borra una programada.

El solape de horarios se valida contra las otras comidas vigentes en
`vigente_desde` Y contra sus programadas posteriores dentro del período
que la nueva versión va a cubrir.
"""

from datetime import date, time, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import reloj
from app.modelos.comedor import HorarioComida
from app.modelos.heredados import Comida, NovedadLaboral
from app.modelos.reglas import ReglaDerecho, ReglaDerechoNovedad
from app.modelos.usuarios import UsuarioSistema

DIA = 24 * 3600


class ErrorRegla(Exception):
    """Un 4xx con motivo. El endpoint la traduce a ErrorAuth."""

    def __init__(self, status_code: int, motivo: str, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.motivo = motivo
        self.detail = detail


def _es_duplicado(error: IntegrityError) -> bool:
    codigo = getattr(getattr(error, "orig", None), "args", [None])[0]
    return codigo == 1062


def _exigir_motivo(motivo: str | None) -> str:
    texto = (motivo or "").strip()
    if len(texto) < 10:
        raise ErrorRegla(
            422, "motivo_obligatorio", "El motivo es obligatorio, 10 o más caracteres."
        )
    return texto


def _exigir_futura_o_hoy(vigente_desde: date) -> None:
    if vigente_desde < reloj.hoy():
        raise ErrorRegla(
            422, "vigencia_en_el_pasado", "La vigencia no puede ser anterior a hoy."
        )


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


def crear_derecho(
    sesion: Session,
    vigente_desde: date,
    duracion_minima_horas: int,
    novedades_que_anulan: list[str],
    excluir_enfermeria: bool,
    motivo: str,
    creada_por: UsuarioSistema,
) -> dict:
    texto = _exigir_motivo(motivo)
    _exigir_futura_o_hoy(vigente_desde)
    limpias = sorted({n.strip() for n in (novedades_que_anulan or []) if n.strip()})
    existe = sesion.execute(
        select(ReglaDerecho.id)
        .where(ReglaDerecho.vigente_desde == vigente_desde)
        .with_for_update()
    ).scalar_one_or_none()
    if existe is not None:
        raise ErrorRegla(
            409, "version_en_esa_fecha", "Ya hay una versión con esa vigencia."
        )
    version = ReglaDerecho(
        vigente_desde=vigente_desde,
        duracion_minima_horas=duracion_minima_horas,
        excluir_enfermeria=1 if excluir_enfermeria else 0,
        motivo=texto,
        creada_por_cuenta=creada_por.id,
    )
    sesion.add(version)
    try:
        sesion.flush()
    except IntegrityError as error:
        sesion.rollback()
        if _es_duplicado(error):
            raise ErrorRegla(
                409, "version_en_esa_fecha", "Ya hay una versión con esa vigencia."
            ) from error
        raise
    for tipo in limpias:
        sesion.add(ReglaDerechoNovedad(regla_id=version.id, tipo_novedad=tipo))
    try:
        sesion.commit()
    except IntegrityError as error:
        sesion.rollback()
        if _es_duplicado(error):
            raise ErrorRegla(
                409, "version_en_esa_fecha", "Ya hay una versión con esa vigencia."
            ) from error
        raise
    sesion.refresh(version)
    hoy = reloj.hoy()
    vigente_id = sesion.execute(
        select(ReglaDerecho.id)
        .where(ReglaDerecho.vigente_desde <= hoy)
        .order_by(ReglaDerecho.vigente_desde.desc(), ReglaDerecho.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    return _version_para_respuesta(
        version, limpias, creada_por.username, _estado(version, vigente_id, hoy)
    )


def eliminar_derecho(sesion: Session, version_id: int) -> None:
    version = sesion.execute(
        select(ReglaDerecho)
        .where(ReglaDerecho.id == version_id)
        .with_for_update()
    ).scalar_one_or_none()
    if version is None:
        raise ErrorRegla(404, "version_inexistente", "No existe esa versión.")
    if version.vigente_desde <= reloj.hoy():
        raise ErrorRegla(
            409, "version_ya_vigente", "Solo se puede borrar una versión programada."
        )
    sesion.execute(
        select(ReglaDerechoNovedad.id).where(
            ReglaDerechoNovedad.regla_id == version.id
        )
    )
    for fila in (
        sesion.execute(
            select(ReglaDerechoNovedad).where(
                ReglaDerechoNovedad.regla_id == version.id
            )
        )
        .scalars()
        .all()
    ):
        sesion.delete(fila)
    sesion.delete(version)
    sesion.commit()


def listar_novedades(sesion: Session) -> list[str]:
    hoy = reloj.hoy()
    vigente_id = sesion.execute(
        select(ReglaDerecho.id)
        .where(ReglaDerecho.vigente_desde <= hoy)
        .order_by(ReglaDerecho.vigente_desde.desc(), ReglaDerecho.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    en_vista = {
        t
        for (t,) in sesion.execute(
            select(func.distinct(NovedadLaboral.tipo_novedad))
        ).all()
        if t
    }
    en_vigente: set[str] = set()
    if vigente_id is not None:
        en_vigente = {
            t
            for (t,) in sesion.execute(
                select(ReglaDerechoNovedad.tipo_novedad).where(
                    ReglaDerechoNovedad.regla_id == vigente_id
                )
            ).all()
        }
    return sorted(en_vista | en_vigente)


def _a_segundos(momento: time) -> int:
    return momento.hour * 3600 + momento.minute * 60 + momento.second


def _segmentos(inicio: time, fin: time) -> list[tuple[int, int]]:
    ini, out = _a_segundos(inicio), _a_segundos(fin)
    if out < ini:
        return [(ini, DIA), (0, out)]
    return [(ini, out)]


def _solapan(a_ini: time, a_fin: time, b_ini: time, b_fin: time) -> bool:
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
    }


def listar_horarios(sesion: Session, fecha: date) -> list[dict]:
    filas = (
        sesion.execute(
            select(HorarioComida)
            .where(HorarioComida.activo == 1)
            .where(HorarioComida.vigente_desde <= fecha)
            .where(
                or_(
                    HorarioComida.vigente_hasta.is_(None),
                    HorarioComida.vigente_hasta >= fecha,
                )
            )
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


def _siguiente_de(
    sesion: Session, comida_id: int, desde: date
) -> HorarioComida | None:
    return sesion.execute(
        select(HorarioComida)
        .where(HorarioComida.comida_id == comida_id)
        .where(HorarioComida.vigente_desde > desde)
        .order_by(HorarioComida.vigente_desde.asc(), HorarioComida.id.asc())
        .limit(1)
        .with_for_update()
    ).scalar_one_or_none()


def _anterior_a(
    sesion: Session, comida_id: int, desde: date
) -> HorarioComida | None:
    return sesion.execute(
        select(HorarioComida)
        .where(HorarioComida.comida_id == comida_id)
        .where(HorarioComida.vigente_desde < desde)
        .order_by(HorarioComida.vigente_desde.desc(), HorarioComida.id.desc())
        .limit(1)
        .with_for_update()
    ).scalar_one_or_none()


def _exigir_sin_solape(
    sesion: Session,
    comida_id: int,
    inicio: time,
    fin: time,
    desde: date,
    fin_cobertura: date | None,
) -> None:
    otras = (
        sesion.execute(
            select(HorarioComida)
            .where(HorarioComida.comida_id != comida_id)
            .where(HorarioComida.activo == 1)
            .order_by(HorarioComida.comida_id, HorarioComida.vigente_desde)
        )
        .scalars()
        .all()
    )
    fechas = {desde}
    for fila in otras:
        if fila.vigente_desde > desde and (
            fin_cobertura is None or fila.vigente_desde <= fin_cobertura
        ):
            fechas.add(fila.vigente_desde)
    por_comida: dict[int, list[HorarioComida]] = {}
    for fila in otras:
        por_comida.setdefault(fila.comida_id, []).append(fila)
    for dia in sorted(fechas):
        for grupo in por_comida.values():
            candidatos = [
                v
                for v in grupo
                if v.vigente_desde <= dia
                and (v.vigente_hasta is None or v.vigente_hasta >= dia)
            ]
            if not candidatos:
                continue
            vigente = max(candidatos, key=lambda v: (v.vigente_desde, v.id))
            if _solapan(inicio, fin, vigente.hora_inicio, vigente.hora_fin):
                raise ErrorRegla(
                    409,
                    "solapa_con_otra_comida",
                    "La franja se superpone con la de otra comida vigente.",
                )


def crear_horario(
    sesion: Session,
    comida_id: int,
    hora_inicio: time,
    hora_fin: time,
    vigente_desde: date,
    motivo: str,
    creada_por: UsuarioSistema,
) -> dict:
    texto = _exigir_motivo(motivo)
    _exigir_futura_o_hoy(vigente_desde)
    if hora_inicio == hora_fin:
        raise ErrorRegla(
            422, "horario_invalido", "La hora de inicio y la de fin no coinciden."
        )
    nombre = sesion.execute(
        select(Comida.nombre).where(Comida.id == comida_id)
    ).scalar_one_or_none()
    if nombre is None:
        raise ErrorRegla(404, "comida_inexistente", "No existe esa comida.")
    duplicada = sesion.execute(
        select(HorarioComida.id)
        .where(
            HorarioComida.comida_id == comida_id,
            HorarioComida.vigente_desde == vigente_desde,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if duplicada is not None:
        raise ErrorRegla(
            409, "version_en_esa_fecha", "Ya hay una versión con esa vigencia."
        )
    siguiente = _siguiente_de(sesion, comida_id, vigente_desde)
    fin_cobertura = siguiente.vigente_desde - timedelta(days=1) if siguiente else None
    _exigir_sin_solape(
        sesion, comida_id, hora_inicio, hora_fin, vigente_desde, fin_cobertura
    )
    anterior = _anterior_a(sesion, comida_id, vigente_desde)
    nuevo = HorarioComida(
        comida_id=comida_id,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
        vigente_desde=vigente_desde,
        vigente_hasta=fin_cobertura,
        activo=1,
        motivo=texto,
        creada_por_cuenta=creada_por.id,
    )
    if anterior is not None:
        anterior.vigente_hasta = vigente_desde - timedelta(days=1)
    sesion.add(nuevo)
    try:
        sesion.flush()
    except IntegrityError as error:
        sesion.rollback()
        if _es_duplicado(error):
            raise ErrorRegla(
                409, "version_en_esa_fecha", "Ya hay una versión con esa vigencia."
            ) from error
        raise
    sesion.commit()
    sesion.refresh(nuevo)
    return _horario_para_respuesta(nuevo, nombre, creada_por.username)


def eliminar_horario(sesion: Session, horario_id: int) -> None:
    horario = sesion.execute(
        select(HorarioComida)
        .where(HorarioComida.id == horario_id)
        .with_for_update()
    ).scalar_one_or_none()
    if horario is None:
        raise ErrorRegla(404, "version_inexistente", "No existe esa versión.")
    if horario.vigente_desde <= reloj.hoy():
        raise ErrorRegla(
            409, "version_ya_vigente", "Solo se puede borrar una versión programada."
        )
    anterior = _anterior_a(sesion, horario.comida_id, horario.vigente_desde)
    siguiente = _siguiente_de(sesion, horario.comida_id, horario.vigente_desde)
    if anterior is not None:
        anterior.vigente_hasta = (
            siguiente.vigente_desde - timedelta(days=1) if siguiente else None
        )
    sesion.delete(horario)
    sesion.commit()
