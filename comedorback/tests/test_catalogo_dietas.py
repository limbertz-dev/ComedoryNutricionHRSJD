"""El catálogo de dietas trabaja solo con los nombres oficiales.

Sin base de datos: se revisa el contrato publicado por la API y el armado de
una dieta con un objeto en memoria. Los datos son ficticios.
"""

from app.consultas.dietas import _formatear_dieta
from app.esquemas.pacientes import DietaOut
from app.main import app
from app.modelos.pacientes import TipoDieta

RUTAS_RETIRADAS = {
    ("/pacientes/dietas/alias", "get"),
    ("/pacientes/dietas/alias", "post"),
    ("/pacientes/dietas/alias/{id}", "put"),
    ("/pacientes/dietas/alias/{id}", "delete"),
    ("/pacientes/dietas/huerfanos", "get"),
}


def _rutas_publicadas() -> set[tuple[str, str]]:
    return {
        (ruta, metodo)
        for ruta, operaciones in app.openapi()["paths"].items()
        for metodo in operaciones
    }


def test_las_cinco_rutas_retiradas_no_se_publican():
    publicadas = _rutas_publicadas()

    assert RUTAS_RETIRADAS.isdisjoint(publicadas)
    # El catálogo sigue: listar, crear y editar dietas.
    assert {
        ("/pacientes/dietas", "get"),
        ("/pacientes/dietas", "post"),
        ("/pacientes/dietas/{id}", "put"),
    } <= publicadas


def test_la_dieta_se_publica_sin_sinonimos():
    npo = TipoDieta(
        id=12,
        codigo="npo",
        nombre="NPO (nada por via oral)",
        columna_informe_id=9,
        cuenta_racion=0,
        orden=12,
        activo=1,
    )

    dieta = DietaOut(**_formatear_dieta(npo, "OTROS"))

    assert "alias" not in DietaOut.model_fields
    assert "alias" not in dieta.model_dump()
    assert dieta.no_suma is True
    assert dieta.es_ayuno is True
    assert dieta.columna_libro == "OTROS"
