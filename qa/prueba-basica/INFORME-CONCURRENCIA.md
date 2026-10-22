# Concurrencia — verificación completada

Fecha: 2026-10-20. Worktree: `wt-qa`. Sin commit ni push.

**APROBADO: 8 de 8 casos contra la API y MySQL reales de QA, con navegador Playwright y huellas simuladas.**

Ejecución final: [resultado.json](evidencias/concurrencia-2026-10-20T23-11-56-426Z/resultado.json), `finalizado: true`, salida del proceso **0**. Fecha del escenario reproducible: 2026-10-19, con reloj de laboratorio pausado.

## Resultados

Cada caso comienza con un ensayo nuevo; los conteos no son acumulativos entre filas.

| Caso | Resultado comprobado | Lecturas | Entregas | Intervenciones |
|---|---|---:|---:|---:|
| Seis reenvíos con la misma clave | Misma lectura y asistencia; otra persona con esa clave recibe conflicto | 1 | 1 | 0 |
| Seis transacciones para una persona desde tres sesiones | Una entrega y cinco rechazos por duplicado | 6 | 1 | 0 |
| Tres personas concurrentes | Tres entregas, identidades correctas incluso con respuestas fuera de orden | 3 | 3 | 0 |
| Cierre del desayuno | Acepta a las 09:59:59; rechaza a las 10:00:00 | 2 | 1 | 0 |
| Doble clic en Confirmar entrega | Un solo POST y confirmación visible; cocinera2 responsable | 1 | 1 | 1 |
| Dos cocineras, una lectura y personas distintas | Una ganadora; conflicto de la otra conservado en auditoría | 1 | 1 | 2 |
| Identificación manual contra lectura biométrica | Una sola ración; el otro intento se rechaza por duplicado | 2 | 1 | 1 |
| Respuesta perdida después del COMMIT | «Verificar entrega» reutiliza clave y persona; recupera la misma asistencia | 1 | 1 | 1 |

Las barreras del adaptador QA confirmaron seis transacciones antes del INSERT (llegadas en 28,3753 ms), tres para personas distintas (10,4231 ms) y dos en el cruce manual/biométrico (0,5819 ms). Al liberar cada barrera, las transacciones compiten sobre las restricciones reales de MySQL. En la ejecución final del cruce ganó la entrega manual.

Se contrastaron los IDs y relaciones persistidas, el contador de raciones, la consulta HTTP autenticada de la jefa y su tabla en el navegador. La lectura no reconocida original conserva `usuario_id=NULL`, `resultado=rechazada` y `motivo=no_identificado`; la entrega manual y la cuenta responsable quedan en sus registros correspondientes.

## Fallos encontrados y corregidos

1. **Pantalla bloqueada tras una confirmación en desarrollo.** El efecto de `IdentificarLectura.jsx` marcaba el componente como desmontado durante la comprobación de StrictMode y no restablecía esa marca en el siguiente montaje. El resultado asíncrono se descartaba: podía persistir la entrega sin mostrar su confirmación ni «Verificar entrega». Cada montaje vuelve ahora a habilitar la recepción del resultado; el desmontaje real sigue descartando actualizaciones. Los casos 5 y 8 exigen la confirmación visible, además del resultado SQL.
2. **Conflicto de archivo en Windows.** Un lector concurrente del diario podía impedir `os.replace` con WinError 5. `guardar_corrida` conserva el archivo anterior y el temporal completo, y reintenta únicamente bloqueos Windows 5/32/33 durante menos de un segundo de espera programada. Un error persistente se propaga; no se informa éxito. Regresiones cubren recuperación transitoria y preservación del diario ante fallo persistente.
3. **QA 03 seguía clasificado como reserva al cerrar un ensayo concurrente.** Verificación y limpieza reconocen sus lecturas solo después de validar titularidad y relaciones; las filas ajenas siguen provocando aborto. La limpieza también contempla las intervenciones concurrentes verificadas.
4. **El Playwright suponía un cierre de desayuno incorrecto.** Ahora consulta la ventana efectiva del backend. La configuración real del escenario es 05:30–10:00; no se modificaron horarios para hacer pasar la prueba.

El adaptador nuevo `concurrencia.py` usa sesiones SQL independientes y bloqueos breves para actualizar el diario, sin serializar toda la transacción. Se instala solo con el arranque de laboratorio y exige bases sintéticas, entorno de desarrollo y rol de cocinera. Las identificaciones manuales usan el endpoint normal de la aplicación.

## Evidencias

Carpeta: [concurrencia-2026-10-20T23-11-56-426Z](evidencias/concurrencia-2026-10-20T23-11-56-426Z/).

- Ocho capturas de Supervisión: `01-jefa.png` a `08-jefa.png`.
- Cuatro capturas de la tabla de intervenciones: `05-intervenciones.png` a `08-intervenciones.png`.
- [Estado incierto y botón Verificar entrega](evidencias/concurrencia-2026-10-20T23-11-56-426Z/08-resultado-incierto.png).
- [Intervención final visible para la jefa](evidencias/concurrencia-2026-10-20T23-11-56-426Z/08-intervenciones.png).

Las ejecuciones fallidas anteriores se conservaron. No se presentan como aprobadas.

## Validación y aislamiento

- Python QA: **314 passed**, 13 advertencias de dependencias.
- Frontend: **265 pruebas aprobadas**.
- Aserciones del runner Node: **4 aprobadas**; rechazan falsos éxitos basados solo en HTTP 200.
- Build frontend: correcto, 948 módulos; conserva el aviso de tamaño de algunos paquetes.
- `git diff --check`: sin errores de formato; avisos de normalización LF/CRLF en archivos existentes.
- Base protegida `bd_proyecto_backend`: checksum de sus 36 tablas sin cambios, `989d8629d14c377fc800b920eab4b8021bacba4e3932b74c244a303e16701cd9`.
- Titularidad final contrastada: lectura **192**, asistencia **142**, intervención **29**, una entrega manual para QA 02 atribuida a cocinera2.
- Sin cambios en `develop` ni `main`. Se conservaron las cuentas, contraseñas y los cambios locales previos.

El frontend queda en `http://127.0.0.1:5173`, la API en `http://127.0.0.1:8001` y el laboratorio en `http://127.0.0.1:8002`, con el último caso disponible para revisión.

## Repetir

```powershell
Set-Location 'C:/__Proyectos__/comedorynutriciónhospitalaria/wt-qa'
node qa/prueba-basica/flujo_concurrencia_playwright.cjs --visible
```

Solicita las contraseñas definitivas con entrada oculta. No se guardan en código ni evidencias. Cada caso archiva y limpia las marcaciones verificadas del ensayo anterior; no operar el laboratorio simultáneamente. Un fallo detiene el script con salida distinta de cero.

**Límite de la aprobación:** valida el circuito software con datos sintéticos y transacciones reales. La demora y pérdida de respuesta se provocan en el transporte después de obtener la respuesta real del servidor. No acredita lectura biométrica física, rebote eléctrico del sensor ni capacidad máxima de usuarios por segundo. La prueba de respuestas fuera de orden verifica correspondencia entre solicitudes, respuestas y registros; no simula todos los posibles retrasos de las consultas de pantalla.
