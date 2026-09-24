# LEGADO: Conexión al SIH para lectura del censo de camas.
# Mantenido temporalmente sin uso activo; el nuevo flujo carga por servicio en raciones_servicio_dia.

"""Conexión al SIH del hospital: SQL Server, base `bdestadistica`.

SOLO LECTURA, sin excepciones. Este motor nunca ejecuta INSERT, UPDATE,
DELETE ni DDL, y el usuario con el que se conecta solo tiene SELECT. Es una
regla del proyecto, no una recomendación: el SIH es el sistema del que
depende el hospital entero.

Es la otra cara del principio del módulo: **en pacientes todo es automático
menos la dieta**. Las camas, las salas, los pacientes y los traslados los
administra el SIH. Este sistema los LEE y los refleja; no tiene forma de
asignar, mover ni quitar una cama, y no debe tenerla nunca.

Está deliberadamente separado del motor de MySQL (`app/core/db.py`) y es
OPCIONAL. Si no hay driver instalado, no hay credenciales o el servidor no
responde, el sistema **sigue funcionando** en lo que puede: los servicios con
`modo = 'cantidad'` se cargan igual. Esa es la razón de que `motor_sih()`
devuelva None en vez de reventar, y de que `estado_sih()` exista.

Driver: pymssql (no necesita ODBC instalado en el servidor, que es una piedra
menos en el despliegue). Se instala con:

    .venv/Scripts/pip install pymssql

Ojo con la configuración: `app.core.config` se cachea con `@lru_cache`, así
que después de tocar `.env` hay que **reiniciar uvicorn**. El `--reload`
vigila archivos `.py`, no `.env`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.core.config import config


@dataclass(frozen=True)
class DivergenciaVista:
    """Un grupo de camas que nuestra consulta ve y `ListaInternados` no.

    Se agrupa por los dos VGRUCODIGO en juego porque la causa es siempre la
    misma: un código de servicio que no está en `VGRUPOSI`. Saber CUÁL falta
    es lo que permite ir a pedirle al hospital que lo cargue.
    """

    cod_servicio_cama: int | None
    servicio_cama: str | None
    cod_servicio_internacion: int | None
    servicio_internacion: str | None
    camas: int


@dataclass(frozen=True)
class EstadoSih:
    """Diagnóstico de la conexión, para el endpoint de salud y para la UI.

    El frontend lo usa para decidir si ofrece "Traer censo" o si arranca
    directamente en carga manual.
    """

    configurado: bool
    conectado: bool
    mensaje: str
    filas_censo: int | None = None
    filas_vista: int | None = None
    # Historias clinicas DISTINTAS entre esas camas. No tiene por que dar
    # igual que `filas_censo`: una misma historia puede ocupar dos camas, y
    # de hecho hoy ocupa (142 camas, 141 historias). Se expone para que la
    # diferencia sea un dato visible y no una sospecha de duplicados: la
    # unidad de conteo del modulo es la CAMA, no el paciente.
    historias_distintas: int | None = None
    # Camas que nosotros vemos y la vista del hospital descarta, agrupadas
    # por servicio. Si esto no está vacío, el hospital está perdiendo camas
    # en su propio informe y hay que mostrarlo, no taparlo.
    descartadas_por_la_vista: list[DivergenciaVista] = field(default_factory=list)
    # Camas que la vista tiene y nosotros no. Con los JOIN actuales es
    # imposible (nuestro FROM es el de la vista con LEFT en vez de INNER, así
    # que nuestro resultado la contiene). Si alguna vez da distinto de cero,
    # alguien cambió `ListaInternados` y hay que volver a leerla.
    solo_en_la_vista: int | None = None


def _url() -> str | None:
    """Cadena de conexión, o None si el SIH no está configurado."""
    if not (config.sih_host and config.sih_database and config.sih_user):
        return None
    clave = quote_plus(config.sih_password)
    return (
        f"mssql+pymssql://{config.sih_user}:{clave}@"
        f"{config.sih_host}:{config.sih_port}/{config.sih_database}"
    )


@lru_cache
def motor_sih() -> Engine | None:
    """Motor de solo lectura hacia el SIH, o None si no se puede crear.

    Se cachea porque crear el motor es caro y porque la configuración no
    cambia durante la vida del proceso. No abre conexión: eso pasa en el
    primer uso, con `pool_pre_ping` para que una conexión muerta se reponga
    sola cuando la red del hospital se cae y vuelve.
    """
    url = _url()
    if url is None:
        return None
    try:
        return create_engine(url, pool_pre_ping=True, pool_recycle=1800, future=True)
    except Exception:
        # Driver ausente o URL inválida. No es un error fatal: el módulo
        # entero puede trabajar en modo manual.
        return None


def estado_sih() -> EstadoSih:
    """Prueba la conexión y mide la divergencia contra la vista oficial.

    El control de sanidad es comparar nuestra consulta contra
    `dbo.ListaInternados`. Antes se comparaban solo los dos totales, que dice
    QUE hay diferencia pero no CUÁL. Ahora se listan las camas que nosotros
    vemos y la vista descarta, agrupadas por VGRUCODIGO: son exactamente las
    que el hospital está perdiendo en su propio informe, y con el código de
    servicio en la mano se puede ir a pedir que lo carguen en `VGRUPOSI`.
    """
    if _url() is None:
        return EstadoSih(
            configurado=False,
            conectado=False,
            mensaje=(
                "El SIH no esta configurado. Completa SIH_HOST, SIH_DATABASE y "
                "SIH_USER en .env y reinicia el servidor (la configuracion se "
                "cachea al arrancar). Mientras tanto, solo se pueden cargar los "
                "servicios por cantidad."
            ),
        )

    motor = motor_sih()
    if motor is None:
        return EstadoSih(
            configurado=True,
            conectado=False,
            mensaje=(
                "Falta el driver de SQL Server. Instalalo con: "
                ".venv/Scripts/pip install pymssql"
            ),
        )

    try:
        with motor.connect() as conexion:
            base = conexion.execute(text(_SQL_CONTEO_BASE)).one()
            propias = int(base.camas)
            historias = int(base.historias)
            descartadas = [
                DivergenciaVista(
                    cod_servicio_cama=f.cod_servicio_cama,
                    servicio_cama=f.servicio_cama,
                    cod_servicio_internacion=f.cod_servicio_internacion,
                    servicio_internacion=f.servicio_internacion,
                    camas=int(f.camas),
                )
                for f in conexion.execute(text(_SQL_DESCARTADAS_POR_LA_VISTA)).all()
            ]
            try:
                vista = conexion.execute(
                    text("SELECT COUNT(*) FROM dbo.ListaInternados")
                ).scalar_one()
            except Exception:
                vista = None
    except Exception as error:
        return EstadoSih(
            configurado=True,
            conectado=False,
            mensaje=f"No se pudo conectar al SIH: {error}",
        )

    perdidas = sum(d.camas for d in descartadas)
    # Lo que la vista debería tener si la única diferencia fueran sus INNER
    # JOIN contra VGRUPOSI. Si no cuadra, la vista cambió por otro lado.
    sobrantes = None if vista is None else vista - (propias - perdidas)

    if vista is not None and vista != propias:
        detalle = ", ".join(
            f"{d.camas} en {d.cod_servicio_cama} ({d.servicio_cama or 'sin nombre'})"
            for d in descartadas
        )
        return EstadoSih(
            configurado=True,
            conectado=True,
            filas_censo=propias,
            filas_vista=vista,
            historias_distintas=historias,
            descartadas_por_la_vista=descartadas,
            solo_en_la_vista=sobrantes,
            mensaje=(
                f"Conectado. Vemos {propias} camas y ListaInternados {vista}: "
                f"el hospital esta perdiendo {perdidas} cama(s) en su propia "
                f"vista porque el servicio no esta en VGRUPOSI"
                + (f" ({detalle})." if detalle else ".")
                + (
                    f" Ademas hay {sobrantes} fila(s) que la vista tiene y "
                    f"nosotros no: revisar ListaInternados, cambio."
                    if sobrantes
                    else " Esas camas salen igual, en Sin clasificar."
                )
            ),
        )

    return EstadoSih(
        configurado=True,
        conectado=True,
        filas_censo=propias,
        filas_vista=vista,
        historias_distintas=historias,
        descartadas_por_la_vista=descartadas,
        solo_en_la_vista=sobrantes,
        mensaje=(
            f"Conectado. {propias} camas vigentes en el censo, "
            f"{historias} historia(s) distinta(s)."
        ),
    )


# El FROM de `ListaInternados`, leído de su propia fuente, más `HCL_SEXO`.
# Se consultan las tablas base y no la vista porque la vista NO expone
# SA_CODIGO, CAM_CODIGO ni el sexo del paciente,
# y sin ellos no se puede resolver el mapeo por sala (Infectologia son las
# salas 38 y 39 dentro de Coloproctologia) ni identificar la cama que la
# encargada está cargando.
#
# Los dos JOIN contra VGRUPOSI van con LEFT y en la vista son INNER. No es un
# descuido: un INNER **filtra**. Si el hospital interna a alguien en una cama
# cuyo VGRUCODIGO todavía no está cargado en VGRUPOSI, la vista hace
# desaparecer la cama y el paciente se queda sin comer. Con LEFT la cama
# aparece igual, cae en "Sin clasificar" y la diferencia queda medida en
# `estado_sih()`.
#
# Ojo con el eje: `d.VGRUCODIGO` es el servicio de INTERNACION y `s.VGRUCODIGO`
# el de la CAMA. El informe se arma por el de la cama, porque el carro de
# comida va a la sala fisica. Hoy 6 de las 142 camas difieren entre los dos.
#
# `s.SA_ENUM` es el número de pieza (205, 306, 509...). `SA_DESCRIPCION` NO
# sirve para identificar: hay 4 salas "CV" en el servicio 204 y 6 "TRM" en
# el 206. La pieza es lo que las distingue en el papel.
_SELECT_CENSO = """
SELECT
    h.HCL_CODIGO                                   AS nro_historia,
    LTRIM(RTRIM(h.HCL_NOMBRE))                     AS nombre,
    LTRIM(RTRIM(h.HCL_APPAT))                      AS paterno,
    LTRIM(RTRIM(h.HCL_APMAT))                      AS materno,
    -- `ListaInternados` no expone el sexo. Hace falta para la hoja
    -- SERVICIO DE NUTRICION, que cuenta raciones de hombres y mujeres por
    -- separado.
    --
    -- Viene CODIFICADO: '1' = masculino, '2' = femenino. No es una
    -- suposicion — es lo que hace el propio SIH en sus procedimientos
    -- (`sp_HC_selSUMI` marca masculino cuando vale 1 y femenino cuando
    -- vale 2, y una veintena mas usa el mismo CASE). La traduccion a
    -- 'M'/'F' se hace arriba, en `censo.py`, para que este SQL siga siendo
    -- un espejo de las tablas del hospital.
    LTRIM(RTRIM(h.HCL_SEXO))                       AS sexo,
    d.VGRUCODIGO                                   AS cod_servicio_internacion,
    LTRIM(RTRIM(v1.VGRUDESCRI))                    AS servicio_internacion,
    s.VGRUCODIGO                                   AS cod_servicio_cama,
    LTRIM(RTRIM(v.VGRUDESCRI))                     AS servicio_cama,
    s.SA_CODIGO                                    AS sa_codigo,
    LTRIM(RTRIM(s.SA_ENUM))                        AS pieza,
    LTRIM(RTRIM(s.SA_DESCRIPCION))                 AS sala,
    c.CAM_CODIGO                                   AS cam_codigo,
    LTRIM(RTRIM(c.CAM_ENUM))                       AS cama
FROM SE_ORATENCAB o
INNER JOIN SE_ORATENDET d ON d.ORAT_CODIGO = o.ORAT_CODIGO
INNER JOIN SE_CAMA      c ON c.CAM_CODIGO  = d.CAM_CODIGO
INNER JOIN SE_SALA      s ON s.SA_CODIGO   = c.SA_CODIGO
INNER JOIN SE_HC        h ON h.HCL_CODIGO  = o.HCL_CODIGO
LEFT  JOIN VGRUPOSI     v ON v.VGRUCODIGO  = s.VGRUCODIGO
LEFT  JOIN VGRUPOSI    v1 ON v1.VGRUCODIGO = d.VGRUCODIGO
WHERE d.ORATDET_EST = 'V'
"""

SQL_CENSO = _SELECT_CENSO + """
ORDER BY s.VGRUCODIGO, s.SA_CODIGO, c.CAM_ENUM
"""

# La misma consulta para UNA cama. Es la que usa el guardado de una fila del
# parte para resolver en el servidor quién ocupa esa cama, en vez de creerle
# al cliente.
SQL_CENSO_UNA_CAMA = _SELECT_CENSO + """
  AND c.CAM_CODIGO = :cam_codigo
"""

_SQL_CONTEO_BASE = """
SELECT COUNT(*) AS camas, COUNT(DISTINCT o.HCL_CODIGO) AS historias
FROM SE_ORATENCAB o
INNER JOIN SE_ORATENDET d ON d.ORAT_CODIGO = o.ORAT_CODIGO
INNER JOIN SE_CAMA      c ON c.CAM_CODIGO  = d.CAM_CODIGO
INNER JOIN SE_SALA      s ON s.SA_CODIGO   = c.SA_CODIGO
INNER JOIN SE_HC        h ON h.HCL_CODIGO  = o.HCL_CODIGO
LEFT  JOIN VGRUPOSI     v ON v.VGRUCODIGO  = s.VGRUCODIGO
LEFT  JOIN VGRUPOSI    v1 ON v1.VGRUCODIGO = d.VGRUCODIGO
WHERE d.ORATDET_EST = 'V'
"""

# Exactamente las camas que los INNER JOIN de `ListaInternados` tiran: las que
# tienen un VGRUCODIGO que no existe en VGRUPOSI, por cualquiera de los dos
# ejes. Agrupadas por servicio para poder ir a reclamar con el código.
_SQL_DESCARTADAS_POR_LA_VISTA = """
SELECT
    s.VGRUCODIGO                    AS cod_servicio_cama,
    LTRIM(RTRIM(v.VGRUDESCRI))      AS servicio_cama,
    d.VGRUCODIGO                    AS cod_servicio_internacion,
    LTRIM(RTRIM(v1.VGRUDESCRI))     AS servicio_internacion,
    COUNT(*)                        AS camas
FROM SE_ORATENCAB o
INNER JOIN SE_ORATENDET d ON d.ORAT_CODIGO = o.ORAT_CODIGO
INNER JOIN SE_CAMA      c ON c.CAM_CODIGO  = d.CAM_CODIGO
INNER JOIN SE_SALA      s ON s.SA_CODIGO   = c.SA_CODIGO
INNER JOIN SE_HC        h ON h.HCL_CODIGO  = o.HCL_CODIGO
LEFT  JOIN VGRUPOSI     v ON v.VGRUCODIGO  = s.VGRUCODIGO
LEFT  JOIN VGRUPOSI    v1 ON v1.VGRUCODIGO = d.VGRUCODIGO
WHERE d.ORATDET_EST = 'V'
  AND (v.VGRUCODIGO IS NULL OR v1.VGRUCODIGO IS NULL)
GROUP BY s.VGRUCODIGO, LTRIM(RTRIM(v.VGRUDESCRI)),
         d.VGRUCODIGO, LTRIM(RTRIM(v1.VGRUDESCRI))
ORDER BY s.VGRUCODIGO, d.VGRUCODIGO
"""
