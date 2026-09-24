# LEGADO: Control de dietas por cama y paciente (dietas_cama).
# Mantenido temporalmente sin uso activo; reemplazado por raciones_servicio_dia.

"""Control de Dietas: el censo del SIH cruzado con lo que decidió nutrición.

Es la pantalla de trabajo del módulo. Muestra una fila por cama ocupada y,
al lado, la dieta que rige ahora mismo para esa cama.

La regla que gobierna todo este archivo:

    **Nunca se actualiza una fila de `dietas_cama`: siempre se inserta una
    nueva con su `momento`.**

Un cambio de dieta no borra el anterior. Para el conteo del día manda la
ÚLTIMA fila de cada cama; para auditar están todas. Es la única forma de
responder después por qué un mes cerrado no coincide con lo que se vio en
el momento, y es la misma decisión que `asistencias` toma en el Módulo 1.

Sobre la fecha, que tiene una trampa
------------------------------------
El SIH no guarda historia de ocupación: `WHERE ORATDET_EST = 'V'` es el
AHORA y nada más. No hay forma de preguntarle quién estaba en la cama 12 el
martes pasado.

Por eso esta consulta trabaja de dos maneras distintas según la fecha, y no
es un capricho:

  · HOY      censo vigente del SIH ∪ las filas congeladas de hoy. Las camas
             del censo sin fila todavía aparecen con `dieta = null`: son
             justamente las que falta cargar.

  · OTRO DÍA solo las filas congeladas de esa fecha. Cruzar una fecha vieja
             con el censo de hoy mostraría a los pacientes de hoy en las
             camas de entonces, que es peor que no mostrar nada.

Una cama que recibió dieta hoy y que el hospital ya dio de alta sigue
apareciendo, con `en_censo = False`: la ración se sirvió y tiene que contar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.consultas.censo import CamaCensada, SihNoDisponible, buscar_cama, leer_censo
from app.modelos.pacientes import DietasCama, TipoDieta


class CamaFueraDelCenso(RuntimeError):
    """Se quiso cargar una dieta para una cama que el SIH no da por ocupada.

    Es un 409, no un 404: el recurso existe, pero el estado del hospital no
    admite la operación. Las camas las administra el SIH; si ahí no está
    ocupada, este sistema no tiene de dónde sacar el paciente, la sala ni el
    servicio que hay que congelar, y no los va a inventar.
    """


class SinDietaVigente(RuntimeError):
    """Se quiso suspender o reanudar una cama que no tiene dieta hoy."""


@dataclass(frozen=True)
class Marca:
    """El `{hora, motivo}` de la línea chica de la pantalla.

    Va en campos separados y no como un texto ya armado porque el que decide
    cómo se lee es el front: en la tabla entra como "09:40 · a cirugía" y en
    el detalle como dos columnas. Armarlo acá obligaría a desarmarlo allá.
    """

    hora: time
    motivo: str | None


@dataclass
class DietaVigente:
    """La dieta que rige para una cama, con su identidad y su hora."""

    dietas_cama_id: int
    tipo_dieta_id: int
    codigo: str
    nombre: str
    cuenta_racion: bool
    prescripcion_texto: str | None
    momento: datetime


@dataclass
class FilaControl:
    """Una cama con su dieta vigente. Todo lo de la cama es de solo lectura.

    Los datos del paciente, la sala y el servicio salen del SIH o de la copia
    congelada: esta pantalla no los edita y la API no expone forma de
    hacerlo. Lo único que se carga acá es la dieta.
    """

    # --- identidad de la cama, del SIH ---
    cam_codigo: int
    cama_texto: str
    sa_codigo: int | None
    sala_texto: str
    pieza_texto: str

    # --- paciente, congelado o del censo ---
    nro_historia: int | None
    nombre_paciente: str | None
    sexo: str | None

    # --- a qué hoja del libro va ---
    servicio_nutricion_id: int | None
    hoja_informe: str | None
    grupo_informe: str | None
    servicio_cama_texto: str | None
    por_sala: bool
    sin_clasificar: bool

    # --- la decisión de nutrición ---
    dieta: DietaVigente | None
    suspendida: bool
    cambio: Marca | None
    suspension: Marca | None
    hechos_hoy: int

    # False = la cama ya no está en el censo vigente. Pasa cuando al paciente
    # le dieron de alta después de que se le sirvió: la ración existió.
    en_censo: bool


@dataclass
class ControlDelDia:
    """Lo que devuelve la pantalla, con su diagnóstico y sus totales."""

    fecha: date
    es_hoy: bool
    sih_disponible: bool
    sih_mensaje: str
    leido_en: datetime | None
    filas: list[FilaControl]

    @property
    def total_camas(self) -> int:
        return len(self.filas)

    @property
    def con_dieta(self) -> int:
        return sum(1 for f in self.filas if f.dieta is not None)

    @property
    def sin_dieta(self) -> int:
        return sum(1 for f in self.filas if f.dieta is None)

    @property
    def suspendidas(self) -> int:
        return sum(1 for f in self.filas if f.suspendida)

    @property
    def sin_clasificar(self) -> int:
        return sum(1 for f in self.filas if f.sin_clasificar)

    @property
    def raciones(self) -> int:
        """Lo que hoy sumaría al libro: ni suspendidas ni NPO.

        Se expone en la pantalla para que el número no aparezca recién a fin
        de mes. Es la misma regla que aplican los informes.
        """
        return sum(
            1
            for f in self.filas
            if f.dieta is not None and not f.suspendida and f.dieta.cuenta_racion
        )


@dataclass(frozen=True)
class FiltroControl:
    """Qué filas de la pantalla se quieren. Los tres criterios se combinan (AND).

    La sala va por `sa_codigo` y nunca por el texto: el texto del SIH se
    repite y tiene errores. "Sin clasificar" es el mismo booleano de la fila
    que cuenta el total `sin_clasificar`, no una deducción desde la hoja.
    """

    sala: int | None = None
    hoja: str | None = None
    sin_clasificar: bool = False

    def admite(self, fila: FilaControl) -> bool:
        return (
            (self.sala is None or fila.sa_codigo == self.sala)
            and (self.hoja is None or fila.hoja_informe == self.hoja)
            and (not self.sin_clasificar or fila.sin_clasificar)
        )


def filtrar_filas(filas: list[FilaControl], filtro: FiltroControl | None) -> list[FilaControl]:
    """Las filas que pasan el filtro, en el mismo orden. Sin filtro, todas."""
    if filtro is None:
        return filas
    return [f for f in filas if filtro.admite(f)]


def _hechos_del_dia(sesion: Session, fecha: date) -> dict[int, list]:
    """Todas las filas de `dietas_cama` de esa fecha, agrupadas por cama.

    Se traen TODAS y no solo la última, en una sola consulta, porque hacen
    falta las dos cosas: la última manda, y la cantidad es la que dice si la
    dieta cambió en el día. Son pocas filas —del orden de las camas— así que
    agrupar en memoria sale más barato que una consulta con ventana más otra
    de conteo.

    Vienen ordenadas por `momento` y, a igual momento, por `id`: dos cambios
    dentro del mismo segundo tienen que resolverse igual siempre.
    """
    filas = sesion.execute(
        select(DietasCama, TipoDieta)
        .join(TipoDieta, TipoDieta.id == DietasCama.tipo_dieta_id)
        .where(DietasCama.fecha == fecha)
        .order_by(DietasCama.cam_codigo, DietasCama.momento, DietasCama.id)
    ).all()

    por_cama: dict[int, list] = {}
    for dieta_cama, tipo in filas:
        por_cama.setdefault(dieta_cama.cam_codigo, []).append((dieta_cama, tipo))
    return por_cama


def _fila_desde_censo(cama: CamaCensada, hechos: list) -> FilaControl:
    """Una cama del censo vigente, con lo que se haya cargado hoy."""
    base = FilaControl(
        cam_codigo=cama.cam_codigo,
        cama_texto=cama.cama_texto,
        sa_codigo=cama.sa_codigo,
        sala_texto=cama.sala_texto,
        pieza_texto=cama.pieza_texto,
        nro_historia=cama.nro_historia,
        nombre_paciente=cama.nombre_paciente,
        sexo=cama.sexo,
        servicio_nutricion_id=cama.servicio_nutricion_id,
        hoja_informe=cama.hoja_informe,
        grupo_informe=cama.grupo_informe,
        servicio_cama_texto=cama.servicio_cama_texto,
        por_sala=cama.por_sala,
        # Sin clasificar es cualquiera de las dos cosas: que la sala no esté
        # mapeada, o que lo esté a una fila que todavía no tiene hoja. Las dos
        # terminan igual en el libro, y las dos hay que poder verlas.
        sin_clasificar=(
            cama.servicio_nutricion_id is None or cama.hoja_informe is None
        ),
        dieta=None,
        suspendida=False,
        cambio=None,
        suspension=None,
        hechos_hoy=0,
        en_censo=True,
    )
    return _aplicar_hechos(base, hechos)


def _fila_desde_congelado(hechos: list, en_censo: bool) -> FilaControl:
    """Una cama que solo existe en lo congelado: fecha vieja, o alta del día.

    Todo sale de la última fila guardada. Es exactamente para esto que
    `dietas_cama` copia el paciente, la sala y la pieza en vez de apuntar al
    SIH con una clave foránea que ni siquiera sería posible.
    """
    ultima, _tipo = hechos[-1]
    base = FilaControl(
        cam_codigo=ultima.cam_codigo,
        cama_texto=ultima.cama_texto or "",
        sa_codigo=ultima.sa_codigo,
        sala_texto=ultima.sala_texto or "",
        pieza_texto=ultima.pieza_texto or "",
        nro_historia=ultima.nro_historia,
        nombre_paciente=ultima.nombre_paciente,
        sexo=ultima.sexo,
        servicio_nutricion_id=ultima.servicio_nutricion_id,
        # La hoja y el grupo no se congelaron en la fila: se resuelven contra
        # el catálogo al armar los informes. Acá van en None y la pantalla
        # muestra el servicio por su id.
        hoja_informe=None,
        grupo_informe=None,
        servicio_cama_texto=None,
        por_sala=False,
        sin_clasificar=ultima.servicio_nutricion_id is None,
        dieta=None,
        suspendida=False,
        cambio=None,
        suspension=None,
        hechos_hoy=0,
        en_censo=en_censo,
    )
    return _aplicar_hechos(base, hechos)


def _aplicar_hechos(fila: FilaControl, hechos: list) -> FilaControl:
    """Vuelca sobre la fila la ÚLTIMA decisión del día y sus marcas."""
    fila.hechos_hoy = len(hechos)
    if not hechos:
        return fila

    ultima, tipo = hechos[-1]
    fila.dieta = DietaVigente(
        dietas_cama_id=ultima.id,
        tipo_dieta_id=tipo.id,
        codigo=tipo.codigo,
        nombre=tipo.nombre,
        cuenta_racion=bool(tipo.cuenta_racion),
        prescripcion_texto=ultima.prescripcion_texto,
        momento=ultima.momento,
    )
    fila.suspendida = bool(ultima.suspendida)

    # `cambio` solo existe si hubo más de un hecho: la primera dieta del día
    # no es un cambio.
    if len(hechos) > 1:
        fila.cambio = Marca(hora=ultima.momento.time(), motivo=ultima.motivo)
    if fila.suspendida:
        fila.suspension = Marca(hora=ultima.momento.time(), motivo=ultima.motivo)
    return fila


def control_del_dia(
    sesion: Session, fecha: date, filtro: FiltroControl | None = None
) -> ControlDelDia:
    """Las camas de esa fecha con su dieta vigente.

    Ver la nota de arriba sobre por qué hoy y cualquier otro día no se
    resuelven igual. El filtro recorta las filas; los totales se siguen
    calculando sobre las filas que se devuelven, como siempre.
    """
    hechos = _hechos_del_dia(sesion, fecha)
    es_hoy = fecha == date.today()

    if not es_hoy:
        # El SIH no puede decir quién ocupaba cada cama ese día. Lo congelado
        # es el único registro que hay, y alcanza: para eso se congeló.
        filas = [
            _fila_desde_congelado(h, en_censo=False)
            for _cam, h in sorted(hechos.items())
        ]
        return ControlDelDia(
            fecha=fecha,
            es_hoy=False,
            sih_disponible=False,
            sih_mensaje=(
                "Fecha pasada: el SIH no guarda historia de ocupacion, asi que "
                "estas filas salen de los datos congelados al momento de cada "
                "hecho."
            ),
            leido_en=None,
            filas=filtrar_filas(filas, filtro),
        )

    censo = leer_censo(sesion)
    filas = [_fila_desde_censo(c, hechos.get(c.cam_codigo, [])) for c in censo.camas]

    # Camas con dieta cargada hoy que ya no están en el censo: el hospital dio
    # de alta al paciente después de servirle. La ración existió y tiene que
    # seguir contando, así que la fila no se descarta.
    en_censo = {c.cam_codigo for c in censo.camas}
    filas += [
        _fila_desde_congelado(h, en_censo=False)
        for cam, h in sorted(hechos.items())
        if cam not in en_censo
    ]

    return ControlDelDia(
        fecha=fecha,
        es_hoy=True,
        sih_disponible=censo.disponible,
        sih_mensaje=censo.mensaje,
        leido_en=censo.leido_en,
        filas=filtrar_filas(filas, filtro),
    )


# --------------------------------------------------------------------------
# Escritura. Los tres caminos terminan en el mismo INSERT y ninguno actualiza.
# --------------------------------------------------------------------------


def _ultima_de_hoy(sesion: Session, cam_codigo: int, fecha: date) -> DietasCama | None:
    """La última decisión tomada para esa cama ese día, o None."""
    return sesion.execute(
        select(DietasCama)
        .where(DietasCama.fecha == fecha, DietasCama.cam_codigo == cam_codigo)
        .order_by(DietasCama.momento.desc(), DietasCama.id.desc())
        .limit(1)
    ).scalars().first()


def _tipo_activo(sesion: Session, tipo_dieta_id: int) -> TipoDieta:
    """La dieta que se quiere asignar: tiene que existir, estar activa y no
    estar eliminada (visible = 0). Cualquier otra cosa es un 422."""
    tipo = sesion.get(TipoDieta, tipo_dieta_id)
    if tipo is None or not tipo.visible:
        raise ValueError(f"El tipo de dieta {tipo_dieta_id} no existe o fue eliminado.")
    if not tipo.activo:
        raise ValueError(f"El tipo de dieta {tipo_dieta_id} esta dado de baja.")
    return tipo


def _congelar(cama: CamaCensada, **decision) -> DietasCama:
    """Arma la fila nueva copiando del censo todo lo que el cliente no manda.

    Acá se hace cumplir el principio del módulo: el cliente manda un
    `cam_codigo` y la decisión de nutrición, nada más. El paciente, el sexo,
    la sala, la pieza y el servicio salen del censo leído en este mismo
    instante, no de lo que diga el navegador.
    """
    ahora = datetime.now()
    return DietasCama(
        fecha=ahora.date(),
        momento=ahora,
        cam_codigo=cama.cam_codigo,
        sa_codigo=cama.sa_codigo,
        nro_historia=cama.nro_historia,
        nombre_paciente=cama.nombre_paciente,
        sexo=cama.sexo,
        sala_texto=cama.sala_texto,
        pieza_texto=cama.pieza_texto,
        cama_texto=cama.cama_texto,
        servicio_nutricion_id=cama.servicio_nutricion_id,
        **decision,
    )


def _cama_vigente(sesion: Session, cam_codigo: int) -> CamaCensada:
    cama = buscar_cama(sesion, cam_codigo)
    if cama is None:
        raise CamaFueraDelCenso(
            f"La cama {cam_codigo} no figura ocupada en el censo vigente del "
            f"SIH. Las camas las administra el hospital: si el paciente fue "
            f"trasladado o dado de alta, la dieta va en su cama nueva."
        )
    return cama


def asignar_dieta(
    sesion: Session,
    cam_codigo: int,
    tipo_dieta_id: int,
    motivo: str | None = None,
    prescripcion_texto: str | None = None,
    registrado_por: int | None = None,
) -> DietasCama:
    """Asigna o cambia la dieta de una cama. Siempre INSERT, nunca UPDATE.

    `motivo` es opcional, también en un cambio: la pantalla no lo pide. Si
    viene, se guarda; si no, el cambio queda igual trazable por su `momento`.
    """
    cama = _cama_vigente(sesion, cam_codigo)
    tipo = _tipo_activo(sesion, tipo_dieta_id)

    fila = _congelar(
        cama,
        tipo_dieta_id=tipo.id,
        prescripcion_texto=(prescripcion_texto or "").strip() or None,
        # Al cambiar la dieta la cama vuelve a recibir comida. Si estaba
        # suspendida, asignarle una dieta es la forma natural de reanudarla.
        suspendida=0,
        motivo=(motivo or "").strip() or None,
        registrado_por=registrado_por,
    )
    sesion.add(fila)
    sesion.commit()
    return fila


def suspender(
    sesion: Session,
    cam_codigo: int,
    motivo: str | None = None,
    registrado_por: int | None = None,
) -> DietasCama:
    """Marca que la cama deja de recibir comida, sin borrar la dieta.

    La fila nueva conserva el `tipo_dieta_id` vigente a propósito: lo que se
    suspende es el servicio de la comida, no la prescripción. Cuando se
    reanuda, se reanuda con la misma dieta y no hay que volver a elegirla.
    """
    cama = _cama_vigente(sesion, cam_codigo)
    previa = _ultima_de_hoy(sesion, cam_codigo, date.today())
    if previa is None:
        raise SinDietaVigente(
            f"La cama {cam_codigo} todavia no tiene dieta hoy: no hay nada que "
            f"suspender. Asignale una dieta primero."
        )
    if previa.suspendida:
        raise SinDietaVigente(f"La cama {cam_codigo} ya esta suspendida.")

    fila = _congelar(
        cama,
        tipo_dieta_id=previa.tipo_dieta_id,
        prescripcion_texto=previa.prescripcion_texto,
        suspendida=1,
        motivo=(motivo or "").strip() or None,
        registrado_por=registrado_por,
    )
    sesion.add(fila)
    sesion.commit()
    return fila


def reanudar(
    sesion: Session,
    cam_codigo: int,
    motivo: str | None = None,
    registrado_por: int | None = None,
) -> DietasCama:
    """Vuelve a poner la cama en el reparto, con la dieta que ya tenía."""
    cama = _cama_vigente(sesion, cam_codigo)
    previa = _ultima_de_hoy(sesion, cam_codigo, date.today())
    if previa is None or not previa.suspendida:
        raise SinDietaVigente(
            f"La cama {cam_codigo} no esta suspendida: no hay nada que reanudar."
        )

    fila = _congelar(
        cama,
        tipo_dieta_id=previa.tipo_dieta_id,
        prescripcion_texto=previa.prescripcion_texto,
        suspendida=0,
        motivo=(motivo or "").strip() or None,
        registrado_por=registrado_por,
    )
    sesion.add(fila)
    sesion.commit()
    return fila


def historial(sesion: Session, cam_codigo: int, fecha: date) -> list[tuple]:
    """Todos los hechos de una cama en un día, del más viejo al más nuevo.

    No lo usa ningún endpoint de esta etapa: lo usa la verificación, y lo va
    a usar la pantalla de auditoría. Está acá y no en una prueba porque la
    pregunta "que paso con esta cama" es del dominio, no del test.
    """
    return sesion.execute(
        select(DietasCama, TipoDieta)
        .join(TipoDieta, TipoDieta.id == DietasCama.tipo_dieta_id)
        .where(DietasCama.fecha == fecha, DietasCama.cam_codigo == cam_codigo)
        .order_by(DietasCama.momento, DietasCama.id)
    ).all()
