# LEGADO: Censo de camas del SIH para el control cama por cama.
# Mantenido temporalmente sin uso activo; reemplazado por raciones_servicio_dia.

"""El censo de camas ocupadas, leído del SIH y traducido al informe.

Este módulo es donde se hace cumplir el principio del Módulo Pacientes:
**todo es automático menos la dieta**. Las camas, las salas, los pacientes y
los traslados los administra el SIH; acá se LEEN y se reflejan. No hay una
sola función que escriba en SQL Server, y no debe haberla nunca.

Tres responsabilidades, separadas a propósito:

  1. Leer `bdestadistica` (SQL Server). Si no se puede, se devuelve una lista
     vacía con el motivo — NUNCA una excepción hacia arriba. La pantalla
     tiene que poder abrirse igual.

  2. Resolver a qué hoja del informe pertenece cada cama. Y ahí vive la regla
     central del módulo:

        una fila de servicios_nutricion con `sa_codigo` GANA
        sobre la fila con `sa_codigo IS NULL`.

     Con eso, Infectología —que no existe como servicio del SIH, son las
     salas 38 y 39 dentro de Coloproctología (208)— sale sin una sola
     excepción escrita en el código.

  3. Resolver UNA cama por su `cam_codigo` (`buscar_cama`). Es lo que usa el
     guardado del parte para no creerle al cliente quién ocupa esa cama.
     Acá la excepción SÍ sube (`SihNoDisponible`): si no se puede leer el
     censo, no se puede congelar una fila, y decirlo es mejor que guardar
     una cama inventada.

Una cama cuya sala no está mapeada NO se rechaza: viaja con
`servicio_nutricion_id = None` y cae en "Sin clasificar". Es la misma regla
que el módulo de personal aplica a las categorías sin mapeo: el hueco se ve,
no se esconde.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.db_sih import SQL_CENSO, SQL_CENSO_UNA_CAMA, motor_sih
from app.modelos.pacientes import ServicioNutricion


class SihNoDisponible(RuntimeError):
    """El SIH no contestó y hacía falta para resolver una cama.

    Solo la levanta `buscar_cama`. `leer_censo` sigue devolviendo
    `disponible=False` sin reventar, porque abrir la pantalla no puede
    depender de la red del hospital.
    """


@dataclass
class CamaCensada:
    """Una cama ocupada, ya traducida al vocabulario del informe."""

    nro_historia: int
    nombre_paciente: str
    # 'M', 'F' o None. Se normaliza al leer porque en SE_HC el campo viene
    # con espacios y en minuscula segun quien cargo la historia. La hoja
    # SERVICIO DE NUTRICION cuenta raciones de hombres y mujeres por
    # separado, asi que sin esto esa hoja no se puede armar.
    sexo: str | None
    sa_codigo: int
    sala_texto: str
    # `SE_SALA.SA_ENUM`: el número de pieza (205, 306, 509...). Es lo que
    # identifica la habitación en el parte de papel, porque SA_DESCRIPCION
    # no alcanza: hay 4 salas "CV" en el servicio 204 y 6 "TRM" en el 206.
    pieza_texto: str
    cam_codigo: int
    cama_texto: str
    cod_servicio_cama: int
    cod_servicio_internacion: int | None
    # `VGRUPOSI.VGRUDESCRI` de cada eje. Viajan para detectar renombres del
    # hospital: si un servicio cambia de nombre, se ve acá antes de que
    # aparezca torcido en un informe firmado. None = el VGRUCODIGO no está
    # en VGRUPOSI, que es justo la cama que la vista del hospital descarta.
    servicio_cama_texto: str | None
    servicio_internacion_texto: str | None
    servicio_nutricion_id: int | None
    hoja_informe: str | None
    grupo_informe: str | None
    # True cuando la cama entró por una fila de sala y no por la del servicio.
    # Sirve para que la UI muestre "Infectologia" y no sorprenda a nadie.
    por_sala: bool = False


@dataclass
class Censo:
    """Resultado de una lectura del SIH, con su diagnóstico."""

    disponible: bool
    mensaje: str
    leido_en: datetime | None = None
    camas: list[CamaCensada] = field(default_factory=list)

    @property
    def sin_clasificar(self) -> int:
        return sum(1 for c in self.camas if c.servicio_nutricion_id is None)


def _mapa(sesion: Session) -> tuple[dict, dict]:
    """Devuelve los dos diccionarios de traducción, en un solo viaje.

    `por_sala[(codigo_sih, sa_codigo)]` y `por_servicio[codigo_sih]`. Se
    resuelven en memoria y no con un JOIN por fila porque son ~30 filas y el
    censo son ~140 camas: traer la tabla entera es más barato que cualquier
    consulta correlacionada.
    """
    filas = sesion.execute(
        select(ServicioNutricion).where(ServicioNutricion.activo == True)  # noqa: E712
    ).scalars().all()

    por_sala = {
        (f.codigo_sih, f.sa_codigo): f for f in filas if f.sa_codigo is not None
    }
    por_servicio = {
        f.codigo_sih: f for f in filas if f.sa_codigo is None and f.codigo_sih is not None
    }
    return por_sala, por_servicio


# `SE_HC.HCL_SEXO` no guarda letras: guarda un codigo. La equivalencia no se
# adivino, se leyo del propio SIH — `sp_HC_selSUMI` marca la casilla
# "masculino" cuando vale 1 y la "femenino" cuando vale 2, y una veintena de
# procedimientos mas repite el mismo CASE.
_SEXO_SIH = {"1": "M", "2": "F"}


def _sexo(crudo) -> str | None:
    """Traduce `SE_HC.HCL_SEXO` a 'M', 'F' o None.

    Cualquier otro valor cae en None a proposito. La hoja SERVICIO DE
    NUTRICION lo muestra como "sin dato" en vez de repartirlo a ojo entre
    las dos columnas: una racion mal atribuida ensucia un informe firmado,
    y una celda vacia se puede ir a corregir al SIH.
    """
    if crudo is None:
        return None
    return _SEXO_SIH.get(str(crudo).strip())


def _traducir(fila, por_sala: dict, por_servicio: dict) -> CamaCensada:
    cod = fila.cod_servicio_cama
    sala = fila.sa_codigo

    # La regla: primero la sala exacta, después el servicio entero.
    servicio = por_sala.get((cod, sala)) or por_servicio.get(cod)
    nombre = " ".join(
        p for p in (fila.nombre, fila.paterno, fila.materno) if p
    ).strip()

    return CamaCensada(
        nro_historia=fila.nro_historia,
        nombre_paciente=nombre,
        sexo=_sexo(fila.sexo),
        sa_codigo=sala,
        sala_texto=fila.sala or "",
        pieza_texto=fila.pieza or "",
        cam_codigo=fila.cam_codigo,
        cama_texto=fila.cama or "",
        cod_servicio_cama=cod,
        cod_servicio_internacion=fila.cod_servicio_internacion,
        servicio_cama_texto=fila.servicio_cama,
        servicio_internacion_texto=fila.servicio_internacion,
        servicio_nutricion_id=servicio.id if servicio else None,
        hoja_informe=servicio.hoja_informe if servicio else None,
        grupo_informe=servicio.grupo_informe if servicio else None,
        por_sala=(cod, sala) in por_sala,
    )


def leer_censo(sesion: Session, servicio_nutricion_id: int | None = None) -> Censo:
    """Lee el censo vigente del SIH y lo traduce.

    `servicio_nutricion_id` filtra a las camas de ese servicio del informe,
    que es lo que pide la pantalla del parte. Sin él devuelve el hospital
    entero, que es lo que necesita la planilla del día.

    El SIH no tiene fecha: `WHERE ORATDET_EST = 'V'` es el ahora y nada más.
    Por eso se guarda `leido_en`: lo que el parte del día no registre, se
    pierde.
    """
    motor = motor_sih()
    if motor is None:
        return Censo(
            disponible=False,
            mensaje=(
                "El SIH no esta disponible. Revisa /pacientes/salud-sih."
            ),
        )

    try:
        with motor.connect() as conexion:
            filas = conexion.execute(text(SQL_CENSO)).all()
    except Exception as error:
        return Censo(
            disponible=False,
            mensaje=f"No se pudo leer el censo del SIH: {error}",
        )

    por_sala, por_servicio = _mapa(sesion)
    camas = [_traducir(f, por_sala, por_servicio) for f in filas]

    if servicio_nutricion_id is not None:
        camas = [c for c in camas if c.servicio_nutricion_id == servicio_nutricion_id]

    return Censo(
        disponible=True,
        mensaje=f"{len(camas)} camas vigentes.",
        leido_en=datetime.now(),
        camas=camas,
    )


def buscar_cama(sesion: Session, cam_codigo: int) -> CamaCensada | None:
    """La cama `cam_codigo` en el censo VIGENTE, o None si no está ocupada.

    Es la pieza que hace cumplir el principio del módulo en el guardado: el
    cliente manda un `cam_codigo` y nada más, y de acá salen la historia, el
    nombre, la sala, la pieza y el número de cama que se congelan en la fila
    del parte. Si el hospital movió al paciente, la próxima lectura lo
    refleja sola; si la cama no está ocupada, esto devuelve None y la fila no
    se guarda.

    A diferencia de `leer_censo`, un SIH caído acá levanta `SihNoDisponible`
    en vez de devolver vacío: "no pude preguntar" y "esa cama está libre" son
    cosas distintas, y confundirlas guardaría datos falsos.
    """
    motor = motor_sih()
    if motor is None:
        raise SihNoDisponible(
            "El SIH no esta disponible y las camas las administra el hospital: "
            "no se puede identificar una cama sin leer el censo."
        )

    try:
        with motor.connect() as conexion:
            fila = conexion.execute(
                text(SQL_CENSO_UNA_CAMA), {"cam_codigo": cam_codigo}
            ).first()
    except Exception as error:
        raise SihNoDisponible(f"No se pudo leer el censo del SIH: {error}") from error

    if fila is None:
        return None

    por_sala, por_servicio = _mapa(sesion)
    return _traducir(fila, por_sala, por_servicio)


def resumen_por_servicio(censo: Censo) -> dict[int | None, int]:
    """Cuántas camas ocupadas tiene hoy cada servicio del informe.

    La clave `None` son las camas cuya sala no está mapeada. Se devuelve
    igual, para que la planilla del día pueda mostrarlas en su propia fila.
    """
    conteo: dict[int | None, int] = {}
    for cama in censo.camas:
        conteo[cama.servicio_nutricion_id] = conteo.get(cama.servicio_nutricion_id, 0) + 1
    return conteo
