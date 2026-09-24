"""Lo que este sistema lee del módulo de turnos, mapeado sobre las vistas v_*.

SOLO LECTURA. Ninguna clase de este archivo apunta a una tabla: todas apuntan
a una vista de `bd_nutricion` que a su vez lee `bd_proyecto_backend` (ver
alembic/versions/0c294cd98c3a_vistas_contrato_turnos.py). Si el otro
ingeniero renombra una columna, se corrige la vista y este archivo no cambia.

Heredan de `BaseContrato`, no de `Base`: viven en otra metadata para que
alembic no las confunda con tablas por crear.

Las vistas no tienen clave primaria real. La que se declara acá es la clave
lógica de cada fila y solo le sirve al ORM para identificarla; nunca se
escribe nada a través de estas clases.
"""

from datetime import date, time

from sqlalchemy import Date, Integer, String, Text, Time
from sqlalchemy.dialects.mysql import BIGINT, TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import BaseContrato

# Las claves de bd_proyecto_backend son BIGINT UNSIGNED.
ID = BIGINT(unsigned=True)


class Comensal(BaseContrato):
    """`v_comensales`: el padrón. Una fila por `users.id`, siempre.

    Reemplaza el viejo `users JOIN personas`: el eje es users.id, el JOIN a
    personas y categorias es LEFT (un usuario sin ficha aparece con
    `tiene_ficha = 0` en vez de desaparecer), se toma una sola ficha por
    usuario (la de menor id) y el nombre llega con los espacios ya limpiados.
    El nombre sale de personas.nombre_completo, nunca de users.name.
    """

    __tablename__ = "v_comensales"

    usuario_id: Mapped[int] = mapped_column(ID, primary_key=True)
    nombre_completo: Mapped[str | None] = mapped_column(String(100))
    carnet_identidad: Mapped[str | None] = mapped_column(String(100))
    tipo_trabajador: Mapped[str | None] = mapped_column(String(30))
    numero_item: Mapped[str | None] = mapped_column(
        String(30), comment="personas.numero_tipo_salario: el ítem de planilla."
    )
    categoria_id: Mapped[int | None] = mapped_column(ID)
    categoria: Mapped[str | None] = mapped_column(String(255))
    categoria_nivel: Mapped[int | None] = mapped_column(Integer)
    tiene_ficha: Mapped[bool] = mapped_column(TINYINT(1))


class Categoria(BaseContrato):
    """`v_categorias`: las 15 categorías reales del hospital."""

    __tablename__ = "v_categorias"

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(255))
    nivel: Mapped[int] = mapped_column(Integer)
    descripcion: Mapped[str | None] = mapped_column(String(255))


class Servicio(BaseContrato):
    """`v_servicios`. Ojo: `servicios` es la SALA del hospital (Pediatría,
    Emergencias), NO la categoría "Servicio" del formulario de Estadística."""

    __tablename__ = "v_servicios"

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(255))
    descripcion: Mapped[str | None] = mapped_column(Text)
    cantidad_pacientes: Mapped[int] = mapped_column(Integer)


class Comida(BaseContrato):
    """`v_comidas`: los tiempos de comida tal como los define el módulo de turnos.

    No se le agrega nada: el orden cronológico sale del propio `id`
    (1 Desayuno, 2 Almuerzo, 3 Té, 4 Cena), el coeficiente vive en
    `coeficientes_racion.comida_id` y el horario en `horarios_comida`.
    """

    __tablename__ = "v_comidas"

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(255))
    codigo: Mapped[str] = mapped_column(String(255))
    estado: Mapped[bool] = mapped_column(TINYINT(1))


class UsuarioServicio(BaseContrato):
    """`v_usuario_servicios`: a qué sala está asignada cada persona."""

    __tablename__ = "v_usuario_servicios"

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ID)
    servicio_id: Mapped[int] = mapped_column(ID)
    estado: Mapped[bool] = mapped_column(TINYINT(1))
    fecha_ingreso: Mapped[date] = mapped_column(Date)


class TurnoAsignado(BaseContrato):
    """`v_turnos_asignados`: la asignación con su turno ya resuelto.

    `duracion_horas` es el dato que declara el hospital; no se calcula de
    hora_inicio/hora_fin porque en los turnos largos no coinciden.
    """

    __tablename__ = "v_turnos_asignados"

    id: Mapped[int] = mapped_column("turno_asignado_id", ID, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ID)
    servicio_id: Mapped[int] = mapped_column(ID)
    area_id: Mapped[int | None] = mapped_column(ID)
    fecha: Mapped[date] = mapped_column(Date)
    estado: Mapped[str] = mapped_column(String(50))
    es_intercambio: Mapped[bool] = mapped_column(TINYINT(1))
    turno_id: Mapped[int] = mapped_column(ID)
    turno: Mapped[str] = mapped_column(String(255))
    hora_inicio: Mapped[time] = mapped_column(Time)
    hora_fin: Mapped[time] = mapped_column(Time)
    duracion_horas: Mapped[int] = mapped_column(Integer)
    turno_categoria_id: Mapped[int] = mapped_column(ID)


class TurnoComida(BaseContrato):
    """`v_turno_comida`. `dia_relativo`: 0 = comida del mismo día del turno,
    1 = del día siguiente (guardias largas)."""

    __tablename__ = "v_turno_comida"

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    turno_id: Mapped[int] = mapped_column(ID)
    comida_id: Mapped[int] = mapped_column(ID)
    dia_relativo: Mapped[int] = mapped_column(TINYINT(unsigned=True))


class NovedadLaboral(BaseContrato):
    """`v_novedades_laborales`: permisos, bajas y cambios de turno.

    Un permiso, una baja médica, una vacación o una licencia anulan el derecho
    a comer de esa asignación. `devolucion_turno` es un cambio entre
    compañeros y no anula nada por sí sola. La regla vive en derecho.py.
    """

    __tablename__ = "v_novedades_laborales"

    id: Mapped[int] = mapped_column(ID, primary_key=True)
    asignacion_id: Mapped[int] = mapped_column(ID)
    tipo_novedad: Mapped[str] = mapped_column(String(30))
    usuario_solicitante_id: Mapped[int] = mapped_column(ID)
    usuario_reemplazo_id: Mapped[int | None] = mapped_column(ID)
    fecha_original: Mapped[date] = mapped_column(Date)
    fecha_nueva: Mapped[date | None] = mapped_column(Date)
    con_devolucion: Mapped[bool] = mapped_column(TINYINT(1))


class ComidaPorTurno(BaseContrato):
    """`v_comidas_por_turno`: el cruce que da origen al derecho, SIN reglas.

        fecha_comida = turnos_asignados.fecha + turno_comida.dia_relativo

    Una fila por (asignación, comida). La vista no filtra por duración ni por
    novedades: eso lo decide `aplicar_reglas()` en app/consultas/derecho.py,
    que es el punto único de la política.
    """

    __tablename__ = "v_comidas_por_turno"

    turno_asignado_id: Mapped[int] = mapped_column(ID, primary_key=True)
    comida_id: Mapped[int] = mapped_column(ID, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ID)
    servicio_id: Mapped[int] = mapped_column(ID)
    fecha_turno: Mapped[date] = mapped_column(Date)
    dia_relativo: Mapped[int] = mapped_column(TINYINT(unsigned=True))
    fecha_comida: Mapped[date] = mapped_column(Date)
    comida: Mapped[str] = mapped_column(String(255))
    turno_id: Mapped[int] = mapped_column(ID)
    turno: Mapped[str] = mapped_column(String(255))
    duracion_horas: Mapped[int] = mapped_column(Integer)
    categoria_id: Mapped[int | None] = mapped_column(ID)
    categoria: Mapped[str | None] = mapped_column(String(255))
