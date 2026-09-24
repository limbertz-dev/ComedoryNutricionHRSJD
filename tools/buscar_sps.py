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
        print("=== PROCEDIMIENTOS ALMACENADOS QUE USAN SE_ORATENDET ===")
        sps = conn.execute(text("""
            SELECT DISTINCT o.name
            FROM sys.sql_modules m
            JOIN sys.objects o ON m.object_id = o.object_id
            WHERE m.definition LIKE '%SE_ORATENDET%'
              AND o.type_desc = 'SQL_STORED_PROCEDURE'
            ORDER BY o.name
        """)).scalars().all()
        print(f"Total SPs: {len(sps)}")
        for sp in sps:
            print(" -", sp)

        # Buscar SPs con nombres relacionados a alta, egreso, traspaso, cama
        keywords = ['ALTA', 'EGRE', 'TRAS', 'CAMA', 'ORATEN', 'INTERN']
        relevant_sps = [sp for sp in sps if any(k in sp.upper() for k in keywords)]
        print(f"\nSPs relevantes ({len(relevant_sps)}):", relevant_sps)

if __name__ == "__main__":
    main()
