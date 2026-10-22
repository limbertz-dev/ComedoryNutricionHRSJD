# Registro de huellas en Supervisión

Implementado y verificado en `wt-qa`, rama `qa`, el 2026-10-20. Sin commit ni push.

La jefa dispone de **Supervisión → Huellas registradas**, al pie de la sección. Cada fila muestra fecha del alta en hora de Bolivia, comensal vinculado con legajo e ID, categoría y servicio actuales, y la cuenta que realizó el alta original. Permite buscar por nombre, legajo, ID o cuenta, actualizar y recorrer páginas de 50 filas.

La consulta es independiente del día y de la comida seleccionada. El registro continúa disponible incluso si aún no existen marcaciones. Conserva los vínculos entre ensayos. Repetir una captura de la misma persona no cambia su fecha ni su cuenta registradora original.

## Contrato y permisos

- `GET /_qa/enrolamiento/registros`: solo jefa; cocinera y sistemas reciben 403. Sin sesión, 401. POST al listado no está disponible.
- Consulta el archivo persistente de vínculos existente y resuelve comensal y operador mediante consultas SQL de solo lectura.
- No retorna referencias del lector, solicitudes de idempotencia, plantillas, imágenes, claves ni tokens. La consulta de cuentas selecciona explícitamente ID, usuario y nombre; no carga hashes de contraseñas.
- Si una ficha o cuenta ya no existe, conserva la fila y su ID con una indicación de no disponible.
- Incluye vínculos anteriores aunque la categoría actual de la persona esté excluida del comedor: consultar un alta existente no concede derecho a una ración.
- El endpoint se instala solo en el laboratorio de desarrollo sobre las bases sintéticas; la sección se habilita en el frontend QA. Corresponde al enrolamiento simulado actual.
- La fecha y cuenta proceden del alta original. Nombre, categoría y servicio se resuelven desde el padrón actual: no representan una copia histórica de esos datos.

## Verificación

- **318 pruebas Python** aprobadas, incluidas cuatro nuevas con SQL real offline, persistencia y permisos.
- **269 pruebas frontend** aprobadas, incluidas cuatro nuevas para contrato HTTP, estados, vínculo visible y Supervisión sin consumos.
- Build de frontend correcto: 950 módulos; configuración sin dotenv. Se conserva el aviso de tamaño de algunos paquetes.
- **Playwright con API y datos reales QA: aprobado, salida 0.** Contrastó los cuatro vínculos existentes contra la tabla de la jefa y comprobó la denegación a cocina, búsqueda por teclado, error de conexión conservando filas, reintento y búsqueda vacía.
- Capturas a **1920×1080 y 1366×768**, sin desborde horizontal global.

Evidencia final: [resultado.json](evidencias/huellas-supervision-2026-10-20T23-33-01-037Z/resultado.json).

- [Vista 1366×768](evidencias/huellas-supervision-2026-10-20T23-33-01-037Z/1366x768.png).
- [Vista 1920×1080](evidencias/huellas-supervision-2026-10-20T23-33-01-037Z/1920x1080.png).
- [Error conservando datos](evidencias/huellas-supervision-2026-10-20T23-33-01-037Z/error-con-datos-conservados.png).
- [Búsqueda sin coincidencias](evidencias/huellas-supervision-2026-10-20T23-33-01-037Z/busqueda-vacia.png).

La prueba de navegador consulta los vínculos existentes: no captura huellas, registra comidas ni limpia ensayos. Los logins usan las cuentas QA existentes y conservan sus contraseñas. Las altas y reenvíos se cubren además con pruebas offline del preparador.

## Archivos de esta entrega

- `qa/prueba-basica/enrolamiento.py`: consulta paginada y resolución de identidades; endpoint de la jefa.
- `comedorfront/src/api.js`: cliente validado del registro.
- `comedorfront/src/components/secciones/HuellasRegistradas.jsx` y `.css`: tabla de consulta, búsqueda y estados.
- `comedorfront/src/components/secciones/Supervision.jsx` y `comedorfront/src/App.jsx`: montaje con permiso de jefa y activación QA.
- `qa/prueba-basica/test_registro_huellas.py` y `comedorfront/tests/huellas-registradas.test.js`: regresiones.
- `qa/prueba-basica/verificar_registro_huellas_playwright.cjs`: comprobación reproducible en navegador.
- `qa/prueba-basica/GUION.md`: instrucciones actualizadas.

Diseño: consulta de producto para la jefa en escritorio, con la tipografía, tokens y tabla del sistema. Variación visual 2/10, movimiento 1/10, densidad 6/10. Carga, vacío, error, resultado anterior, búsqueda y paginación disponen de estados explícitos y controles de teclado.

Para repetir desde `wt-qa`, con los servicios encendidos:

```powershell
node qa/prueba-basica/verificar_registro_huellas_playwright.cjs --visible
```
