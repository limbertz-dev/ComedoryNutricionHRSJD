import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(BASE_DIR, "comedorback")
sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text
from app.core.db_sih import motor_sih

def main():
    engine = motor_sih()
    if not engine:
        print("Error: No se pudo inicializar motor_sih")
        return

    with engine.connect() as conn:
        print("=== 1. MOTOR Y USUARIO ===")
        version = conn.execute(text("SELECT @@VERSION AS ver")).scalar_one()
        print("Version:", version.strip().split('\n')[0])
        
        db_name = conn.execute(text("SELECT DB_NAME()")).scalar_one()
        current_user = conn.execute(text("SELECT SUSER_NAME() AS suser, CURRENT_USER AS dbuser, IS_SRVROLEMEMBER('sysadmin') AS is_sysadmin")).mappings().one()
        print(f"Base: {db_name}, Usuario server: {current_user['suser']}, Usuario DB: {current_user['dbuser']}, is_sysadmin: {current_user['is_sysadmin']}")

        print("\n=== PERMISOS EFECTIVOS (fn_my_permissions) ===")
        perms = conn.execute(text("SELECT * FROM fn_my_permissions(NULL, 'DATABASE')")).mappings().all()
        perm_names = [p['permission_name'] for p in perms]
        print(f"Total permisos en BD: {len(perm_names)}")
        if 'CONTROL' in perm_names or current_user['is_sysadmin']:
            print("AVISO CRITICO: El usuario de conexion tiene privilegios de CONTROL/sysadmin (sa). NO es un usuario de solo lectura a nivel de base de datos. Se debe ser extremadamente cuidadoso con las consultas.")

        print("\n=== 2. TABLAS Y VISTAS RELEVANTES ===")
        keywords = [
            'ORATEN', 'INTERN', 'ALTA', 'EGRE', 'CAMA', 'SALA', 'TRASLAD', 
            'MOV', 'ORDEN', 'MEDIC', 'INDIC', 'EPICRIS', 'EVOLUC', 'LOG', 
            'AUDIT', 'HIST', 'CENSO', 'PACIENTE', 'SE_'
        ]
        
        tables = conn.execute(text("""
            SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
            FROM INFORMATION_SCHEMA.TABLES
            ORDER BY TABLE_TYPE, TABLE_NAME
        """)).mappings().all()
        
        matched_tables = []
        for t in tables:
            tname = t['TABLE_NAME'].upper()
            if any(k in tname for k in keywords):
                matched_tables.append(t)
                
        print(f"Total tablas/vistas encontradas con palabras clave: {len(matched_tables)} de {len(tables)} totales.")
        for mt in matched_tables:
            print(f"[{mt['TABLE_TYPE']}] {mt['TABLE_SCHEMA']}.{mt['TABLE_NAME']}")

        print("\n=== 3. VISTA ListaInternados DEFINICION ===")
        try:
            view_def = conn.execute(text("SELECT OBJECT_DEFINITION(OBJECT_ID('dbo.ListaInternados'))")).scalar_one()
            print("Definicion de dbo.ListaInternados:")
            print(view_def)
        except Exception as e:
            print("Error al leer definicion de ListaInternados:", e)

if __name__ == "__main__":
    main()
