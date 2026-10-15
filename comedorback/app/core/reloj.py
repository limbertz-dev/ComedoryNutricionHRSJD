"""El reloj único del servidor. Toda la aplicación lee la hora de acá.

  · ahora() / hoy()       la hora del NEGOCIO: marcación, pantalla, historial,
                          informes.
  · real() / real_utc()   la hora del servidor para el bloqueo de login y los
                          JWT.

Hoy las dos son la hora del servidor; se mantienen separadas para que la
lógica de negocio y la de seguridad no dependan de la misma función.

Hora local sin zona, como el resto de las tablas.
"""

from datetime import date, datetime, timezone


def real() -> datetime:
    """La hora del servidor."""
    return datetime.now()


def real_utc() -> datetime:
    """La hora del servidor con zona UTC, para los JWT."""
    return datetime.now(timezone.utc)


def ahora() -> datetime:
    """La hora del negocio."""
    return real()


def hoy() -> date:
    return ahora().date()
