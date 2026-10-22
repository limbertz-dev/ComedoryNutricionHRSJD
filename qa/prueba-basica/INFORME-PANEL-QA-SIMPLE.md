# Laboratorio QA: arranque y recorrido simplificados

Trabajo realizado exclusivamente en `wt-qa`, sin commit ni push. Se conservaron los cambios previos del worktree, las contraseñas, el diario del ensayo y las huellas vinculadas.

## Problema comprobado

El laboratorio y la API estaban encendidos. `GET /estado` respondía 503 porque la validación de QA 03 esperaba una reserva vacía: la lectura no reconocida del caso QA 02 se había identificado como QA 03, mediante otra cuenta distinta de la esperada por ese caso. Es una discrepancia del ensayo, no una caída de conexión. No se ha convertido ese resultado en aprobado ni se han borrado sus filas.

La comprobación en navegador detectó además que recargar el iframe podía perder el origen de la pantalla principal. El puente ahora valida el origen del padre y restablece la comunicación al cargar el panel.

## Resultado

- Un comando: `& ./qa/prueba-basica/probar.ps1 -SinClave`, desde `wt-qa`, con MySQL local encendido. Inicia laboratorio, API y frontend o reutiliza servicios QA saludables. No inicia otro ensayo ni resetea cuentas. Los servicios ajenos no se terminan; Ctrl+C solicita cierre normal del laboratorio propio y detiene únicamente los procesos creados por este lanzador.
- Cuatro botones de comida aplican su hora sugerida pausada; no limpian las marcaciones de otras comidas. Fecha/hora manuales quedan en un desplegable.
- Registro de huella, lectura normal, relectura para comprobar duplicados y fallo de huella. La identificación sigue siendo una operación explícita de la cocinera. La jefa solo consulta.
- La relectura usa la sesión autenticada y el endpoint QA existente. Doble clic no duplica el POST. Una respuesta incierta conserva cuenta, referencia y solicitud en la pestaña, incluso tras recargar el panel o expirar la sesión; requiere verificar antes de cambiar de comida o ensayo.
- Nuevo ensayo exige confirmación. El fallo del caso se informa dentro del estado sin convertirlo en desconexión; una excepción SQL sigue siendo un error de consulta. Reconectar renueva el control local y conserva datos.

## Cambios

`laboratorio.py`, `laboratorio/index.html`, `panel.js`, `panel.css`, `modal.js`; lanzador `iniciar-laboratorio.ps1`, nuevos `probar.ps1` y `arrancar_qa.py`; `test_arranque_simple.py`, `comedorfront/tests/laboratorio-qa.test.js`, `verificar_panel_simple_playwright.cjs` y `GUION.md`.

## Validación

- Suite Python del kit: **327 aprobadas**, 13 avisos de deprecación. Suite completa del frontend: **274 aprobadas**, ninguna fallida.
- Playwright: **7 controles aprobados**, capturas a 1366×768 y 1920×1080, Escape/foco, servicio con un clic, resultado incierto, reconexión y confirmación/cancelación de nuevo ensayo.
- Estado real consultado contra el laboratorio/API/MySQL, sin generar nuevas entregas. Las interacciones de escritura del verificador visual usan **respuestas HTTP interceptadas**; no acreditan nuevas entregas reales ni una nueva aprobación de los casos de negocio.
- El verificador compara byte a byte `corrida.json` y `huellas_simuladas.json`: quedan idénticos. No se captura ningún dedo físico.
- Comando único ejecutado con servicios ya abiertos: reutiliza laboratorio y frontend, código de salida 0. Sintaxis PowerShell y `git diff --check` correctos.

Evidencia final: `evidencias/panel-simple-2026-10-21T14-56-17-489Z/resultado.json`, `real-1366x768.png`, `real-1920x1080.png`, `interacciones-simuladas.png`.

## Estados de la interfaz

| Estado | Comportamiento |
|---|---|
| Consulta inicial | Informa que consulta; no genera lecturas sin estado válido. |
| Conectado | Muestra fecha, comida y resultado de cada caso. |
| Operación en curso | Bloquea acciones de escritura; permite salir del modal. |
| Huella faltante | Abre el registro de la persona exacta en la pantalla central. |
| Lectura registrada | Ofrece volver a leer y revisar la entrega. |
| Resultado incierto | Conserva solicitud e identidad y ofrece verificar. |
| Caso inconsistente | Muestra advertencia; no aprueba ni borra el resultado. |
| Error de consulta | Conserva lo mostrado y ofrece reconectar. |
| Nuevo ensayo | Explica qué limpia, requiere confirmar y permite cancelar. |

Se reutilizan tokens, tipografía y colores existentes; no se encontraron `DESIGN.md` ni `COPY.md` en `wt-qa`. Registro producto, variación 2, movimiento 1 y densidad 5. La escena es un operador de cocina que prueba el lector desde el mismo navegador. No se añadieron animaciones ni dependencia visual.

## Corrección posterior: pantalla vacía al recargar

El operador mostró una recarga con únicamente el texto del simulador. La aplicación de React no se había montado; el botón se inyectaba en el HTML de forma independiente. En una sesión nueva no se reprodujo espontáneamente ese fallo: cuatro cargas consecutivas mostraron login y estilos, sin errores JavaScript.

Sí se confirmó otra configuración incorrecta: la caché optimizada estaba en `qa/prueba-basica/evidencias/vite`, fuera del directorio que excluye el plugin de React. El log mostraba que Babel transformaba el bundle optimizado de ReactDOM (>500 KB). Se trasladó a `comedorfront/node_modules/.vite-qa`, ignorado por Git, con caché separada para QA. No se presenta este hallazgo como prueba de la causa exacta del fallo del navegador del operador.

El arranque QA sirve tokens visuales independientemente de React, evita conservar respuestas de desarrollo y muestra un aviso de carga con un enlace de recuperación. El simulador solo se hace visible cuando React monta la aplicación. Ante error o carga sin terminar, muestra «No se pudo cargar la aplicación» y «Volver a cargar»; no borra almacenamiento, contraseñas ni datos del ensayo.

Se reinició únicamente el frontend; API, laboratorio, diario y huellas permanecieron activos. El verificador `verificar_recarga_frontend_playwright.cjs` pasó **5 controles**: ubicación correcta de las dependencias, carga y tres recargas reales, fallo JavaScript provocado en el navegador, recuperación mediante el enlace y funcionamiento posterior del modal. Se compararon nuevamente los archivos del ensayo byte a byte. El verificador del panel volvió a pasar sus **7 controles**. `git diff --check` limpio.

Evidencias: `evidencias/recarga-front-2026-10-21T15-19-37-883Z/` y `evidencias/panel-simple-2026-10-21T15-19-38-000Z/`. El fallo JavaScript provocado es una prueba controlada, no una captura de la sesión del operador. No se hicieron commits ni cambios en develop/main.

### Ajuste visual del estado de carga

Se sustituyó el aviso inicial por un círculo giratorio centrado y «Cargando…». Durante la carga normal no se muestra el texto técnico ni el enlace de reintento. Ante fallo se detiene y oculta el círculo, y se muestra el aviso con «Volver a cargar». Se respeta la preferencia de movimiento reducido. El vigilante de arranque se carga de forma asíncrona e independiente del módulo principal, por lo que puede detectar una carga atascada.

Playwright: **6 controles aprobados**. Se retuvo el módulo principal para comprobar el círculo y el enlace oculto, se verificó el vigilante independiente y se liberó la carga hasta mostrar el login. Se mantienen los controles previos de recarga, error y recuperación, y la comparación byte a byte del ensayo y huellas. Evidencia: `evidencias/recarga-front-2026-10-21T16-35-50-345Z/cargando-circulo.png` y `resultado.json`. Se reinició únicamente el frontend de QA.
