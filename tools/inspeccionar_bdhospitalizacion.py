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
        tables_to_check = [
            'adm_altas', 'internacion', 'orden_internacion', 
            'indicacion', 'epicrisis', 'bitacora', 'auditoria',
            'cama_bloqueo', 'transferenciaD7b'
        ]
        print("=== COLUMNAS EN BDHOSPITALIZACION ===")
        for t in tables_to_check:
            try:
                cols = conn.execute(text(f"""
                    SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE
                    FROM bdhospitalizacion.INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_NAME = '{t}'
                    ORDER BY ORDINAL_POSITION
                """)).mappings().all()
                print(f"\n--- bdhospitalizacion.dbo.{t} ({len(cols)} columnas) ---")
                for c in cols:
                    maxlen = f"({c['CHARACTER_MAXIMUM_LENGTH']})" if c['CHARACTER_MAXIMUM_LENGTH'] else ""
                    print(f"  {c['COLUMN_NAME']}: {c['DATA_TYPE']}{maxlen} (null: {c['IS_NULLABLE']})")
            except Exception as e:
                print(f"Error en {t}: {e}")

if __name__ == "__main__":
    main()
