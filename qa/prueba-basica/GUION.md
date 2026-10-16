# Prueba básica: huella no reconocida y entrega por cocinera2

**Solo funciona entre 11:00 y 15:00, con las 15:00 excluidas**, en la hora local del servidor. Lectura e identificación deben ocurrir en la misma ventana efectiva. No se modifica el reloj ni los horarios. Fuente: `comedorback/app/semillas/horarios.py:43`, `comedorback/app/consultas/servicio.py:100` y `comedorback/app/core/reloj.py:19`.

Código verificado: `qa` y `develop` en `15520eda5bb91daa0af62410da44a2e1b2f35c4e`. Esta entrega habilita la prueba; **no constituye una ejecución contra MySQL, navegador o lector físico**. Complete cada celda «Obtenido» al operar.

Solo usar el escenario dedicado y reservar cocinera2/cocinera3 para esta corrida. Nadie debe cambiar sus datos o usar otra API sobre estas bases durante la prueba. No ejecutar el preparador histórico: se leyó con `git show`, no se incorporó al árbol.

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

No usar ni abrir archivos `.env`, imprimir el entorno ni registrar las claves temporales. Si falta una variable requerida, la salida del script es únicamente su nombre. No se incluyen credenciales en los archivos entregados.

Todos los comandos Python usan guardas y `before_cursor_execute` global para ese proceso. Primero validan los nombres, después el marcador en una conexión **AUTOCOMMIT** (sin abrir una transacción de base de datos), la revisión, las vistas y la ausencia de triggers/FK externas. Solo entonces habilitan las escrituras permitidas y las transacciones. Ante un esquema inesperado abortan.

El lanzador `ejecutar_app.py` evita que `Configuracion` o `AjustesSeguridad` lean dotenv. Ejecuta la semilla original `app.semillas.admin --username X --rol cocinera --resetear` mediante `runpy`, sin cambiarla. Para esta prueba no ejecutar directamente `python -m app.semillas.admin` ni `uvicorn app.main:app`: esos procesos no llevarían el auditor y cargarían dotenv por defecto (`comedorback/app/core/config.py:23`, `comedorback/app/core/seguridad.py:48`).

## Registro de ejecución

Los archivos y líneas se refieren al código de `wt-qa`, salvo las referencias que incluyen un commit. Cada fila corresponde a un paso, en orden.

| Paso | Acción del operador | Esperado (leído del código, archivo:línea) | Obtenido |
|---|---|---|---|
| 1. Huella base | `& $qaPython qa/prueba-basica/comun.py --huella-base` | Verifica escenario y crea `corrida.json` **antes del primer login/reseteo**. Incluye CHECKSUM de todas las tablas de `bd_proyecto_backend`, fecha original, IDs de cuentas y límite inicial de intentos. Huellas antes/después iguales. `qa/prueba-basica/comun.py:129`, `qa/prueba-basica/comun.py:330`. | |
| 2. Refechar, simulacro | `& $qaPython qa/prueba-basica/refechar.py --dry-run` | Muestra únicamente asignación `91739904` de `900001`, fecha original y fecha destino; ninguna escritura SQL ni modificación del diario. `qa/prueba-basica/refechar.py:10`. | |
| 3. Refechar, aplicar | `& $qaPython qa/prueba-basica/refechar.py` (opcional `--fecha AAAA-MM-DD`) | Cambia solo `fecha` en esa asignación y confirma con `buscar_derecho` el almuerzo `2` por `91739904` **antes de confirmar la transacción**; si falta derecho, rollback. El diario preserva la fecha original. `qa/prueba-basica/refechar.py:10`, `comedorback/app/consultas/derecho.py:234`. Para ejecutar hoy, la fecha debe ser hoy. | |
| 4. Habilitar cocineras | Ejecutar los dos comandos del bloque «Cuentas» de abajo, con las variables ya fijadas. | La semilla reactiva la cuenta existente, genera clave temporal y aumenta `version_token`. La muestra una vez; `debe_cambiar=1`. El lanzador solo permite UPDATE de `usuarios_sistema`. `comedorback/app/semillas/admin.py:40`, `comedorback/app/logica/autenticacion.py:169`. | |
| 5. Levantar API | En consola dedicada: `& $qaPython qa/prueba-basica/ejecutar_app.py api --port 8001` | API de escenario en `http://127.0.0.1:8001`, sin reload/workers. `/salud` informa base sim, base demo y revisión `e1a7c3b9d5f2`. Auditor activo durante todo el proceso; al detenerlo compara huellas nuevamente. `qa/prueba-basica/ejecutar_app.py:10`, `comedorback/app/main.py:44`. | |
| 6. Levantar front | Ejecutar el bloque «Frontend» de abajo en otra consola. | Usa el front de develop del mismo commit y `VITE_API_URL=http://127.0.0.1:8001`. Abre `http://127.0.0.1:5173`. `comedorfront/src/config.js:14`. | |
| 7. Login y cambio en navegador | Entrar como `cocinera2` con la temporal y elegir clave propia. Conservarla solo en el gestor/Vault local. | Login temporal: 428; cambio: 200 y tokens nuevos. Login/intento fallido/bloqueado escriben `intentos_login`; cambio escribe `usuarios_sistema`. `comedorback/app/api/auth.py:92`, `comedorback/app/api/auth.py:129`, `comedorback/app/logica/autenticacion.py:104`. | |
| 8. Simular huella | Durante el almuerzo: `& $qaPython qa/prueba-basica/huella.py` | Comida actual=2, derecho vigente y ninguna lectura QA anterior; UNA llamada a `registrar_marcacion(usuario_id=None, metodo='biometrico')`. Respuesta `valido=false`, `motivo=no_identificado`, `lectura_id` visible y guardado. Dispositivo `lector-prueba-qa`. `qa/prueba-basica/huella.py:10`, `comedorback/app/logica/marcacion.py:214`, `comedorback/tests/lector_prueba.py:19`. | |
| 9. Postman: autenticar | Importar colección, completar `base` y `lectura_id`, guardar la clave actual en Vault como `qa-cocinera2-actual`. Ejecutar solicitudes 1 y 2. | Tras el cambio en navegador, login=200 y se omite la solicitud 2. Si devuelve 428, la 2 usa `qa-cocinera2-nueva` del Vault y guarda el nuevo access; volver a entrar en el navegador porque el cambio anula sus tokens. `comedorback/app/api/auth.py:92`, `comedorback/app/logica/autenticacion.py:169`. | |
| 10. Postman: confirmar | Ejecutar solicitud 3 dentro del mismo servicio. Cuerpo fijo `{"usuario_id":900001}`; pre-request genera UUID v4 una sola vez para esa lectura. | 200, `valido=true`, `resultado=registrada`, `asistencia_id` e `intervencion_id`. En el primer envío nuevo, `reintento=false`. Una asistencia y una intervención registrada; lectura original intacta. `comedorback/app/api/asistencias.py:89`, `comedorback/app/logica/intervencion.py:458`, `comedorback/app/consultas/servicio.py:100`. | |
| 11. Postman: repetir | Ejecutar solicitud 4, sin alterar cuenta, persona, lectura ni clave. | 200, `reintento=true`, mismos IDs; ninguna segunda ración. `comedorback/app/logica/intervencion.py:458`. | |
| 12. Consultar pantalla | Ejecutar solicitud 5 y mirar la pantalla de cocinera2 en el navegador. | Evento `lectura_biometrica:<id>`, decisión original `no_identificado`, `estado_final=racion_servida`, vía `identificacion_manual`, comensal 900001 y `resuelta_por_mi=true`. La pantalla muestra «Identificada por cocina». `comedorback/app/api/pantalla.py:64`, `comedorfront/src/components/secciones/PantallaEnVivo.jsx:623`. | |
| 13. Detener clientes/API | Cerrar sesión en navegador, cerrar front y detener API con Ctrl+C; no enviar más solicitudes. | Finaliza el lanzador, compara huella antes/después y elimina `api.activa`; quedan disponibles los scripts de limpieza. `qa/prueba-basica/ejecutar_app.py:10`, `qa/prueba-basica/comun.py:185`. | |
| 14. Limpiar, simulacro | `& $qaPython qa/prueba-basica/limpiar.py` | Muestra conteos de corrida y totales antes/después sin cambiarlos, fecha a restaurar y huellas iguales. No DELETE ni UPDATE. `qa/prueba-basica/limpiar.py:72`. | |
| 15. Limpiar, aplicar | Revisados los conteos: `& $qaPython qa/prueba-basica/limpiar.py --aplicar` | En **una transacción**, borra intervenciones de esa lectura (incluidos rechazos), su asistencia y su lectura, luego sesiones/ingresos de las dos cuentas desde el inicio. Restaura solo la fecha original. Conteos seleccionados finales=0. FK: `comedorback/app/modelos/comedor.py:419`, `comedorback/app/modelos/comedor.py:467`, `comedorback/app/modelos/comedor.py:319`. Implementación: `qa/prueba-basica/limpiar.py:72`. | |
| 16. Huella final | `& $qaPython qa/prueba-basica/comun.py --huella-final` | Corrida marcada limpia y huella actual exactamente igual a la inicial, incluyendo nombres y CHECKSUM de todas las tablas. `qa/prueba-basica/comun.py:330`. | |

### Cuentas

```powershell
& $qaPython qa/prueba-basica/ejecutar_app.py admin --username cocinera2
& $qaPython qa/prueba-basica/ejecutar_app.py admin --username cocinera3
```

Cada comando ejecuta la semilla original con `--rol cocinera --resetear`. No copiar su clave temporal al guion, a Git ni a un log. Se requieren las cuentas existentes y sin vínculo; no se crean ni borran cuentas. `cocinera3` puede permanecer con cambio pendiente si no participa.

### Frontend

`wt-qa` no necesita instalar dependencias. Se usa `wt-develop/comedorfront`, cuyo HEAD y ausencia de cambios de frontend se verificaron al preparar esta entrega. Antes de la prueba, repetir:

```powershell
git -C '../wt-develop' rev-parse HEAD
git -C '../wt-develop' status --short -- comedorfront
```

Continuar solo si el HEAD coincide con el indicado y no hay cambios en el front. En otra consola, ejecutar lo siguiente. `envFile:false` impide la carga de dotenv; `configFile:false` evita generar un archivo de configuración compilado fuera de QA. La caché de Vite se dirige a QA. No hay cambios al código del frontend.

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

La corrección se realiza por HTTP/Postman: `comedorfront/src/App.jsx:192` no entrega `puedeIdentificar` a `PantallaEnVivo`, cuyo valor por defecto es false (`comedorfront/src/components/secciones/PantallaEnVivo.jsx:205`). La visualización del resultado sí existe. No intentar registrar la huella con `POST /asistencias`: una sesión recibe 403 `biometrico_solo_lector` antes de cualquier escritura (`comedorback/app/api/asistencias.py:51`). No hay endpoint de lector en los routers de este HEAD.

Antes de cada solicitud, la colección consulta `/salud` y cancela si no declara las dos bases del escenario, entorno de desarrollo y revisión esperada. Usar Postman de escritorio con Vault habilitado para scripts, `pm.execution.skipRequest` y llamadas asíncronas; no ejecutar esta colección con un runner que carezca de Vault. La colección exportada no contiene claves ni tokens.

## Tablas y alcance de la limpieza

| Circuito | Escrituras comprobadas en el código | Evidencia |
|---|---|---|
| Refechar/restaurar | UPDATE de una fila de `bd_turnos_escenario_demo.turnos_asignados` | Preparador `5cd80fa:scripts/preparar_escenario_sintetico.py:347`; manifiesto `0c9ae77:qa/manifiesto_escenario_2026-10-15.json`, asignación 91739904. |
| Habilitación/cambio de clave | UPDATE `bd_nutricion_escenario_sim.usuarios_sistema`: clave, debe_cambiar, version_token, updated_at; la semilla también reactiva. | `comedorback/app/semillas/admin.py:40`, `comedorback/app/logica/autenticacion.py:169`, `comedorback/app/modelos/usuarios.py:36`. |
| Login y cambio voluntario con access | INSERT `intentos_login`, tanto exitoso como fallido/bloqueado; la validación de clave actual vuelve a llamar a ingresar. | `comedorback/app/logica/autenticacion.py:104`, `comedorback/app/api/auth.py:129`. |
| Huella no reconocida/rechazos biométricos | INSERT `lecturas_biometricas`. Una huella no reconocida no crea asistencia. | `comedorback/app/logica/marcacion.py:173`, `comedorback/app/logica/marcacion.py:214`. |
| Identificación exitosa | INSERT `asistencias` + INSERT `intervenciones_lectura`, en una transacción. | `comedorback/app/logica/intervencion.py:458`. |
| Identificación rechazada | INSERT `intervenciones_lectura` para reglas de persona o conflicto de lectura/servicio. Errores previos de auth/cabecera, inexistencia o clave reutilizada no agregan esa fila. | `comedorback/app/logica/intervencion.py:502`, `comedorback/app/api/asistencias.py:89`. |
| Reintento idéntico | Solo SELECT; devuelve la fila previa. | `comedorback/app/logica/intervencion.py:458`. |
| Sesiones | No existe modelo/tabla de sesiones en este HEAD; JWT emitidos en memoria. `version_token` invalida tokens. | `comedorback/app/api/auth.py:48`, `comedorback/app/modelos/usuarios.py:36`, `comedorback/app/core/seguridad.py:139`. |

La limpieza no borra cuentas preexistentes, no restaura hashes ni revierte los cambios de clave. Esos cambios permanecen y los contadores AUTO_INCREMENT pueden avanzar. Se limpian los datos del ensayo y se restaura la fecha. Las cuentas no se borran por API (`comedorback/app/api/admin.py:99`). Descartar los tokens de Postman y cerrar sesión en el navegador al acabar; no se almacenan contraseñas ni tokens en `corrida.json`.

Si existe una tabla `sesiones`, se admite únicamente un esquema reconocible con `id`, referencia inequívoca de cuenta (`username`, `cuenta_id` o `usuario_sistema_id`) y fecha (`fecha_hora`, `created_at` o `creada_en`). Si no coincide, se aborta para evitar borrar por una columna supuesta. `intentos_login` y `sesiones` se filtran por cuenta, fecha desde el inicio e ID mayor al máximo inicial, preservando filas previas incluso en el mismo segundo. No se borran lecturas o asistencias por fecha general.

El auditor permite solo los verbos/tablas del paso. Rechaza DDL, procedimientos, USE, comentarios ejecutables, CTE de escritura, SQL multitabla y sentencias múltiples. Se verifican triggers y FK externas para evitar efectos indirectos. Las tablas deben ser InnoDB y las nueve vistas deben apuntar a la demo. Se requieren permisos de lectura de metadata y CHECKSUM de **todas** las tablas protegidas: una huella parcial o NULL aborta. No hay escrituras a `bd_nutricion` o `bd_proyecto_backend` autorizadas.

El SHA-256 mostrado es propio de estas herramientas (JSON canónico de nombre→CHECKSUM completo). Comparar el inicio/final de esta corrida; no comparar su texto con el hash abreviado del manifiesto, que usa otra representación. Se conservan los CHECKSUM individuales en el diario.

## Fallos y nueva corrida

- `valido=false` con HTTP 200 no es una entrega. No marcar el paso como exitoso solo por su status.
- Ante timeout o 503 de identificación, conservar la UUID original y repetir con la misma cuenta/persona/lectura. La solicitud 3 conserva la clave si se vuelve a enviar. La 4 exige la clave previa y verifica `reintento=true`; si el primer intento no llegó a confirmar, el primer resultado recuperado puede ser nuevo (`reintento=false`), y se verifica el replay con otro envío de la 4. No generar otra clave para «arreglar» un resultado incierto.
- Si falla `refechar.py` o `huella.py` después de preparar su diario, no repetir a ciegas. El estado pendiente evita duplicaciones; ejecutar limpieza en simulacro para contrastar lo realmente persistido. El ID de lectura se guarda después de flush y antes del commit de la app. Si el commit falló o el proceso se cortó, limpiar admite que esa fila no exista.
- Si la limpieza se interrumpe tras commit, conservar `corrida.json` y repetir primero el simulacro. El alcance no cambia; es seguro aplicar nuevamente si las filas ya no existen y la fecha ya está restaurada.
- Una huella protegida distinta aborta. Puede deberse a actividad externa: detener la prueba y revisar; el checksum por sí solo no atribuye la causa.
- Si queda `corrida.lock` o `api.activa` tras una terminación forzada, comprobar manualmente que ese proceso QA terminó antes de retirar **solo ese archivo**. No matar procesos ajenos ni eliminar el diario. La comparación final del lanzador requiere parada normal; `comun.py --huella-final` vuelve a contrastar con la base registrada.
- Tras limpiar y verificar, archivar manualmente `corrida.json` en `qa/prueba-basica/evidencias/` con nombre único. Solo entonces empezar otra corrida con `--huella-base`. No archivar una corrida pendiente para eludir sus guardas.

## Verificación offline de esta entrega

Desde `wt-qa`, sin cargar configuración ni credenciales:

```powershell
$qaPython = 'C:/__Proyectos__/comedorynutriciónhospitalaria/wt-develop/comedorback/.venv/Scripts/python.exe'
Get-ChildItem qa/prueba-basica/*.py | ForEach-Object {
    & $qaPython -m py_compile $_.FullName
    if ($LASTEXITCODE -ne 0) { throw 'Falló py_compile' }
}
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
& $qaPython -m pytest qa/prueba-basica/test_guardas.py -q -p no:cacheprovider --confcutdir=qa/prueba-basica
```

Las pruebas no usan MySQL: ejercitan las guardas, el auditor (incluido un listener real con SQLite en memoria), exclusión de dotenv, diario y bloqueo. No sustituyen la comprobación en vivo de CHECKSUM, permisos, ventanas, transacciones MySQL ni Postman/navegador. No hacer commit ni push como parte de este guion.
