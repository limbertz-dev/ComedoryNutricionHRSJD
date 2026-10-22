"""Punto de entrada al SIH del hospital. Hoy no hay conector: nada lo llama.

El SIH es un SQL Server del hospital (base de estadística) del que depende el
hospital entero. Cuando se conecte, el conector real va aquí, dentro de
`cliente_sih()`, con estas reglas:

- Motor propio de SQLAlchemy contra SQL Server, separado del de
  `bd_nutricion` (app/core/db.py). Nunca comparte sesión ni transacción.
- Solo lectura: el usuario de SIH_USER tiene solo SELECT, y el conector no
  emite escrituras aunque el usuario lo permita.
- La URL se arma con `config.sih_password.get_secret_value()` escapada con
  quote_plus, igual que `url_base_datos`, y no se registra en ningún log.
- Si el SIH no responde, la API sigue funcionando: quien llame a
  `cliente_sih()` atrapa `SIHNoConfigurado` o el error de conexión y muestra
  el aviso, sin tumbar la pantalla.
"""

from app.core.config import config


class SIHNoConfigurado(RuntimeError):
    """El SIH no se puede usar: faltan variables SIH_* o aún no hay conector."""


def cliente_sih():
    """Devolverá el cliente de solo lectura del SIH. Hoy siempre lanza
    `SIHNoConfigurado`: sin variables SIH_* porque falta configurarlo, y con
    ellas porque el conector todavía no existe."""
    if not config.sih_configurado:
        raise SIHNoConfigurado(
            "SIH no configurado: faltan SIH_HOST, SIH_DATABASE, SIH_USER o "
            "SIH_PASSWORD en .env."
        )
    raise SIHNoConfigurado("SIH no configurado: el conector todavía no existe.")
