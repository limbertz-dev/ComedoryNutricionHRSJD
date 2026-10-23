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
