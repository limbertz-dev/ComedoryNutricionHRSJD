"""Lo que hace la API con un lector biométrico autorizado.

El lector se identifica con su clave (LECTORES en .env), nunca con la sesión
de una persona. Entrega el identificador con que enroló la huella; acá se
traduce a `users.id` con `vinculos_lector` y se pasa por la MISMA marcación de
siempre (app/logica/marcacion.py): derecho, horario y duplicado no cambian.

La hora es la del servidor. El puente no manda la suya: si pudiera, podría
antedatar raciones (la misma regla que POST /asistencias biométrico).

Idempotencia: cada envío trae una Idempotency-Key. La primera vez se registra
la lectura y se guarda la respuesta en `solicitudes_lector`; un reintento con
la misma clave devuelve lo guardado sin escribir otra lectura. Si el proceso
cayera justo entre el COMMIT de la lectura y el de la solicitud, el reintento
registraría una segunda lectura; para una entrega aceptada esa segunda sale
`duplicado`, así que nunca da dos raciones.
"""

import hmac
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import reloj
from app.core.config import config
from app.esquemas.marcacion import RespuestaMarcacion
from app.logica import marcacion
from app.modelos.heredados import Comensal
from app.modelos.lector import SolicitudLector, VinculoLector


class ConflictoLector(Exception):
    """Algo del envío o del vínculo choca con lo ya guardado (HTTP 409)."""

    def __init__(self, motivo: str, detalle: str):
        super().__init__(detalle)
        self.motivo = motivo
        self.detalle = detalle


def dispositivo_de(clave: str | None) -> str | None:
    """El nombre del lector dueño de `clave`, o None. Compara contra todas en
    tiempo constante: la respuesta no dice cuántos caracteres acertaron."""
    if not clave:
        return None
    encontrado = None
    for conocida, nombre in config.lectores_por_clave.items():
        if hmac.compare_digest(conocida.encode(), clave.encode()):
            encontrado = nombre
    return encontrado


def usuario_de(sesion: Session, identificador: str | None) -> int | None:
    if identificador is None:
        return None
    return sesion.execute(
        select(VinculoLector.usuario_id).where(
            VinculoLector.identificador == identificador, VinculoLector.activo == 1
        )
    ).scalar_one_or_none()


@dataclass
class Resultado:
    cuerpo: dict
    reintento: bool


def _guardado(sesion: Session, clave: str, dispositivo: str, identificador: str | None):
    previo = sesion.get(SolicitudLector, clave)
    if previo is None:
        return None
    if previo.dispositivo != dispositivo or previo.identificador != identificador:
        raise ConflictoLector(
            "clave_reutilizada_con_otro_contenido",
            "Esa Idempotency-Key ya se usó para otra lectura.",
        )
    return Resultado({**previo.respuesta, "reintento": True}, reintento=True)


def registrar_lectura(
    sesion: Session, *, dispositivo: str, clave: str, identificador: str | None
) -> Resultado:
    previo = _guardado(sesion, clave, dispositivo, identificador)
    if previo is not None:
        return previo
    usuario_id = usuario_de(sesion, identificador)
    sesion.rollback()

    resultado = marcacion.registrar_marcacion(
        sesion, usuario_id=usuario_id, dispositivo=dispositivo, metodo="biometrico"
    )
    cuerpo = {
        **RespuestaMarcacion(**vars(resultado)).model_dump(mode="json"),
        "dispositivo": dispositivo,
        "vinculado": usuario_id is not None,
        "reintento": False,
    }
    sesion.add(SolicitudLector(
        clave=clave, dispositivo=dispositivo, identificador=identificador,
        lectura_id=resultado.lectura_id, respuesta=cuerpo,
    ))
    try:
        sesion.commit()
    except IntegrityError:
        # Otro envío con la misma clave se guardó primero: vale el suyo.
        sesion.rollback()
        previo = _guardado(sesion, clave, dispositivo, identificador)
        if previo is None:
            raise
        return previo
    return Resultado(cuerpo, reintento=False)


def salud(sesion: Session, dispositivo: str) -> dict:
    momento = reloj.ahora()
    comida = marcacion.resolver_comida_en_curso(sesion, momento)
    activos = sesion.execute(
        select(func.count()).select_from(VinculoLector).where(VinculoLector.activo == 1)
    ).scalar_one()
    return {
        "dispositivo": dispositivo,
        "momento": momento,
        "comida_en_curso": comida.comida if comida else None,
        "vinculos_activos": activos,
    }


# --- vínculos (jefatura) ------------------------------------------------------


def _a_dict(sesion: Session, vinculo: VinculoLector) -> dict:
    ficha = sesion.get(Comensal, vinculo.usuario_id)
    return {
        "id": vinculo.id,
        "identificador": vinculo.identificador,
        "usuario_id": vinculo.usuario_id,
        "nombre": ficha.nombre_completo if ficha else None,
        "categoria": ficha.categoria if ficha else None,
        "activo": bool(vinculo.activo),
        "created_at": vinculo.created_at,
        "updated_at": vinculo.updated_at,
    }


def listar_vinculos(sesion: Session, *, solo_activos: bool) -> list[dict]:
    consulta = select(VinculoLector).order_by(VinculoLector.identificador)
    if solo_activos:
        consulta = consulta.where(VinculoLector.activo == 1)
    return [_a_dict(sesion, v) for v in sesion.execute(consulta).scalars()]


def vincular(sesion: Session, *, identificador: str, usuario_id: int, cuenta_id: int) -> dict:
    """Crea el vínculo, o reactiva uno dado de baja con la persona nueva."""
    if sesion.get(Comensal, usuario_id) is None:
        raise LookupError("La persona no figura en el padrón.")
    vinculo = sesion.execute(
        select(VinculoLector).where(VinculoLector.identificador == identificador).with_for_update()
    ).scalar_one_or_none()
    if vinculo is not None and vinculo.activo:
        raise ConflictoLector(
            "identificador_en_uso",
            "Ese identificador ya está vinculado. Dalo de baja antes de reasignarlo.",
        )
    if vinculo is None:
        vinculo = VinculoLector(identificador=identificador)
        sesion.add(vinculo)
    vinculo.usuario_id = usuario_id
    vinculo.activo = 1
    vinculo.creado_por_cuenta = cuenta_id
    try:
        sesion.commit()
    except IntegrityError:
        sesion.rollback()
        raise ConflictoLector(
            "identificador_en_uso", "Ese identificador se acaba de vincular."
        ) from None
    sesion.refresh(vinculo)
    return _a_dict(sesion, vinculo)


def dar_de_baja(sesion: Session, vinculo_id: int) -> dict:
    vinculo = sesion.get(VinculoLector, vinculo_id, with_for_update=True)
    if vinculo is None:
        raise LookupError("No existe ese vínculo.")
    vinculo.activo = 0
    sesion.commit()
    sesion.refresh(vinculo)
    return _a_dict(sesion, vinculo)
