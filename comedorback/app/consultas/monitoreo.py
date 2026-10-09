"""Consultas del diagnóstico técnico (GET /monitoreo/estado, R3-1-20261009).

Catálogo: la misma comprobación de presencia que hace /salud, acotada a lo
que el diagnóstico necesita. /salud no se toca ni se reutiliza: su contenido
público es un contrato aparte.

Actividad: dos lecturas de `lecturas_biometricas`, solo con las columnas del
contrato. Nunca se seleccionan usuario_id ni dispositivo, que es un texto
que declara el cliente y no una identidad. Contar lecturas no prueba que el
lector esté conectado: cualquier cliente autenticado puede marcar.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.db import Base
from app.core.tablas_heredadas import VISTAS_CONTRATO
from app.modelos.comedor import LecturaBiometrica

TABLA_ACTIVIDAD = LecturaBiometrica.__tablename__


@dataclass(frozen=True)
class Catalogo:
    tablas: frozenset[str]
    vistas: frozenset[str]
    revision_alembic: str | None

    @property
    def faltan(self) -> list[str]:
        return sorted(
            (set(Base.metadata.tables) - self.tablas)
            | (set(VISTAS_CONTRATO) - self.vistas)
        )

    @property
    def tablas_propias(self) -> int:
        return len(set(Base.metadata.tables) & self.tablas)

    @property
    def vistas_contrato(self) -> int:
        return len(set(VISTAS_CONTRATO) & self.vistas)


def leer_catalogo(sesion: Session) -> Catalogo:
    """Qué tablas y vistas tiene la base propia, y su revisión de alembic.

    Si falla, no se captura: sin catálogo no hay estado de la base que
    informar, y el endpoint no inventa uno.
    """
    objetos = sesion.execute(
        text(
            "SELECT TABLE_NAME, TABLE_TYPE FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE()"
        )
    ).all()
    tablas = frozenset(nombre for nombre, tipo in objetos if tipo == "BASE TABLE")
    vistas = frozenset(nombre for nombre, tipo in objetos if tipo == "VIEW")

    revision = None
    if "alembic_version" in tablas:
        revision = sesion.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()
    return Catalogo(tablas=tablas, vistas=vistas, revision_alembic=revision)


@dataclass(frozen=True)
class LecturaMayorId:
    id: int
    fecha_hora: datetime
    resultado: str
    motivo: str | None
    created_at: datetime


@dataclass(frozen=True)
class ActividadLecturas:
    aceptadas_dia: int
    rechazadas_dia: int
    registro_mayor_id: LecturaMayorId | None


def contar_lecturas_del_dia(sesion: Session, dia: date) -> dict[str, int]:
    """Lecturas por resultado en el día de negocio, por rango para usar el
    índice de fecha_hora. Un resultado sin filas no aparece: vale 0."""
    inicio = datetime.combine(dia, time.min)
    fin = inicio + timedelta(days=1)
    return dict(
        sesion.execute(
            select(LecturaBiometrica.resultado, func.count())
            .where(LecturaBiometrica.fecha_hora >= inicio)
            .where(LecturaBiometrica.fecha_hora < fin)
            .group_by(LecturaBiometrica.resultado)
        ).all()
    )


def lectura_de_mayor_id(sesion: Session) -> LecturaMayorId | None:
    """La fila de mayor id que ve esta transacción, en toda la tabla y sin
    filtro de día. No es necesariamente el último commit: el id se asigna al
    insertar, y una fila sin confirmar no se ve."""
    fila = sesion.execute(
        select(
            LecturaBiometrica.id,
            LecturaBiometrica.fecha_hora,
            LecturaBiometrica.resultado,
            LecturaBiometrica.motivo,
            LecturaBiometrica.created_at,
        )
        .order_by(LecturaBiometrica.id.desc())
        .limit(1)
    ).first()
    if fila is None:
        return None
    return LecturaMayorId(
        id=fila.id,
        fecha_hora=fila.fecha_hora,
        resultado=fila.resultado,
        motivo=fila.motivo,
        created_at=fila.created_at,
    )


def leer_actividad(sesion: Session, dia: date) -> ActividadLecturas:
    """Las dos lecturas juntas: si una falla, no sale nada de la otra.

    Sin manejo de errores acá; lo decide el endpoint, que es el único que
    sabe que un fallo de actividad no anula el resto del diagnóstico.
    """
    por_resultado = contar_lecturas_del_dia(sesion, dia)
    mayor = lectura_de_mayor_id(sesion)
    return ActividadLecturas(
        aceptadas_dia=por_resultado.get("aceptada", 0),
        rechazadas_dia=por_resultado.get("rechazada", 0),
        registro_mayor_id=mayor,
    )
