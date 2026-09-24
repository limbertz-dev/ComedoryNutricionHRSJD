# Comedor y Nutrición Hospitalaria

React (frontend) + FastAPI con SQLAlchemy (backend) + MySQL. Sin Docker.
Corre en un servidor del hospital, solo red local.

## Comandos
- Levantar backend: `cd comedorback; .\.venv\Scripts\uvicorn.exe app.main:app --reload --port 8000`
- Levantar frontend: `cd comedorfront; npm run dev`
- Tests frontend: `cd comedorfront; npm test`
- Build frontend: `cd comedorfront; npm run build`

## Reglas
- IMPORTANTE: no inventar datos, cifras, horarios ni reglas de negocio.
  Si algo figura como PENDIENTE en docs/, preguntar.
- Datos de prueba ficticios; nunca nombres ni historias clínicas reales.
- Textos de la interfaz en español.
- Si la tarea es de un módulo, no modificar el otro sin avisar.
- Contexto del módulo de pacientes: docs/contexto-modulo-pacientes-dietas.md
