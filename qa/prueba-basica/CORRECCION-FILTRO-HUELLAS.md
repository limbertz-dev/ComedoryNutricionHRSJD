# Filtro del padrón y reconocimiento simulado

Fecha: 2026-10-19. Implementado exclusivamente en `wt-qa`, rama `qa`. Sin commit ni push.

## Causas comprobadas

- Los tres comensales sintéticos pertenecían a Administrativo. Ese perfil contradice la nueva regla de acceso solicitada.
- El alta conservaba correctamente una referencia sintética, pero los botones del laboratorio ejecutaban personas fijas: QA 01 para el normal y QA 02 para el fallo deliberado. Registrar a otra persona no cambiaba esos casos.
- El auditor QA confundía la función de texto SQL `REPLACE(...)` usada para normalizar acentos con una escritura. Ahora admite esa función dentro de SELECT; sigue rechazando `REPLACE INTO`, DML, múltiples sentencias y operaciones fuera de las listas permitidas.

## Política aplicada

Se consultaron los nombres de categorías y servicios del catálogo del hospital, en modo de solo lectura. La lista permitida usa los nombres existentes: `Medicos`, `Tecnicos`, `Internos`, `Residentes`, `Internos-Medicina`, `Internos-Bioquimica`, `Internos-Imagenologia`, `Internos-Fisioterapia`. Se normalizan mayúsculas, espacios exteriores y acentos.

Se excluyen Enfermera, Aux. Enfermeria, Interno-Enfermeria y Administrativo. Los perfiles desconocidos tampoco se autorizan. No se presupone que Manual, Mantenimiento o Camillero equivalgan a un área técnica autorizada o a policías. **Policías queda pendiente de identificar su equivalencia real**: ese nombre no apareció en categorías ni servicios. Se consultó al responsable sin inventar una asociación.

Categoría y Servicio filtran las personas devueltas por el servidor. El servicio mostrado es la asignación activa más reciente. Elegir un servicio no habilita una categoría excluida. El mismo criterio limita padrón, derecho, cupo y entrega; las comprobaciones de turno, fecha, comida, duración, novedades y duplicados permanecen. Ni la huella registrada ni una intervención de cocina pueden saltar la exclusión. Los registros históricos se conservan.

## Prueba desde la pantalla

1. Abrir `http://127.0.0.1:5173` con el frontend `dev:qa` y la API del laboratorio activa. Tras el reinicio del backend puede ser necesario ingresar otra vez; las contraseñas no se resetearon.
2. Pulsar **Nuevo**, filtrar por categoría/servicio y elegir expresamente una persona.
3. Pulsar **Simular captura**. El alta conserva una referencia; todavía no entrega comida.
4. Pulsar **Leer huella de prueba**. El servidor resuelve la referencia registrada y ejecuta la lógica real de marcación. La pantalla actualiza las marcaciones y el contador.
5. Pulsar **Volver a leer**. Si ya recibió esa comida en la fecha actual del laboratorio, se registra un rechazo por duplicado sin sumar otra ración. Ante una respuesta incierta, **Verificar lectura** conserva la solicitud y recupera su resultado sin reenviar una entrega distinta.

Para una primera entrega libre de consumos anteriores, utilizar un perfil sin consumo, por ejemplo QA 03, o abrir **Nuevo ensayo** con confirmación. El caso **Huella no reconocida** del modal sigue provocando el fallo a propósito: no indica pérdida del alta. No mezclar su resultado con la prueba de reconocimiento normal.

## Datos y aislamiento

Se aplicó `preparar_perfiles.py` a las tres identidades sintéticas, con comprobación estricta de identidad y colisiones e idempotencia. El inicio del laboratorio vuelve a comprobar estos perfiles:

| Comensal | Categoría | Servicio |
|---|---|---|
| QA 01 NORMAL | Medicos | MEDICINA INTERNA |
| QA 02 IDENTIFICACION | Tecnicos | LABORATORIO |
| QA 03 RESERVA | Internos | IMAGENOLOGIA |

Se conservaron cuentas, contraseñas, huellas y entregas. Las lecturas de referencias enroladas se registran en `lecturas_enroladas` del diario. La limpieza comprueba dispositivo, momento, usuario, comida, fecha, servicio, turno y relaciones antes de borrar IDs exactos; conserva las referencias. QA 03 utilizado por este circuito se informa como `USADO_EN_LECTURA_ENROLADA`, sin afirmar que sigue siendo una reserva intacta.

La interfaz de captura exige el arranque independiente `dev:qa` y el modo de desarrollo. El backend normal no monta las rutas `/_qa/enrolamiento`. No se modificaron los worktrees develop ni main. Registrar una referencia sintética no prueba captura física ni integración con ZKTeco.

## Evidencia y límites

- Consulta real de MySQL QA con auditor: padrón de tres perfiles y derecho a 3 × 4 comidas. El router se consultó con un actor fixture; no se usaron ni resetearon contraseñas del operador.
- Huella protegida antes/después idéntica: `989d8629d14c377fc800b920eab4b8021bacba4e3932b74c244a303e16701cd9`, 36 tablas.
- Pruebas SQL offline verifican categorías permitidas/excluidas, captura, reconocimiento por referencia, duplicados, cuatro comidas, recuperación idempotente, relaciones cruzadas, limpieza exacta y migración de perfiles.
- Navegador a 1920×1080 y 1366×768: filtros, selección explícita, captura, entrega normal, repetición rechazada y recuperación tras respuesta 503 perdida. Capturas y lecturas usan routers y lógica reales sobre SQLite temporal, con actor fixture. La sesión y las consultas visuales de pantalla se simulan; no es una prueba autenticada del operador ni de hardware. Evidencia: `evidencias/enrolamiento-visual-resultado.json` y `evidencias/enrolamiento-*-05-duplicado.png`.
- Build normal comprobado en navegador: captura QA oculta incluso con un marcador DOM de prueba.
- Suite QA offline: **280 pruebas aprobadas**, con 13 avisos de deprecación de dependencias. Frontend: **252 pruebas aprobadas**. Build completado; permanece el aviso de tamaño de bundles. `git diff --check` sin errores.

La corrida anterior se conservó durante la corrección de perfiles: QA 01 estaba comprobado y QA 02 mantenía una asistencia que no coincidía con la identificación esperada para 900102 por cocinera2. No se cambió esa evidencia ni se marcó como aprobada. El modal permite archivar el ensayo con confirmación.

## Recuperación desde el modal

El aviso genérico de huella faltante dejaba al operador sin un camino directo; además, registrar QA 03 no habilita los casos fijos QA 01/02. El estado ahora incluye persona, legajo y disponibilidad de huella por caso. Cuando falta, su botón abre el alta de esa persona exacta en el área central. **Simular captura → Continuar con el caso** regresa al mismo modal, refresca el estado y habilita la simulación. El alta no genera una entrega ni omite el requisito de huella.

El puente entre iframe y aplicación verifica origen, ventana emisora y correspondencia caso/usuario. Solo una pantalla de cocina con QA habilitado atiende la solicitud. Si no hay una sesión de cocina, el modal permanece abierto y pide iniciar sesión. No transmite tokens de sesión ni captura automáticamente una huella.

Validación de esta recuperación: **281 pruebas QA y 256 frontend aprobadas**. Navegador a 1920×1080 y 1366×768, partiendo de QA 03 enrolado y QA 01/02 pendientes: alta de ambos sin comida, vuelta al modal, una entrega normal y una lectura desconocida sin entrega. Alta por router real con actor fixture; sesión y consultas visuales interceptadas; simulación mediante transporte de prueba hacia la lógica real sobre SQLite temporal. No se ejecutó el control del laboratorio vivo ni se consumieron raciones de la base QA para esta comprobación. Evidencias: `evidencias/modal-enrolamiento-*-01-pendientes.png`, `evidencias/modal-enrolamiento-*-02-ejecutados.png` y `evidencias/validar_modal_enrolamiento.py`.
