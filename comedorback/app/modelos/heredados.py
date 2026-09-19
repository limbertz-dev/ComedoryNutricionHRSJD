"""Modelos de las tablas que ya existen en el módulo de turnos.

SOLO LECTURA. Este sistema las consulta pero no las administra: no se crean,
no se alteran y no se borran desde aquí. Están marcadas con
`info={"heredada": True}` para que alembic/env.py las excluya del autogenerate.

Se declaran porque las claves foráneas de las tablas del comedor necesitan
resolver su destino, y porque el padrón de comensales se lee de `users` y
`personas`. Los tipos reproducen exactamente el DDL de bd_turnos.
"""

from datetime import date, datetime, time

from sqlalchemy import Date, DateTime, Integer, String, Text, Time
from sqlalchemy.dialects.mysql import BIGINT, TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# Las claves de bd_turnos son BIGINT UNSIGNED. Cualquier FK que las apunte
# debe usar el mismo tipo o MySQL rechaza la restricción.
ID = BIGINT(unsigned=True)

HEREDADA = {"info": {"heredada": True}}


class Categoria(Base):
    __tablename__ = "categorias"
    __table_args__ = HEREDADA

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(255))
    nivel: Mapped[int] = mapped_column(Integer)
    descripcion: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class Servicio(Base):
    __tablename__ = "servicios"
    __table_args__ = HEREDADA

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(255))
    descripcion: Mapped[str | None] = mapped_column(Text)
    cantidad_pacientes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class Usuario(Base):
    """Tabla `users`. Su `name` es un nombre de acceso, no sirve para reportes:
    el nombre real del comensal está en `Persona.nombre_completo`."""

    __tablename__ = "users"
    __table_args__ = HEREDADA

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    password: Mapped[str] = mapped_column(String(255))
    categoria_id: Mapped[int] = mapped_column(ID)
    remember_token: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    must_change_password: Mapped[bool] = mapped_column(TINYINT(1))


class Persona(Base):
    """Ficha real del comensal: de aquí salen nombre y carnet para los informes."""

    __tablename__ = "personas"
    __table_args__ = HEREDADA

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    nombre_completo: Mapped[str] = mapped_column(String(100))
    carnet_identidad: Mapped[str] = mapped_column(String(100), unique=True)
    fecha_nacimiento: Mapped[date | None] = mapped_column(Date)
    genero: Mapped[str] = mapped_column(String(20))
    telefono: Mapped[str] = mapped_column(String(22))
    direccion: Mapped[str] = mapped_column(String(150))
    tipo_trabajador: Mapped[str | None] = mapped_column(String(30))
    nacionalidad: Mapped[str] = mapped_column(String(150))
    tipo_salario: Mapped[str] = mapped_column(String(20))
    numero_tipo_salario: Mapped[str] = mapped_column(String(30))
    fecha_ingreso_institucion: Mapped[date | None] = mapped_column(Date)
    user_id: Mapped[int] = mapped_column(ID)
    created_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class Comida(Base):
    """Los cuatro tiempos de comida, tal como los define el módulo de turnos.

    Tabla heredada de solo lectura: este sistema no le agrega columnas. El
    orden cronológico sale del propio `id` (1 Desayuno, 2 Almuerzo, 3 Té,
    4 Cena) y el coeficiente vive en `coeficientes_racion.comida_id`.
    """

    __tablename__ = "comidas"
    __table_args__ = HEREDADA

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(255))
    codigo: Mapped[str] = mapped_column(String(255), unique=True)
    estado: Mapped[bool] = mapped_column(TINYINT(1))
    created_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class UsuarioServicio(Base):
    """A qué sala del hospital está asignada cada persona.

    Ojo con el vocabulario: `servicios` aquí es la sala (Pediatría, Emergencias),
    NO la categoría "Servicio" del formulario de Estadística.
    """

    __tablename__ = "usuario_servicios"
    __table_args__ = HEREDADA

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ID)
    servicio_id: Mapped[int] = mapped_column(ID)
    descripcion_usuario_servicio: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[bool] = mapped_column(TINYINT(1))
    fecha_ingreso: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class Turno(Base):
    __tablename__ = "turnos"
    __table_args__ = HEREDADA

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    nombre_turno: Mapped[str] = mapped_column(String(255))
    hora_inicio: Mapped[time] = mapped_column(Time)
    hora_fin: Mapped[time] = mapped_column(Time)
    duracion_horas: Mapped[int] = mapped_column(Integer)
    categoria_id: Mapped[int] = mapped_column(ID)
    created_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class TurnoComida(Base):
    """De aquí sale el derecho a comer. `dia_relativo` resuelve las guardias
    largas: 0 = comida del mismo día, 1 = del día siguiente."""

    __tablename__ = "turno_comida"
    __table_args__ = HEREDADA

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    turno_id: Mapped[int] = mapped_column(ID)
    comida_id: Mapped[int] = mapped_column(ID)
    dia_relativo: Mapped[int] = mapped_column(TINYINT(unsigned=True))
    created_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class TurnoAsignado(Base):
    __tablename__ = "turnos_asignados"
    __table_args__ = HEREDADA

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ID)
    servicio_id: Mapped[int] = mapped_column(ID)
    area_id: Mapped[int | None] = mapped_column(ID)
    turno_id: Mapped[int] = mapped_column(ID)
    semana_id: Mapped[int] = mapped_column(ID)
    mes_id: Mapped[int] = mapped_column(ID)
    gestion_id: Mapped[int] = mapped_column(ID)
    fecha: Mapped[date] = mapped_column(Date)
    estado: Mapped[str] = mapped_column(String(50))
    es_intercambio: Mapped[bool] = mapped_column(TINYINT(1))
    observacion: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class NovedadLaboral(Base):
    """Permisos, bajas y cambios de turno. Se consulta, nunca se escribe.

    Un permiso, una baja médica, una vacación o una licencia anulan el derecho
    a comer de esa asignación. `devolucion_turno` es otra cosa —un cambio entre
    compañeros— y no anula nada por sí sola.
    """

    __tablename__ = "novedades_laborales"
    __table_args__ = HEREDADA

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    asignacion_id: Mapped[int] = mapped_column(ID)
    tipo_novedad: Mapped[str] = mapped_column(String(30))
    usuario_solicitante_id: Mapped[int] = mapped_column(ID)
    usuario_reemplazo_id: Mapped[int | None] = mapped_column(ID)
    fecha_original: Mapped[date] = mapped_column(Date)
    fecha_nueva: Mapped[date | None] = mapped_column(Date)
    con_devolucion: Mapped[bool] = mapped_column(TINYINT(1))
    documento_respaldo: Mapped[str | None] = mapped_column(String(255))
    observacion_detalle: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class Mes(Base):
    __tablename__ = "meses"
    __table_args__ = HEREDADA

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(255))
    numero_mes: Mapped[int] = mapped_column(Integer)
    gestion_id: Mapped[int] = mapped_column(ID)
    created_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class Gestion(Base):
    __tablename__ = "gestiones"
    __table_args__ = HEREDADA

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    # La columna en la base se llama "año", con eñe. El atributo de Python no
    # puede llevarla, así que se mapea explícitamente.
    anio: Mapped[int] = mapped_column("año", Integer)
    activo: Mapped[bool] = mapped_column(TINYINT(1))
    created_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)
