"""Identificar a mano una lectura no reconocida y confirmar la entrega.

La cocinera ve a la persona frente al lector cuando éste no reconoce la
huella: elige a quién es y confirma la entrega. El servidor vuelve a comprobar
TODO (derecho, servicio, duplicado), registra una asistencia vinculada a la
lectura y una fila de auditoría, y deja la lectura original intacta. Nunca se
afirma que el lector reconoció la huella: la lectura sigue sin usuario.

Orden de una petición (el que importa; no conviene reordenarlo):

  0. El endpoint autentica, exige el rol y valida cabecera y cuerpo. Copia
     `cuenta_id` en un valor simple: el rollback siguiente expira los objetos
     ORM de la sesión.
  1. `rollback()`. La autenticación SÍ consulta la base y dejó abierta una
     transacción de solo lectura con su snapshot de REPEATABLE READ; se
     termina para que nada de lo que se lea después sea una foto vieja.
  2. Recuperación de idempotencia, en su propia transacción y sin bloqueo:
     una fila confirmada es inmutable (la tabla solo admite inserciones). Con
     la misma huella se responde SOLO con lo guardado, sin tocar la lectura,
     el padrón, los horarios ni las asistencias; con otra huella, conflicto.
     Después, `rollback()` otra vez.
  3. Bloqueo: `SELECT ... FOR UPDATE` sobre la fila de la lectura. Es la
     primera sentencia de la transacción nueva, así que el snapshot (que se
     crea en la primera lectura NO bloqueante) nace DESPUÉS de obtener el
     bloqueo y ve lo último que confirmó quien lo tuvo antes. Es el único
     bloqueo sobre filas de este flujo, y es sobre una tabla propia.
  4. Se repite la recuperación de la clave (lectura plana, ya con el
     snapshot fresco): quien la ganó antes la dejó confirmada.
  5. El comensal existe (404 si no; no consume la clave).
  6. Estado de la lectura, servicio, derecho y duplicado, en este orden.
     Cada rechazo deja su fila `rechazada` con la clave y confirma.
  7. Éxito: la asistencia entra dentro de un SAVEPOINT y la fila `registrada`
     fuera de él; un solo COMMIT confirma las dos.

NO se aplica FOR UPDATE / FOR SHARE al padrón, a las vistas ni a nada de la
base de turnos: ahí solo hay SELECT planos. Los únicos bloqueos son el de la
lectura (paso 3) y, solo para clasificar un 1062, un FOR SHARE sobre
`asistencias`, que es propia.

Por qué la clave no se lee con bloqueo en el paso 2: un `FOR UPDATE` sobre una
clave ausente toma un bloqueo de hueco en REPEATABLE READ, y dos solicitudes
iguales podrían interbloquearse. Dos solicitudes con la misma clave y la misma
lectura se ordenan por el bloqueo del paso 3; con otra lectura, por el UNIQUE
(cuenta, clave).

Confirmación incierta: si algo falla al confirmar (una desconexión, por
ejemplo) no se sabe si el servidor llegó a registrarlo. Se responde 503
`resultado_incierto` SIN afirmar que no hubo entrega; el cliente repite con la
MISMA clave y recupera la respuesta confirmada, si la hubo (paso 2).
"""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.consultas.derecho import buscar_derecho
from app.consultas.servicio import Servicio, VentanasDelDia, evaluar_servicio
from app.core import reloj
from app.logica.marcacion import ComidaEnCurso, categoria_reporte_de, ya_comio
from app.logica.reglas import ESPERA_AGOTADA, INTERBLOQUEO, _codigo_mysql
from app.modelos.comedor import (
    CAUSA_IDENTIFICACION,
    ORIGEN_SERVICIO,
    Asistencia,
    IntervencionLectura,
    LecturaBiometrica,
)
from app.modelos.heredados import Comensal

CLAVE_UUID4 = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)

# Reglas de la PERSONA: se responden 200 con valido=False, como POST /asistencias.
# El resto de los rechazos son conflictos sobre la lectura: 409.
MOTIVOS_DE_PERSONA = ("sin_derecho", "duplicado")

DETALLE_CONFLICTO = {
    "lectura_ya_resuelta": "La lectura ya fue resuelta.",
    "lectura_no_resoluble": "La lectura no es una huella no reconocida pendiente.",
    "reloj_inconsistente": "El reloj del servidor está antes de la hora de la lectura.",
    "servicio_distinto": "La lectura no pertenece al servicio en curso.",
    "servicio_no_determinable": "No se pudo determinar el servicio de la lectura.",
}

# Lo que se lee de una fila de auditoría para responder un reintento. Sin
# `created_at`: tiene server_default y leerlo tras un INSERT abre otra lectura.
_CAMPOS = (
    "id",
    "lectura_id",
    "usuario_id",
    "cuenta_id",
    "huella_solicitud",
    "resultado",
    "motivo_rechazo",
    "asistencia_id",
    "comida_id",
    "fecha_comida",
    "nombre_comensal",
    "nombre_comida",
    "servicio_id",
    "momento",
)


class ErrorIntervencion(Exception):
    """Un error con status, motivo y, a veces, campos extra en el cuerpo."""

    def __init__(self, status_code: int, motivo: str, detail: str, **extra):
        super().__init__(detail)
        self.status_code = status_code
        self.motivo = motivo
        self.detail = detail
        self.extra = extra

    def cuerpo(self) -> dict:
        return {"detail": self.detail, "motivo": self.motivo, **self.extra}


class _Reintentar(Exception):
    """Una carrera que se resuelve repitiendo la decisión completa una vez."""


@dataclass(frozen=True)
class Respuesta:
    valido: bool
    resultado: str
    motivo: str | None
    titulo: str
    detalle: str
    reintento: bool
    lectura_id: int
    asistencia_id: int | None
    intervencion_id: int
    usuario_id: int
    nombre: str | None
    comida: str | None
    comida_id: int | None
    fecha_comida: date | None
    servicio_id: int | None
    causa: str
    momento: datetime
    raciones_restantes: int | None = None


@dataclass(frozen=True)
class _Contexto:
    cuenta_id: int
    lectura_id: int
    usuario_id: int
    clave: str
    huella: str


def calcular_huella(lectura_id: int, usuario_id: int) -> str:
    """SHA-256 de {lectura_id, usuario_id}, en forma canónica."""
    canonico = json.dumps(
        {"lectura_id": lectura_id, "usuario_id": usuario_id},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def normalizar_clave(valor: str | None) -> str | None:
    """La clave en minúsculas si es un UUID v4; si no, None."""
    if valor is None:
        return None
    clave = valor.strip().lower()
    return clave if CLAVE_UUID4.fullmatch(clave) else None


# --- errores que se repiten ---------------------------------------------------


def _en_curso() -> ErrorIntervencion:
    return ErrorIntervencion(
        409,
        "intervencion_en_curso",
        "Hay otra intervención en curso. Repita la solicitud con la misma clave.",
    )


def _incierto() -> ErrorIntervencion:
    return ErrorIntervencion(
        503,
        "resultado_incierto",
        "No se pudo confirmar el resultado. Repita la solicitud con la misma "
        "clave: se recupera lo que haya quedado registrado.",
    )


def _soltar(sesion: Session) -> None:
    """Un rollback que no esconde el error original si la conexión ya murió."""
    try:
        sesion.rollback()
    except Exception:  # noqa: BLE001
        pass


# --- lectura y escritura de la auditoría --------------------------------------


def _recuperar(sesion: Session, ctx: _Contexto) -> tuple[dict, int | None] | None:
    """La fila de esta (cuenta, clave), si existe, y la cuenta que registró la
    entrega de su lectura cuando hace falta para `resuelta_por_mi`."""
    fila = (
        sesion.execute(
            select(*(IntervencionLectura.__table__.c[nombre] for nombre in _CAMPOS)).where(
                IntervencionLectura.cuenta_id == ctx.cuenta_id,
                IntervencionLectura.clave_idempotencia == ctx.clave,
            )
        )
        .mappings()
        .first()
    )
    if fila is None:
        return None
    datos = dict(fila)
    registradora = None
    if datos["motivo_rechazo"] == "lectura_ya_resuelta":
        registradora = _cuenta_registradora(sesion, datos["lectura_id"])
    return datos, registradora


def nombre_en_padron(sesion: Session, usuario_id: int):
    """`(nombre,)` si la persona está en el padrón (`v_comensales`), o None.

    Un SELECT plano sobre la vista, sin bloqueo. Está aparte, igual que
    `buscar_derecho`, para que las pruebas puedan sustituir SOLO la fuente del
    padrón con datos sintéticos sin tocar la base de turnos ni nada de lo que
    la operación escribe.
    """
    return sesion.execute(
        select(Comensal.nombre_completo).where(Comensal.usuario_id == usuario_id)
    ).first()


def _cuenta_registradora(sesion: Session, lectura_id: int) -> int | None:
    return sesion.execute(
        select(IntervencionLectura.cuenta_id).where(
            IntervencionLectura.lectura_id == lectura_id,
            IntervencionLectura.resultado == "registrada",
        )
    ).scalar_one_or_none()


def _nueva_fila(
    ctx: _Contexto,
    ahora: datetime,
    nombre: str | None,
    servicio: Servicio | None,
    *,
    resultado: str,
    motivo: str | None,
    asistencia_id: int | None = None,
    servicio_id: int | None = None,
) -> IntervencionLectura:
    return IntervencionLectura(
        lectura_id=ctx.lectura_id,
        usuario_id=ctx.usuario_id,
        cuenta_id=ctx.cuenta_id,
        clave_idempotencia=ctx.clave,
        huella_solicitud=ctx.huella,
        resultado=resultado,
        motivo_rechazo=motivo,
        causa=CAUSA_IDENTIFICACION,
        comida_id=servicio.comida_id if servicio else None,
        fecha_comida=servicio.fecha_comida if servicio else None,
        ventana_inicio=servicio.inicio if servicio else None,
        ventana_fin=servicio.fin if servicio else None,
        origen_servicio=ORIGEN_SERVICIO if servicio else None,
        nombre_comensal=nombre,
        nombre_comida=servicio.comida if servicio else None,
        servicio_id=servicio_id,
        asistencia_id=asistencia_id,
        momento=ahora,
    )


def _a_dict(fila: IntervencionLectura) -> dict:
    return {nombre: getattr(fila, nombre) for nombre in _CAMPOS}


def _confirmar(sesion: Session) -> None:
    """COMMIT. Si falla no se sabe qué quedó: se avisa como incierto."""
    try:
        sesion.commit()
    except DBAPIError as error:
        _soltar(sesion)
        raise _incierto() from error


def _es_duplicado(error: IntegrityError) -> bool:
    return _codigo_mysql(error) == 1062


def _clave_existe(sesion: Session, ctx: _Contexto) -> bool:
    return (
        sesion.execute(
            select(IntervencionLectura.id).where(
                IntervencionLectura.cuenta_id == ctx.cuenta_id,
                IntervencionLectura.clave_idempotencia == ctx.clave,
            )
        ).first()
        is not None
    )


def _insertar(sesion: Session, fila: IntervencionLectura, ctx: _Contexto) -> None:
    """INSERT de la auditoría dentro de la transacción abierta.

    Solo UNA carrera se reconoce y se resuelve repitiendo la decisión: otra
    solicitud acaba de dejar la misma (cuenta, clave). Se comprueba, no se
    supone: tras el rollback, el error tiene que ser un duplicado (1062) Y la
    clave tiene que existir ya; la segunda pasada la encuentra y responde el
    replay o el conflicto de contenido.

    Cualquier otro error de integridad (una FK, un CHECK, un valor inválido) NO
    es concurrencia: se propaga como fallo interno, sin disfrazarlo de
    `intervencion_en_curso`, y no queda nada a medias (el rollback deshace
    también la ración si la había).
    """
    sesion.add(fila)
    try:
        sesion.flush()
    except IntegrityError as error:
        sesion.rollback()
        if _es_duplicado(error) and _clave_existe(sesion, ctx):
            raise _Reintentar() from error
        raise


# --- la respuesta -------------------------------------------------------------


def _detalle_rechazo(motivo: str, comida: str | None) -> str:
    nombre = (comida or "la comida").lower()
    if motivo == "sin_derecho":
        return f"No se registró entrega: su turno asignado no incluye {nombre} en esta fecha."
    return f"No se registró entrega: ya recibió su {nombre} de hoy."


def _responder(
    fila: dict, ctx: _Contexto, *, reintento: bool, registradora: int | None = None
) -> Respuesta:
    """Convierte una fila de auditoría en la respuesta, o en el conflicto que
    esa fila registra. Es el MISMO camino para un resultado recién guardado y
    para un reintento: solo lee la fila, nunca la lectura ni el padrón."""
    if fila["huella_solicitud"] != ctx.huella:
        raise ErrorIntervencion(
            409,
            "clave_reutilizada_con_otro_contenido",
            "Esa clave de idempotencia ya se usó con otra solicitud.",
        )

    base = dict(
        reintento=reintento,
        lectura_id=fila["lectura_id"],
        asistencia_id=fila["asistencia_id"],
        intervencion_id=fila["id"],
        usuario_id=fila["usuario_id"],
        nombre=fila["nombre_comensal"],
        comida=fila["nombre_comida"],
        comida_id=fila["comida_id"],
        fecha_comida=fila["fecha_comida"],
        servicio_id=fila["servicio_id"],
        causa=CAUSA_IDENTIFICACION,
        momento=fila["momento"],
    )
    if fila["resultado"] == "registrada":
        return Respuesta(
            valido=True,
            resultado="registrada",
            motivo=None,
            titulo="Entrega registrada",
            detalle="Identificada manualmente por cocina. La lectura original no se modificó.",
            **base,
        )

    motivo = fila["motivo_rechazo"]
    if motivo in MOTIVOS_DE_PERSONA:
        return Respuesta(
            valido=False,
            resultado="rechazada",
            motivo=motivo,
            titulo="Intento rechazado",
            detalle=_detalle_rechazo(motivo, fila["nombre_comida"]),
            **base,
        )

    extra = dict(
        resultado="rechazada",
        lectura_id=fila["lectura_id"],
        intervencion_id=fila["id"],
        reintento=reintento,
    )
    if motivo == "lectura_ya_resuelta":
        # Solo si la entrega fue de esta cuenta. Nunca quién fue, y nunca se le
        # atribuye a quien repite la solicitud.
        extra["resuelta_por_mi"] = registradora == ctx.cuenta_id
    raise ErrorIntervencion(409, motivo, DETALLE_CONFLICTO[motivo], **extra)


# --- la operación -------------------------------------------------------------


def identificar_lectura(
    sesion: Session,
    *,
    cuenta_id: int,
    lectura_id: int,
    usuario_id: int,
    clave: str,
) -> Respuesta:
    """Ver el docstring del módulo. `cuenta_id` ya viene copiado del token."""
    ctx = _Contexto(
        cuenta_id=cuenta_id,
        lectura_id=lectura_id,
        usuario_id=usuario_id,
        clave=clave,
        huella=calcular_huella(lectura_id, usuario_id),
    )
    for pasada in (1, 2):
        try:
            return _una_pasada(sesion, ctx)
        except _Reintentar:
            # Solo llega aquí con la clave ya confirmada por otra solicitud: la
            # segunda pasada la recupera en el paso 2. Si ni así, no hay
            # carrera que explicarlo y no se inventa una.
            if pasada == 2:
                raise RuntimeError(
                    "La clave de idempotencia existía y no se pudo recuperar."
                ) from None
            continue
        except ErrorIntervencion:
            raise
        except IntegrityError:
            _soltar(sesion)
            raise
        except OperationalError as error:
            _soltar(sesion)
            if _codigo_mysql(error) in (ESPERA_AGOTADA, INTERBLOQUEO):
                raise _en_curso() from error
            raise _incierto() from error
        except DBAPIError as error:
            _soltar(sesion)
            raise _incierto() from error
    raise RuntimeError("Inalcanzable: la segunda pasada responde o propaga.")


def _una_pasada(sesion: Session, ctx: _Contexto) -> Respuesta:
    # 1. La transacción de la autenticación, fuera.
    sesion.rollback()

    # 2. Idempotencia, sin bloqueo y en su propia transacción.
    previo = _recuperar(sesion, ctx)
    sesion.rollback()
    if previo is not None:
        return _responder(previo[0], ctx, reintento=True, registradora=previo[1])

    # 3. El bloqueo, primera sentencia de la transacción nueva.
    lectura = sesion.execute(
        select(LecturaBiometrica)
        .where(LecturaBiometrica.id == ctx.lectura_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if lectura is None:
        sesion.rollback()
        raise ErrorIntervencion(404, "lectura_inexistente", "No existe esa lectura.")
    # Valores simples: un rollback de SAVEPOINT puede expirar el objeto ORM.
    lectura_pk = lectura.id
    momento_lectura = lectura.fecha_hora
    rechazo_original_elegible = (
        lectura.resultado == "rechazada"
        and lectura.motivo == "no_identificado"
        and lectura.usuario_id is None
    )

    # 4. La clave otra vez: quien tuvo el bloqueo antes pudo dejarla.
    previo = _recuperar(sesion, ctx)
    if previo is not None:
        sesion.rollback()
        return _responder(previo[0], ctx, reintento=True, registradora=previo[1])

    # 5. La persona.
    ficha = nombre_en_padron(sesion, ctx.usuario_id)
    if ficha is None:
        sesion.rollback()
        raise ErrorIntervencion(404, "comensal_inexistente", "No existe ese comensal.")
    nombre = ficha[0]

    ahora = reloj.ahora()

    def rechazar(motivo: str, servicio: Servicio | None = None) -> Respuesta:
        registradora = (
            _cuenta_registradora(sesion, lectura_pk)
            if motivo == "lectura_ya_resuelta"
            else None
        )
        fila = _nueva_fila(ctx, ahora, nombre, servicio, resultado="rechazada", motivo=motivo)
        _insertar(sesion, fila, ctx)
        _confirmar(sesion)
        return _responder(_a_dict(fila), ctx, reintento=False, registradora=registradora)

    # 6a. El rechazo original, ¿es de los que se pueden identificar?
    if not rechazo_original_elegible:
        return rechazar("lectura_no_resoluble")
    # 6b. ¿Ya tiene una ración? Es un caso APARTE de la elegibilidad: si el
    # predicado de arriba incluyera "sin asistencia", esta rama no existiría.
    ya_vinculada = sesion.execute(
        select(Asistencia.id).where(Asistencia.lectura_id == lectura_pk)
    ).first()
    if ya_vinculada is not None:
        return rechazar("lectura_ya_resuelta")

    # 6c. Mismo servicio efectivo.
    evaluacion = evaluar_servicio(sesion, VentanasDelDia(sesion), momento_lectura, ahora)
    if evaluacion.motivo is not None:
        return rechazar(evaluacion.motivo, evaluacion.servicio)
    servicio = evaluacion.servicio

    # 6d. Derecho y duplicado: siempre obligatorios, sobre el servicio de la lectura.
    derecho = buscar_derecho(sesion, ctx.usuario_id, servicio.comida_id, servicio.fecha_comida)
    if derecho is None:
        return rechazar("sin_derecho", servicio)
    comida = ComidaEnCurso(servicio.comida_id, servicio.comida, servicio.fecha_comida)
    if ya_comio(sesion, ctx.usuario_id, comida):
        return rechazar("duplicado", servicio)

    # 7. La ración, dentro de un SAVEPOINT.
    asistencia = Asistencia(
        usuario_id=ctx.usuario_id,
        fecha_comida=servicio.fecha_comida,
        comida_id=servicio.comida_id,
        categoria_reporte_id=categoria_reporte_de(sesion, ctx.usuario_id),
        servicio_id=derecho.servicio_id,
        turno_asignado_id=derecho.turno_asignado_id,
        metodo="manual",
        lectura_id=lectura_pk,
        fecha_hora=ahora,
        registrado_por_cuenta=ctx.cuenta_id,
    )
    try:
        with sesion.begin_nested():
            sesion.add(asistencia)
            sesion.flush()
    except IntegrityError as error:
        # El 1062 aborta la sentencia y el SAVEPOINT se revirtió solo: el
        # bloqueo de la lectura y todo lo anterior siguen vivos. La causa se
        # averigua CONSULTANDO, no leyendo el texto del driver. Solo un
        # duplicado (1062) que una de las dos filas confirmadas explique es una
        # carrera; una FK u otro error de integridad es un fallo interno y se
        # propaga, aunque casualmente exista una ración.
        motivo = (
            _clasificar_conflicto(sesion, lectura_pk, ctx.usuario_id, servicio)
            if _es_duplicado(error)
            else None
        )
        if motivo is None:
            sesion.rollback()
            raise
        return rechazar(motivo, servicio)

    fila = _nueva_fila(
        ctx,
        ahora,
        nombre,
        servicio,
        resultado="registrada",
        motivo=None,
        asistencia_id=asistencia.id,
        servicio_id=derecho.servicio_id,
    )
    _insertar(sesion, fila, ctx)
    _confirmar(sesion)
    return _responder(_a_dict(fila), ctx, reintento=False)


def _clasificar_conflicto(
    sesion: Session, lectura_id: int, usuario_id: int, servicio: Servicio
) -> str | None:
    """Por qué chocó el INSERT de la ración, averiguado con lecturas
    bloqueantes (FOR SHARE) sobre `asistencias`, que es propia.

    Un 1062 significa que la otra fila ya está confirmada: el INSERT espera a
    la otra transacción y solo falla si ésta confirma. Una lectura plana no la
    vería en REPEATABLE READ (el snapshot es anterior); la bloqueante sí.
    None si ninguna de las dos explica el choque: no se adivina.
    """
    racion = sesion.execute(
        select(Asistencia.id)
        .where(
            Asistencia.usuario_id == usuario_id,
            Asistencia.fecha_comida == servicio.fecha_comida,
            Asistencia.comida_id == servicio.comida_id,
        )
        .with_for_update(read=True)
    ).first()
    if racion is not None:
        return "duplicado"
    vinculada = sesion.execute(
        select(Asistencia.id).where(Asistencia.lectura_id == lectura_id).with_for_update(read=True)
    ).first()
    if vinculada is not None:
        return "lectura_ya_resuelta"
    return None
