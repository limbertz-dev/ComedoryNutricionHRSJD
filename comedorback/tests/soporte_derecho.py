"""Ayudas compartidas sobre el derecho: elegir un comensal real con derecho
al almuerzo en la base de turnos (solo SELECT)."""

from datetime import date

import pytest
from sqlalchemy import bindparam, select, text

from app.consultas.derecho import aplicar_reglas
from app.core.config import config
from app.core.db import SesionLocal
from app.modelos.heredados import Comida, ComidaPorTurno

DIA_PREFERIDO = date(2026, 9, 24)


def candidato_almuerzo() -> tuple[int, date]:
    """Alguien con derecho al almuerzo según las reglas y con la asignación en
    estado 'programado' en la base de turnos (solo SELECT). Prefiere el
    24/09 si la base lo tiene."""
    with SesionLocal() as sesion:
        almuerzo = sesion.execute(
            select(Comida.id).where(Comida.codigo == "almuerzo")
        ).scalar_one()
        filas = sesion.execute(
            aplicar_reglas(
                select(
                    ComidaPorTurno.usuario_id,
                    ComidaPorTurno.fecha_comida,
                    ComidaPorTurno.turno_asignado_id,
                ).where(ComidaPorTurno.comida_id == almuerzo)
            )
        ).all()
        programados = set(
            sesion.execute(
                text(
                    f"SELECT id FROM `{config.db_name_turnos}`.turnos_asignados "
                    "WHERE estado = 'programado' AND id IN :ids"
                ).bindparams(bindparam("ids", expanding=True)),
                {"ids": [f.turno_asignado_id for f in filas] or [0]},
            ).scalars()
        )
    candidatos = sorted(
        ((f.fecha_comida == DIA_PREFERIDO, f.fecha_comida, f.usuario_id)
         for f in filas if f.turno_asignado_id in programados),
        reverse=True,
    )
    if not candidatos:
        pytest.skip("la base de turnos no tiene ningún almuerzo programado con derecho")
    _, fecha, usuario_id = candidatos[0]
    return usuario_id, fecha
