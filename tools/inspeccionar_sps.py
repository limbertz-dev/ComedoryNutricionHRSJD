import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(BASE_DIR, "comedorback")
sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text
from app.core.db_sih import motor_sih

def main():
    engine = motor_sih()
    with engine.connect() as conn:
        sps = ['sp_ORATENDET_abm', 'sp_ORATENCAB_abm', 'sp_cama_cambio', 'sp_cama_abm']
        for sp in sps:
            try:
                definition = conn.execute(text(f"SELECT OBJECT_DEFINITION(OBJECT_ID('{sp}'))")).scalar_one()
                print(f"==================================================")
                print(f"=== PROCEDIMIENTO: {sp} ===")
                print(f"==================================================")
                print(definition)
            except Exception as e:
                print(f"Error en {sp}: {e}")

if __name__ == "__main__":
    main()
