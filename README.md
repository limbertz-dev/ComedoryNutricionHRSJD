# ComedoryNutricionHRSJD

Sistema de Comedor y Nutrición Hospitalaria, módulo Personal / Comensales: control del acceso del personal al comedor y los informes de raciones.

- `comedorback/`: API en FastAPI + SQLAlchemy + Alembic sobre MySQL. Marcaciones, cupos, historiales y reportes. Ver `comedorback/README.md`.
- `comedorfront/`: interfaz en React + Vite. Todas las pantallas consumen la API a través de `src/api.js`. Ver `comedorfront/README.md`.
- Base de datos: dos bases en el mismo MySQL. `bd_nutricion` es la propia (8 tablas + 9 vistas `v_*`); `bd_proyecto_backend`, la del módulo de turnos, se lee solo a través de esas vistas y nunca se escribe. Las vistas viven en la migración `comedorback/alembic/versions/0c294cd98c3a_vistas_contrato_turnos.py`; `bd_nutricion` se recrea desde cero con `scripts/recrear_bd_limpia.py`. Los volcados `*.sql`, `*.xlsx` y `*.csv` con datos del hospital nunca se versionan (ver `.gitignore`).
- Simulación: `scripts/preparar_simulacion.py` clona la base de turnos en `bd_turnos_demo` y arma `bd_nutricion_sim` sobre la copia, sin escribir nunca en `bd_proyecto_backend` (ver su docstring).

## Flujo de ramas

- `feature/*` y `fix/*` se mergean a `develop` (integración diaria, `--no-ff`).
- `develop` pasa a `qa` cuando está verde (pytest, `npm test` y `npm run build`); `qa` es de Limbert (pruebas y control de calidad; fixes `fix/qa-*` vuelven también a `develop`).
- `qa` avanza solo por fast-forward: `git fetch . develop:qa`, que se niega si no lo es. Nunca merge ni force.
- `main` solo recibe merges desde `qa`, con aprobación explícita de Limbert. Nadie mergea directo a `main`.
- Demo congelada en el tag `demo-2026-09-24`; respaldo de main en `respaldo/main-2026-09-24`.

## Modo simulación (runbook de la demo)

La demo corre sobre copias: `bd_turnos_demo` (clon de `bd_proyecto_backend`) y `bd_nutricion_sim`. `bd_nutricion` y `bd_proyecto_backend` no se tocan, y la API normal (8000 / 5173) puede seguir corriendo al lado. Todo en PowerShell; usar una terminal aparte, porque las variables `$env:` quedan puestas en esa sesión.

0. **`.env`** (una vez por clon o worktree): los scripts y la API leen las credenciales de MySQL de `comedorback/.env`, que no se versiona. En un clon o worktree nuevo no existe y nada arranca sin él:

   ```powershell
   Copy-Item comedorback\.env.example comedorback\.env
   ```

   Completar `DB_PASSWORD` y dejar `DB_NAME` / `DB_NAME_TURNOS` con las bases reales: `preparar_simulacion.py` lee de ahí cuál es el original, y las bases de simulación se eligen con `$env:` en el paso 2 (las variables de entorno pisan al `.env`).

1. **Bases** (desde la raíz; destructivo solo para `*_demo` y `*_sim`):

   ```powershell
   comedorback\.venv\Scripts\python scripts\preparar_simulacion.py --si
   ```

   Parámetros fijos: `--semana-origen 2026-08-03 --dias 49` (son los valores por defecto): la semana del 03/08/2026 pasa al 21-27/09/2026. El escenario de `scripts/demo_reloj.py` depende de ellos. El script corre alembic y la semilla general (horarios, coeficientes, mapeo de categorías) sobre `bd_nutricion_sim`, y verifica con CHECKSUM que el original no cambió.

2. **Entorno de simulación** (en `comedorback/`). `ENTORNO=simulacion` monta `/simulacion/*` y solo arranca con `DB_NAME=*_sim` y `DB_NAME_TURNOS=*_demo`; con las bases reales la configuración se niega a cargar. Fuera de `desarrollo`, `AUTH_JWT_SECRETO` es obligatorio (32+ caracteres):

   ```powershell
   cd comedorback
   $env:ENTORNO = 'simulacion'
   $env:DB_NAME = 'bd_nutricion_sim'
   $env:DB_NAME_TURNOS = 'bd_turnos_demo'
   $env:AUTH_JWT_SECRETO = (.venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(48))")
   $env:ORIGENES_PERMITIDOS = 'http://localhost:5174,http://127.0.0.1:5174'
   ```

3. **Cuentas** (misma terminal). `preparar_simulacion.py` no crea cuentas: se dan de alta con clave temporal, que se muestra una sola vez y se cambia en el primer ingreso:

   ```powershell
   .venv\Scripts\python -m app.semillas.admin --username jefa --rol jefa
   .venv\Scripts\python -m app.semillas.admin --username cocinera --rol cocinera
   ```

4. **Verificación** (opcional, desde la raíz): `comedorback\.venv\Scripts\python scripts\demo_reloj.py` fija el reloj al 24/09 12:30, marca el almuerzo del usuario 2040, limpia lo que creó y compara el CHECKSUM del original antes y después.

5. **API**, con UN solo worker: el reloj simulado vive en la memoria del proceso y con varios workers cada uno tendría el suyo:

   ```powershell
   .venv\Scripts\python -m uvicorn app.main:app --port 8001 --workers 1
   ```

   `GET /salud` tiene que responder `"entorno": "simulacion"`.

6. **Front**, en otra terminal, apuntado a esa API con `VITE_API_URL`:

   ```powershell
   cd comedorfront
   $env:VITE_API_URL = 'http://127.0.0.1:8001'
   npm.cmd run dev -- --port 5174
   ```

   El header muestra la franja SIMULACIÓN; jefa y sistemas mueven el reloj desde Control Biométrico (ver `comedorfront/README.md`).

7. **Historial** (opcional, desde la raíz, con la API del paso 5 corriendo): `scripts/cargar_historial_sim.py` llena los días previos a la demo marcando POR LA API, como jefa y con método manual, así que valen las reglas de siempre (horario, duplicado, derecho). Por defecto marca el 80 % de los candidatos con derecho de cada día del 21 al 23/09, elegidos y fechados de forma determinista (misma base, mismos parámetros, mismas filas):

   ```powershell
   comedorback\.venv\Scripts\python scripts\cargar_historial_sim.py --api http://127.0.0.1:8001
   ```

   - `--api` hace falta: el valor por defecto del script es `8100`, no el `8001` de este runbook. Antes de marcar verifica con `/salud` que la API apunte a `bd_nutricion_sim` / `bd_turnos_demo`.
   - La cuenta (`--usuario`, por defecto `jefa`) tiene que ser de jefatura y ya tener cambiada la clave temporal en el front (paso 6): un 428 aborta. La clave se pide por consola o se lee de `CARGA_HISTORIAL_CLAVE`; ni ella ni el token se imprimen.
   - Nunca toca la demo en vivo (24-27/09) y se niega si el rango ya tiene raciones: para volver a cargarlo hay que regenerar con el paso 1, que borra todo lo marcado en la simulación.
   - Otros parámetros: `--porcentaje`, `--desde`, `--hasta`, `--solo-programados` (ver su docstring). Termina comparando el CHECKSUM de `bd_proyecto_backend` antes y después.

Para salir: "volver a la hora real" en el front (o `DELETE /simulacion/reloj`), o cerrar la API; al reiniciar vuelve sola a la hora real.
