# Revisión del circuito de huellas y de los reportes

> Este informe describe el estado previo al alta simulada. Posteriormente se implementó «Nuevo» con selección de persona y captura de prueba persistente en el área central; ver `evidencias/reporte-enrolamiento-central.md`. La captura física y los dos defectos de reportes descritos abajo siguen pendientes.

Fecha: 2026-10-19. Worktree: `wt-qa`, rama `qa`, HEAD `833a704` con cambios locales previos del laboratorio. Esta revisión conserva esos cambios. No modifica el comportamiento de la aplicación, cuentas, reloj de una corrida ni bases MySQL.

## Dictamen

Hace falta incorporar una primera fase de alta y vinculación de la huella y ampliar el laboratorio para probar repeticiones y reintentos dentro del mismo ensayo. La lógica de entrega normal, duplicados, derecho y aprobación de cocina ya existe y se comprobó offline. Los reportes usan la fuente correcta, pero tienen dos defectos reproducidos de conservación del historial.

Registrar una huella identifica a una persona; no le concede derecho a comer. Se puede evitar que el operador filtre categorías al marcar, pero el servidor debe seguir comprobando categoría permitida, asignación, duración, novedades, fecha y comida. La categoría también es necesaria para los informes.

La regla existente excluye enfermería cuando la versión aplicable de `reglas_derecho.excluir_enfermeria` lo indica. No es una prohibición incondicional independiente de las versiones históricas.

## Qué existe y qué falta

| Paso solicitado | Encontrado | Resultado de esta revisión |
|---|---|---|
| Registrar la huella antes de consumir | No se encontró un módulo de enrolamiento, almacenamiento de referencia biométrica ni ruta de captura del lector en los routers de la aplicación. | Pendiente de desarrollar. |
| Asociar un código a una persona para simular | El preparador inserta códigos `SIM-ID-*` en `escenario_identificaciones`, con origen `simulado`. `huella.py` envía directamente el `usuario_id` del caso; no resuelve una huella registrada por el operador. | Es una preparación sintética; no acredita enrolamiento. |
| Huella reconocida con derecho | `registrar_marcacion` crea una lectura aceptada y una asistencia. | Comprobado offline con SQL y lógica reales. |
| Volver a pedir la misma comida | `ya_comio` comprueba persona + fecha de comida + comida. La tabla protege esa combinación con un índice único. | Rechazo `duplicado`, sin otra asistencia; el intento queda guardado. |
| Huella no reconocida | Conserva `usuario_id=NULL`, lectura rechazada y motivo `no_identificado`. | No crea ración. |
| Volver a intentar la lectura | Cada nueva marcación puede quedar registrada, pero no se encontró un circuito de captura con sesión de reintentos del lector. El botón «Repetir» del laboratorio reinicia el ensayo. | Falta una acción distinta: reintentar dentro del ensayo actual, conservando el primer fallo. |
| Cocina identifica y confirma | Solo cocinera; exige servicio, derecho, ausencia de duplicado e idempotencia. | Una asistencia manual atribuida a la cuenta y una intervención; la lectura original permanece intacta. |
| Jefa revisa la intervención | `GET /intervenciones-cocina` permite solo consulta de jefa y entrega decisión original, resultado final, persona, comida, momento y cuenta responsable. | Verificado en código y por pruebas existentes; no hubo un nuevo ingreso autenticado de jefa durante esta revisión. |
| Enfermería con identidad reconocida | El derecho aplica la exclusión de categoría de la versión vigente para la asignación. La identificación manual usa el mismo derecho. | Rechazada por ambos caminos cuando está excluida. |

La unicidad corresponde a **persona + comida + fecha de la comida**, no a una sola comida por toda la guardia laboral. Alguien puede recibir desayuno y almuerzo si tiene derecho a ambos. Una guardia prolongada puede justificar desayunos en fechas distintas. Debe mantenerse esa distinción y el tratamiento de servicios que cruzan medianoche.

## Reportes y trazabilidad

Los informes diario, mensual, anual y por rango cuentan `asistencias`. Las lecturas rechazadas y las intervenciones rechazadas no son raciones. Una entrega de cocina crea una asistencia y suma una sola vez. No se debe sumar una intervención como si fuera otra entrega.

La categoría del informe se copia en la asistencia al servir. Cambiar después la categoría del padrón no debe reclasificar esa ración. La vista de intervenciones, en cambio, consulta parte de la ficha actual y debe distinguirse de una instantánea histórica completa. Además, la comida de la lectura original se reconstruye mediante horarios: la respuesta declara ese origen.

### Hallazgo 1: una categoría inactiva oculta raciones históricas

Ubicación: `comedorback/app/consultas/informes.py`, `_columnas` (línea 91) y construcción de filas/totales.

`_columnas` incluye únicamente categorías con `activo=1`. Las asistencias de una categoría desactivada siguen existiendo, pero no encuentran columna y se omiten de la suma. No se convierten automáticamente en «Sin clasificar».

Reproducción offline: dos asistencias válidas; desactivar su categoría en la base SQLite de prueba; `informe_rango.total_general` pasa de 2 a 0, mientras la suma de `grupos.servidas` sigue en 2. No se verificó que exista esa condición en MySQL actualmente.

Corrección necesaria: incluir las categorías referenciadas por raciones del período aunque estén inactivas, o una presentación histórica equivalente que conserve cada ración y su clasificación. Agregar regresiones de todos los informes y de sus exportaciones.

### Hallazgo 2: una comida inactiva hace divergir los informes

Ubicación: `comedorback/app/consultas/informes.py`, `informe_mensual` (línea 291) e `informe_rango` (línea 317).

Las filas de comida se obtienen filtrando `Comida.estado == 1`. Al desactivar una comida con asistencias históricas, el mensual y el informe por rango omiten sus raciones. El registro diario y el resumen anual sí las conservan si la categoría permanece visible.

Reproducción offline: dos almuerzos válidos; desactivar Almuerzo en la tabla fixture; diario = 2 y mensual = 0. No se cambió ningún catálogo real.

Corrección necesaria: mostrar también comidas consumidas en el período aunque estén inactivas, conservar coeficientes por fecha y conciliar las mismas fechas entre informes.

## Flujo que se debe implementar y probar

1. **Alta:** elegir una persona del padrón y registrar una referencia de huella, primero simulada en QA. Confirmar el vínculo y prevenir que el mismo identificador activo se asocie a otra persona. Esta operación no crea asistencias ni turnos.
2. **Lectura normal:** resolver la referencia registrada; el servidor evalúa el derecho; una aceptación crea una ración y su lectura.
3. **Repetición:** leer de nuevo a la misma persona, comida y fecha sin limpiar ni reiniciar; mostrar «Ya recibió esta comida», guardar el intento y mantener una sola ración.
4. **Primer fallo:** registrar la lectura no identificada y ofrecer volver a intentar. El resultado sigue siendo identidad desconocida; no se debe interpretar como falta de turno.
5. **Reintento:** si se reconoce, aplicar las mismas reglas. Si sigue fallando, permitir a cocinera identificar a la persona y confirmar la entrega. Todos los intentos originales permanecen.
6. **Intervención:** volver a comprobar derecho y duplicados; guardar responsable, momento, lectura y resultado; jefa solo consulta. Si no hay derecho o ya recibió comida, cocina tampoco puede concederla.
7. **Conciliación:** comparar raciones efectivas, pantalla, historial, intervenciones y reportes. Los rechazos no incrementan raciones; las entregas normales y manuales suman una vez.

No se debe relacionar una lectura desconocida con una persona por cercanía horaria. Para relacionar reintentos de la misma interacción hace falta un contexto explícito del adaptador/ensayo; sin él, se conservan como lecturas independientes.

El código sintético no es una plantilla dactilar y no prueba presencia del dedo. El lector físico, su modelo, SDK, protocolo y método de captura no están identificados en esta revisión. El laboratorio puede completar las pruebas de negocio con un adaptador simulado claramente rotulado; la integración física queda pendiente de esos datos y de una prueba con el dispositivo.

## Validación realizada

- `evidencias/auditar_flujo_reportes.py`: 15 controles cumplidos, incluidos dos defectos reproducidos. Ejecuta lógica real y consultas SQL sobre SQLite en memoria, con vistas materializadas como tablas fixture. Convierte tipos del esquema a tipos genéricos para SQLite. No prueba concurrencia, bloqueos o códigos de error de MySQL, HTTP autenticado ni hardware.
- Resultado estructurado: `evidencias/auditoria_flujo_reportes_resultado.json`.
- Suite QA offline: **238 passed**, 12 advertencias del adaptador de fechas SQLite. No se ejecutó el `conftest.py` del backend, que recrea una base `_test` y carga configuración dotenv.
- Suite frontend: `npm.cmd test`, **245 pruebas aprobadas**, ninguna fallida. Incluye contratos y presentación de informes e intervenciones; no sustituye revisar exportaciones reales con datos autenticados.
- `git diff --check`: código 0, sin errores de espacios; Git informa advertencias de conversión LF/CRLF en archivos preexistentes.
- Ninguna conexión real a MySQL, reinicio de procesos, lectura de `.env`, reseteo de contraseñas, commit ni push durante esta revisión.

Comando de reproducción puntual, desde `wt-qa`:

```powershell
& './comedorback/.venv/Scripts/python.exe' -B qa/prueba-basica/evidencias/auditar_flujo_reportes.py
```

## Archivos de referencia revisados

- `comedorback/app/logica/marcacion.py`: comida vigente, rechazo, duplicado, asistencia.
- `comedorback/app/consultas/derecho.py`: derecho y exclusión de enfermería por versión.
- `comedorback/app/modelos/comedor.py`: unicidad de ración y lectura, intervención y snapshots.
- `comedorback/app/logica/intervencion.py`: transacción e idempotencia de la entrega de cocina.
- `comedorback/app/api/asistencias.py` y `app/core/autorizacion.py`: restricciones de origen y roles.
- `comedorback/app/consultas/informes.py` y `app/api/reportes.py`: agrupaciones y endpoints.
- `comedorback/app/consultas/intervenciones.py` y `app/api/intervenciones.py`: consulta de jefa.
- `comedorfront/src/components/secciones/Reportes.jsx`, `InformeRaciones.jsx`, `LectorBiometrico.jsx` y adaptadores de `api.js`.
- `comedorback/tests/test_intervenciones.py`, `test_biometria_origen.py`: contratos existentes inspeccionados, no ejecutados en MySQL.
- `qa/prueba-basica/huella.py`, `preparar_comensales.py`, `laboratorio.py` y `laboratorio/panel.js`: límites actuales del simulador.
