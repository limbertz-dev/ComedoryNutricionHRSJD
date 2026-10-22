# Prompt para una sesión nueva de Codex

> Actualización: ya existe alta simulada persistente desde «Nuevo» en el área central. Inspeccionar `enrolamiento.py`, `RegistrarHuella.jsx`, sus pruebas y `evidencias/reporte-enrolamiento-central.md` antes de ejecutar este encargo; no duplicar esa implementación. Las fases de reintentos completos, reportes e integración física conservan las limitaciones indicadas en el informe actual.

Usar una sesión nueva; si reutilizas otra, `/clear` sí y pegar este documento completo. Un solo Codex implementa y valida; no requiere otros agentes.

---

Trabaja directamente como responsable de implementación del circuito de huellas del comedor hospitalario. El usuario autoriza completar el flujo en QA y corregir los defectos de reportes indicados abajo. Ejecuta el trabajo; no te limites a proponer un plan. Informa avances en español y entrega resultados verificables.

## Entorno y límites

- Único worktree autorizado: `C:/__Proyectos__/comedorynutriciónhospitalaria/wt-qa`, rama `qa`. Python exclusivo: `wt-qa/comedorback/.venv/Scripts/python.exe`; frontend: `wt-qa/comedorfront`. Nunca uses `wt-develop`, develop ni main.
- Último HEAD observado: `833a704fdc787cade2e1be7ec49a29558d125da0`. Hay cambios locales previos importantes del laboratorio y del frontend. Inspecciona el estado real, respétalos y trabaja encima de ellos sin descartarlos ni asumir árbol limpio.
- Puedes modificar dentro de este worktree el kit `qa/prueba-basica/` y los archivos de backend/frontend necesarios para este alcance, con pruebas. No publiques ni hagas commit, push, merge o limpieza de cambios ajenos.
- No leas `.env`, no pidas contraseñas por chat, no guardes claves/tokens/biometría real en diarios o evidencias. No resetees las contraseñas definitivas de cocinera1, cocinera2, cocinera3 o jefa.
- Datos sintéticos exclusivamente en `bd_nutricion_escenario_sim` y `bd_turnos_escenario_demo`. Conservar guardas, auditor por tabla/verbo, checksum de `bd_proyecto_backend`, bloqueo y escritura atómica de `corrida.json`, comprobaciones de propiedad, limpieza selectiva y evidencias manuales de fallas. No generalices permisos SQL para poder ejecutar migraciones sin revisión de su destino.
- No cambies `reloj.real()` ni `reloj.real_utc()` usados por autenticación. El reloj QA solo afecta negocio.
- No detengas ni reinicies procesos ajenos. Si hay una corrida activa, inspecciona primero su estado y conserva su evidencia. No ejecutes el pytest del backend indiscriminadamente: su conftest recrea una base `_test` y configura dotenv.

## Arranque obligatorio

Lee `qa/prueba-basica/INFORME-HUELLAS-Y-REPORTES.md` y reproduce `evidencias/auditar_flujo_reportes.py` si existe. Los archivos de evidencias están ignorados y pueden faltar en otra copia: en ese caso reproduce los defectos con una prueba offline propia; no des por ejecutada una evidencia ausente.

Lee `GUION.md`, `comun.py`, `laboratorio.py`, `laboratorio/`, `huella.py`, `limpiar.py`, `limpiar_fallido.py`, `verificar_casos.py`, `preparar_comensales.py`, `preparar_servicios.py`, el manifiesto y sus pruebas. Lee las lógicas `marcacion.py`, `intervencion.py`, las consultas `derecho.py`, `informes.py`, `intervenciones.py`, modelos, permisos, routers y componentes correspondientes.

El laboratorio ya se abre como modal en la misma página mediante `npm.cmd run dev:qa`. Permite Desayuno, Almuerzo, Té y Cena, fecha/hora QA y QA01 normal/QA02 no reconocida. Sus cambios no están registrados en un commit. No lo sustituyas por otra pestaña o una maqueta desconectada. Marcaciones del turno conserva su columna completa. La identificación usa el área central sin tarjeta envolvente. El bloque vacío de huellas pendientes se oculta.

## Resultado solicitado

La secuencia del operador debe ser:

1. Registrar/vincular una huella a una persona del padrón.
2. Leerla correctamente y registrar una comida si tiene derecho.
3. Leerla de nuevo en la misma comida y fecha, rechazar por duplicado y conservar el intento.
4. Simular huella no reconocida, volver a intentar dentro del mismo ensayo y, si sigue fallando, permitir identificación y confirmación por cocinera.
5. La jefa consulta quién confirmó y qué lectura originó la entrega.
6. Una persona excluida, por ejemplo enfermería con la regla de exclusión aplicable, sigue siendo rechazada aunque tenga huella vinculada y aunque cocina intente confirmar.
7. Pantalla, historial, reportes y exportaciones coinciden con las raciones reales.

La huella acredita identidad; nunca sustituye `buscar_derecho`. La unicidad sigue siendo persona + comida + fecha_comida, no una ración por toda la guardia. Categorías del comensal y roles de cuentas son conceptos distintos.

## Fase 1: enrolamiento simulado completo y contrato del lector

- Implementa en el modal QA una fase «Registrar huella de prueba»: seleccionar explícitamente una persona, generar/capturar un identificador sintético, confirmar y consultar su vínculo. No preseleccionar silenciosamente personas. Permitir consultar o revocar el vínculo de prueba con atribución y sin borrar historia de entregas.
- Usa un adaptador con operaciones claras de enrolar, reconocer y revocar. La implementación simulada debe estar rotulada como simulación y resolver el identificador a través del vínculo persistido; no puede ignorarlo y enviar un usuario_id elegido directamente.
- Enrolar no crea asistencia, no concede derecho, no cambia categoría ni turno. La misma referencia activa no puede pertenecer a dos personas; una referencia revocada no reconoce. Controlar colisiones y reintentos concurrentes en la persistencia, además de validaciones UI.
- Separa el catálogo sintético preexistente `escenario_identificaciones` del estado «enrolado por el operador». Tener un `SIM-ID-*` presembrado no significa que el operador haya registrado la huella. Inspecciona el esquema antes de reutilizarlo; crea almacenamiento QA propio si hace falta, con guardas y reconciliación, sin alterar tablas heredadas del hospital.
- La persona del padrón es el titular; no necesita una cuenta de acceso al sistema. Como diseño de alta operativa, propón/enmarca la captura supervisada por personal autorizado de sistemas y la participación del titular, sin dar por existentes permisos de enrolamiento que hoy no existen. Los controles exclusivos del laboratorio siguen aislados y protegidos en loopback.
- Conserva el rechazo `biometrico_solo_lector` para sesiones humanas. No abras un POST biométrico genérico que acepte usuario_id declarado por el navegador como si fuera prueba de una huella.
- No hay modelo/SDK/protocolo del lector físico confirmado. Completa la simulación y el contrato del adaptador, documenta exactamente qué dato falta para implementar el real. No inventes captura física, imágenes, plantillas ni matching biométrico, y no presentes un código de prueba como biometría real.

## Fase 2: ampliar escenarios dentro de la misma corrida

- Mantén los tres comensales QA existentes y sus identidades. Normal y duplicado usan la misma persona enrolada; el duplicado debe ocurrir sin limpiar o reiniciar el ensayo.
- Agrega controles explícitos para lectura reconocida, volver a leer/repetir comida y lectura no reconocida con su reintento. Distingue «Reintentar lectura» de «Nuevo ensayo»: reintentar conserva lecturas y asistencias; nuevo ensayo archiva y limpia solo datos propios.
- Para el caso de enfermería, crea una fixture adicional inequívocamente sintética si es necesario. No conviertas los QA existentes ni usuarios ajenos en enfermería durante una corrida; no cambies las reglas históricas para forzar un resultado.
- Un fallo conserva usuario_id=NULL y no_identificado. Ofrece volver a intentar antes del recurso a cocina sin inventar que una huella fallida revela una identidad. Si hay contexto explícito de captura, agrupa intentos con él; nunca por proximidad horaria o dispositivo compartido solamente.
- Reintento reconocido: el servidor aplica derecho y duplicados normalmente. Reintentos fallidos: cocina selecciona explícitamente del padrón y usa el endpoint de identificación existente. Si una entrega posterior resuelve el caso, otras lecturas no pueden producir otra ración.
- Conserva la lectura original, idempotencia UUID v4, control de doble envío, relaciones mutuas entre asistencia/intervención y bloqueo de identidad ante resultado incierto. No conviertas un 503 en una nueva entrega con otra clave.
- Cocina no puede autorizar un duplicado ni una persona sin derecho. Jefa solo consulta intervenciones, sin botones de aprobación.
- Actualiza el diario para múltiples lecturas por caso, verificadores y limpieza de forma compatible con corridas previas. Identificar exactamente qué filas son propias antes de borrar; reconciliar commit/rollback sin elegir arbitrariamente la última lectura. El simulacro de limpieza no escribe el diario.
- Mantén el modal en la página, servicios seleccionables y botones utilizables; si una condición impide una acción, explica la causa. No ocupes la columna de Marcaciones del turno con nuevos paneles.

## Fase 3: corregir y conciliar reportes

Se reprodujeron dos defectos con SQL y lógica reales sobre SQLite, no sobre MySQL:

1. `_columnas` en `app/consultas/informes.py` filtra CategoriaReporte.activo=1 y omite raciones históricas de categorías inactivas. Con dos asistencias, total_general=0 mientras grupos.servidas=2.
2. Mensual y rango filtran Comida.estado=1. Desactivar una comida con dos asistencias produce diario=2 y mensual=0.

Corrige la selección de categorías/comidas para incluir las usadas por asistencias del período aunque estén inactivas. No reasignes raciones históricas a categorías actuales, no ocultes el desfase modificando solo la cifra final y no sumes lecturas/intervenciones como raciones. Conserva filas, columnas, totales y coeficientes por fecha de forma coherente, incluyendo periodos sin datos.

Verifica `GET /reportes/registro-diario`, `/mensual`, `/gestion`, `/informe`, historial y consulta de intervenciones. La categoría congelada en asistencia se conserva aunque el padrón cambie. La consulta de intervenciones distingue decisión original y resultado final, y muestra cuenta responsable; no afirma que todos sus campos sean snapshots si consulta ficha actual.

Comprueba PDF y Excel generados por la aplicación con los mismos filtros y totales de la respuesta API. No basta comprobar que el botón descarga. La exportación debe contener lo mostrado y mantener categorías/comidas históricas inactivas.

## Validación y aceptación

- Reproduce enrolamiento previo, código desconocido, colisión, revocación y referencia ya vinculada. El alta nunca suma comida.
- Por cada servicio: normal=1 asistencia; repetición de la misma persona=0 adicionales; fallo sin identificar=0; entrega de cocina a otra persona con derecho=1. Con esa fixture básica aislada, el incremento final del reporte es 2; repetir la aprobación o el envío no lo aumenta.
- Prueba en fixtures separadas fallo seguido de lectura reconocida, fallos persistentes seguidos de cocina, intento de cocina sobre persona que ya comió, enfermería excluida por lector y por cocina, sin turno, fuera de horario, doble envío/concurrencia y fallo de red tras confirmar. No heredes aprobaciones manuales de un ensayo anterior.
- Repite Desayuno, Almuerzo, Té y Cena usando el reloj QA; incluye frontera de horario y servicio que cruce medianoche. No alteres la hora real de autenticación.
- Incorpora regresiones reales SQL para los dos defectos de reportes y conserva las suites actuales. Separa las pruebas SQLite de bloqueos, concurrencia y errores específicos de MySQL: no presentes SQLite como validación de esas garantías.
- Ejecuta pytest offline de qa/prueba-basica con el Python QA y --confcutdir=qa/prueba-basica, sin plugins externos ni lectura de dotenv; npm.cmd test; build con carga dotenv deshabilitada en el entorno QA; git diff --check.
- Verifica navegador con modal en la misma pestaña, selección explícita, reintentos sin reinicio y revisión de jefa. Aísla sesiones por perfil/contexto. No inventes credenciales ni cambies las del usuario. Si no hay sesión disponible, informa esa parte como pendiente; un fetch interceptado no acredita HTTP autenticado.
- Para el ensayo real usa solo las dos bases sintéticas y los permisos exactos necesarios. Conserva la evidencia previa antes de cualquier cierre selectivo. Hardware físico sigue pendiente hasta identificar el dispositivo y validarlo realmente.

Entrega un informe en `qa/prueba-basica/` con: archivos modificados, flujo utilizable y comandos exactos; matriz Esperado/Obtenido con evidencia; resultados offline, SQL real y navegador separados; conciliación de reportes/exportaciones; limitaciones del adaptador físico; git status y diff --stat. No pegues secretos ni declares completo lo que no ejecutaste. No hagas commit ni push.
