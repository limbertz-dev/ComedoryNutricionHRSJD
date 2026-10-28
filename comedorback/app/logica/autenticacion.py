"""Reglas del ingreso: credenciales, bloqueo por intentos y cambio de clave.

Escribe solo en `usuarios_sistema` e `intentos_login`, tablas propias de
`bd_nutricion`. No lee ni escribe la base de turnos.

El bloqueo está APAGADO por omisión (AUTH_INTENTOS_MAXIMOS=0): una cocinera
que se equivoca de clave en plena hora de comida no puede quedar 15 minutos
afuera. Todo intento se sigue registrando en `intentos_login`. Si se activa
(por ejemplo AUTH_INTENTOS_MAXIMOS=5 en .env), funciona así:

  · N fallidos seguidos (sin un ingreso exitoso en el medio) que caen dentro
    de AUTH_VENTANA_MINUTOS bloquean la cuenta AUTH_BLOQUEO_MINUTOS desde el último.
  · Mientras dura, no se verifica la clave: el intento se registra como
    `bloqueado` y NO cuenta como fallido. Si contara, alguien probando claves
    sin parar mantendría bloqueada para siempre la cuenta de la jefa.
  · Un username que no existe se bloquea igual. Si no, la diferencia entre
    "401" y "423" diría qué cuentas existen.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import reloj, seguridad
from app.modelos.usuarios import IntentoLogin, UsuarioSistema


def ahora() -> datetime:
    """Reloj del módulo. Hora local sin zona, como el resto de las tablas.
    Existe como función para que los tests puedan adelantarlo. Sin
    microsegundos: la columna es DATETIME y MySQL los redondearía."""
    return reloj.real().replace(microsecond=0)


def normalizar_username(username: str) -> str:
    return username.strip().lower()


# --- la costura -------------------------------------------------------------


def verificar_credenciales(
    sesion: Session, username: str, clave: str
) -> UsuarioSistema | None:
    """¿Esta clave es la de este usuario? Devuelve la cuenta, o None.

    Es el ÚNICO lugar que sabe DÓNDE se validan las claves. Hoy contra la
    tabla propia `usuarios_sistema`. Si mañana la validación pasa a otro sistema del hospital o a
    los `users` de la base de turnos, se reemplaza el cuerpo de esta función
    (la cuenta local sigue aportando el rol) y el bloqueo, los tokens y los
    endpoints no se enteran.

    No distingue "no existe" de "clave incorrecta" de "cuenta inactiva": las
    tres son None, y las tres tardan lo mismo.
    """
    usuario = sesion.execute(
        select(UsuarioSistema).where(UsuarioSistema.username == username)
    ).scalar_one_or_none()
    if usuario is None:
        seguridad.verificar_clave(clave, seguridad.hash_senuelo())
        return None
    if not seguridad.verificar_clave(clave, usuario.password_hash):
        return None
    if not usuario.activo:
        return None
    return usuario


# --- bloqueo ----------------------------------------------------------------


def bloqueado_hasta(sesion: Session, username: str, momento: datetime) -> datetime | None:
    """Hasta cuándo está bloqueado `username` en `momento`, o None."""
    a = seguridad.ajustes()
    if a.intentos_maximos <= 0:
        return None
    # "Después del último éxito" se corta por id y no por hora: la columna
    # guarda segundos, y un fallido en el mismo segundo que el éxito quedaría
    # del lado equivocado.
    ultimo_exito = sesion.execute(
        select(func.max(IntentoLogin.id)).where(
            IntentoLogin.username == username,
            IntentoLogin.resultado == "exitoso",
        )
    ).scalar_one()

    consulta = select(IntentoLogin.fecha_hora).where(
        IntentoLogin.username == username,
        IntentoLogin.resultado == "fallido",
    )
    if ultimo_exito is not None:
        consulta = consulta.where(IntentoLogin.id > ultimo_exito)
    fallidos = (
        sesion.execute(consulta.order_by(IntentoLogin.id.desc()).limit(a.intentos_maximos))
        .scalars()
        .all()
    )
    if len(fallidos) < a.intentos_maximos:
        return None
    ultimo, primero = fallidos[0], fallidos[-1]
    if ultimo - primero > timedelta(minutes=a.ventana_minutos):
        return None
    hasta = ultimo + timedelta(minutes=a.bloqueo_minutos)
    return hasta if momento < hasta else None


def _registrar(sesion: Session, username: str, resultado: str, ip: str | None, momento: datetime):
    sesion.add(
        IntentoLogin(
            username=username[:50], resultado=resultado, ip=ip, fecha_hora=momento
        )
    )
    sesion.commit()


# --- ingreso ----------------------------------------------------------------


@dataclass
class Ingreso:
    """Resultado de un intento. Exactamente uno de los tres casos:

    `usuario`  credenciales correctas (el endpoint mira `debe_cambiar`)
    `hasta`    cuenta bloqueada hasta ese momento
    ninguno    credenciales inválidas
    """

    usuario: UsuarioSistema | None = None
    hasta: datetime | None = None


def ingresar(sesion: Session, username: str, clave: str, ip: str | None) -> Ingreso:
    username = normalizar_username(username)
    momento = ahora()

    hasta = bloqueado_hasta(sesion, username, momento)
    if hasta is not None:
        _registrar(sesion, username, "bloqueado", ip, momento)
        return Ingreso(hasta=hasta)

    usuario = verificar_credenciales(sesion, username, clave)
    if usuario is None:
        _registrar(sesion, username, "fallido", ip, momento)
        # El fallido que completa la serie ya responde con el bloqueo.
        return Ingreso(hasta=bloqueado_hasta(sesion, username, momento))

    _registrar(sesion, username, "exitoso", ip, momento)
    return Ingreso(usuario=usuario)


# --- cambio de clave --------------------------------------------------------


class ClaveRechazada(Exception):
    """La clave nueva no cumple la política. El mensaje es para el usuario."""


def validar_clave_nueva(usuario: UsuarioSistema, nueva: str) -> None:
    a = seguridad.ajustes()
    if len(nueva) < a.largo_minimo_clave:
        raise ClaveRechazada(
            f"La contraseña debe tener al menos {a.largo_minimo_clave} caracteres."
        )
    if len(nueva.encode("utf-8")) > seguridad.MAX_BYTES_CLAVE:
        raise ClaveRechazada("La contraseña es demasiado larga.")
    if nueva.strip().lower() == usuario.username:
        raise ClaveRechazada("La contraseña no puede ser el nombre de usuario.")
    if seguridad.verificar_clave(nueva, usuario.password_hash):
        raise ClaveRechazada("La contraseña nueva debe ser distinta de la actual.")


def fijar_clave(
    sesion: Session, usuario: UsuarioSistema, nueva: str, *, temporal: bool
) -> None:
    """Guarda la clave y anula todos los tokens emitidos hasta ahora.

    `temporal=True` es lo que hace el script de alta/reseteo: la próxima vez
    que ingrese, la persona tendrá que cambiarla.
    """
    usuario.password_hash = seguridad.hashear_clave(nueva)
    usuario.debe_cambiar = temporal
    usuario.version_token = (usuario.version_token or 0) + 1
    sesion.commit()
