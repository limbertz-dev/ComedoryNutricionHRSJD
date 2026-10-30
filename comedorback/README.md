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

`bd_nutricion` tiene exactamente **12 tablas + 9 vistas** (más `alembic_version`):

- **Tablas propias:** `categorias_reporte`, `categoria_reporte_map`,
  `horarios_comida`, `coeficientes_racion`, `lecturas_biometricas`, `asistencias`.
- **Tablas de la autenticación:** `usuarios_sistema`, `intentos_login`
  (ver [Autenticación y roles](#autenticación-y-roles)).
- **Tablas de reglas versionadas:** `reglas_derecho`,
  `reglas_derecho_novedad` (parámetros del derecho por fecha).
- **Cerrojos de escritura:** `cerrojos` (el mutex de los guardados de horarios).
- **Intervenciones de cocina:** `intervenciones_lectura`, la auditoría de cada
  intento de identificar a mano una lectura no reconocida (ver
  [Intervenciones de cocina](#intervenciones-de-cocina)).
- **Vistas del contrato de lectura** (`SQL SECURITY INVOKER`, leen
  `bd_proyecto_backend`): `v_comensales`, `v_categorias`, `v_servicios`,
  `v_comidas`, `v_usuario_servicios`, `v_turnos_asignados`, `v_turno_comida`,
  `v_novedades_laborales`, `v_comidas_por_turno`. `v_comensales` expone además
  `login` (`users.name`).

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
Expone además `login` (`users.name`) para vincular cuentas desde el padrón;
nunca password, email ni tokens.

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

`GET /salud` responde `"estado": "ok"` con `tablas_propias: 10`,
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
`e1a7c3b9d5f2` (head):

| Revisión | Qué hace |
|---|---|
| `4b5a9ed9330e` | Las 6 tablas propias, sin FK hacia la base de turnos |
| `ff4ddf3c8a18` | Las 6 columnas del formulario de Estadística (`categorias_reporte`) |
| `0c294cd98c3a` | Las 9 vistas `v_*`; el nombre de la base de turnos sale de `DB_NAME_TURNOS` |
| `7e2b9c4d1a60` | `usuarios_sistema` e `intentos_login` (autenticación) |
| `b7c4d2e8f1a3` | `asistencias.registrado_por_cuenta` (FK a `usuarios_sistema`, RESTRICT) y comentario LEGACY en `registrado_por` |
| `2555bc00750e` | `usuarios_sistema`: `usuario_turnos_id` (UNIQUE, referencia lógica a `users.id`), `nombre` y `creada_por_cuenta`; `v_comensales` suma la columna `login` (`users.name`) |
| `f13dd53094ae` | `reglas_derecho` + `reglas_derecho_novedad` (parámetros de derecho versionados, versión base 2000-01-01: 12 h, permiso/baja_medica/vacacion/licencia, enfermería excluida); `horarios_comida` suma `motivo` y `creada_por_cuenta`; índice (`comida_id`, `vigente_desde`) |

| `ca83b39b791c` | Horarios inmediatos: `horarios_comida.vigente_desde/hasta` y `lecturas_biometricas.fecha_hora` pasan a `DATETIME(6)`; tabla `cerrojos`. Se niega a perder horas o microsegundos al bajar |
| `e1a7c3b9d5f2` | Intervenciones de cocina: tabla `intervenciones_lectura` (solo inserciones) y `UNIQUE(asistencias.lectura_id)`. La subida se detiene, sin tocar nada, si ya hay una lectura con dos asistencias; la bajada se niega a borrar auditoría |
| `b9d1f3a5c7e8` | Internos y Residentes con columna propia, como en el rol de turnos: Internos · Residentes · Policías · Médicos · Técnicos · Sin clasificar. Todo Internos-* va a Internos; las raciones ya servidas no se reclasifican |

Reemplaza a la cadena vieja `fa64a5d4e912 → … → f6a7b8c9d0e1`, que asumía las
tablas heredadas copiadas en la misma base y le agregaba columnas a `comidas`.
Una base creada con esa cadena no se migra: se recrea con la receta de arriba.

`alembic/env.py` sigue excluyendo de la comparación las 36 tablas heredadas
(`app/core/tablas_heredadas.py`) y también las vistas `v_*`, que el autogenerate
no entiende y se administran a mano en su migración.

## Carga inicial (semilla)

La corre la receta; a mano, después de `alembic upgrade head`:

```powershell
python -m app.semillas     # las cuatro, idempotentes
```

| Semilla | Qué carga |
|---|---|
| `app.semillas.horarios` | Franjas horarias de cada comida (**provisionales**, solo el punto de partida): desde R2 se cambian desde «Reglas del sistema» |
| `app.semillas.coeficientes` | Coeficientes de ración del formulario (0,15 · 0,50 · 0,05 · 0,30) |
| `app.semillas.mapeo_categorias` | Categoría del hospital → columna del formulario (Internos-* → Internos, Residentes, Medicos → Médicos, Tecnicos → Técnicos) |
| `app.semillas.cuentas_iniciales` | Cuentas `root` (sistemas), `jefa` y `cocinera`, con clave inicial nombre + 2026 que se cambia en el primer ingreso. Una cuenta que ya existe no se toca |

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
rechaza las peticiones con credenciales, y eso rompería el login.

Si abres el front por otra dirección —por ejemplo la IP de tu máquina en la red,
para probarlo desde un celular— hay que agregar ese origen exacto a la lista, o
el navegador lo bloquea aunque sea el mismo front. En producción va la dirección
real del servidor del hospital.

## Autenticación y roles

Cuentas **propias** del comedor en `usuarios_sistema` (no son los `users` de la
base de turnos, y no se les escribe nada allá). Dónde se validan las claves
está aislado en `verificar_credenciales()` (`app/logica/autenticacion.py`): si
mañana se valida contra otro sistema del hospital o contra `users`, se cambia esa función y nada
más.

| Rol | Puede |
|---|---|
| `jefa` | Todo lo operativo: pantalla, padrón, historial, informes, marcación biométrica y manual. Las intervenciones de cocina solo las **consulta** (`GET /intervenciones-cocina`) |
| `cocinera` | Solo `GET /pantalla/*`, `POST /asistencias` con `metodo='biometrico'` y, ella sola, `POST /asistencias/lecturas/{id}/identificar`; en `/personal` recibe `carnet_identidad` y `tipo_trabajador` en null, y en `/pantalla/dia-personal` recibe `carnet_identidad` en null (esa ficha no trae `tipo_trabajador`) |
| `sistemas` | Todo lo de la jefa, más administración de cuentas (crea cuentas de cocinera y jefa desde el padrón o sin vínculo). **Fuera** de las intervenciones de cocina: ni las ejecuta ni las consulta, y no recibe datos de quién las hizo |

La matriz vive en `app/core/permisos.py` y se aplica router por router en
`app/main.py` con `requiere_rol(...)`. La regla "manual solo jefatura" depende
del cuerpo de la petición, así que la aplica `POST /asistencias`. Sin token
solo responden `/salud`, `/auth/login` y `/auth/refresh`.

Reglas:

- **Claves:** solo hash bcrypt. Mínimo 8 caracteres, máximo 72 bytes, distinta
  del usuario y de la anterior.
- **Bloqueo:** apagado por omisión (`AUTH_INTENTOS_MAXIMOS=0`): equivocarse de
  clave nunca deja a la cocina fuera en plena hora de comida. Todo intento
  queda igual en `intentos_login`. Con `AUTH_INTENTOS_MAXIMOS=5` en `.env` se
  activa: 5 fallidos dentro de 15 minutos bloquean la cuenta 15 minutos (423),
  y un usuario inexistente se bloquea igual, para no revelar qué cuentas existen.
- **Cuentas desde Administración:** root escribe la contraseña definitiva al
  crear la cuenta o al cambiarla; la cuenta entra con ella sin cambio
  obligatorio y la contraseña nunca vuelve en una respuesta.
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
#             AUTH_INTENTOS_MAXIMOS=0 (sin bloqueo)  AUTH_VENTANA_MINUTOS=15  AUTH_BLOQUEO_MINUTOS=15
#             AUTH_BCRYPT_RONDAS=12
```

Generar el secreto: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
En desarrollo, sin secreto se usa uno efímero y las sesiones se pierden cada
vez que la API se reinicia.

### Cuentas iniciales

`python -m app.semillas` crea `root` (sistemas), `jefa` y `cocinera` con clave
inicial `root2026`, `jefa2026` y `cocinera2026`. Son temporales: en el primer
ingreso el sistema pide cambiarlas, así que una clave conocida no queda en uso.

Para otras cuentas o para resetear una clave, desde `comedorback/`:

```powershell
python -m app.semillas.admin --username cocinera2 --rol cocinera   # otra cuenta
python -m app.semillas.admin --username jefa --resetear            # clave temporal nueva
```

`admin` imprime una clave temporal aleatoria **una sola vez**. Es idempotente, y
`--resetear` también reactiva la cuenta y cierra sus sesiones.

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
| POST | `/asistencias/lecturas/{lectura_id}/identificar` | Solo cocinera. Identifica una lectura no reconocida y confirma la entrega. Cabecera `Idempotency-Key` (UUID v4), cuerpo `{usuario_id}` |
| GET | `/intervenciones-cocina` | Solo jefa. Las intervenciones de cocina (registradas y rechazadas), paginadas |
| GET | `/pantalla/lecturas-por-identificar` | Solo cocinera. Las lecturas no reconocidas que se pueden identificar AHORA, en el servicio actual, sin depender de la fecha ni de las 100 filas de `ultimas-marcaciones` |
| GET | `/historial/diario` | Lista nominal de un día, con los 4 estados |
| GET | `/historial/mensual` | Resumen nominal del mes, persona por persona |
| GET | `/reportes/periodos` | Gestiones y meses para el selector |
| GET | `/reportes/registro-diario` | Planilla del mes, una fila por día |
| GET | `/reportes/mensual` | Formulario de Estadística, con coeficientes |
| GET | `/reportes/gestion` | Resumen anual, una fila por mes |
| GET | `/reportes/informe?desde=AAAA-MM-DD&hasta=AAAA-MM-DD` | Formulario de Estadística para un rango de fechas arbitrario (hoy, una semana, una quincena), con coeficientes. 422 si `desde > hasta` |
| GET | `/admin/cuentas` | Todas las cuentas, con vínculo, nombre y último ingreso |
| GET | `/admin/candidatos?busqueda=` | Personas del padrón para vincular (búsqueda de 2+ letras) |
| POST | `/admin/cuentas` | Crea una cuenta vinculada o sin vínculo con la contraseña que elige root (`password`). 201 `{cuenta}` |
| POST | `/admin/cuentas/{id}/desactivar` | Da de baja la cuenta y cierra sus sesiones |
| POST | `/admin/cuentas/{id}/reactivar` | Reactiva la cuenta |
| POST | `/admin/cuentas/{id}/clave` | `{password}`: root fija la contraseña nueva y se cierran sus sesiones. 200 `{cuenta}` |
| GET | `/cuentas` | Cuentas en solo lectura (jefa y sistemas; la jefa no ve cuentas sistemas) |
| GET | `/reglas/derecho` | Versión vigente de hoy + todas, nueva a vieja |
| GET | `/reglas/derecho/novedades` | Tipos de novedad reales para la UI |
| POST | `/reglas/derecho` | Programa una versión nueva. 201 |
| DELETE | `/reglas/derecho/{id}` | Borra una versión programada. 204 |
| GET | `/reglas/horarios?fecha=` | Horario vigente de cada comida en esa fecha (hoy por defecto) |
| GET | `/reglas/horarios/historial?comida_id=` | Todas las versiones de una comida |
| POST | `/reglas/horarios` | Programa un horario nuevo, cierra el anterior. 201 |
| DELETE | `/reglas/horarios/{horario_id}` | Borra un horario programado, reabre el anterior. 204 |

Las seis rutas `/admin/*` son solo para `sistemas`: jefa y cocinera reciben
403. Los errores traen `motivo`: `username_en_uso`, `persona_ya_tiene_cuenta`,
`persona_inexistente`, `cuenta_inexistente`, `login_invalido`,
`rol_no_permitido`, `password_rechazada`, `no_puede_desactivarse_a_si_misma`,
`ultima_cuenta_sistemas`.

Las rutas `/reglas/*` son solo para `sistemas`. Los errores traen `motivo`:
`vigencia_en_el_pasado`, `horario_invalido`, `solapa_con_otra_comida`,
`version_en_esa_fecha`, `comida_inexistente`, `version_inexistente`,
`version_ya_vigente`, `motivo_obligatorio`.

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

### Intervenciones de cocina

Cuando el lector no reconoce una huella, la lectura queda `rechazada` /
`no_identificado` y sin usuario. La **cocinera** ve a la persona, la elige en
el padrón y confirma la entrega con
`POST /asistencias/lecturas/{lectura_id}/identificar`. El servidor vuelve a
comprobar todo y, en una sola transacción, registra la asistencia vinculada a
la lectura y una fila de auditoría en `intervenciones_lectura`. **La lectura
original no se modifica** y nunca se dice que el lector reconoció la huella.
La jefa **solo consulta** (`GET /intervenciones-cocina`); sistemas queda
fuera. Esto no amplía `POST /asistencias` manual, que sigue siendo solo de
jefatura, y el registro manual independiente de jefatura sigue separado.

- **Sin nota, sin motivo escrito, sin límite de minutos.** La causa la fija el
  servidor (`identificacion_manual_por_no_identificado`); la cuenta sale del
  token y la hora del reloj del servidor.
- **Mismo servicio efectivo.** La lectura tiene que pertenecer al servicio de
  ahora: la misma comida, la misma `fecha_comida` y la misma ventana efectiva
  (`app/consultas/servicio.py`). `lecturas_biometricas` no guarda comida ni
  fecha, así que el servicio de la lectura se **reconstruye por horario**; no es
  un dato histórico. Todo lo dudoso falla cerrado: `reloj_inconsistente` (el
  reloj está antes de la lectura), `servicio_no_determinable` (ninguna ventana
  la contiene, hay más de una, o dos formas de resolverla discrepan) y
  `servicio_distinto`.
- **Derecho, horario y duplicado siguen siendo obligatorios.** Una regla de la
  persona (`sin_derecho`, `duplicado`) responde **200** con `valido: false` y
  `resultado: "rechazada"`; un conflicto sobre la lectura
  (`lectura_no_resoluble`, `lectura_ya_resuelta`, `servicio_*`,
  `reloj_inconsistente`) responde **409** con `motivo`. Solo
  `resultado: "registrada"` es una entrega: un intento rechazado nunca se
  llama entrega.
- **El rechazo original elegible y "ya resuelta" son dos casos.** Elegible =
  `rechazada`, `no_identificado`, sin usuario (valores guardados, no lo que
  muestra la pantalla). Que ya tenga una ración es otra comprobación
  (`lectura_ya_resuelta`).
- **Idempotencia por intento.** `Idempotency-Key` (UUID v4, por cuenta) más la
  huella `SHA-256({lectura_id, usuario_id})`. Misma clave y misma huella:
  devuelve lo guardado (`reintento: true`), también un rechazo, sin otra fila ni
  otra ración, y **sin reevaluar nada** (ni la lectura, ni el padrón, ni los
  horarios). Misma clave con otra persona: 409
  `clave_reutilizada_con_otro_contenido`. Una lectura resuelta por otra cuenta
  responde 409 `lectura_ya_resuelta` con `resuelta_por_mi`, nunca quién fue.
- **Confirmación incierta.** Si algo falla al confirmar (una desconexión) no se
  sabe qué quedó: 503 `resultado_incierto`, sin afirmar que no hubo entrega. El
  cliente repite con la **misma** clave y recupera lo confirmado, si lo hubo.
  Un bloqueo agotado o un interbloqueo es 409 `intervencion_en_curso`
  (también: repetir con la misma clave).
- **Transacción y bloqueos.** La autenticación consulta la base: el endpoint
  copia `cuenta_id`, la lógica hace `rollback()`, recupera la clave sin
  bloqueo y recién entonces toma `SELECT ... FOR UPDATE` sobre la fila de la
  lectura, como primera sentencia de la transacción nueva (el snapshot de
  REPEATABLE READ nace después del bloqueo). Ese es el único bloqueo sobre
  filas; **nada se bloquea en el padrón, las vistas ni la base de turnos**
  (solo SELECT planos). La ración entra dentro de un SAVEPOINT: si
  `uq_asistencias_racion` da `IntegrityError`, el rollback se limita al
  SAVEPOINT, la causa se averigua **consultando** (no leyendo el texto del
  driver) y el rechazo se audita en la misma transacción, con el bloqueo
  vigente. Detalle en `app/logica/intervencion.py`.
- **Pantalla.** `GET /pantalla/ultimas-marcaciones` muestra ahora el `motivo`
  **guardado** (antes toda lectura sin usuario se presentaba como
  `no_identificado`) y separa `decision_original` (inmutable) de `estado_final`
  / `resultado_final`. `intervencion.revision` solo crece y sube cuando alguien
  registra una entrega de esa lectura, aunque sea otra cocinera: así el front
  detecta el cambio de una fila que ya existía. La cocinera nunca recibe datos
  de cuentas ajenas ni de intentos ajenos; la jefa ve quién registró;
  sistemas recibe `intervencion: null`.
- **Servicio nocturno.** `ultimas-marcaciones` se consulta por la fecha de la
  lectura y corta en 100 filas; una lectura de las 23:58 sigue en el servicio a
  las 00:30 y ya es de "ayer". Para eso existe
  `GET /pantalla/lecturas-por-identificar` (solo cocinera): parte del servicio
  actual y trae sus lecturas pendientes, de ayer o de hoy. Una lectura que sale
  de esa lista dejó de ser identificable (la resolvió alguien o terminó el
  servicio); su estado se ve en `ultimas-marcaciones?fecha=<fecha de la lectura>`.
- **Errores de integridad.** Solo se trata como carrera un duplicado (1062) que
  la base confirma: en la auditoría, que la clave de idempotencia ya exista; en
  la ración, que lo explique una ración de esa persona o una asistencia de esa
  lectura. Cualquier otro error (una FK, un valor inválido) se propaga como
  fallo interno (500), sin disfrazarlo de `intervencion_en_curso`, y no queda
  nada a medias.
- **Coherencia de la auditoría.** Ninguna restricción de la base garantiza que
  `registrada` tenga `asistencia_id` y `rechazada` no (el CHECK solo cubre
  `motivo_rechazo`; no se verificó que MySQL admita uno sobre esa columna con
  FK). La sostiene el único camino de inserción y la comprueban las pruebas.
- **Métricas.** Los informes, el historial y el cupo salen de `asistencias`: la
  ración cuenta una vez. La lectura rechazada sigue contando como rechazo (es un
  toque de dedo, no una ración).

Pendientes de decisión, **no implementados**: bloquear que una cuenta se
identifique a sí misma y un tope de intentos rechazados por lectura.

### El derecho a comer

Una asignación de turno da derecho sólo si cumple **las tres** condiciones:

1. El turno dura lo suficiente (`turnos.duracion_horas`). Es política del
   hospital: 12 horas o más en la versión base (descarta 49 de los 76
   turnos cargados).
2. El turno tiene comidas mapeadas en `turno_comida`.
3. No hay una novedad que lo anule (permiso, baja_medica, vacacion y licencia
   en la versión base).

La primera **habilita**, la segunda **otorga**: son cosas distintas. Un turno
largo sin filas en `turno_comida` sigue sin dar derecho, y es correcto.

Los parámetros —turno mínimo, novedades que anulan y exclusión de
enfermería— ya no están fijos en el código: se leen de la versión vigente
según `fecha_turno`, resuelta en SQL dentro de `aplicar_reglas()`, que sigue
siendo el punto único (`app/consultas/derecho.py`, sobre `v_comidas_por_turno`)
por el que pasan la marcación, la pantalla y los dos historiales. El padrón
y el conteo de la pantalla usan la versión vigente de hoy. Cada cambio crea
una versión nueva con «vigente desde» (hoy o futura), nunca hacia atrás;
solo se puede borrar una programada.

## Estructura

```
app/
├─ main.py              aplicación FastAPI y endpoint /salud
├─ api/                 los endpoints
├─ consultas/           consultas de lectura (padrón, derecho, servicio, intervenciones)
├─ logica/              reglas del negocio (marcación, intervención de cocina)
├─ esquemas/            formas de entrada y salida
├─ modelos/
│  ├─ heredados.py      las 9 vistas v_* (base de turnos), SOLO LECTURA
│  ├─ comedor.py        las tablas propias del comedor (incluye intervenciones_lectura y cerrojos)
│  ├─ usuarios.py       usuarios_sistema e intentos_login
│  └─ reglas.py         reglas_derecho y reglas_derecho_novedad (parámetros por fecha)
├─ semillas/            carga de datos iniciales (python -m app.semillas)
└─ core/
   ├─ config.py         configuración leída de .env (DB_NAME, DB_NAME_TURNOS)
   ├─ seguridad.py      ajustes AUTH_*, bcrypt y tokens JWT
   ├─ autorizacion.py   usuario_actual, requiere_rol, errores con motivo
   ├─ permisos.py       la matriz rol x recurso
   ├─ db.py             motor único, sesión, Base y BaseContrato
   └─ tablas_heredadas.py   lo que no administramos + la lista de vistas v_*
alembic/                migraciones (base 4b5a9ed9330e, head e1a7c3b9d5f2)
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
