"""Administración de cuentas para root (rol sistemas).

Dos formas de nacer:

  · Vinculada   se copia el login del padrón (users.name normalizado) como
                username y queda atada a ese users.id. La clave es del
                comedor: temporal, se cambia en el primer ingreso. Acá no
                se lee ninguna clave, email ni token de la base de turnos.
  · Sin vínculo  username y nombre a mano, para quien aún no está en el
                padrón. usuario_turnos_id queda en NULL.

Por API solo nacen cocinera y jefa: sistemas se crea por consola
(python -m app.semillas.admin).

Concurrencia: los chequeos previos ("¿ya tiene cuenta?", "¿es la última
de sistemas?") se leen con bloqueo en la misma transacción, y si dos
roots igual chocan, el UNIQUE lo ataja y el error 1062 se traduce al
409 que corresponda (mismo patrón que _es_duplicado en marcacion.py).
"""

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import seguridad
from app.logica.autenticacion import fijar_clave, normalizar_username
from app.modelos.heredados import Comensal
from app.modelos.usuarios import IntentoLogin, UsuarioSistema
from app.semillas.admin import clave_temporal

ROLES_POR_API = frozenset({"cocinera", "jefa"})


class ErrorCuenta(Exception):
    """Un 4xx con motivo. El endpoint la traduce a ErrorAuth."""

    def __init__(self, status_code: int, motivo: str, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.motivo = motivo
        self.detail = detail


# --- lectura ----------------------------------------------------------------


def _ultimos_ingresos(sesion: Session) -> dict[str, datetime]:
    filas = (
        sesion.execute(
            select(IntentoLogin.username, func.max(IntentoLogin.fecha_hora))
            .where(IntentoLogin.resultado == "exitoso")
            .group_by(IntentoLogin.username)
        )
        .all()
    )
    return {username: fecha for username, fecha in filas}


def _fichas(sesion: Session, ids: set[int]) -> dict[int, Comensal]:
    if not ids:
        return {}
    filas = (
        sesion.execute(
            select(Comensal).where(Comensal.usuario_id.in_(sorted(ids)))
        )
        .scalars()
        .all()
    )
    return {ficha.usuario_id: ficha for ficha in filas}


def _para_respuesta(
    usuario: UsuarioSistema, ficha: Comensal | None, ultimo: datetime | None
) -> dict:
    vinculada = usuario.usuario_turnos_id is not None
    if vinculada:
        # Si la persona se borró del padrón, la cuenta sigue valiendo: el
        # vínculo es lógico, como todos los ids de la base de turnos.
        nombre = ficha.nombre_completo if ficha else None
        categoria = ficha.categoria if ficha else None
    else:
        nombre = usuario.nombre
        categoria = None
    return {
        "id": usuario.id,
        "username": usuario.username,
        "rol": usuario.rol,
        "activo": bool(usuario.activo),
        "debe_cambiar": bool(usuario.debe_cambiar),
        "usuario_turnos_id": usuario.usuario_turnos_id,
        "vinculada": vinculada,
        "nombre": nombre,
        "categoria": categoria,
        "creada": usuario.created_at,
        "ultimo_ingreso": ultimo,
    }


def listar_cuentas(sesion: Session) -> list[dict]:
    usuarios = (
        sesion.execute(select(UsuarioSistema).order_by(UsuarioSistema.id))
        .scalars()
        .all()
    )
    fichas = _fichas(
        sesion,
        {
            u.usuario_turnos_id
            for u in usuarios
            if u.usuario_turnos_id is not None
        },
    )
    ingresos = _ultimos_ingresos(sesion)
    return [
        _para_respuesta(u, fichas.get(u.usuario_turnos_id), ingresos.get(u.username))
        for u in usuarios
    ]


def cuenta_para_respuesta(sesion: Session, usuario: UsuarioSistema) -> dict:
    ficha = (
        sesion.get(Comensal, usuario.usuario_turnos_id)
        if usuario.usuario_turnos_id is not None
        else None
    )
    ultimo = sesion.execute(
        select(func.max(IntentoLogin.fecha_hora)).where(
            IntentoLogin.username == usuario.username,
            IntentoLogin.resultado == "exitoso",
        )
    ).scalar_one()
    return _para_respuesta(usuario, ficha, ultimo)


def buscar_candidatos(sesion: Session, busqueda: str, limite: int) -> list[dict]:
    patron = f"%{busqueda.strip()}%"
    filas = (
        sesion.execute(
            select(Comensal)
            .where(
                or_(
                    Comensal.nombre_completo.like(patron),
                    Comensal.login.like(patron),
                )
            )
            .order_by(
                Comensal.nombre_completo.is_(None),
                Comensal.nombre_completo,
                Comensal.usuario_id,
            )
            .limit(limite)
        )
        .scalars()
        .all()
    )
    cuentas = {
        u.usuario_turnos_id: u.id
        for u in sesion.execute(
            select(UsuarioSistema).where(UsuarioSistema.usuario_turnos_id.is_not(None))
        )
        .scalars()
        .all()
    }
    return [
        {
            "usuario_turnos_id": ficha.usuario_id,
            "login": ficha.login,
            "nombre": ficha.nombre_completo,
            "categoria": ficha.categoria,
            "cuenta_id": cuentas.get(ficha.usuario_id),
        }
        for ficha in filas
    ]


# --- creación ---------------------------------------------------------------


def _es_duplicado(error: IntegrityError) -> bool:
    codigo = getattr(getattr(error, "orig", None), "args", [None])[0]
    return codigo == 1062


def _motivo_duplicado(error: IntegrityError) -> str | None:
    """Qué UNIQUE chocó, por el nombre que trae el propio error 1062."""
    if not _es_duplicado(error):
        return None
    mensaje = str(getattr(error, "orig", error))
    if "uq_usuarios_sistema_usuario_turnos_id" in mensaje:
        return "persona_ya_tiene_cuenta"
    if "uq_usuarios_sistema_username" in mensaje:
        return "username_en_uso"
    return None


def _traducir_insercion(error: IntegrityError) -> ErrorCuenta:
    motivo = _motivo_duplicado(error)
    if motivo == "persona_ya_tiene_cuenta":
        return ErrorCuenta(409, motivo, "Esa persona ya tiene una cuenta.")
    if motivo == "username_en_uso":
        return ErrorCuenta(409, motivo, "Ese username ya está en uso.")
    raise error


def crear_cuenta(
    sesion: Session,
    rol: str,
    usuario_turnos_id: int | None,
    username: str | None,
    nombre: str | None,
    creada_por: UsuarioSistema,
) -> tuple[UsuarioSistema, str]:
    if rol not in ROLES_POR_API:
        raise ErrorCuenta(
            422,
            "rol_no_permitido",
            "Por API solo se crean cuentas de cocinera o jefa.",
        )
    if usuario_turnos_id is not None:
        return _crear_vinculada(sesion, rol, usuario_turnos_id, creada_por)
    # El esquema exige una de las dos formas: acá username y nombre vienen.
    assert username is not None and nombre is not None
    return _crear_sin_vinculo(sesion, rol, username, nombre, creada_por)


def _nueva_cuenta(
    sesion: Session,
    username: str,
    rol: str,
    usuario_turnos_id: int | None,
    nombre: str | None,
    creada_por: UsuarioSistema,
) -> tuple[UsuarioSistema, str]:
    clave = clave_temporal()
    usuario = UsuarioSistema(
        username=username,
        # El hash va en el INSERT: password_hash es NOT NULL y este flush
        # tiene que salir para traducir el 1062, así que no puede esperar.
        password_hash=seguridad.hashear_clave(clave),
        rol=rol,
        activo=1,
        debe_cambiar=1,
        version_token=0,
        usuario_turnos_id=usuario_turnos_id,
        nombre=nombre,
        creada_por_cuenta=creada_por.id,
    )
    sesion.add(usuario)
    try:
        sesion.flush()
    except IntegrityError as error:
        sesion.rollback()
        raise _traducir_insercion(error) from error
    sesion.commit()
    return usuario, clave


def _crear_vinculada(
    sesion: Session, rol: str, usuario_turnos_id: int, creada_por: UsuarioSistema
) -> tuple[UsuarioSistema, str]:
    persona = sesion.execute(
        select(Comensal).where(Comensal.usuario_id == usuario_turnos_id)
    ).scalar_one_or_none()
    if persona is None:
        raise ErrorCuenta(
            404, "persona_inexistente", "Esa persona no está en el padrón."
        )
    username = normalizar_username(persona.login or "")
    if not username or len(username) > 50:
        # Nunca se recorta en silencio: root decide el username a mano.
        raise ErrorCuenta(
            422,
            "login_invalido",
            "El login del padrón está vacío o pasa de 50 caracteres.",
        )
    ya_tiene = sesion.execute(
        select(UsuarioSistema)
        .where(UsuarioSistema.usuario_turnos_id == usuario_turnos_id)
        .with_for_update()
    ).scalar_one_or_none()
    if ya_tiene is not None:
        raise ErrorCuenta(
            409, "persona_ya_tiene_cuenta", "Esa persona ya tiene una cuenta."
        )
    en_uso = sesion.execute(
        select(UsuarioSistema)
        .where(UsuarioSistema.username == username)
        .with_for_update()
    ).scalar_one_or_none()
    if en_uso is not None:
        raise ErrorCuenta(409, "username_en_uso", "Ese username ya está en uso.")
    return _nueva_cuenta(sesion, username, rol, usuario_turnos_id, None, creada_por)


def _crear_sin_vinculo(
    sesion: Session, rol: str, username: str, nombre: str, creada_por: UsuarioSistema
) -> tuple[UsuarioSistema, str]:
    username = normalizar_username(username)
    en_uso = sesion.execute(
        select(UsuarioSistema)
        .where(UsuarioSistema.username == username)
        .with_for_update()
    ).scalar_one_or_none()
    if en_uso is not None:
        raise ErrorCuenta(409, "username_en_uso", "Ese username ya está en uso.")
    return _nueva_cuenta(sesion, username, rol, None, nombre, creada_por)


# --- estado y clave ---------------------------------------------------------


def _obtener_bloqueada(sesion: Session, cuenta_id: int) -> UsuarioSistema:
    cuenta = sesion.execute(
        select(UsuarioSistema)
        .where(UsuarioSistema.id == cuenta_id)
        .with_for_update()
    ).scalar_one_or_none()
    if cuenta is None:
        raise ErrorCuenta(404, "cuenta_inexistente", "No existe esa cuenta.")
    return cuenta


def cambiar_activo(
    sesion: Session, cuenta_id: int, activo: bool, solicitante: UsuarioSistema
) -> UsuarioSistema:
    cuenta = _obtener_bloqueada(sesion, cuenta_id)
    if not activo:
        if cuenta.id == solicitante.id:
            raise ErrorCuenta(
                409,
                "no_puede_desactivarse_a_si_misma",
                "Una cuenta no puede desactivarse a sí misma.",
            )
        if cuenta.activo and cuenta.rol == "sistemas":
            # Las activas de sistemas, bloqueadas: dos desactivaciones a la
            # vez no pueden dejar cero.
            activas = (
                sesion.execute(
                    select(UsuarioSistema)
                    .where(
                        UsuarioSistema.rol == "sistemas",
                        UsuarioSistema.activo == 1,
                    )
                    .with_for_update()
                )
                .scalars()
                .all()
            )
            if len(activas) <= 1:
                raise ErrorCuenta(
                    409,
                    "ultima_cuenta_sistemas",
                    "No se puede desactivar la última cuenta de sistemas.",
                )
        if cuenta.activo:
            cuenta.activo = 0
            cuenta.version_token = (cuenta.version_token or 0) + 1
    else:
        cuenta.activo = 1
    sesion.commit()
    return cuenta


def reiniciar_clave(sesion: Session, cuenta_id: int) -> tuple[UsuarioSistema, str]:
    cuenta = _obtener_bloqueada(sesion, cuenta_id)
    clave = clave_temporal()
    fijar_clave(sesion, cuenta, clave, temporal=True)
    return cuenta, clave
