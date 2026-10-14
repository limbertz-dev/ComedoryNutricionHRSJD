"""Quién puede qué: la matriz de roles, en un solo lugar.

Tres roles, sin jerarquía implícita (no hay "nivel 1, 2, 3": cada recurso
dice qué roles lo abren):

  · jefa       la jefatura de nutrición. Todo lo operativo: padrón,
               historial, informes, pantalla y marcación, también la manual.
               Las intervenciones de cocina solo las consulta (GET
               /intervenciones-cocina): no las aprueba ni las ejecuta.
  · cocinera   el personal frente al lector. Mira la pantalla en vivo
               (GET /pantalla/*), consulta el padrón en solo lectura (GET
               /personal/*) para operar el lector y marca con el biométrico.
               Es la única que identifica a mano una lectura no reconocida y
               confirma la entrega (POST /asistencias/lecturas/{id}/identificar).
               Ni escrituras en el padrón, ni historial, ni informes, ni
               registro manual.
  · sistemas   soporte técnico. Todo lo de la jefa y, además, la
               administración de cuentas de usuario y el diagnóstico técnico,
               salvo las intervenciones de cocina: ahí queda fuera.

La matriz se aplica en app/main.py, router por router, con `requiere_rol`
(app/core/autorizacion.py). Las reglas finas de la marcación (manual solo
jefatura; biométrico desde una sesión solo en simulación) no se pueden
decidir por la ruta porque dependen del cuerpo de la petición, así que las
aplica el endpoint con `exigir_origen_biometrico` y `exigir_metodo_marcacion`.
Si una política cambia, se cambia AQUÍ y no en cada endpoint.
"""

ROLES: tuple[str, ...] = ("jefa", "cocinera", "sistemas")

JEFATURA: frozenset[str] = frozenset({"jefa", "sistemas"})
ADMINISTRACION: frozenset[str] = frozenset({"sistemas"})

# Roles que pueden registrar una ración a mano (metodo='manual'). Un registro
# manual salta el lector, así que queda en manos de quien responde por el
# informe, no de quien está sirviendo.
MARCACION_MANUAL: frozenset[str] = JEFATURA

# Quién identifica a mano una lectura `no_identificado` y confirma la entrega:
# solo la cocinera, que es quien ve a la persona frente al lector. Ni la jefa
# ni sistemas participan. No es la marcación manual de jefatura (que sigue
# siendo MARCACION_MANUAL y no deja vínculo con ninguna lectura).
IDENTIFICACION_LECTURA: frozenset[str] = frozenset({"cocinera"})

# Quién consulta las intervenciones de cocina: solo la jefa. Sistemas queda
# fuera y no recibe ni los responsables ni las vistas nuevas.
CONSULTA_INTERVENCIONES: frozenset[str] = frozenset({"jefa"})

# Entornos en que una sesión humana puede declarar una marcación biométrica
# (el simulador del navegador). Fuera de ellos, quién apoyó el dedo solo lo
# puede decir un lector autorizado, que todavía no existe: hoy, en producción
# y en desarrollo, POST /asistencias con metodo='biometrico' da 403
# `biometrico_solo_lector` para los tres roles. Se compara contra el entorno
# de la app (app/core/entorno.py), nunca contra config.entorno.
BIOMETRICO_DESDE_SESION: frozenset[str] = frozenset({"simulacion"})


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
    # Las tres pueden llegar al endpoint; el método lo filtran
    # `exigir_origen_biometrico` y `exigir_metodo_marcacion`.
    "asistencias": Regla(completo=frozenset(ROLES)),
    # La cocinera lee el padrón para operar el lector; escribirlo, no.
    "personal": Regla(completo=JEFATURA, lectura=frozenset({"cocinera"})),
    "historial": Regla(completo=JEFATURA),
    "reportes": Regla(completo=JEFATURA),
    # Administración de cuentas: solo root. Sin lectura parcial: jefa y
    # cocinera reciben 403 en todo /admin/*.
    "admin": Regla(completo=ADMINISTRACION),
    # Reglas versionadas: solo root. Jefa y cocinera reciben 403 en /reglas/*.
    "reglas": Regla(completo=ADMINISTRACION),
    # Intervenciones de cocina (GET /intervenciones-cocina): solo la jefa.
    # Sistemas y cocinera reciben 403. El POST que las crea vive bajo
    # /asistencias y lo restringe `usuario_identificador`.
    "intervenciones": Regla(completo=CONSULTA_INTERVENCIONES),
    # Cuentas en solo lectura: jefa y sistemas. Solo existe GET /cuentas;
    # la cocinera recibe 403 y la jefa no ve cuentas de sistemas.
    "cuentas": Regla(completo=JEFATURA),
    # Diagnóstico técnico (GET /monitoreo/estado): solo root. Jefa y cocinera
    # reciben 403.
    "monitoreo": Regla(completo=ADMINISTRACION),
    # Solo existe con ENTORNO=simulacion (app/main.py).
    "simulacion": Regla(completo=JEFATURA),
}
