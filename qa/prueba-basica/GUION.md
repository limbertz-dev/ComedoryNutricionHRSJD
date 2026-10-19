# Prueba básica: Parte A (cuentas y permisos) y Parte B (huella no reconocida, entrega por cocinera2 y consulta de la jefa)

**La prueba puede iniciarse a cualquier hora real.** El kit usa un reloj de laboratorio compartido, por omisión `2026-10-15T11:30:00`, dentro del almuerzo del manifiesto. Ese reloj sigue corriendo: lectura e identificación deben ocurrir entre las 11:00 y las 15:00 del laboratorio, con las 15:00 excluidas y dentro de la misma ventana efectiva. No se cambian los horarios ni el reloj del sistema operativo. Fuente: `comedorback/app/semillas/horarios.py:43`, `comedorback/app/consultas/servicio.py:100` y `comedorback/tests/reloj_prueba.py:17`.

El ensayo se divide en dos partes, donde **la Parte B depende de que la Parte A haya pasado completa**:
- **PARTE A (preparación automática, cambio de contraseña en frontend y pruebas de integración de identidad y permisos contra la API QA)**: huella base → preparación automática y comprobación de claves temporales (`cuentas.py --preparar`, que crea/resetea `cocinera1`, `cocinera2`, `cocinera3` con rol fijo `cocinera` y `jefa` con rol fijo `jefa`, muestra una vez cada temporal, levanta la API QA, verifica automáticamente los cuatro `428 cambio_password_pendiente`, guarda el estado pendiente en `corrida.json` y mantiene disponible la API) → login en frontend y cambio a contraseña definitiva por el operador en las 4 cuentas → verificación de identidad y permisos con `cuentas.py` → revisar resultados. Permite terminar aquí (detener procesos → limpiar → huella final) o continuar con la Parte B. *Nota*: estos controles contra la API son pruebas de integración de cuentas y permisos; las pruebas unitarias offline (`pytest`) usan respuestas HTTP simuladas.
- **PARTE B (flujo operativo, solo con Parte A aprobada)**: con la API y el front activos → sesiones de `cocinera2` y `jefa` autenticadas con sus claves definitivas en sesiones separadas del navegador → simular lectura no reconocida (`huella.py`) → identificación por Postman como `cocinera2` (`POST /asistencias/lecturas/{id}/identificar` para `900001`) → consulta de la `jefa` en `Supervisión → Intervenciones de cocina` → verificación por API (`GET /intervenciones-cocina?usuario_id=900001`) → detener procesos → limpiar → huella final.

**Distinción entre resultados esperados y obtenidos:** las columnas «Esperado» de este guion documentan el comportamiento verificado en el código y los contratos; las columnas «Obtenido» permanecen vacías en la entrega offline y solo deben completarse con lo observado al ejecutar en vivo contra el escenario.

**Alcance y limitaciones verificadas:**
- **La consulta API de pantalla (`GET /pantalla/estado` o `GET /pantalla/ultimas-marcaciones`) solo acredita la respuesta del backend; no demuestra por sí sola que la interfaz gráfica se haya mostrado correctamente en el navegador.**
- **La huella no reconocida generada por `huella.py` es una simulación por software (`registrar_marcacion(usuario_id=None, metodo='biometrico')`); no acredita una falla física del lector biométrico.**
- **Limitación verificada en `develop` local:** `PantallaEnVivo` tiene `puedeIdentificar = false` por defecto (`comedorfront/src/components/secciones/PantallaEnVivo.jsx:205`) y `App.jsx` (`comedorfront/src/App.jsx:192`) no le pasa esa propiedad. Por ello esta versión del guion usa Postman para identificar la lectura como `cocinera2`. No se modifica el frontend en esta tarea ni se declara validado el flujo completo de aprobación por navegador.

Solo usar el escenario dedicado y reservar `cocinera1`, `cocinera2`, `cocinera3` y `jefa` para esta corrida. Nadie debe cambiar sus datos o usar otra API sobre estas bases durante la prueba. No ejecutar el preparador histórico: se leyó con `git show`, no se incorporó al árbol.

## Preparación de las consolas

Desde PowerShell, establecer estas rutas (en cada consola nueva):

```powershell
$qaRoot = 'C:/__Proyectos__/comedorynutriciónhospitalaria/wt-qa'
$qaPython = 'C:/__Proyectos__/comedorynutriciónhospitalaria/wt-develop/comedorback/.venv/Scripts/python.exe'
Set-Location $qaRoot
$env:DB_NAME = 'bd_nutricion_escenario_sim'
$env:DB_NAME_TURNOS = 'bd_turnos_escenario_demo'
$env:ENTORNO = 'desarrollo'
```

Proveer además `DB_HOST`, `DB_PORT` y `DB_USER` mediante el entorno de esa consola. Para Laragon/root sin clave, usar explícitamente este bloque en cada consola Python (en este PowerShell, asignar `''` elimina la variable):

```powershell
Remove-Item Env:DB_PASSWORD -ErrorAction SilentlyContinue
$env:QA_DB_SIN_CLAVE = '1'
```

Con contraseña, definir `DB_PASSWORD` por el mecanismo seguro habitual y quitar `QA_DB_SIN_CLAVE` (`Remove-Item Env:QA_DB_SIN_CLAVE -ErrorAction SilentlyContinue`). Una contraseña no vacía junto con `QA_DB_SIN_CLAVE=1` aborta por ambigüedad. Si `DB_PASSWORD` está ausente, solo el valor exacto `QA_DB_SIN_CLAVE=1` permite usar clave vacía; cualquier otro caso aborta con `DB_PASSWORD`.

No usar ni abrir archivos `.env`, imprimir el entorno ni registrar las claves temporales. Si falta una variable requerida, la salida del script es únicamente su nombre. No se incluyen credenciales en los archivos entregados ni en `corrida.json`.

Todos los comandos Python con acceso a base usan guardas y `before_cursor_execute` global para ese proceso. Primero validan los nombres, después el marcador en una conexión **AUTOCOMMIT** (sin abrir una transacción de base de datos), la revisión, las vistas y la ausencia de triggers/FK externas. Solo entonces habilitan las escrituras permitidas y las transacciones. Ante un esquema inesperado abortan.

El comando único de preparación (`& $qaPython qa/prueba-basica/cuentas.py --preparar`, también disponible como `& $qaPython qa/prueba-basica/ejecutar_app.py preparar`) y el lanzador `ejecutar_app.py` evitan que `Configuracion` o `AjustesSeguridad` lean dotenv. Si hay una API QA anterior activa (`api.activa` o puerto ocupado), la preparación aborta con instrucción clara de detenerla mediante `Ctrl+C` en su consola, sin matar procesos ajenos. Bajo las guardas y el bloqueo del diario, antes de efectuar el primer reseteo invalida cualquier aprobación o control `PASA` anterior registrando `parte_a: {"estado": "preparacion_pendiente", "completa": false}`. Luego valida las 4 cuentas e invoca la semilla original `app.semillas.admin.sembrar(username, rol=<rol_fijo>, resetear=True)` usando su generador original `clave_temporal()`, mostrando cada clave temporal generada exactamente una vez en la consola del operador y conservándolas únicamente en memoria, fijando el rol de cada cuenta (`cocinera` para `cocinera1`/`cocinera2`/`cocinera3` y `jefa` para `jefa`, nunca `sistemas`) y abortando antes si alguna cuenta existe con otro rol o con vínculo (`usuario_turnos_id`). A continuación levanta la API QA mediante `ejecutar_app.py api`, verifica automáticamente con las temporales en memoria que el primer login de las 4 cuentas devuelve `428 cambio_password_pendiente`, limpia las temporales de memoria, guarda en `corrida.json` únicamente resultados seguros con estado `PENDIENTE` (`parte_a.completa=false`), y mantiene disponible la API para que el operador ingrese al frontend y cambie cada contraseña allí. Al detener el proceso API propio, confirma su finalización antes de retirar `api.activa`, conserva la marca si no puede detenerse y no presenta una terminación forzada como cierre normal con checksum verificado. Para esta prueba no ejecutar directamente `python -m app.semillas.admin` ni `uvicorn app.main:app`: esos procesos no llevarían el auditor ni las guardas y cargarían dotenv por defecto (`comedorback/app/core/config.py:23`, `comedorback/app/core/seguridad.py:48`).

## Reloj compartido del laboratorio

`comun.py --huella-base --reloj AAAA-MM-DDTHH:MM:SS` guarda `reloj: {lab, real}` en `corrida.json`. Si se omite `--reloj`, usa `2026-10-15T11:30:00`. El formato es hora local sin zona. En cada proceso, `reloj.ahora()` se sustituye temporalmente por `reloj.real() + (ancla.lab - ancla.real)`; `reloj.hoy()` sigue esa hora. API, admin, lector y refechado imprimen `Reloj de laboratorio: <lab> (real: <real>)` antes de ejecutar su lógica.

El ancla se crea una vez y no se reinicia al levantar otro proceso. Todos deben ejecutarse en esta máquina, con la misma zona horaria y el mismo diario. Con el valor por omisión hay aproximadamente 3 horas y 30 minutos reales para completar la entrega, contados desde la creación del ancla. Si vence la ventana, detener la API, limpiar, verificar la huella final, archivar el diario y abrir otra corrida con una nueva ancla; no editar la existente.

`reloj.real()` y `reloj.real_utc()` permanecen intactos: login, bloqueo y JWT siguen en hora real (`comedorback/app/logica/autenticacion.py:28`, `comedorback/app/core/reloj.py:19`). `inicio` y `fin` del diario también son reales; la limpieza de intentos conserva su filtro real. `limpiar.py` no instala el reloj de laboratorio y puede limpiar diarios antiguos sin ancla.

El flujo normal conserva la asignación del **2026-10-15**: estado `iniciada`, `fecha_destino=null`, sin UPDATE de fecha. Si la fecha de laboratorio coincide con `fecha_original`, ya se pueden habilitar las cuentas, levantar la API, verificar cuentas y crear la lectura. Solo la creación de lectura pasa a `lectura_pendiente` y después a `lectura_creada`. Los estados pendientes o `limpia` no habilitan una nueva lectura. La API admite `lectura_creada` para continuar la misma prueba tras reiniciar, conservando el desfase.

## PARTE A: Verificación de integración de cuentas y permisos (`cocinera1`, `cocinera2`, `cocinera3` y `jefa`)

Los archivos y líneas se refieren al código de `wt-qa`, salvo las referencias que incluyen un commit. Cada fila corresponde a un paso, en orden.

| Paso | Acción del operador | Esperado (leído del código, archivo:línea) | Obtenido |
|---|---|---|---|
| A1. Elegir reloj | `$qaReloj = '2026-10-15T11:30:00'` | Instante del almuerzo de la asignación original; todavía no escribe en la base ni crea el ancla. `qa/prueba-basica/comun.py:432`, `comedorback/app/semillas/horarios.py:43`. | |
| A2. Huella base y fijar ancla | `& $qaPython qa/prueba-basica/comun.py --huella-base --reloj $qaReloj` | Verifica escenario (`cocinera2` y `cocinera3` obligatorias; acepta que `cocinera1` y `jefa` no existan aún) y crea `corrida.json` **antes del primer login/reseteo**, registrando cuáles de las 4 cuentas existían, ancla `{lab, real}`, estado `iniciada`, CHECKSUM de todas las tablas protegidas y fecha original. Huellas antes/después iguales. `qa/prueba-basica/comun.py:338`, `qa/prueba-basica/comun.py:510`. | |
| A3. Preparación automática y comprobación de temporales | En consola dedicada: `& $qaPython qa/prueba-basica/cuentas.py --preparar` (o `& $qaPython qa/prueba-basica/ejecutar_app.py preparar`). Tomar nota de las 4 claves temporales mostradas una única vez en consola. | Si hay una API anterior activa, aborta pidiendo detenerla con `Ctrl+C` sin matar procesos ajenos. Bajo las guardas y el bloqueo del diario, invalida antes del primer reseteo cualquier aprobación o resultado `PASA` previo (`parte_a: {"estado": "preparacion_pendiente", "completa": false}`). Valida las 4 cuentas, crea/resetea `cocinera1`, `cocinera2`, `cocinera3` (`rol=cocinera`) y `jefa` (`rol=jefa`) con `app.semillas.admin.sembrar(..., resetear=True)` (`debe_cambiar=1`, `version_token` incrementado), muestra cada temporal una vez en consola conservándolas solo en memoria, levanta la API QA mediante `ejecutar_app.py api --port 8001`, valida `/salud` y verifica automáticamente que `POST /auth/login` con cada temporal devuelve `428 cambio_password_pendiente`. Guarda solo resultados seguros en `corrida.json` con `resultado="PENDIENTE"` y `parte_a: {"estado": "pendiente_cambio_frontend", "completa": false}` (sin pedir `getpass`, sin asignar claves definitivas y sin dar por completada la Parte A). Mantiene activa la API en esa consola. `qa/prueba-basica/ejecutar_app.py:23`, `qa/prueba-basica/cuentas.py:555`, `comedorback/app/semillas/admin.py:40`. | |
| A4. Login en frontend y cambio a contraseña definitiva | En otra consola, levantar el frontend (bloque «Frontend» de abajo), abrir `http://127.0.0.1:5173`, iniciar sesión sucesivamente con `cocinera1`, `cocinera2`, `cocinera3` y `jefa` usando la temporal de A3 y cambiar cada contraseña por la definitiva que elija el operador. | En cada cuenta, el ingreso con la clave temporal abre la vista obligatoria de cambio de contraseña (`428 cambio_password_pendiente`), el operador introduce y confirma su contraseña definitiva en el navegador (`POST /auth/cambio-password` → `200 debe_cambiar=false`), y la cuenta queda con su clave definitiva vigente. `comedorfront/src/App.jsx:144`, `comedorfront/src/components/auth/CambiarPassword.jsx:17`, `comedorback/app/api/auth.py:129`. | |
| A5. Verificar identidad y permisos tras el cambio | En una tercera consola (con la API de A3 activa): `& $qaPython qa/prueba-basica/cuentas.py` (admite `--base <url>` y `--solo <cuenta>`). | Valida `/salud` y exige que cada cuenta tenga su `428` previo registrado en `corrida.json`; solicita con `getpass` únicamente la contraseña definitiva elegida en A4 (sin imprimir claves ni tokens y sin reintentar automáticamente credenciales fallidas), verifica `POST /auth/login (definitiva)` → `200 debe_cambiar=false`, `GET /auth/yo` y los controles de permisos por rol, muestra la tabla `Cuenta \| Control \| Esperado \| Obtenido \| PASA/FALLA` y guarda resultados seguros en `corrida.json`. Solo cuando las 4 cuentas pasan todos sus controles actualiza `parte_a` a `{"estado": "aprobada", "completa": true}`. Sale con código `!= 0` si algún control falla. `qa/prueba-basica/cuentas.py:249`, `qa/prueba-basica/cuentas.py:478`. | |
| A6. Cierre si termina en Parte A | Si el ensayo termina tras revisar Parte A: cerrar el frontend, detener la API de A3 con `Ctrl+C`, ejecutar `& $qaPython qa/prueba-basica/limpiar.py`, luego `& $qaPython qa/prueba-basica/limpiar.py --aplicar` y `& $qaPython qa/prueba-basica/comun.py --huella-final`. | Borra `intentos_login` de las 4 cuentas desde `inicio`; verifica y conserva las 4 cuentas fijas en `usuarios_sistema`; marca `corrida.json` como `limpia` y confirma huella final idéntica a la base. Si Parte A aprobó (`parte_a.completa=true`) y se continúa con Parte B, omitir A6 y continuar en Parte B con la misma corrida, la API de A3 activa y el frontend abierto. `qa/prueba-basica/limpiar.py:10`, `qa/prueba-basica/comun.py:510`. | |

### Preparación automática y verificación posterior (pasos A3 a A5)

1. **Iniciar el flujo de preparación y comprobación automática de temporales (paso A3)**:
   ```powershell
   & $qaPython qa/prueba-basica/cuentas.py --preparar
   ```
   *(Equivalente a `& $qaPython qa/prueba-basica/ejecutar_app.py preparar`.)*
   Este comando único crea/resetea las 4 cuentas con sus roles fijos usando `app.semillas.admin.sembrar`, muestra en consola cada clave temporal exactamente una vez (`Clave temporal: <valor>`), las conserva únicamente en memoria, levanta la API QA mediante `ejecutar_app.py api`, verifica automáticamente que el primer login de cada cuenta responde `428 cambio_password_pendiente`, descarta las temporales de memoria, registra ese avance en `corrida.json` con `resultado="PENDIENTE"` (`parte_a.completa=false`) y deja la API corriendo en esa consola. **Las cuatro respuestas `428` no completan la Parte A**: los controles de identidad y permisos permanecen pendientes hasta que el operador cambie las 4 claves desde el frontend.
2. **Cambiar cada clave temporal a su definitiva en el frontend (paso A4)**:
   Con la API activa y el frontend abierto en `http://127.0.0.1:5173`, el operador inicia sesión con cada una de las 4 cuentas (`cocinera1`, `cocinera2`, `cocinera3` y `jefa`) usando la clave temporal mostrada en la consola de A3 y define la contraseña definitiva en el formulario del navegador.
3. **Verificar identidad y permisos con las claves definitivas (paso A5)**:
   En otra consola PowerShell configurada con el entorno del escenario (mientras la consola de A3 mantiene activa la API):
   ```powershell
   & $qaPython qa/prueba-basica/cuentas.py
   ```
   `cuentas.py` comprueba primero `/salud` y que el `428` inicial de cada cuenta ya conste en `corrida.json`; luego pide mediante `getpass` únicamente la contraseña definitiva de cada cuenta (`[<cuenta>] Clave definitiva: `) y ejecuta `POST /auth/login (definitiva)`, `GET /auth/yo` y los controles de permisos por rol. Admite `--solo <cuenta>` para repetir la verificación de una cuenta individual conservando los resultados de las demás. No guardar ni copiar ninguna clave temporal ni definitiva al guion, a Git, a archivos, a `corrida.json` ni a logs; conservar las definitivas de `cocinera2` y `jefa` únicamente en el gestor/Vault local para la Parte B.

### Controles de `cuentas.py` (pasos A3 y A5 — completar columna «Obtenido»)

| Cuenta | Rol fijo | Control | Esperado (código y contrato) | Obtenido |
|---|---|---|---|---|
| `cocinera1` | `cocinera` | `POST /auth/login (temporal)` *(automático en A3)* | `428 cambio_password_pendiente` (`comedorback/app/api/auth.py:103`) | |
| `cocinera1` | `cocinera` | `POST /auth/login (definitiva)` *(en A5 tras cambio en frontend)* | `200 debe_cambiar=false` (`comedorback/app/api/auth.py:115`) | |
| `cocinera1` | `cocinera` | `GET /auth/yo` | `200 cocinera1 rol=cocinera debe_cambiar=false` (`comedorback/app/api/auth.py:194`) | |
| `cocinera1` | `cocinera` | `GET /pantalla/estado` | `200` (`comedorback/app/core/permisos.py:68`; solo API, no acredita renderizado UI) | |
| `cocinera1` | `cocinera` | `POST /asistencias (manual)` | `403 metodo_no_autorizado` (`comedorback/app/core/autorizacion.py:163`) | |
| `cocinera1` | `cocinera` | `GET /intervenciones-cocina` | `403` (`comedorback/app/core/permisos.py:84`) | |
| `cocinera1` | `cocinera` | `GET /admin/cuentas` | `403` (`comedorback/app/core/permisos.py:78`) | |
| `cocinera2` | `cocinera` | `POST /auth/login (temporal)` *(automático en A3)* | `428 cambio_password_pendiente` (`comedorback/app/api/auth.py:103`) | |
| `cocinera2` | `cocinera` | `POST /auth/login (definitiva)` *(en A5 tras cambio en frontend)* | `200 debe_cambiar=false` (`comedorback/app/api/auth.py:115`) | |
| `cocinera2` | `cocinera` | `GET /auth/yo` | `200 cocinera2 rol=cocinera debe_cambiar=false` (`comedorback/app/api/auth.py:194`) | |
| `cocinera2` | `cocinera` | `GET /pantalla/estado` | `200` (`comedorback/app/core/permisos.py:68`; solo API, no acredita renderizado UI) | |
| `cocinera2` | `cocinera` | `POST /asistencias (manual)` | `403 metodo_no_autorizado` (`comedorback/app/core/autorizacion.py:163`) | |
| `cocinera2` | `cocinera` | `GET /intervenciones-cocina` | `403` (`comedorback/app/core/permisos.py:84`) | |
| `cocinera2` | `cocinera` | `GET /admin/cuentas` | `403` (`comedorback/app/core/permisos.py:78`) | |
| `cocinera3` | `cocinera` | `POST /auth/login (temporal)` *(automático en A3)* | `428 cambio_password_pendiente` (`comedorback/app/api/auth.py:103`) | |
| `cocinera3` | `cocinera` | `POST /auth/login (definitiva)` *(en A5 tras cambio en frontend)* | `200 debe_cambiar=false` (`comedorback/app/api/auth.py:115`) | |
| `cocinera3` | `cocinera` | `GET /auth/yo` | `200 cocinera3 rol=cocinera debe_cambiar=false` (`comedorback/app/api/auth.py:194`) | |
| `cocinera3` | `cocinera` | `GET /pantalla/estado` | `200` (`comedorback/app/core/permisos.py:68`; solo API, no acredita renderizado UI) | |
| `cocinera3` | `cocinera` | `POST /asistencias (manual)` | `403 metodo_no_autorizado` (`comedorback/app/core/autorizacion.py:163`) | |
| `cocinera3` | `cocinera` | `GET /intervenciones-cocina` | `403` (`comedorback/app/core/permisos.py:84`) | |
| `cocinera3` | `cocinera` | `GET /admin/cuentas` | `403` (`comedorback/app/core/permisos.py:78`) | |
| `jefa` | `jefa` | `POST /auth/login (temporal)` *(automático en A3)* | `428 cambio_password_pendiente` (`comedorback/app/api/auth.py:103`) | |
| `jefa` | `jefa` | `POST /auth/login (definitiva)` *(en A5 tras cambio en frontend)* | `200 debe_cambiar=false` (`comedorback/app/api/auth.py:115`) | |
| `jefa` | `jefa` | `GET /auth/yo` | `200 jefa rol=jefa debe_cambiar=false` (`comedorback/app/api/auth.py:194`) | |
| `jefa` | `jefa` | `GET /intervenciones-cocina` | `200` (`comedorback/app/api/intervenciones.py:101`) | |
| `jefa` | `jefa` | `POST /asistencias/lecturas/1/identificar` | `403 rol_no_autorizado` (`comedorback/app/core/autorizacion.py:108`) | |

## PARTE B: Huella no reconocida, identificación por `cocinera2` y consulta de la `jefa` (solo con Parte A aprobada)

Ejecutar únicamente si los controles de las 4 cuentas pasaron en la Parte A (`PASA`, `parte_a.completa=true`), con sus claves definitivas ya vigentes y la API QA activa en `http://127.0.0.1:8001`. **Limitación verificada en `develop` local:** `PantallaEnVivo` define `puedeIdentificar = false` por defecto (`comedorfront/src/components/secciones/PantallaEnVivo.jsx:205`) y `App.jsx` (`comedorfront/src/App.jsx:192`) no le pasa esa propiedad. Por ello esta versión del guion utiliza Postman para identificar la lectura como `cocinera2`; no se modifica el frontend ni se declara validado el flujo completo de aprobación desde el navegador.

| Paso | Acción del operador | Esperado (leído del código, archivo:línea) | Obtenido |
|---|---|---|---|
| B1. Mantener o levantar front | Si el frontend abierto en A4 sigue activo en `http://127.0.0.1:5173`, conservarlo; de lo contrario, ejecutar el bloque «Frontend» de abajo en otra consola. | Usa el front de `develop` con contenido igual al de `qa` y `VITE_API_URL=http://127.0.0.1:8001`. Abre `http://127.0.0.1:5173`. `comedorfront/src/config.js:14`. | |
| B2. Login en navegador (`cocinera2` y `jefa`) | Ingresar como `cocinera2` en una ventana del navegador y como `jefa` en otra sesión/perfil aislado, usando las claves definitivas definidas en el frontend durante Parte A. | Ambas sesiones ingresan directo (`200`, `debe_cambiar=false`). `cocinera2` abre «Pantalla en vivo»; `jefa` ve el panel con acceso a «Supervisión». `comedorback/app/api/auth.py:115`, `comedorfront/src/App.jsx:153`. | |
| B3. Simular huella no reconocida | `& $qaPython qa/prueba-basica/huella.py` antes de que venza el almuerzo del laboratorio. | Reloj compartido, comida actual=2, derecho vigente para `900001` y ninguna lectura QA anterior; UNA llamada a `registrar_marcacion(usuario_id=None, metodo='biometrico')` (simulación por software; no acredita falla física del lector). Respuesta `valido=false`, `motivo=no_identificado`, `lectura_id` guardado en `corrida.json`. `qa/prueba-basica/huella.py:19`, `comedorback/app/logica/marcacion.py:214`. | |
| B4. Postman: `cocinera2` identifica y confirma entrega | Importar colección, completar `base` y `lectura_id`, guardar en Vault `qa-cocinera2-actual` (clave cambiada en Parte A) y `qa-jefa-actual`. Ejecutar solicitudes 1 a 5. | Solicitud 1: login 200; solicitud 2 se omite; solicitud 3 (`POST /asistencias/lecturas/{{lectura_id}}/identificar`, `{"usuario_id":900001}` y cabecera `Idempotency-Key` UUID v4): 200 con `valido=true`, `resultado=registrada`, `reintento=false`; solicitud 4: replay idempotente `reintento=true`; solicitud 5: evento `lectura_biometrica:<id>` con `estado_final=racion_servida`, `via=identificacion_manual`, `resuelta_por_mi=true` (la consulta API no acredita por sí sola el renderizado visual, que se observa en la ventana de `cocinera2`). `comedorback/app/api/asistencias.py:89`, `comedorback/app/logica/intervencion.py:458`, `comedorback/app/api/pantalla.py:64`. | |
| B5. Navegador: consulta de la `jefa` | En la ventana de la `jefa`, abrir **Supervisión → Intervenciones de cocina**. | En la tabla de intervenciones aparece la fila del comensal `900001` (Almuerzo), columna «Cocinera» = `cocinera2` (`cuenta.nombre ?? cuenta.usuario`), decisión original «Rechazada · Huella no reconocida» y resultado final «Entrega registrada». `comedorfront/src/App.jsx:203`, `comedorfront/src/components/secciones/IntervencionesCocina.jsx:236`. | |
| B6. Verificación por API (`jefa`) | Ejecutar en Postman las solicitudes 6 (`6 - Login jefa`) y 7 (`7 - Registro de la jefa`: `GET /intervenciones-cocina?usuario_id=900001`). | Solicitud 6: 200, `rol=jefa`, `debe_cambiar=false`. Solicitud 7: HTTP 200 y una misma fila de `datos` cumple `resultado == 'registrada'`, `decision_original.lectura_id == {{lectura_id}}` y `cuenta.usuario == 'cocinera2'`. `comedorback/app/api/intervenciones.py:101`, `comedorback/app/consultas/intervenciones.py:109`. | |
| B7. Detener procesos | Cerrar sesiones en navegador, cerrar front y detener API con Ctrl+C; no enviar más solicitudes. | Finaliza el lanzador, compara huella antes/después y elimina `api.activa`; quedan disponibles los scripts de limpieza. `qa/prueba-basica/ejecutar_app.py:55`, `qa/prueba-basica/comun.py:196`. | |
| B8. Limpiar, simulacro | `& $qaPython qa/prueba-basica/limpiar.py` | Comprueba identidad y rol de las 4 cuentas (aceptando las creadas en la corrida), muestra conteos de corrida y totales antes/después sin cambiarlos, fecha a restaurar y huellas iguales. No DELETE ni UPDATE. `qa/prueba-basica/limpiar.py:44`, `qa/prueba-basica/limpiar.py:79`. | |
| B9. Limpiar, aplicar | Revisados los conteos: `& $qaPython qa/prueba-basica/limpiar.py --aplicar` | En **una transacción**, borra intervenciones de esa lectura, su asistencia y su lectura, luego sesiones/ingresos (`intentos_login`) de las 4 cuentas desde el inicio real. Restaura la fecha únicamente si fue movida. Las 4 cuentas quedan en `usuarios_sistema`. Conteos seleccionados finales=0. `qa/prueba-basica/limpiar.py:10`, `qa/prueba-basica/limpiar.py:79`. | |
| B10. Huella final | `& $qaPython qa/prueba-basica/comun.py --huella-final` | Corrida marcada `limpia` y huella actual exactamente igual a la inicial, incluyendo nombres y CHECKSUM de todas las tablas protegidas. `qa/prueba-basica/comun.py:493`. | |

### Opción: probar otra fecha

Solo si se eligió un ancla con fecha distinta de `fecha_original`, ejecutar estos pasos **después de crear el diario (paso A2) y antes de crear/resetear cuentas o levantar la API**. El reloj sigue siendo el de la misma ancla; refechar no lo modifica. Por omisión se toma la fecha actual del laboratorio, nunca la fecha real. Un `--fecha AAAA-MM-DD` explícito debe corresponder al día de laboratorio al operar.

| Paso opcional | Acción | Esperado (archivo:línea) | Obtenido |
|---|---|---|---|
| Simulacro | `& $qaPython qa/prueba-basica/refechar.py --dry-run` | Muestra fecha original y destino del laboratorio, sin UPDATE ni cambios al diario. `qa/prueba-basica/refechar.py:22`. | |
| Aplicar | `& $qaPython qa/prueba-basica/refechar.py` | Cambia solo `91739904` de `900001`, guarda destino y confirma derecho al almuerzo antes del commit; pasa por `refechado_pendiente` a `refechada`. Si ya coincide la fecha, omite el UPDATE. `qa/prueba-basica/refechar.py:22`, `comedorback/app/consultas/derecho.py:234`. | |

### Frontend (paso B1)

`wt-qa` no necesita instalar dependencias. Se usa `wt-develop/comedorfront`, cuyo contenido coincide con el frontend de `qa`. Los commits de QA pueden diferir por las herramientas; comparar el contenido del front, no exigir el mismo HEAD. Desde `wt-qa`, repetir:

```powershell
git diff HEAD develop -- comedorfront
git -C '../wt-develop' status --short -- comedorfront
```

Continuar solo si ambas salidas están vacías. En otra consola, ejecutar lo siguiente. `envFile:false` impide la carga de dotenv; `configFile:false` evita generar un archivo de configuración compilado fuera de QA. La caché de Vite se dirige a QA. No hay cambios al código del frontend.

```powershell
Set-Location 'C:/__Proyectos__/comedorynutriciónhospitalaria/wt-develop/comedorfront'
$env:VITE_API_URL = 'http://127.0.0.1:8001'
@'
import { createServer } from 'vite';
import react from '@vitejs/plugin-react';
const server = await createServer({
  configFile: false,
  envFile: false,
  plugins: [react()],
  cacheDir: '../../wt-qa/qa/prueba-basica/evidencias/vite',
  server: { host: '127.0.0.1', port: 5173, strictPort: true, open: false }
});
await server.listen();
server.printUrls();
'@ | node --input-type=module
```

No intentar registrar la huella con `POST /asistencias`: una sesión recibe 403 `biometrico_solo_lector` antes de cualquier escritura (`comedorback/app/api/asistencias.py:51`). No hay endpoint de lector en los routers de este HEAD.

**El encabezado muestra la fecha del navegador, solo como presentación** (`comedorfront/src/components/layout/Header.jsx:18`). Puede diferir de la fecha del laboratorio. La pantalla de cocina y la vista de supervisión usan el reloj del servidor: `App.jsx:115` pide el estado sin fecha; `PantallaEnVivo.jsx:283` pide marcaciones sin fecha; `PantallaEnVivo.jsx:400` pide la ficha del día sin fecha y `Supervision.jsx:181` junto con `IntervencionesCocina.jsx:90` consultan sin fijar fecha cuando se abren desde `App.jsx:203`. El backend resuelve los valores omitidos con `reloj.ahora()/hoy()` (`app/consultas/pantalla.py:237`, `app/api/pantalla.py:170`, `app/api/intervenciones.py:122`).

Antes de cada solicitud, la colección Postman y `cuentas.py` consultan `/salud` y cancelan si no declara las dos bases del escenario, entorno de desarrollo y revisión esperada (`e1a7c3b9d5f2`). Usar Postman de escritorio con Vault habilitado para scripts (`qa-cocinera2-actual`, `qa-cocinera2-nueva`, `qa-jefa-actual`), `pm.execution.skipRequest` y llamadas asíncronas; no ejecutar la colección con un runner que carezca de Vault. La colección exportada no contiene claves ni tokens.

## Tablas y alcance de la limpieza

| Circuito | Escrituras comprobadas en el código | Evidencia |
|---|---|---|
| Refechar/restaurar | UPDATE de una fila de `bd_turnos_escenario_demo.turnos_asignados` | Preparador `5cd80fa:scripts/preparar_escenario_sintetico.py:347`; manifiesto `0c9ae77:qa/manifiesto_escenario_2026-10-15.json`, asignación 91739904. |
| Alta/reseteo y cambio de clave | INSERT (solo en modo `admin` si `cocinera1` o `jefa` no existían) y UPDATE `bd_nutricion_escenario_sim.usuarios_sistema`: clave, `debe_cambiar`, `version_token`, `updated_at`; la semilla también reactiva. | `qa/prueba-basica/ejecutar_app.py:10`, `comedorback/app/semillas/admin.py:40`, `comedorback/app/logica/autenticacion.py:169`. |
| Login y cambio voluntario con access | INSERT `intentos_login`, tanto exitoso como fallido/bloqueado (5 fallos en 15 min bloquean la cuenta). | `comedorback/app/logica/autenticacion.py:104`, `comedorback/app/api/auth.py:129`. |
| Huella no reconocida/rechazos biométricos | INSERT `lecturas_biometricas`. Una huella no reconocida no crea asistencia. | `comedorback/app/logica/marcacion.py:173`, `comedorback/app/logica/marcacion.py:214`. |
| Identificación exitosa | INSERT `asistencias` + INSERT `intervenciones_lectura`, en una transacción. | `comedorback/app/logica/intervencion.py:458`. |
| Identificación rechazada | INSERT `intervenciones_lectura` para reglas de persona o conflicto de lectura/servicio. Errores previos de auth/cabecera/rol (como el 403 `rol_no_autorizado` de la jefa), inexistencia o clave reutilizada no agregan esa fila. | `comedorback/app/logica/intervencion.py:502`, `comedorback/app/api/asistencias.py:89`, `comedorback/app/core/autorizacion.py:101`. |
| Reintento idéntico | Solo SELECT; devuelve la fila previa. | `comedorback/app/logica/intervencion.py:458`. |
| Sesiones | No existe modelo/tabla de sesiones en este HEAD; JWT emitidos en memoria. `version_token` invalida tokens. | `comedorback/app/api/auth.py:48`, `comedorback/app/modelos/usuarios.py:36`, `comedorback/app/core/seguridad.py:139`. |

La limpieza no borra cuentas de `usuarios_sistema` (ni las preexistentes ni las creadas en el escenario), no restaura hashes ni revierte los cambios de clave: las 4 cuentas quedan como fijas del escenario. Se limpian los datos del ensayo (`intervenciones_lectura`, `asistencias`, `lecturas_biometricas` de la lectura e `intentos_login` de las 4 cuentas desde `inicio` con `id > max_intento_inicial`) y se restaura la fecha si fue movida. Las cuentas no se borran por API (`comedorback/app/api/admin.py:99`). Descartar los tokens de Postman y cerrar sesión en el navegador al acabar; nunca se almacenan contraseñas ni tokens en `corrida.json`.

Si existe una tabla `sesiones`, se admite únicamente un esquema reconocible con `id`, referencia inequívoca de cuenta (`username`, `cuenta_id` o `usuario_sistema_id`) y fecha (`fecha_hora`, `created_at` o `creada_en`). Si no coincide, se aborta para evitar borrar por una columna supuesta. `intentos_login` y `sesiones` se filtran por las 4 cuentas, fecha desde el inicio e ID mayor al máximo inicial, preservando filas previas incluso en el mismo segundo. No se borran lecturas o asistencias por fecha general.

El auditor permite solo los verbos/tablas del paso. Rechaza DDL, procedimientos, USE, comentarios ejecutables, CTE de escritura, SQL multitabla y sentencias múltiples. Se verifican triggers y FK externas para evitar efectos indirectos. Las tablas deben ser InnoDB y las nueve vistas deben apuntar a la demo. Se requieren permisos de lectura de metadata y CHECKSUM de **todas** las tablas protegidas: una huella parcial o NULL aborta. No hay escrituras a `bd_nutricion` o `bd_proyecto_backend` autorizadas.

El SHA-256 mostrado es propio de estas herramientas (JSON canónico de nombre→CHECKSUM completo). Comparar el inicio/final de esta corrida; no comparar su texto con el hash abreviado del manifiesto, que usa otra representación. Se conservan los CHECKSUM individuales en el diario.

## Fallos y nueva corrida

- `valido=false` con HTTP 200 no es una entrega. No marcar el paso como exitoso solo por su status.
- Cuatro respuestas `428 cambio_password_pendiente` en `cuentas.py --preparar` solo acreditan las claves temporales iniciales; la Parte A queda en `PENDIENTE` (`parte_a.completa=false`) hasta que el operador cambie las 4 claves en el frontend y ejecute `cuentas.py` para verificar identidad y permisos.
- Cinco intentos de login fallidos en 15 minutos bloquean la cuenta por 15 minutos (`423 cuenta_bloqueada`). `cuentas.py` no reintenta automáticamente credenciales fallidas. Si en el paso A5 se ingresó mal la contraseña definitiva de una cuenta o faltó cambiarla en el frontend, corregirla y repetir únicamente esa cuenta con `& $qaPython qa/prueba-basica/cuentas.py --solo <cuenta>`; si se requiere regenerar las temporales, detener primero la API activa con `Ctrl+C` y volver a ejecutar `& $qaPython qa/prueba-basica/cuentas.py --preparar`.
- Ante timeout o 503 (`resultado_incierto`) de identificación, conservar la UUID original y repetir con la misma cuenta/persona/lectura. La solicitud 3 conserva la clave si se vuelve a enviar; no generar otra clave para repetir la misma decisión. La 4 exige la clave previa y verifica `reintento=true`; si el primer intento no llegó a confirmar, el primer resultado recuperado puede ser nuevo (`reintento=false`), y se verifica el replay con otro envío de la 4.
- Si falla `refechar.py` o `huella.py` después de preparar su diario, no repetir a ciegas. El estado pendiente evita duplicaciones; ejecutar limpieza en simulacro para contrastar lo realmente persistido. El ID de lectura se guarda después de flush y antes del commit de la app. Si el commit falló o el proceso se cortó, limpiar admite que esa fila no exista.
- Si falta el ancla (diario del kit anterior) o el laboratorio salió de su ventana, limpiar primero y abrir otra corrida. No inventar un ancla al arrancar la API ni reemplazar `inicio` por la fecha de laboratorio.
- Si la limpieza se interrumpe tras commit, conservar `corrida.json` y repetir primero el simulacro. El alcance no cambia; es seguro aplicar nuevamente si las filas ya no existen y la fecha ya está restaurada.
- Una huella protegida distinta aborta. Puede deberse a actividad externa: detener la prueba y revisar; el checksum por sí solo no atribuye la causa.
- Si queda `corrida.lock` o `api.activa` tras una terminación forzada, comprobar manualmente que ese proceso QA terminó antes de retirar **solo ese archivo**. No matar procesos ajenos ni eliminar el diario. La comparación final del lanzador requiere parada normal; `comun.py --huella-final` vuelve a contrastar con la base registrada.
- Tras limpiar y verificar con `--huella-final`, archivar manualmente `corrida.json` en `qa/prueba-basica/evidencias/` con nombre único. Solo entonces empezar otra corrida con `--huella-base`. No archivar una corrida pendiente para eludir sus guardas.

## Verificación offline de esta entrega

Desde `wt-qa`, sin cargar configuración ni credenciales:

```powershell
$qaPython = 'C:/__Proyectos__/comedorynutriciónhospitalaria/wt-develop/comedorback/.venv/Scripts/python.exe'
Get-ChildItem qa/prueba-basica/*.py | ForEach-Object {
    & $qaPython -m py_compile $_.FullName
    if ($LASTEXITCODE -ne 0) { throw 'Falló py_compile' }
}
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
& $qaPython -m pytest qa/prueba-basica -q -p no:cacheprovider --confcutdir=qa/prueba-basica
```

Las pruebas offline no usan MySQL ni leen dotenv: ejercitan guardas, auditor (incluido un listener real con SQLite en memoria), exclusión de dotenv, diario, bloqueo, rol fijo por cuenta, comando único de preparación automática (`cuentas.py --preparar` / `ejecutar_app.py preparar`) con presentación única de temporales, uso en memoria para comprobar `428`, aborto ante API previa activa sin matar procesos ajenos, estado `PENDIENTE` separado del cambio definitivo en frontend y verificación posterior de identidad y permisos sin persistir secretos en `corrida.json`, aborto ante rol distinto o vínculo, cuentas opcionales ausentes al inicio y su conservación en limpieza, evaluación PASA/FALLA con respuestas HTTP simuladas (incluidos `--solo`, rechazo de `/salud` ajeno y ausencia de claves/tokens/mensajes arbitrarios en diario y consola), reloj corriendo, ancla compartida en dos procesos, seguridad en hora real y estados del flujo. No sustituyen la comprobación en vivo contra MySQL, la API real ni el navegador.
