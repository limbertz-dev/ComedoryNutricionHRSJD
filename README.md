# ComedoryNutricionHRSJD

Sistema de Comedor y Nutrición Hospitalaria, módulo Personal / Comensales: control del acceso del personal al comedor y los informes de raciones.

- `comedorback/`: API en FastAPI + SQLAlchemy + Alembic sobre MySQL. Marcaciones, cupos, historiales y reportes. Ver `comedorback/README.md`.
- `comedorfront/`: interfaz en React + Vite. Todas las pantallas consumen la API a través de `src/api.js`. Ver `comedorfront/README.md`.
- Base de datos: dos bases en el mismo MySQL. `bd_nutricion` es la propia (16 tablas + 9 vistas `v_*`); `bd_proyecto_backend`, la del módulo de turnos, se lee solo a través de esas vistas y nunca se escribe. Las vistas viven en la migración `comedorback/alembic/versions/0c294cd98c3a_vistas_contrato_turnos.py`; `bd_nutricion` se recrea desde cero con `scripts/recrear_bd_limpia.py`. Los volcados `*.sql`, `*.xlsx` y `*.csv` con datos del hospital nunca se versionan (ver `.gitignore`).

## Desarrollo

Los cambios revisados se integran en `develop`. La publicacion requiere
autorizacion explicita y no forma parte del arranque local.

## Puesta en marcha

Todo en PowerShell.

0. **`.env`** (una vez por clon o worktree): la API y los scripts leen las credenciales de MySQL de `comedorback/.env`, que no se versiona:

   ```powershell
   Copy-Item comedorback\.env.example comedorback\.env
   ```

   Completar `DB_PASSWORD`, `DB_NAME` y `DB_NAME_TURNOS`. Fuera de `desarrollo`, `AUTH_JWT_SECRETO` es obligatorio (32+ caracteres).

1. **Base propia** (en `comedorback/`): `.venv\Scripts\python -m alembic upgrade head` y `.venv\Scripts\python -m app.semillas` (horarios, coeficientes y mapeo de categorías).

2. **Cuentas**: se dan de alta con clave temporal, que se muestra una sola vez y se cambia en el primer ingreso:

   ```powershell
   .venv\Scripts\python -m app.semillas.admin --username jefa --rol jefa
   .venv\Scripts\python -m app.semillas.admin --username cocinera --rol cocinera
   ```

3. **API**: `.venv\Scripts\python -m uvicorn app.main:app --port 8000`. `GET /salud` informa el entorno, las dos bases y la revisión de alembic.

4. **Front**, en otra terminal: `cd comedorfront` y `npm.cmd run dev` (ver `comedorfront/README.md`).
