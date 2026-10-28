"""El reloj único del servidor. Toda la aplicación lee la hora de acá.

  · ahora() / hoy()       la hora del NEGOCIO: marcación, pantalla, historial,
                          informes.
  · real() / real_utc()   la hora del servidor para el bloqueo de login y los
                          JWT.

Hoy las dos son la hora del servidor; se mantienen separadas para que la
lógica de negocio y la de seguridad no dependan de la misma función.

Hora local del hospital (Tarija, Bolivia), sin zona, como el resto de las
tablas. Bolivia es UTC-4 todo el año, sin horario de verano: la hora se
calcula con ese desfase fijo y no depende de la zona configurada en el
servidor (un equipo o contenedor en UTC abriría las comidas 4 h tarde).
"""

from datetime import date, datetime, timedelta, timezone

ZONA_HOSPITAL = timezone(timedelta(hours=-4), "America/La_Paz")


def real() -> datetime:
    """La hora del servidor, en hora de Bolivia."""
    return datetime.now(ZONA_HOSPITAL).replace(tzinfo=None)


def real_utc() -> datetime:
    """La hora del servidor con zona UTC, para los JWT."""
    return datetime.now(timezone.utc)


def ahora() -> datetime:
    """La hora del negocio."""
    return real()


def hoy() -> date:
    return ahora().date()
