# Backend — Sistema de Comedor y Nutrición Hospitalaria

FastAPI + SQLAlchemy + Alembic sobre MySQL. Python 3.13.

## Poner en marcha

```powershell
cd .\comedorback
.\.venv\Scripts\Activate.ps1        # entorno virtual
pip install -r requirements.txt     # solo la primera vez
copy .env.example .env              # y ajustar credenciales
uvicorn app.main:app --reload       # http://127.0.0.1:8000
```

Verificar que todo responde: `http://127.0.0.1:8000/salud`
Documentación automática de la API: `http://127.0.0.1:8000/docs`

## Bases de datos: dos bases, un solo servidor

| Base | Variable | Qué es | Se toca |
|---|---|---|---|
| `bd_nutricion` | `DB_NAME` | La base propia del comedor | Sí: la administra alembic |
| `bd_proyecto_backend` | `DB_NAME_TURNOS` | La base del módulo de turnos (otro ingeniero) | **Nunca**: ni ALTER, ni CREATE, ni INSERT, ni FK que le apunte |

`bd_nutricion` tiene exactamente **6 tablas + 9 vistas** (más `alembic_version`):

- **Tablas propias:** `categorias_reporte`, `categoria_reporte_map`,
  `horarios_comida`, `coeficientes_racion`, `lecturas_biometricas`, `asistencias`.
- **Vistas del contrato de lectura** (`SQL SECURITY INVOKER`, leen
  `bd_proyecto_backend`): `v_comensales`, `v_categorias`, `v_servicios`,
  `v_comidas`, `v_usuario_servicios`, `v_turnos_asignados`, `v_turno_comida`,
  `v_novedades_laborales`, `v_comidas_por_turno`.

### Estrategia de lectura entre bases

Las consultas leen la base de turnos **solo a través de las vistas `v_*`**, con
un único motor contra `bd_nutricion`. Se descartó el doble motor con `bind`
porque los informes y el historial cruzan `asistencias` con el padrón en un
mismo JOIN, y dos motores no pueden hacer eso en una sola consulta ni en una
sola transacción. Las vistas, además, son el único punto que conoce los nombres
de columnas del otro ingeniero: si él renombra algo, se redefine la vista en
una migración nueva y el resto del código no se entera. Se mapean en
`app/modelos/heredados.py` sobre una metadata aparte (`BaseContrato`), así que
alembic nunca las toma por tablas.

Las columnas propias que guardan un id de la base de turnos (`usuario_id`,
`comida_id`, `categoria_id`, `servicio_id`, `turno_asignado_id`,
`registrado_por`) son referencias **lógicas, sin FK**: una FK entre bases le
impediría al otro ingeniero borrar un usuario o migrar su propio esquema.

`v_comensales` entrega una fila por `users.id` (LEFT JOIN a `personas` y
`categorias`, `tiene_ficha = 0` si no hay ficha), toma la ficha de menor id si
hubiera duplicados y trae el nombre con los espacios ya limpiados.

### Receta limpia: recrear `bd_nutricion` desde cero

Desde la raíz del repositorio:

```powershell
comedorback\.venv\Scripts\python scripts\recrear_bd_limpia.py        # pide escribir el nombre de la base
comedorback\.venv\Scripts\python scripts\recrear_bd_limpia.py --si   # sin preguntar
```

Hace, en orden: guardas (`DB_NAME` no puede ser `DB_NAME_TURNOS` ni una base del
sistema, y la base de turnos tiene que existir) → `DROP DATABASE IF EXISTS` +
`CREATE DATABASE` (`utf8mb4_unicode_ci`) → `alembic upgrade head` (tablas,
columnas del formulario, vistas) → verificación de 6 tablas + 9 vistas → semilla.
Es idempotente. **Borra todo lo que tenga `bd_nutricion`, asistencias incluidas**;
sobre `bd_proyecto_backend` solo ejecuta los `SELECT` de las vistas.

`GET /salud` responde `"estado": "ok"` con `tablas_propias: 6`,
`vistas_contrato: 9` y la revisión de alembic, o **503** con la lista de lo que
falta. Solo mira objetos de `bd_nutricion`: no lee la base de turnos.

## Migraciones

```powershell
alembic upgrade head
alembic downgrade -1
alembic check                                   # modelos y base coinciden
alembic revision --autogenerate -m "descripción"
```

La cadena empieza en `4b5a9ed9330e` (nueva base) y hoy termina en
`0c294cd98c3a` (head):

| Revisión | Qué hace |
|---|---|
| `4b5a9ed9330e` | Las 6 tablas propias, sin FK hacia la base de turnos |
| `ff4ddf3c8a18` | Las 6 columnas del formulario de Estadística (`categorias_reporte`) |
| `0c294cd98c3a` | Las 9 vistas `v_*`; el nombre de la base de turnos sale de `DB_NAME_TURNOS` |

Reemplaza a la cadena vieja `fa64a5d4e912 → … → f6a7b8c9d0e1`, que asumía las
tablas heredadas copiadas en la misma base y le agregaba columnas a `comidas`.
Una base creada con esa cadena no se migra: se recrea con la receta de arriba.

`alembic/env.py` sigue excluyendo de la comparación las 36 tablas heredadas
(`app/core/tablas_heredadas.py`) y también las vistas `v_*`, que el autogenerate
no entiende y se administran a mano en su migración.

## Carga inicial (semilla)

La corre la receta; a mano, después de `alembic upgrade head`:

```powershell
python -m app.semillas     # las tres, idempotentes
```

| Semilla | Qué carga |
|---|---|
| `app.semillas.horarios` | Franjas horarias de cada comida. **Provisionales**: confirmar con la jefa de nutrición |
| `app.semillas.coeficientes` | Coeficientes de ración del formulario (0,15 · 0,50 · 0,05 · 0,30) |
| `app.semillas.mapeo_categorias` | Categoría del hospital → columna del formulario. Decisión del hospital, a confirmar |

Las columnas del formulario van en migración porque son datos 100 % propios e
impresos en el papel. Horarios, coeficientes y mapeo van en semilla porque
dependen de ids de la base de turnos (se resuelven por código o nombre a través
de las vistas) o de decisiones del hospital.

## Conexión con el front (CORS)

El front corre en un puerto distinto al de la API, así que para el navegador
son dos sitios diferentes y bloquea las peticiones salvo que la API declare
quién puede llamarla. Los orígenes permitidos se listan en `.env`:

```
ORIGENES_PERMITIDOS=http://localhost:5173,http://127.0.0.1:5173
```

Uno por uno, separados por comas, **nunca con `*`**: con comodín el navegador
rechaza las peticiones con credenciales, y eso rompería el login cuando exista.

Si abres el front por otra dirección —por ejemplo la IP de tu máquina en la red,
para probarlo desde un celular— hay que agregar ese origen exacto a la lista, o
el navegador lo bloquea aunque sea el mismo front. En producción va la dirección
real del servidor del hospital.

## Endpoints

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/salud` | Comprueba API y que `bd_nutricion` tenga sus 6 tablas y 9 vistas (503 si falta algo) |
| GET | `/pantalla/estado` | Todo lo que la pantalla en vivo necesita para pintarse |
| GET | `/pantalla/ultimas-marcaciones` | Hilo del lector, incluidos los rechazos |
| GET | `/personal` | Padrón paginado, con búsqueda y filtros |
| GET | `/personal/{usuario_id}` | Ficha de un comensal |
| GET | `/personal/{usuario_id}/derecho` | A qué comidas tiene derecho en una fecha |
| POST | `/asistencias` | Marcar una ración |
| GET | `/historial/diario` | Lista nominal de un día, con los 4 estados |
| GET | `/historial/mensual` | Resumen nominal del mes, persona por persona |
| GET | `/reportes/periodos` | Gestiones y meses para el selector |
| GET | `/reportes/registro-diario` | Planilla del mes, una fila por día |
| GET | `/reportes/mensual` | Formulario de Estadística, con coeficientes |
| GET | `/reportes/gestion` | Resumen anual, una fila por mes |
| GET | `/reportes/informe?desde=AAAA-MM-DD&hasta=AAAA-MM-DD` | Formulario de Estadística para un rango de fechas arbitrario (hoy, una semana, una quincena), con coeficientes. 422 si `desde > hasta` |

Los informes salen de la misma tabla, `asistencias`, con distinto
agrupamiento: el total del registro diario y el del informe mensual tienen que
dar exactamente igual, y `/reportes/informe` sobre el mes completo también. Cada uno devuelve además `sin_clasificar` y
`sin_coeficiente`, que miden lo que falta en vez de esconderlo.

`POST /asistencias` responde **200 tanto si acepta como si rechaza**: un rechazo
no es un error de la API, es una respuesta del negocio que el lector muestra en
pantalla. El campo `valido` lo distingue y `motivo` dice por qué.

El orden de las validaciones no es arbitrario: `fuera_horario` (necesidad
técnica: sin comida resuelta no se puede comprobar nada), luego `duplicado` y
después `sin_derecho`. En el registro manual se invierten los dos últimos.

### El derecho a comer

Una asignación de turno da derecho sólo si cumple **las tres** condiciones:

1. El turno dura **12 horas o más** (`turnos.duracion_horas`). Es política del
   hospital y descarta 49 de los 76 turnos cargados. Enfermería queda fuera.
2. El turno tiene comidas mapeadas en `turno_comida`.
3. No hay una novedad que lo anule (permiso, baja, vacación, licencia).

La primera **habilita**, la segunda **otorga**: son cosas distintas. Un turno de
12 horas sin filas en `turno_comida` sigue sin dar derecho, y es correcto.

Las tres viven en `aplicar_reglas()` de `app/consultas/derecho.py`, sobre
`v_comidas_por_turno`, que entrega el cruce sin reglas. Es el punto único por
el que pasan la marcación, la pantalla y los dos historiales. Si la política
cambia, se cambia ahí y los tres caminos quedan alineados.

## Estructura

```
app/
├─ main.py              aplicación FastAPI y endpoint /salud
├─ api/                 los endpoints
├─ consultas/           consultas de lectura (padrón, derecho)
├─ logica/              reglas del negocio (marcación)
├─ esquemas/            formas de entrada y salida
├─ modelos/
│  ├─ heredados.py      las 9 vistas v_* (base de turnos), SOLO LECTURA
│  └─ comedor.py        las 6 tablas propias
├─ semillas/            carga de datos iniciales (python -m app.semillas)
└─ core/
   ├─ config.py         configuración leída de .env (DB_NAME, DB_NAME_TURNOS)
   ├─ db.py             motor único, sesión, Base y BaseContrato
   └─ tablas_heredadas.py   lo que no administramos + la lista de vistas v_*
alembic/                migraciones (base 4b5a9ed9330e, head 0c294cd98c3a)
../scripts/recrear_bd_limpia.py   receta limpia de bd_nutricion
```
