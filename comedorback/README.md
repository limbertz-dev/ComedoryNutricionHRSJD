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

## Bases de datos

| Base | Qué es | Se toca |
|---|---|---|
| `bd_proyecto_backend` | La base viva del módulo de turnos | **Nunca** |
| `bd_comedor_dev` | Copia de `bd_turnos.sql` para desarrollar | Sí |

Para rehacer la copia de desarrollo desde cero:

```bash
mysql -h 127.0.0.1 -u root -e "DROP DATABASE IF EXISTS bd_comedor_dev; CREATE DATABASE bd_comedor_dev CHARACTER SET utf8mb4;"
sed '/^CREATE DATABASE /d; /^USE `/d' ../bd_turnos.sql | mysql -h 127.0.0.1 -u root bd_comedor_dev
```

El `sed` no es opcional: el dump trae `CREATE DATABASE` y `USE bd_proyecto_backend`
en las líneas 19-20, así que sin filtrarlas escribe sobre la base viva del hospital
aunque hayas seleccionado otra.

## Migraciones

```powershell
alembic revision --autogenerate -m "descripción"
alembic upgrade head
alembic downgrade -1
```

**Este sistema no administra las tablas del módulo de turnos.** Las 36 tablas
heredadas están listadas en `app/core/tablas_heredadas.py` y `alembic/env.py` las
excluye de la comparación. Sin ese filtro, el primer autogenerate emitiría un
`DROP TABLE` por cada una. Si agregas un modelo que mapea una tabla heredada,
márcalo con `__table_args__ = {"info": {"heredada": True}}`.

No hay excepciones: ni siquiera se les agrega una columna. Lo que este sistema
necesita saber de ellas vive en tablas propias que las referencian por FK —
por ejemplo el coeficiente de cada comida, en `coeficientes_racion.comida_id`.

## Carga inicial

Después de `alembic upgrade head`:

```powershell
python -m app.semillas.horarios   # franjas horarias de cada comida
```

Lo que **sí** va en migraciones, porque está impreso en el formulario y sin
ello el sistema no funciona: las 6 columnas del Servicio de Estadística y los
coeficientes de ración. Lo que va en scripts, porque toca decisiones del
hospital o escribe en tablas del otro ingeniero: los horarios —cuyos valores
son **provisionales** y hay que confirmar con la jefa de nutrición— y la
asignación de orden y grupo a `comidas`.

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
| GET | `/salud` | Comprueba API y base de datos |
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

Los tres informes salen de la misma tabla, `asistencias`, con distinto
agrupamiento: el total del registro diario y el del informe mensual tienen que
dar exactamente igual. Cada uno devuelve además `sin_clasificar` y
`sin_coeficiente`, que miden lo que falta en vez de esconderlo.

`POST /asistencias` responde **200 tanto si acepta como si rechaza**: un rechazo
no es un error de la API, es una respuesta del negocio que el lector muestra en
pantalla. El campo `valido` lo distingue y `motivo` dice por qué.

El orden de las validaciones no es arbitrario: `fuera_horario` (necesidad
técnica: sin comida resuelta no se puede comprobar nada), luego `duplicado`,
después `sin_derecho` y por último `sin_cupo`. Decirle "no hay raciones" a
alguien que ya comió genera un reclamo injusto en la cocina.

### El derecho a comer

Una asignación de turno da derecho sólo si cumple **las tres** condiciones:

1. El turno dura **12 horas o más** (`turnos.duracion_horas`). Es política del
   hospital y descarta 49 de los 76 turnos cargados.
2. El turno tiene comidas mapeadas en `turno_comida`.
3. No hay una novedad que lo anule (permiso, baja, vacación, licencia).

La primera **habilita**, la segunda **otorga**: son cosas distintas. Un turno de
12 horas sin filas en `turno_comida` sigue sin dar derecho, y es correcto.

Las tres viven en `aplicar_reglas()` de `app/consultas/derecho.py`, que es el
punto único por el que pasan la marcación y los dos historiales. Si la política
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
│  ├─ heredados.py      tablas del módulo de turnos, SOLO LECTURA
│  └─ comedor.py        las 11 tablas nuevas
├─ semillas/            carga de datos iniciales
└─ core/
   ├─ config.py         configuración leída de .env
   ├─ db.py             motor, sesión y base declarativa
   └─ tablas_heredadas.py   las 36 tablas que no administramos
alembic/                migraciones
```
