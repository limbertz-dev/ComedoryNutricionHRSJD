"""La ración de un policía, registrada por el lector biométrico.

Los policías no están en la base de turnos: su huella se vincula como
`tipo='policia'` (sin persona del padrón). Cuando el lector la reconoce, acá
se registra una ración con «vía libre»: sin derecho ni duplicado que
comprobar, solo que haya una comida en curso para que caiga en su fila del
informe. Va a `raciones_policia`, aparte del personal, y solo cuenta como
ración en la columna Policías (app/consultas/raciones.py). No aparece en
historiales ni crea lecturas de personal.

La idempotencia la da el envío del lector (solicitudes_lector), como en
cualquier otra lectura.
"""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import reloj
from app.logica.marcacion import resolver_comida_en_curso
from app.modelos.comedor import CategoriaReporte
from app.modelos.lector import RacionPolicia

CODIGO_POLICIAS = "policias"
NOMBRE = "Policía"


def _en_comida(sesion: Session, fecha_comida, comida_id) -> int:
    return sesion.execute(
        select(func.count()).select_from(RacionPolicia).where(
            RacionPolicia.fecha_comida == fecha_comida, RacionPolicia.comida_id == comida_id
        )
    ).scalar_one()


def registrar(sesion: Session, *, vinculo_id: int, dispositivo: str, nombre: str | None = None) -> dict:
    """La respuesta, con la misma forma que una marcación del lector. No hace
    COMMIT: lo hace quien guarda el envío, en la misma transacción."""
    base = {
        "usuario_id": None, "nombre": nombre or NOMBRE, "servicio_id": None,
        "lectura_id": None, "asistencia_id": None, "raciones_restantes": None,
    }
    momento = reloj.ahora()
    comida = resolver_comida_en_curso(sesion, momento)
    if comida is None:
        return {**base, "valido": False, "motivo": "fuera_horario",
                "titulo": "Marcación rechazada",
                "detalle": "No hay un tiempo de comida vigente a esta hora",
                "comida": None, "comida_id": None, "fecha_comida": None}
    columna = sesion.execute(
        select(CategoriaReporte.id).where(
            CategoriaReporte.codigo == CODIGO_POLICIAS, CategoriaReporte.activo == 1
        )
    ).scalar_one_or_none()
    if columna is None:
        return {**base, "valido": False, "motivo": "sin_derecho",
                "titulo": "Marcación rechazada",
                "detalle": "La columna Policías no está activa en el catálogo de reportes.",
                "comida": comida.comida, "comida_id": comida.comida_id,
                "fecha_comida": comida.fecha_comida.isoformat()}

    sesion.add(RacionPolicia(
        fecha_comida=comida.fecha_comida, comida_id=comida.comida_id,
        categoria_reporte_id=columna, fecha_hora=momento,
        dispositivo=dispositivo, vinculo_id=vinculo_id,
    ))
    sesion.flush()
    servidas = _en_comida(sesion, comida.fecha_comida, comida.comida_id)
    return {**base, "valido": True, "motivo": None,
            "titulo": "Ración de policía",
            "detalle": f"Ración habilitada · {servidas} de policía en esta comida",
            "comida": comida.comida, "comida_id": comida.comida_id,
            "fecha_comida": comida.fecha_comida.isoformat()}


# --- identificación por cocina de una huella no reconocida -----------------------


class ErrorIdentificacionPolicia(Exception):
    """Un conflicto con la lectura o el policía elegido; `status` va a HTTP."""

    def __init__(self, status: int, motivo: str, detalle: str):
        super().__init__(detalle)
        self.status = status
        self.motivo = motivo
        self.detalle = detalle


DETALLES = {
    "lectura_inexistente": (404, "No existe esa lectura."),
    "lectura_no_resoluble": (409, "Esa lectura no es una huella no reconocida que se pueda identificar."),
    "lectura_ya_resuelta": (409, "Esa huella ya se identificó y tiene su ración."),
    "policia_inexistente": (404, "Ese policía no tiene una huella activa."),
    "clave_reutilizada_con_otro_contenido": (409, "Esa Idempotency-Key ya se usó para otra identificación."),
    "sin_columna_policias": (409, "La columna Policías no está activa en el catálogo de reportes."),
}


def _error(motivo: str) -> ErrorIdentificacionPolicia:
    if motivo in DETALLES:
        status, detalle = DETALLES[motivo]
    else:  # los del servicio: los mismos textos que la identificación del personal
        from app.logica.intervencion import DETALLE_CONFLICTO
        status, detalle = 409, DETALLE_CONFLICTO.get(motivo, "La lectura no pertenece al servicio en curso.")
    return ErrorIdentificacionPolicia(status, motivo, detalle)


def _respuesta_identificacion(racion: RacionPolicia, nombre: str, comida: str | None, reintento: bool) -> dict:
    return {
        "valido": True, "lectura_id": racion.lectura_id, "racion_id": racion.id,
        "vinculo_id": racion.vinculo_id, "nombre": nombre, "comida": comida,
        "fecha_comida": racion.fecha_comida, "reintento": reintento,
    }


def identificar(sesion: Session, *, cuenta_id: int, lectura_id: int, vinculo_id: int, clave: str) -> dict:
    """La cocinera elige a un policía para una huella no reconocida.

    Las mismas garantías que la identificación del personal: la lectura se
    bloquea, tiene que ser un rechazo `no_identificado` sin resolver y del
    servicio en curso; la ración queda ligada a la lectura (UNIQUE) y la
    Idempotency-Key hace que un reintento devuelva lo mismo. Vía libre: no se
    mira turno ni duplicado del policía.
    """
    from app.consultas.servicio import VentanasDelDia, evaluar_servicio
    from app.modelos.comedor import Asistencia, LecturaBiometrica
    from app.modelos.heredados import Comida
    from app.modelos.lector import VinculoLector

    def nombre_de(vinculo_pk):
        vinculo = sesion.get(VinculoLector, vinculo_pk)
        return (vinculo.nombre if vinculo else None) or NOMBRE

    def comida_de(comida_pk):
        return sesion.execute(select(Comida.nombre).where(Comida.id == comida_pk)).scalar_one_or_none()

    def recuperar():
        previa = sesion.execute(
            select(RacionPolicia).where(RacionPolicia.clave_idempotencia == clave)
        ).scalar_one_or_none()
        if previa is None:
            return None
        if previa.lectura_id != lectura_id or previa.vinculo_id != vinculo_id:
            raise _error("clave_reutilizada_con_otro_contenido")
        return _respuesta_identificacion(previa, nombre_de(previa.vinculo_id), comida_de(previa.comida_id), True)

    sesion.rollback()
    previa = recuperar()
    if previa is not None:
        sesion.rollback()
        return previa

    lectura = sesion.execute(
        select(LecturaBiometrica).where(LecturaBiometrica.id == lectura_id).with_for_update()
    ).scalar_one_or_none()
    if lectura is None:
        sesion.rollback()
        raise _error("lectura_inexistente")
    previa = recuperar()  # quien tuvo el bloqueo antes pudo dejarla
    if previa is not None:
        sesion.rollback()
        return previa
    if not (lectura.resultado == "rechazada" and lectura.motivo == "no_identificado"
            and lectura.usuario_id is None):
        sesion.rollback()
        raise _error("lectura_no_resoluble")
    ya_resuelta = sesion.execute(select(Asistencia.id).where(Asistencia.lectura_id == lectura_id)).first() \
        or sesion.execute(select(RacionPolicia.id).where(RacionPolicia.lectura_id == lectura_id)).first()
    if ya_resuelta is not None:
        sesion.rollback()
        raise _error("lectura_ya_resuelta")

    vinculo = sesion.get(VinculoLector, vinculo_id)
    if vinculo is None or vinculo.tipo != "policia" or not vinculo.activo:
        sesion.rollback()
        raise _error("policia_inexistente")
    nombre = vinculo.nombre or NOMBRE

    ahora = reloj.ahora()
    evaluacion = evaluar_servicio(sesion, VentanasDelDia(sesion), lectura.fecha_hora, ahora)
    if evaluacion.motivo is not None:
        sesion.rollback()
        raise _error(evaluacion.motivo)
    servicio = evaluacion.servicio
    columna = sesion.execute(
        select(CategoriaReporte.id).where(
            CategoriaReporte.codigo == CODIGO_POLICIAS, CategoriaReporte.activo == 1
        )
    ).scalar_one_or_none()
    if columna is None:
        sesion.rollback()
        raise _error("sin_columna_policias")

    racion = RacionPolicia(
        fecha_comida=servicio.fecha_comida, comida_id=servicio.comida_id,
        categoria_reporte_id=columna, fecha_hora=ahora, dispositivo=lectura.dispositivo,
        vinculo_id=vinculo_id, lectura_id=lectura_id, registrado_por_cuenta=cuenta_id,
        clave_idempotencia=clave,
    )
    sesion.add(racion)
    try:
        sesion.commit()
    except IntegrityError:
        # Otra solicitud resolvió esa lectura o usó esa clave a la vez.
        sesion.rollback()
        previa = recuperar()
        if previa is not None:
            return previa
        raise _error("lectura_ya_resuelta") from None
    return _respuesta_identificacion(racion, nombre, servicio.comida, False)


def listar_activos(sesion: Session) -> list[dict]:
    """Los policías con huella activa, para elegirlos al identificar."""
    from app.modelos.lector import VinculoLector
    filas = sesion.execute(
        select(VinculoLector.id, VinculoLector.nombre, VinculoLector.documento)
        .where(VinculoLector.tipo == "policia", VinculoLector.activo == 1)
        .order_by(VinculoLector.nombre, VinculoLector.id)
    ).all()
    return [{"id": i, "nombre": n or NOMBRE, "documento": d} for i, n, d in filas]
