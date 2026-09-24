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
        print("=== TODAS LAS COLUMNAS DE FECHA/HORA EN TABLAS BASE ===")
        date_cols = conn.execute(text("""
            SELECT c.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE
            FROM INFORMATION_SCHEMA.COLUMNS c
            JOIN INFORMATION_SCHEMA.TABLES t ON c.TABLE_NAME = t.TABLE_NAME AND c.TABLE_SCHEMA = t.TABLE_SCHEMA
            WHERE t.TABLE_TYPE = 'BASE TABLE'
              AND c.DATA_TYPE IN ('datetime', 'date', 'time', 'datetime2', 'smalldatetime', 'timestamp')
            ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION
        """)).mappings().all()
        
        current_table = None
        for dc in date_cols:
            if dc['TABLE_NAME'] != current_table:
                current_table = dc['TABLE_NAME']
                print(f"\n{current_table}:")
            print(f"  - {dc['COLUMN_NAME']} ({dc['DATA_TYPE']})")

if __name__ == "__main__":
    main()
