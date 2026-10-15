"""Las intervenciones de cocina, para que la jefa las consulte.

Sale de `intervenciones_lectura` (solo inserciones) con la lectura original
al lado: la decisión del lector se muestra tal como quedó guardada, sin que
una intervención la sobrescriba. Solo lectura: ningún SELECT de acá bloquea.

Aquí NO entran los registros manuales independientes de jefatura (siguen su
propio camino y no tienen lectura vinculada) ni nada histórico: no hay forma
honesta de decir que una asistencia manual anterior respondió a una lectura,
y menos a una cocinera.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import case, exists, func, select
from sqlalchemy.orm import Session, aliased

from app.modelos.comedor import IntervencionLectura, LecturaBiometrica
from app.modelos.heredados import Comensal
from app.modelos.usuarios import UsuarioSistema

MAXIMO_DIAS = 31


@dataclass
class Filtros:
    desde: date
    hasta: date
    resultado: str | None = None
    motivo_rechazo: str | None = None
    comida_id: int | None = None
    cuenta_id: int | None = None
    usuario_id: int | None = None


def clave_evento(id_: int) -> str:
    return f"intervencion_lectura:{id_}"


def _condiciones(filtros: Filtros) -> list:
    inicio = datetime.combine(filtros.desde, time.min)
    fin = datetime.combine(filtros.hasta, time.min) + timedelta(days=1)
    condiciones = [
        IntervencionLectura.momento >= inicio,
        IntervencionLectura.momento < fin,
    ]
    if filtros.resultado is not None:
        condiciones.append(IntervencionLectura.resultado == filtros.resultado)
    if filtros.motivo_rechazo is not None:
        condiciones.append(IntervencionLectura.motivo_rechazo == filtros.motivo_rechazo)
    if filtros.comida_id is not None:
        condiciones.append(IntervencionLectura.comida_id == filtros.comida_id)
    if filtros.cuenta_id is not None:
        condiciones.append(IntervencionLectura.cuenta_id == filtros.cuenta_id)
    if filtros.usuario_id is not None:
        condiciones.append(IntervencionLectura.usuario_id == filtros.usuario_id)
    return condiciones


def listar(
    sesion: Session, filtros: Filtros, limite: int, desplazamiento: int
) -> tuple[int, dict[str, int], list[dict]]:
    """(total, totales por resultado, página). `total` y `totales` cubren todo
    el filtro. Orden: momento y id descendentes."""
    condiciones = _condiciones(filtros)

    por_resultado = dict(
        sesion.execute(
            select(IntervencionLectura.resultado, func.count())
            .where(*condiciones)
            .group_by(IntervencionLectura.resultado)
        ).all()
    )
    totales = {
        "registradas": por_resultado.get("registrada", 0),
        "rechazadas": por_resultado.get("rechazada", 0),
    }
    total = totales["registradas"] + totales["rechazadas"]

    otra = aliased(IntervencionLectura)
    resuelta = exists().where(
        otra.lectura_id == IntervencionLectura.lectura_id,
        otra.resultado == "registrada",
    )
    ficha_cuenta = aliased(Comensal, name="ficha_cuenta")
    consulta = (
        select(
            IntervencionLectura.id,
            IntervencionLectura.resultado,
            IntervencionLectura.motivo_rechazo,
            IntervencionLectura.causa,
            IntervencionLectura.momento,
            IntervencionLectura.lectura_id,
            IntervencionLectura.usuario_id,
            IntervencionLectura.cuenta_id,
            IntervencionLectura.comida_id,
            IntervencionLectura.fecha_comida,
            IntervencionLectura.ventana_inicio,
            IntervencionLectura.ventana_fin,
            IntervencionLectura.origen_servicio,
            IntervencionLectura.nombre_comida,
            IntervencionLectura.nombre_comensal,
            IntervencionLectura.asistencia_id,
            LecturaBiometrica.resultado.label("lectura_resultado"),
            LecturaBiometrica.motivo.label("lectura_motivo"),
            LecturaBiometrica.fecha_hora.label("lectura_fecha_hora"),
            LecturaBiometrica.dispositivo.label("lectura_dispositivo"),
            UsuarioSistema.username.label("cuenta_usuario"),
            # Igual que app/logica/cuentas.py: vinculada, el nombre del padrón;
            # sin vínculo, el escrito a mano.
            case(
                (UsuarioSistema.usuario_turnos_id.is_not(None), ficha_cuenta.nombre_completo),
                else_=UsuarioSistema.nombre,
            ).label("cuenta_nombre"),
            func.coalesce(Comensal.nombre_completo, IntervencionLectura.nombre_comensal).label(
                "comensal_nombre"
            ),
            Comensal.categoria.label("comensal_categoria"),
            resuelta.label("lectura_resuelta"),
        )
        .select_from(IntervencionLectura)
        .join(LecturaBiometrica, LecturaBiometrica.id == IntervencionLectura.lectura_id)
        .join(UsuarioSistema, UsuarioSistema.id == IntervencionLectura.cuenta_id)
        .outerjoin(Comensal, Comensal.usuario_id == IntervencionLectura.usuario_id)
        .outerjoin(ficha_cuenta, ficha_cuenta.usuario_id == UsuarioSistema.usuario_turnos_id)
        .where(*condiciones)
        .order_by(IntervencionLectura.momento.desc(), IntervencionLectura.id.desc())
        .limit(limite)
        .offset(desplazamiento)
    )
    filas = [dict(f) for f in sesion.execute(consulta).mappings().all()]
    return total, totales, filas


def cuentas_por_id(sesion: Session, ids: set[int]) -> dict[int, dict]:
    """{cuenta_id: {cuenta_id, usuario, nombre}} para la vista de la jefa."""
    if not ids:
        return {}
    ficha = aliased(Comensal, name="ficha_cuenta")
    filas = sesion.execute(
        select(
            UsuarioSistema.id,
            UsuarioSistema.username,
            case(
                (UsuarioSistema.usuario_turnos_id.is_not(None), ficha.nombre_completo),
                else_=UsuarioSistema.nombre,
            ).label("nombre"),
        )
        .select_from(UsuarioSistema)
        .outerjoin(ficha, ficha.usuario_id == UsuarioSistema.usuario_turnos_id)
        .where(UsuarioSistema.id.in_(sorted(ids)))
    ).all()
    return {
        id_: {"cuenta_id": id_, "usuario": usuario, "nombre": nombre}
        for id_, usuario, nombre in filas
    }
