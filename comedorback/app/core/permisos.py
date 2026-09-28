"""Quién puede qué: la matriz de roles, en un solo lugar.

Tres roles, sin jerarquía implícita (no hay "nivel 1, 2, 3": cada recurso
dice qué roles lo abren):

  · jefa       la jefatura de nutrición. Todo lo operativo: padrón,
               historial, informes, pantalla y marcación, también la manual.
  · cocinera   el personal frente al lector. Mira la pantalla en vivo
               (GET /pantalla/*), consulta el padrón en solo lectura (GET
               /personal/*) para operar el lector y marca con el biométrico.
               Ni escrituras en el padrón, ni historial, ni informes, ni
               registro manual.
  · sistemas   soporte técnico. Todo lo de la jefa y, además, lo de
               administración (cuentas de usuario) cuando exista.

La matriz se aplica en app/main.py, router por router, con `requiere_rol`
(app/core/autorizacion.py). La regla fina de la marcación (manual solo
jefatura) no se puede decidir por la ruta porque depende del cuerpo de la
petición, así que la aplica el endpoint llamando a `exigir_metodo_marcacion`.
Si una política cambia, se cambia AQUÍ y no en cada endpoint.
"""

ROLES: tuple[str, ...] = ("jefa", "cocinera", "sistemas")

JEFATURA: frozenset[str] = frozenset({"jefa", "sistemas"})
ADMINISTRACION: frozenset[str] = frozenset({"sistemas"})

# Roles que pueden registrar una ración a mano (metodo='manual'). Un registro
# manual salta el lector, así que queda en manos de quien responde por el
# informe, no de quien está sirviendo.
MARCACION_MANUAL: frozenset[str] = JEFATURA


class Regla:
    """Acceso a un grupo de rutas.

    `completo`: roles que pueden usar cualquier método.
    `lectura`:  roles que solo pueden hacer GET/HEAD. Así una ruta de
                escritura que alguien agregue mañana bajo /pantalla no queda
                abierta para la cocinera sin que nadie lo decida.
    """

    def __init__(self, completo: frozenset[str], lectura: frozenset[str] = frozenset()):
        self.completo = completo
        self.lectura = lectura


ACCESO: dict[str, Regla] = {
    "pantalla": Regla(completo=JEFATURA, lectura=frozenset({"cocinera"})),
    # Las tres pueden llegar al endpoint; el método lo filtra
    # `exigir_metodo_marcacion`.
    "asistencias": Regla(completo=frozenset(ROLES)),
    # La cocinera lee el padrón para operar el lector; escribirlo, no.
    "personal": Regla(completo=JEFATURA, lectura=frozenset({"cocinera"})),
    "historial": Regla(completo=JEFATURA),
    "reportes": Regla(completo=JEFATURA),
    # Solo existe con ENTORNO=simulacion (app/main.py).
    "simulacion": Regla(completo=JEFATURA),
}
