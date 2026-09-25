"""Corre al final (por el nombre): revisa TODO el SQL que se ejecutó en la
sesión de tests, alembic incluido, y exige cero escrituras sobre la base de
turnos, sus tablas heredadas o las vistas del contrato."""

import re

from app.core.config import config
from app.core.tablas_heredadas import TABLAS_HEREDADAS, VISTAS_CONTRATO, VISTAS_HEREDADAS
from conftest import SENTENCIAS

ESCRITURA = re.compile(
    r"^\s*(?:INSERT\s+(?:IGNORE\s+)?INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM|"
    r"ALTER\s+TABLE|DROP\s+TABLE(?:\s+IF\s+EXISTS)?|CREATE\s+TABLE|TRUNCATE(?:\s+TABLE)?)"
    r"\s+(?:`?(\w+)`?\.)?`?(\w+)`?",
    re.IGNORECASE,
)
PROHIBIDAS = TABLAS_HEREDADAS | VISTAS_HEREDADAS | set(VISTAS_CONTRATO)


def test_cero_escrituras_a_heredadas():
    assert SENTENCIAS, "no se registró ninguna sentencia: el listener no está activo"
    escrituras = [m for s in SENTENCIAS if (m := ESCRITURA.match(s))]
    assert escrituras, "el patrón no reconoce ni las escrituras propias"

    ajenas = [
        m.group(0)
        for m in escrituras
        if (m.group(1) or "").lower() == config.db_name_turnos.lower()
        or m.group(2).lower() in PROHIBIDAS
    ]
    assert ajenas == []
