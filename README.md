# ComedoryNutricionHRSJD

Sistema de Comedor y Nutrición Hospitalaria, módulo Personal / Comensales: control del acceso del personal al comedor y los informes de raciones.

- `comedorback/`: API en FastAPI + SQLAlchemy + Alembic sobre MySQL. Marcaciones, cupos, historiales y reportes. Ver `comedorback/README.md`.
- `comedorfront/`: interfaz en React + Vite. Todas las pantallas consumen la API a través de `src/api.js`. Ver `comedorfront/README.md`.
- Base de datos: dos bases en el mismo MySQL. `bd_nutricion` es la propia (6 tablas + 9 vistas `v_*`); `bd_proyecto_backend`, la del módulo de turnos, se lee solo a través de esas vistas y nunca se escribe. Las vistas viven en la migración `comedorback/alembic/versions/0c294cd98c3a_vistas_contrato_turnos.py`; `bd_nutricion` se recrea desde cero con `scripts/recrear_bd_limpia.py`. Los volcados `*.sql`, `*.xlsx` y `*.csv` con datos del hospital nunca se versionan (ver `.gitignore`).

## Flujo de ramas

- `feature/*` y `fix/*` se mergean a `develop` (integración diaria, `--no-ff`).
- `develop` se mergea a `qa` cuando está verde; `qa` es de Limbert (pruebas y control de calidad; fixes `fix/qa-*` vuelven también a `develop`).
- `main` solo recibe merges desde `qa`, con aprobación explícita de Limbert. Nadie mergea directo a `main`.
- Demo congelada en el tag `demo-2026-09-24`; respaldo de main en `respaldo/main-2026-09-24`.
