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

`bd_nutricion` tiene exactamente **8 tablas + 9 vistas** (más `alembic_version`):

- **Tablas propias:** `categorias_reporte`, `categoria_reporte_map`,
  `horarios_comida`, `coeficientes_racion`, `lecturas_biometricas`, `asistencias`.
- **Tablas de la autenticación:** `usuarios_sistema`, `intentos_login`
  (ver [Autenticación y roles](#autenticación-y-roles)).
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
`comida_id`, `categoria_id`, `servicio_id`, `turno_asignado_id`) son
referencias **lógicas, sin FK**: una FK entre bases le
impediría al otro ingeniero borrar un usuario o migrar su propio esquema. `registrado_por` queda como LEGACY (un `users.id`, NULL en filas nuevas): quién registra una ración manual sale del token y se guarda en `registrado_por_cuenta` (FK a `usuarios_sistema`), y el campo `registrado_por` del cuerpo del POST está deprecado y se ignora.

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
columnas del formulario, vistas) → verificación de las tablas propias + 9 vistas → semilla.
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
`b7c4d2e8f1a3` (head):

| Revisión | Qué hace |
|---|---|
| `4b5a9ed9330e` | Las 6 tablas propias, sin FK hacia la base de turnos |
| `ff4ddf3c8a18` | Las 6 columnas del formulario de Estadística (`categorias_reporte`) |
| `0c294cd98c3a` | Las 9 vistas `v_*`; el nombre de la base de turnos sale de `DB_NAME_TURNOS` |
| `7e2b9c4d1a60` | `usuarios_sistema` e `intentos_login` (autenticación) |
| `b7c4d2e8f1a3` | `asistencias.registrado_por_cuenta` (FK a `usuarios_sistema`, RESTRICT) y comentario LEGACY en `registrado_por` |

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

## Autenticación y roles

Cuentas **propias** del comedor en `usuarios_sistema` (no son los `users` de la
base de turnos, y no se les escribe nada allá). Dónde se validan las claves
está aislado en `verificar_credenciales()` (`app/logica/autenticacion.py`): si
mañana se valida contra el SIH o contra `users`, se cambia esa función y nada
más.

| Rol | Puede |
|---|---|
| `jefa` | Todo lo operativo: pantalla, padrón, historial, informes, marcación biométrica y manual |
| `cocinera` | Solo `GET /pantalla/*` y `POST /asistencias` con `metodo='biometrico'` |
| `sistemas` | Todo lo de la jefa, más administración de cuentas |

La matriz vive en `app/core/permisos.py` y se aplica router por router en
`app/main.py` con `requiere_rol(...)`. La regla "manual solo jefatura" depende
del cuerpo de la petición, así que la aplica `POST /asistencias`. Sin token
solo responden `/salud`, `/auth/login` y `/auth/refresh`.

Reglas:

- **Claves:** solo hash bcrypt. Mínimo 8 caracteres, máximo 72 bytes, distinta
  del usuario y de la anterior.
- **Bloqueo:** 5 fallidos seguidos dentro de 15 minutos bloquean la cuenta 15
  minutos desde el 5.º (423). Mientras dura no se verifica la clave, y esos
  intentos no alargan el bloqueo. Un usuario inexistente se bloquea igual,
  para no revelar qué cuentas existen. Todo intento queda en `intentos_login`.
- **Primer ingreso:** una cuenta con clave temporal (`debe_cambiar = 1`)
  recibe 428 con un token `temporal` que **solo** sirve para
  `POST /auth/cambio-password`. En cualquier otra ruta da 403.
- **Tokens JWT:** `access` de 15 min y `refresh` de 12 h. Cambiar la clave
  o dar de baja la cuenta anula en el acto todas las sesiones abiertas
  (`version_token`).
- Los errores traen `motivo` además de `detail`: `falta_token`,
  `token_invalido`, `token_expirado` (el front renueva con `/auth/refresh`),
  `credenciales_invalidas`, `cuenta_bloqueada`, `cambio_password_pendiente`,
  `rol_no_autorizado`, `metodo_no_autorizado`, `password_rechazada`,
  `password_actual_incorrecta`.

Ajustes en `.env`, prefijo `AUTH_` (`app/core/seguridad.py`, no `config.py`):

```
AUTH_JWT_SECRETO=<32+ caracteres al azar>   # OBLIGATORIO fuera de desarrollo
# Opcionales: AUTH_ACCESS_MINUTOS=15  AUTH_REFRESH_HORAS=12  AUTH_TEMPORAL_MINUTOS=10
#             AUTH_INTENTOS_MAXIMOS=5  AUTH_VENTANA_MINUTOS=15  AUTH_BLOQUEO_MINUTOS=15
#             AUTH_BCRYPT_RONDAS=12
```

Generar el secreto: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
En desarrollo, sin secreto se usa uno efímero y las sesiones se pierden cada
vez que la API se reinicia.

### Primera cuenta

Después de `alembic upgrade head`, desde `comedorback/`:

```powershell
python -m app.semillas.admin                                 # 'admin', rol sistemas
python -m app.semillas.admin --username jefa --rol jefa      # otras cuentas
python -m app.semillas.admin --username jefa --resetear      # clave temporal nueva
```

Imprime una clave temporal **una sola vez**: en el primer ingreso se pide
cambiarla. Es idempotente, y `--resetear` también reactiva la cuenta y cierra
sus sesiones. No va dentro de `python -m app.semillas` para que la clave no
se pierda en la salida de la receta de recreación.

## Endpoints

Todos exigen `Authorization: Bearer <access>` salvo `/salud`, `/auth/login` y
`/auth/refresh`.

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/salud` | Comprueba API y que `bd_nutricion` tenga sus tablas propias y 9 vistas (503 si falta algo) |
| POST | `/auth/login` | `{username, password}` → 200 `{access, refresh, rol, debe_cambiar}` · 401 · 423 `{reintento_en}` · 428 `{temporal}` |
| POST | `/auth/cambio-password` | `{password_nueva, password_actual?}` con el temporal del 428 o con un access (ahí pide la actual). 200 como login |
| POST | `/auth/refresh` | `{refresh}` → 200 como login, con access nuevo y el mismo refresh |
| GET | `/auth/yo` | `{id, username, rol, debe_cambiar}` de la sesión |
| GET | `/pantalla/estado` | Todo lo que la pantalla en vivo necesita para pintarse |
| GET | `/pantalla/ultimas-marcaciones` | Hilo del lector, incluidos los rechazos |
| GET | `/pantalla/comidas-del-dia` | Una fila por comida vigente del día: horario, estado (pendiente/en_curso/cerrada según el reloj del servidor), previstas, servidas, manuales y rechazos_por_motivo; más rechazos_sin_comida |
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
│  ├─ comedor.py        las 6 tablas propias del comedor
│  └─ usuarios.py       usuarios_sistema e intentos_login
├─ semillas/            carga de datos iniciales (python -m app.semillas)
└─ core/
   ├─ config.py         configuración leída de .env (DB_NAME, DB_NAME_TURNOS)
   ├─ seguridad.py      ajustes AUTH_*, bcrypt y tokens JWT
   ├─ autorizacion.py   usuario_actual, requiere_rol, errores con motivo
   ├─ permisos.py       la matriz rol x recurso
   ├─ db.py             motor único, sesión, Base y BaseContrato
   └─ tablas_heredadas.py   lo que no administramos + la lista de vistas v_*
alembic/                migraciones (base 4b5a9ed9330e, head b7c4d2e8f1a3)
tests/                  pytest, contra bd_nutricion_test
../scripts/recrear_bd_limpia.py   receta limpia de bd_nutricion
```

## Tests

```powershell
cd .\comedorback
.\.venv\Scripts\python -m pytest
```

Corren contra **`bd_nutricion_test`**, nunca contra la base de desarrollo:
`tests/conftest.py` fija `DB_NAME` antes de importar la app, y al empezar
**borra y recrea** esa base con `alembic upgrade head`. Toma las credenciales
(`DB_HOST`, `DB_USER`, `DB_PASSWORD`) de `.env`. Las vistas leen la base de
turnos, así que `DB_NAME_TURNOS` tiene que existir en el servidor (solo se le
hacen SELECT). Para otra base: `TEST_DB_NAME=otra_test` (tiene que terminar en
`_test`).

`test_zz_sin_escrituras_heredadas.py` corre al final y revisa todo el SQL de
la sesión, alembic incluido: falla si alguna sentencia escribió en la base de
turnos, en sus tablas heredadas o en las vistas `v_*`.
