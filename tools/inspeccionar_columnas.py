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
        # 1. Definición de vistas de internación y altas
        views_to_check = [
            'se_internacion', 'se_internacion_SNIS', 'VCONALTA', 
            'VistaEgresosDiagnosticos', 'se_TIPOALTA', 'VTIPOALTA'
        ]
        print("=== DEFINICIONES DE VISTAS ===")
        for v in views_to_check:
            try:
                vdef = conn.execute(text(f"SELECT OBJECT_DEFINITION(OBJECT_ID('dbo.{v}'))")).scalar_one()
                print(f"\n--- Vista: dbo.{v} ---")
                print(vdef)
            except Exception as e:
                print(f"Error al leer dbo.{v}: {e}")

        # 2. Columnas de tablas clave
        tables_to_check = [
            'SE_ORATENCAB', 'SE_ORATENDET', 'se_oratendet_asoc', 
            'se_epicrisis', 'se_EstadoAperturaInternacion', 'AUDITORIA', 
            'SE_CAMA', 'SE_SALA', 'SE_SERVHOSP'
        ]
        print("\n=== COLUMNAS DE TABLAS CLAVE ===")
        for t in tables_to_check:
            cols = conn.execute(text(f"""
                SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_NAME = '{t}'
                ORDER BY ORDINAL_POSITION
            """)).mappings().all()
            print(f"\n--- Tabla: dbo.{t} ({len(cols)} columnas) ---")
            for c in cols:
                maxlen = f"({c['CHARACTER_MAXIMUM_LENGTH']})" if c['CHARACTER_MAXIMUM_LENGTH'] else ""
                print(f"  {c['COLUMN_NAME']}: {c['DATA_TYPE']}{maxlen} (null: {c['IS_NULLABLE']})")

if __name__ == "__main__":
    main()
