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
        print("=== 1. TRIGGERS EN SE_ORATENCAB, SE_ORATENDET, SE_CAMA ===")
        triggers = conn.execute(text("""
            SELECT t.name AS trigger_name, o.name AS table_name, t.is_disabled
            FROM sys.triggers t
            JOIN sys.objects o ON t.parent_id = o.object_id
            WHERE o.name IN ('SE_ORATENCAB', 'SE_ORATENDET', 'SE_CAMA', 'se_epicrisis')
        """)).mappings().all()
        for tr in triggers:
            print(f"Trigger {tr['trigger_name']} en {tr['table_name']} (deshabilitado: {tr['is_disabled']})")
            tdef = conn.execute(text(f"SELECT OBJECT_DEFINITION(OBJECT_ID('{tr['trigger_name']}'))")).scalar_one()
            print(f"Definicion:\n{tdef}\n")

        print("\n=== 2. TABLA AUDITORIA: ESTRUCTURA Y TIPO DE REGISTROS ===")
        # Ver qué tipo de texto guarda AUDITORIA (solo formato/metadatos, sin mostrar datos personales)
        # Ojo: no seleccionar datos de pacientes.
        audit_sample = conn.execute(text("""
            SELECT TOP 5 AU_FECHA, 
                   LEN(AU_TEXTO) as len_texto,
                   SUBSTRING(AU_TEXTO, 1, 60) as preview
            FROM dbo.AUDITORIA
            ORDER BY AU_FECHA DESC
        """)).mappings().all()
        for a in audit_sample:
            print(f"Fecha: {a['AU_FECHA']}, Len: {a['len_texto']}, Preview: {a['preview']}")

        print("\n=== 3. OTRAS TABLAS MEDICAS/ENFERMERIA/INDICACIONES ===")
        all_tables = conn.execute(text("""
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
        """)).scalars().all()
        
        medical_kws = ['ORD', 'INDIC', 'EVOL', 'EPIC', 'RECET', 'ENF', 'DIETA', 'NUTRI', 'TRAT']
        matched = [t for t in all_tables if any(k in t.upper() for k in medical_kws)]
        print("Tablas encontradas:", matched)

if __name__ == "__main__":
    main()
