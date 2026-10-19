# Prueba básica: Parte A (cuentas y permisos) y Parte B (escenario de tres comensales QA: registro normal, identificación por cocinera2 y consulta de la jefa)

**La prueba puede iniciarse a cualquier hora real.** El kit usa un reloj de laboratorio compartido, por omisión `2026-10-15T11:30:00`, dentro del almuerzo del manifiesto. Ese reloj sigue corriendo: lectura e identificación deben ocurrir entre las 11:00 y las 15:00 del laboratorio, con las 15:00 excluidas y dentro de la misma ventana efectiva. No se cambian los horarios ni el reloj del sistema operativo. Fuente: `comedorback/app/semillas/horarios.py:43`, `comedorback/app/consultas/servicio.py:100` y `comedorback/tests/reloj_prueba.py:17`.

El ensayo se divide en dos partes, donde **la Parte B depende de que la Parte A haya pasado completa**:
- **PARTE A (preparación automática, cambio de contraseña en frontend y pruebas de integración de identidad y permisos contra la API QA)**: huella base → preparación automática y comprobación de claves temporales (`cuentas.py --preparar`, que crea/resetea `cocinera1`, `cocinera2`, `cocinera3` con rol fijo `cocinera` y `jefa` con rol fijo `jefa`, muestra una vez cada temporal, levanta la API QA, verifica automáticamente los cuatro `428 cambio_password_pendiente`, guarda el estado pendiente en `corrida.json` y mantiene disponible la API) → login en frontend y cambio a contraseña definitiva por el operador en las 4 cuentas → verificación de identidad y permisos con `cuentas.py` → revisar resultados. Si la Parte A ya fue aprobada en una corrida previa y las 4 cuentas conservan sus contraseñas definitivas (`debe_cambiar=0`), la nueva corrida puede heredar esa evidencia con `comun.py --huella-base --conservar-cuentas-de <archivo>` sin resetear contraseñas. *Nota*: estos controles contra la API son pruebas de integración de cuentas y permisos; las pruebas unitarias offline (`pytest`) usan respuestas HTTP simuladas.
- **PARTE B (flujo operativo con tres comensales sintéticos, solo con Parte A aprobada)**: con los tres comensales preparados (`preparar_comensales.py --aplicar`) y la API y el front activos → sesiones de `cocinera2` y `jefa` autenticadas con sus claves definitivas en sesiones separadas del navegador → ejecutar separadamente (a) el registro normal reconocido de **QA 01** (`huella.py --caso qa01`, `usuario_id=900101`) y (b) la lectura no reconocida para el caso **QA 02** (`huella.py --caso qa02`, conservando `usuario_id=None` en `lecturas_biometricas` con `comensal_previsto_id=900102` en el manifiesto/diario) → identificación en el navegador como `cocinera2` seleccionando a `QA 02 IDENTIFICACION` (`LEG-QA02`, `900102`) y confirmando la entrega → consulta de la `jefa` en `Supervisión → Intervenciones de cocina` → comprobación automatizada de los tres casos y de la consulta de jefa (`verificar_casos.py`) → detener procesos → limpiar (`limpiar.py --aplicar`) → huella final (`comun.py --huella-final`).

**Distinción entre cuentas del sistema y comensales del padrón:**
- **Cuentas del sistema (`bd_nutricion_escenario_sim.usuarios_sistema`)**: `cocinera1`, `cocinera2`, `cocinera3` (`rol=cocinera`) y `jefa` (`rol=jefa`), todas con `usuario_turnos_id=NULL`. Se conservan sus cuentas y sus contraseñas definitivas.
- **Comensales sintéticos del padrón (`bd_turnos_escenario_demo` → `v_comensales`)**, definidos en `qa/prueba-basica/manifiesto_comensales_qa.json` sin tocar ni borrar a las personas existentes (`900001..900007`):
  - **QA 01 — Registro normal (`qa01`)**: `usuario_id=900101`, `login=qa01_normal`, `nombre="QA 01 NORMAL"`, legajo visible `LEG-QA01` (`personas.numero_tipo_salario` → `v_comensales.numero_item`), `carnet_identidad=SIM-900101`, `identificador_unico=SIM-ID-900101`, `asignacion_id=191739904` (turno `9001`, derecho al almuerzo `comida_id=2` en `2026-10-15`).
  - **QA 02 — Identificación (`qa02`)**: `usuario_id=900102`, `login=qa02_identificacion`, `nombre="QA 02 IDENTIFICACION"`, legajo visible `LEG-QA02`, `carnet_identidad=SIM-900102`, `identificador_unico=SIM-ID-900102`, `asignacion_id=192739904` (turno `9001`, derecho al almuerzo `comida_id=2` en `2026-10-15`). Su lectura biométrica se registra con `usuario_id=None`; `cocinera2` selecciona después a `QA 02 IDENTIFICACION` (`LEG-QA02`) en el frontend.
  - **QA 03 — Reserva (`qa03`)**: `usuario_id=900103`, `login=qa03_reserva`, `nombre="QA 03 RESERVA"`, legajo visible `LEG-QA03`, `carnet_identidad=SIM-900103`, `identificador_unico=SIM-ID-900103`, `asignacion_id=193739904` (turno `9001`, derecho al almuerzo `comida_id=2` en `2026-10-15`). Queda preparado en reserva sin ejecutar todavía otro caso.

**Distinción entre resultados esperados y obtenidos:** las columnas «Esperado» de este guion documentan el comportamiento verificado en el código y los contratos; las columnas «Obtenido» permanecen vacías en la entrega offline y solo deben completarse con lo observado al ejecutar en vivo contra el escenario.

**Alcance y limitaciones verificadas:**
- **La consulta API de pantalla (`GET /pantalla/estado` o `GET /pantalla/ultimas-marcaciones`) solo acredita la respuesta del backend; no demuestra por sí sola que la interfaz gráfica se haya mostrado correctamente en el navegador.**
- **La huella no reconocida generada por `huella.py --caso qa02` es una simulación por software (`registrar_marcacion(usuario_id=None, metodo='biometrico')`); no acredita una falla física del lector biométrico.**
- **Identificación habilitada en QA:** `App.jsx` pasa `puedeIdentificarLecturas(rol)` a `PantallaEnVivo`. La cocinera puede seleccionar al comensal y pulsar «Confirmar entrega»; la jefa solo consulta las intervenciones. Las pruebas automatizadas no sustituyen la validación del recorrido real en navegador.

Solo usar el escenario dedicado y reservar `cocinera1`, `cocinera2`, `cocinera3` y `jefa` para esta corrida. Nadie debe cambiar sus datos o usar otra API sobre estas bases durante la prueba. No ejecutar el preparador histórico: se leyó con `git show`, no se incorporó al árbol.

## Preparación de las consolas

Desde PowerShell, establecer estas rutas (en cada consola nueva):

```powershell
$qaRoot = 'C:/__Proyectos__/comedorynutriciónhospitalaria/wt-qa'
$qaPython = 'C:/__Proyectos__/comedorynutriciónhospitalaria/wt-qa/comedorback/.venv/Scripts/python.exe'
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

## Transición desde la corrida v1 actual y preparación de los tres comensales QA

Si existe una `corrida.json` anterior en disco (como la corrida v1 con `parte_a` aprobada y `lectura_id=1` de `900001`), **cerrarla, limpiarla, verificar su huella final y archivarla antes de preparar los tres comensales y abrir la nueva corrida**, conservando la evidencia de cuentas aprobadas y **sin resetear sus contraseñas definitivas**:

1. **Detener la API QA activa**:
   En la consola donde corre la API QA, pulsar `Ctrl+C` y esperar a que termine limpiamente (verifica la huella protegida final y retira `qa/prueba-basica/api.activa`).
2. **Limpiar la corrida v1 actual (simulacro y aplicación)**:
   ```powershell
   & $qaPython qa/prueba-basica/limpiar.py
   & $qaPython qa/prueba-basica/limpiar.py --aplicar
   ```
3. **Confirmar la huella protegida final de la corrida v1**:
   ```powershell
   & $qaPython qa/prueba-basica/comun.py --huella-final
   ```
4. **Archivar `corrida.json` en `qa/prueba-basica/evidencias/`**:
   ```powershell
   New-Item -ItemType Directory -Force -Path qa/prueba-basica/evidencias | Out-Null
   $archivoPrevio = "qa/prueba-basica/evidencias/$(Get-Date -Format 'yyyyMMdd-HHmmss')-corrida-v1-parte-a.json"
   Move-Item qa/prueba-basica/corrida.json $archivoPrevio
   ```
5. **Preparar los tres comensales sintéticos (`QA 01`, `QA 02`, `QA 03`) en `bd_turnos_escenario_demo` (simulacro y aplicación idempotente)**:
   ```powershell
   & $qaPython qa/prueba-basica/preparar_comensales.py
   & $qaPython qa/prueba-basica/preparar_comensales.py --aplicar
   ```
   `preparar_comensales.py` valida el manifiesto `qa/prueba-basica/manifiesto_comensales_qa.json`, comprueba que no existan colisiones en `users`, `personas`, `usuario_servicios`, `turnos_asignados` ni `escenario_identificaciones` (nunca emite `UPDATE` ni `DELETE` y jamás toca `900001..900007`), inserta los tres comensales con sus legajos visibles (`LEG-QA01`, `LEG-QA02`, `LEG-QA03`) y verifica sus fichas en `v_comensales` y su derecho al almuerzo con `buscar_derecho`.
6. **Abrir la nueva corrida multi-comensal conservando la evidencia de Parte A aprobada (sin resetear contraseñas)**:
   ```powershell
   $qaReloj = '2026-10-15T11:30:00'
   & $qaPython qa/prueba-basica/comun.py --huella-base --reloj $qaReloj --conservar-cuentas-de $archivoPrevio
   ```
   Esto valida en `usuarios_sistema` que las 4 cuentas (`cocinera1`, `cocinera2`, `cocinera3`, `jefa`) siguen activas con `debe_cambiar=0` y sus mismos IDs, copia `verificacion_cuentas` y `parte_a: {"estado": "aprobada", "completa": true}` al nuevo `corrida.json` (`version=2`, `escenario="tres_comensales_qa"`), y permite pasar directamente a levantar la API QA (`& $qaPython qa/prueba-basica/ejecutar_app.py api --port 8001`) y ejecutar la Parte B sin regenerar temporales ni cambiar las contraseñas definitivas.

## Reloj compartido del laboratorio

`comun.py --huella-base --reloj AAAA-MM-DDTHH:MM:SS` guarda `reloj: {lab, real}` en `corrida.json`. Si se omite `--reloj`, usa `2026-10-15T11:30:00`. El formato es hora local sin zona. En cada proceso, `reloj.ahora()` se sustituye temporalmente por `reloj.real() + (ancla.lab - ancla.real)`; `reloj.hoy()` sigue esa hora. API, admin, lector, verificador y refechado imprimen `Reloj de laboratorio: <lab> (real: <real>)` antes de ejecutar su lógica.

El ancla se crea una vez y no se reinicia al levantar otro proceso. Todos deben ejecutarse en esta máquina, con la misma zona horaria y el mismo diario. Con el valor por omisión hay aproximadamente 3 horas y 30 minutos reales para completar la entrega, contados desde la creación del ancla. Si vence la ventana, detener la API, limpiar, verificar la huella final, archivar el diario y abrir otra corrida con una nueva ancla; no editar la existente.

`reloj.real()` y `reloj.real_utc()` permanecen intactos: login, bloqueo y JWT siguen en hora real (`comedorback/app/logica/autenticacion.py:28`, `comedorback/app/core/reloj.py:19`). `inicio` y `fin` del diario también son reales; la limpieza de intentos conserva su filtro real. `limpiar.py` no instala el reloj de laboratorio y puede limpiar diarios antiguos sin ancla.

El flujo normal conserva las tres asignaciones del **2026-10-15** (`191739904`, `192739904`, `193739904`): estado `iniciada`, `fecha_destino=null`, sin UPDATE de fecha. Cada caso ejecutable (`qa01` y `qa02`) registra su propio estado, `momento_lectura`, `lectura_id` y `asistencia_id` dentro de `corrida.json["casos"]`.

## PARTE A: Verificación de integración de cuentas y permisos (`cocinera1`, `cocinera2`, `cocinera3` y `jefa`)

> **Nota:** Si ya se completó la Parte A en la corrida anterior y se abrió la nueva corrida con `--conservar-cuentas-de $archivoPrevio` (sección «Transición desde la corrida v1 actual»), **omitir A3 y A4 para no resetear las contraseñas definitivas**, levantar únicamente la API QA con `& $qaPython qa/prueba-basica/ejecutar_app.py api --port 8001` y pasar directamente a la Parte B (o, si se desea revalidar los controles HTTP con las claves definitivas actuales sin resetearlas, ejecutar solo A5 `& $qaPython qa/prueba-basica/cuentas.py`).

| Paso | Acción del operador | Esperado (leído del código, archivo:línea) | Obtenido |
|---|---|---|---|
| A1. Elegir reloj | `$qaReloj = '2026-10-15T11:30:00'` | Instante del almuerzo de las asignaciones originales; todavía no escribe en la base ni crea el ancla. `qa/prueba-basica/comun.py:617`, `comedorback/app/semillas/horarios.py:43`. | |
| A2. Huella base y fijar ancla | `& $qaPython qa/prueba-basica/comun.py --huella-base --reloj $qaReloj` *(o con `--conservar-cuentas-de $archivoPrevio` si se hereda Parte A)* | Verifica los 3 comensales QA en `turnos_asignados` y `v_comensales`, verifica las cuentas en `usuarios_sistema` y crea `corrida.json` (`version=2`, `escenario="tres_comensales_qa"`) registrando `comensales` (`qa01`, `qa02`, `qa03`), `casos` (`qa01`, `qa02`), ancla `{lab, real}`, estado `iniciada` y CHECKSUM de todas las tablas protegidas. `qa/prueba-basica/comun.py:554`, `qa/prueba-basica/comun.py:706`. | |
| A3. Preparación automática y comprobación de temporales *(solo si no se heredó Parte A)* | En consola dedicada: `& $qaPython qa/prueba-basica/cuentas.py --preparar` (o `& $qaPython qa/prueba-basica/ejecutar_app.py preparar`). Tomar nota de las 4 claves temporales mostradas una única vez en consola. | Si hay una API anterior activa, aborta pidiendo detenerla con `Ctrl+C` sin matar procesos ajenos. Bajo las guardas y el bloqueo del diario, invalida antes del primer reseteo cualquier aprobación o resultado `PASA` previo (`parte_a: {"estado": "preparacion_pendiente", "completa": false}`). Valida las 4 cuentas, crea/resetea `cocinera1`, `cocinera2`, `cocinera3` (`rol=cocinera`) y `jefa` (`rol=jefa`), muestra cada temporal una vez en consola conservándolas solo en memoria, levanta la API QA, verifica automáticamente los cuatro `428 cambio_password_pendiente`, guarda resultados seguros en `corrida.json` y mantiene activa la API. `qa/prueba-basica/cuentas.py:555`. | |
| A4. Login en frontend y cambio a contraseña definitiva *(solo si se ejecutó A3)* | En otra consola, levantar el frontend (bloque «Frontend» de abajo), abrir `http://127.0.0.1:5173`, iniciar sesión sucesivamente con `cocinera1`, `cocinera2`, `cocinera3` y `jefa` usando la temporal de A3 y cambiar cada contraseña por la definitiva que elija el operador. | En cada cuenta, el ingreso con la clave temporal abre la vista obligatoria de cambio de contraseña (`428 cambio_password_pendiente`), el operador introduce y confirma su contraseña definitiva en el navegador (`POST /auth/cambio-password` → `200 debe_cambiar=false`), y la cuenta queda con su clave definitiva vigente. `comedorfront/src/App.jsx:144`, `comedorfront/src/components/auth/CambiarPassword.jsx:17`. | |
| A5. Verificar identidad y permisos tras el cambio | En una tercera consola (con la API activa): `& $qaPython qa/prueba-basica/cuentas.py` (admite `--base <url>` y `--solo <cuenta>`). | Valida `/salud` y exige que cada cuenta tenga su `428` previo registrado en `corrida.json`; solicita con `getpass` únicamente la contraseña definitiva (sin imprimir claves ni tokens y sin reintentar automáticamente credenciales fallidas), verifica `POST /auth/login (definitiva)` → `200 debe_cambiar=false`, `GET /auth/yo` y los controles de permisos por rol, muestra la tabla `Cuenta \| Control \| Esperado \| Obtenido \| PASA/FALLA` y guarda resultados seguros en `corrida.json` (`parte_a: {"estado": "aprobada", "completa": true}`). `qa/prueba-basica/cuentas.py:249`, `qa/prueba-basica/cuentas.py:478`. | |
| A6. Cierre si termina en Parte A | Si el ensayo termina tras revisar Parte A: cerrar el frontend, detener la API con `Ctrl+C`, ejecutar `& $qaPython qa/prueba-basica/limpiar.py`, luego `& $qaPython qa/prueba-basica/limpiar.py --aplicar` y `& $qaPython qa/prueba-basica/comun.py --huella-final`. | Borra `intentos_login` de las 4 cuentas desde `inicio`; verifica y conserva las 4 cuentas fijas en `usuarios_sistema`; marca `corrida.json` como `limpia` y confirma huella final idéntica a la base. Si Parte A aprobó (`parte_a.completa=true`) y se continúa con Parte B, omitir A6 y continuar en Parte B. `qa/prueba-basica/limpiar.py:10`, `qa/prueba-basica/comun.py:706`. | |

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

## PARTE B: Registro normal (`QA 01`), lectura no reconocida e identificación por `cocinera2` (`QA 02`), reserva (`QA 03`) y consulta de la `jefa`

Ejecutar únicamente con la Parte A aprobada (`parte_a.completa=true`), los tres comensales preparados en `bd_turnos_escenario_demo` (`preparar_comensales.py --aplicar`) y la API QA activa en `http://127.0.0.1:8001` (si no está corriendo, iniciarla en su propia consola con `& $qaPython qa/prueba-basica/ejecutar_app.py api --port 8001`).

| Paso | Acción del operador | Esperado (leído del código, archivo:línea) | Obtenido |
|---|---|---|---|
| B1. Mantener o levantar API y frontend | Con la API QA activa en `http://127.0.0.1:8001`, mantener el frontend en `http://127.0.0.1:5173` o ejecutar el bloque «Frontend» de abajo en otra consola. | Usa exclusivamente el frontend de `wt-qa` y `VITE_API_URL=http://127.0.0.1:8001`. Abre `http://127.0.0.1:5173`. `comedorfront/src/config.js:14`. | |
| B2. Login en navegador (`cocinera2` y `jefa`) | Ingresar como `cocinera2` en una ventana del navegador y como `jefa` en otra sesión/perfil aislado, usando sus contraseñas definitivas vigentes. | Ambas sesiones ingresan directo (`200`, `debe_cambiar=false`). `cocinera2` abre «Pantalla en vivo»; `jefa` ve el panel con acceso a «Supervisión». `comedorback/app/api/auth.py:115`, `comedorfront/src/App.jsx:153`. | |
| B3a. Ejecutar registro normal de `QA 01` | `& $qaPython qa/prueba-basica/huella.py --caso qa01` *(o `--normal`)* antes de que venza el almuerzo del laboratorio. | Verifica reloj compartido, comida actual=2 (almuerzo) y derecho vigente de `QA 01 NORMAL` (`usuario_id=900101`, `asignacion_id=191739904`); invoca `registrar_marcacion(sesion, usuario_id=900101, momento=momento, dispositivo='lector-prueba-qa', metodo='biometrico')`. Crea 1 lectura `aceptada` (`motivo=None`, `usuario_id=900101`) y 1 asistencia (`metodo='biometrico'`, `registrado_por_cuenta=None`), sin crear intervenciones de cocina. Guarda `lectura_id` y `asistencia_id` en `corrida.json["casos"]["qa01"]`. En «Pantalla en vivo» aparece la marcación válida de `QA 01 NORMAL`. `qa/prueba-basica/huella.py:102`, `comedorback/app/logica/marcacion.py:273`. | |
| B3b. Comprobar caso normal `QA 01` (opcional intermedio) | `& $qaPython qa/prueba-basica/verificar_casos.py --caso qa01` | Verifica en solo lectura que `QA 01` (`900101`) tiene exactamente 1 lectura `aceptada`, 1 asistencia `biometrico` (`registrado_por_cuenta=None`) y 0 intervenciones en `intervenciones_lectura`, y que `QA 03` (`900103`) permanece con 0 filas. `qa/prueba-basica/verificar_casos.py:34`. | |
| B4. Ejecutar lectura no reconocida para el caso `QA 02` | `& $qaPython qa/prueba-basica/huella.py --caso qa02` *(o `--no-reconocida`)* | Verifica derecho vigente del comensal previsto `QA 02 IDENTIFICACION` (`usuario_id=900102`, `asignacion_id=192739904`); invoca `registrar_marcacion(sesion, usuario_id=None, momento=momento, dispositivo='lector-prueba-qa', metodo='biometrico')`. Crea 1 lectura en `lecturas_biometricas` que **conserva `usuario_id=None`**, `resultado='rechazada'` y `motivo='no_identificado'`, sin crear asistencia todavía. Guarda `lectura_id`, `usuario_id=None` y `comensal_previsto_id=900102` en `corrida.json["casos"]["qa02"]`. `qa/prueba-basica/huella.py:102`, `comedorback/app/logica/marcacion.py:214`. | |
| B5. Navegador: `cocinera2` identifica a `QA 02` y confirma entrega | En la sesión de `cocinera2`, en «Huellas por identificar», abrir la lectura no reconocida creada en B4, buscar por nombre (`QA 02 IDENTIFICACION`) o por legajo visible (`LEG-QA02`), seleccionar a `QA 02 IDENTIFICACION — Administrativo (LEG-QA02)` y pulsar «Confirmar entrega» una sola vez. | Aparece «Entrega registrada» y la marcación pasa a entregada por cocina. La petición envía `POST /asistencias/lecturas/{id}/identificar` con `{usuario_id: 900102}` y `Idempotency-Key` UUID v4; responde HTTP 200, `valido=true` y `resultado=registrada`. La lectura original en `lecturas_biometricas` conserva `usuario_id=None`, `resultado='rechazada'` y `motivo='no_identificado'`; se inserta 1 asistencia vinculada (`usuario_id=900102`, `lectura_id`, `metodo='manual'`, `registrado_por_cuenta=cocinera2.id`) y 1 intervención `registrada` atribuida a `cocinera2`. `comedorfront/src/components/secciones/IdentificarLectura.jsx:238`, `comedorback/app/logica/intervencion.py:539`. | |
| B6. Navegador: consulta de la `jefa` | En la ventana de la `jefa`, abrir **Supervisión → Intervenciones de cocina**. | En la tabla de intervenciones aparece únicamente la fila del comensal `QA 02 IDENTIFICACION` (`usuario_id=900102`, Almuerzo), con el mismo `lectura_id` de B4, columna «Cocinera» = `cocinera2`, decisión original conservada «Rechazada · Huella no reconocida» y resultado final «Entrega registrada». `QA 01 NORMAL` (registro biométrico normal) y `QA 03 RESERVA` (sin ejecutar) no figuran en intervenciones de cocina. `comedorfront/src/components/secciones/IntervencionesCocina.jsx:236`, `comedorback/app/consultas/intervenciones.py:85`. | |
| B7. Comprobación automatizada de los casos y consulta de jefa | `& $qaPython qa/prueba-basica/verificar_casos.py` | En modo de solo lectura (0 permisos DML en el auditor), comprueba: (1) **Normal (`qa01`, `900101`)**: 1 lectura `aceptada`, 1 asistencia `biometrico` sin cuenta registradora y 0 intervenciones; (2) **Identificación (`qa02`, `900102`)**: 1 lectura originalmente `rechazada` (`no_identificado`, `usuario_id=None`), 1 asistencia vinculada (`lectura_id`, `registrado_por_cuenta=cocinera2.id`) y 1 intervención `registrada` atribuida a `cocinera2`; (3) **Consulta de jefa**: mismo comensal (`900102`) y `lectura_id`, decisión original conservada (`rechazada`/`no_identificado`) y resultado final `registrada` por `cocinera2`, con 0 intervenciones para `900101` y `900103`; (4) **Reserva (`qa03`, `900103`)**: 0 lecturas, 0 asistencias y 0 intervenciones. Actualiza `corrida.json` con `verificacion_casos` y estado `casos_ejecutados`. `qa/prueba-basica/verificar_casos.py:372`. | |
| B8. Detener procesos | Cerrar sesiones en navegador, cerrar front y detener la API QA con `Ctrl+C`; no enviar más solicitudes. | Finaliza el lanzador, compara huella protegida antes/después y elimina `api.activa`; quedan disponibles los scripts de limpieza. `qa/prueba-basica/ejecutar_app.py:55`, `qa/prueba-basica/comun.py:198`. | |
| B9. Limpiar, simulacro | `& $qaPython qa/prueba-basica/limpiar.py` | Comprueba propiedad estricta de todas las filas de `qa01`, `qa02` y `qa03`, identidad y rol de las 4 cuentas y fechas de las 3 asignaciones (`191739904`, `192739904`, `193739904`), mostrando conteos antes/después sin emitir DELETE ni UPDATE. `qa/prueba-basica/limpiar.py:67`. | |
| B10. Limpiar, aplicar | Revisados los conteos: `& $qaPython qa/prueba-basica/limpiar.py --aplicar` | En **una transacción**, borra la intervención de `qa02`, las asistencias de `qa01` y `qa02`, las lecturas de `qa01` y `qa02`, y las sesiones/`intentos_login` de las 4 cuentas desde `inicio` con `id > max_intento_inicial`. Restaura las fechas de las 3 asignaciones únicamente si fueron refechadas. Conserva en la base los 3 comensales QA, los comensales existentes (`900001..900007`) y las 4 cuentas con sus claves definitivas. `qa/prueba-basica/limpiar.py:217`. | |
| B11. Huella final | `& $qaPython qa/prueba-basica/comun.py --huella-final` | Corrida marcada `limpia` y huella protegida actual exactamente igual a la inicial en todas las tablas de `bd_proyecto_backend`. `qa/prueba-basica/comun.py:706`. | |

### Comprobaciones de `verificar_casos.py` (paso B7 — completar columna «Obtenido»)

| Bloque | Comensal / Cuenta | Control | Esperado | Obtenido |
|---|---|---|---|---|
| `QA 01` (Normal) | `900101` (`QA 01 NORMAL`, `LEG-QA01`) | `lecturas_biometricas`, `asistencias`, `intervenciones_lectura` | 1 lectura (`usuario_id=900101`, `resultado='aceptada'`, `motivo=None`), 1 asistencia (`metodo='biometrico'`, `lectura_id`, `registrado_por_cuenta=None`), 0 intervenciones de cocina | |
| `QA 02` (Identificación) | `900102` (`QA 02 IDENTIFICACION`, `LEG-QA02`) + `cocinera2` | `lecturas_biometricas`, `asistencias`, `intervenciones_lectura` | 1 lectura originalmente rechazada (`usuario_id=None`, `resultado='rechazada'`, `motivo='no_identificado'`), 1 asistencia vinculada (`usuario_id=900102`, `metodo='manual'`, `lectura_id`, `registrado_por_cuenta=cocinera2.id`), 1 intervención registrada (`resultado='registrada'`, `motivo_rechazo=None`, `cuenta_id=cocinera2.id`) | |
| Consulta de Jefa | `jefa` sobre `900102` | `app.consultas.intervenciones.listar` / `GET /intervenciones-cocina` | Mismo comensal (`usuario_id=900102`, `QA 02 IDENTIFICACION`) y mismo `lectura_id`; `decision_original` conservada (`resultado='rechazada'`, `motivo='no_identificado'`); `resultado='registrada'`, `resultado_final.entrega_registrada=true`, `estado_actual_lectura='resuelta'`, `cuenta.usuario='cocinera2'`; 0 intervenciones para `900101` y `900103` | |
| `QA 03` (Reserva) | `900103` (`QA 03 RESERVA`, `LEG-QA03`) | Estado de reserva | 0 lecturas, 0 asistencias y 0 intervenciones; turno y derecho al almuerzo disponibles en reserva | |

### Opción: probar otra fecha

Solo si se eligió un ancla con fecha distinta de `fecha_original`, ejecutar estos pasos **después de crear el diario (paso A2) y antes de levantar la API o ejecutar marcaciones**. El reloj sigue siendo el de la misma ancla; refechar no lo modifica. Por omisión se toma la fecha actual del laboratorio, nunca la fecha real.

| Paso opcional | Acción | Esperado (archivo:línea) | Obtenido |
|---|---|---|---|
| Simulacro | `& $qaPython qa/prueba-basica/refechar.py --dry-run` | Muestra fecha original y destino del laboratorio para las asignaciones del escenario (`191739904`, `192739904`, `193739904`), sin UPDATE ni cambios al diario. `qa/prueba-basica/refechar.py:22`. | |
| Aplicar | `& $qaPython qa/prueba-basica/refechar.py` | Actualiza las 3 asignaciones QA (`qa01`, `qa02`, `qa03`), guarda `fecha_destino` y confirma el derecho al almuerzo de los 3 comensales con `buscar_derecho` antes del commit; pasa por `refechado_pendiente` a `refechada`. `qa/prueba-basica/refechar.py:22`, `comedorback/app/consultas/derecho.py:234`. | |

### Frontend (paso B1)

Todo el circuito de pruebas se ejecuta dentro de `wt-qa`, rama `qa`: backend, frontend, dependencias, cachés, casos simulados y evidencias. `develop` conserva la versión limpia para integrar las correcciones funcionales validadas antes del paso a `main`.

```powershell
Set-Location 'C:/__Proyectos__/comedorynutriciónhospitalaria/wt-qa/comedorback'
python -m venv .venv
& .venv/Scripts/python.exe -m pip install -r requirements.txt
Set-Location '../comedorfront'
npm.cmd ci --no-audit --no-fund
```

La instalación anterior se realiza una vez al preparar el entorno de QA. Para abrir el frontend, ejecutar el siguiente comando en otra consola. El lanzador exige la rama `qa`, fija la API local en el puerto 8001 y evita leer dotenv con `envFile:false`.

```powershell
Set-Location 'C:/__Proyectos__/comedorynutriciónhospitalaria/wt-qa/comedorfront'
npm.cmd run dev:qa
```

No intentar registrar la huella con `POST /asistencias`: una sesión recibe 403 `biometrico_solo_lector` antes de cualquier escritura (`comedorback/app/api/asistencias.py:51`). No hay endpoint de lector en los routers de este HEAD.

**El encabezado muestra la fecha del navegador, solo como presentación** (`comedorfront/src/components/layout/Header.jsx:18`). Puede diferir de la fecha del laboratorio. La pantalla de cocina y la vista de supervisión usan el reloj del servidor (`reloj.ahora()/hoy()`).

## Tablas y alcance de la limpieza

| Circuito | Escrituras comprobadas en el código | Evidencia |
|---|---|---|
| Preparación de comensales QA | INSERT idempotente en `bd_turnos_escenario_demo` (`users`, `personas`, `usuario_servicios`, `turnos_asignados`, `escenario_identificaciones`) para `900101`, `900102` y `900103`. Sin UPDATE ni DELETE. | `qa/prueba-basica/preparar_comensales.py:197`, `qa/prueba-basica/manifiesto_comensales_qa.json`. |
| Refechar/restaurar | UPDATE de las asignaciones del escenario en `bd_turnos_escenario_demo.turnos_asignados` (`191739904`, `192739904`, `193739904` en v2; `91739904` en v1). | `qa/prueba-basica/comun.py:617`, `qa/prueba-basica/refechar.py:22`. |
| Alta/reseteo y cambio de clave | INSERT (solo si `cocinera1` o `jefa` no existían) y UPDATE `bd_nutricion_escenario_sim.usuarios_sistema`: clave, `debe_cambiar`, `version_token`, `updated_at`. | `qa/prueba-basica/ejecutar_app.py:10`, `comedorback/app/semillas/admin.py:40`. |
| Login y cambio de clave | INSERT `intentos_login`, tanto exitoso como fallido/bloqueado. | `comedorback/app/logica/autenticacion.py:104`, `comedorback/app/api/auth.py:129`. |
| Caso `qa01` (registro normal reconocido) | INSERT `lecturas_biometricas` (`usuario_id=900101`, `resultado='aceptada'`) + INSERT `asistencias` (`usuario_id=900101`, `metodo='biometrico'`, `registrado_por_cuenta=None`). | `qa/prueba-basica/huella.py:102`, `comedorback/app/logica/marcacion.py:273`. |
| Caso `qa02` (lectura no reconocida) | INSERT `lecturas_biometricas` (`usuario_id=None`, `resultado='rechazada'`, `motivo='no_identificado'`). No crea asistencia en este paso. | `qa/prueba-basica/huella.py:102`, `comedorback/app/logica/marcacion.py:214`. |
| Identificación exitosa de `qa02` por `cocinera2` | INSERT `asistencias` (`usuario_id=900102`, `metodo='manual'`, `lectura_id`, `registrado_por_cuenta=cocinera2.id`) + INSERT `intervenciones_lectura` (`resultado='registrada'`, `cuenta_id=cocinera2.id`), en una transacción. | `comedorback/app/logica/intervencion.py:458`. |

La limpieza no borra cuentas de `usuarios_sistema` ni comensales de `bd_turnos_escenario_demo` (ni los preexistentes `900001..900007` ni los tres nuevos `900101..900103`), no restaura hashes ni revierte los cambios de clave: las 4 cuentas y los 3 comensales QA quedan como fijos del escenario reproducible. Se limpian únicamente los datos transaccionales de la corrida (`intervenciones_lectura`, `asistencias` y `lecturas_biometricas` de los casos ejecutados, más `sesiones`/`intentos_login` de las 4 cuentas desde `inicio` con `id > max_intento_inicial`) tras verificar estrictamente la propiedad de cada fila, y se restauran las fechas de las asignaciones si fueron refechadas.

## Fallos y nueva corrida

- `valido=false` con HTTP 200 no es una entrega. No marcar el paso como exitoso solo por su status.
- Si se conserva la Parte A desde una corrida previa (`--conservar-cuentas-de`), no ejecutar `cuentas.py --preparar`: ese comando está diseñado para regenerar claves temporales e invalidar la aprobación previa.
- Si falla `refechar.py` o `huella.py` después de preparar su diario, no repetir a ciegas. El estado pendiente por caso evita duplicaciones; ejecutar limpieza en simulacro para contrastar lo realmente persistido. Los IDs de lectura y asistencia se guardan después de `flush` y antes del `commit` interno de la app.
- Tras limpiar y verificar con `--huella-final`, archivar manualmente `corrida.json` en `qa/prueba-basica/evidencias/` con nombre único antes de abrir otra corrida con `--huella-base`.

## Verificación offline de esta entrega

Desde `wt-qa`, sin cargar configuración ni credenciales:

```powershell
$qaPython = 'C:/__Proyectos__/comedorynutriciónhospitalaria/wt-qa/comedorback/.venv/Scripts/python.exe'
Get-ChildItem qa/prueba-basica/*.py | ForEach-Object {
    & $qaPython -m py_compile $_.FullName
    if ($LASTEXITCODE -ne 0) { throw 'Falló py_compile' }
}
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
& $qaPython -m pytest qa/prueba-basica -q -p no:cacheprovider --confcutdir=qa/prueba-basica
```

Las pruebas offline no usan MySQL ni leen dotenv: ejercitan guardas, auditor (incluido un listener real con SQLite en memoria), exclusión de dotenv, diario v1 y v2 multi-comensal, bloqueo, manifiesto de los tres comensales QA y rechazo de colisiones, preparador idempotente `preparar_comensales.py` (simulacro, aplicación e idempotencia), conservación de Parte A aprobada sin resetear claves (`--conservar-cuentas-de`), ejecución separada de `qa01` (normal) y `qa02` (no reconocida con `usuario_id=None`) y rechazo de `qa03` (reserva), comprobaciones de `verificar_casos.py` (normal, identificación por `cocinera2`, consulta de jefa y reserva), limpieza multi-caso con validación estricta de propiedad, reloj corriendo y estados del flujo. No sustituyen la comprobación en vivo contra MySQL, la API real ni el navegador.
