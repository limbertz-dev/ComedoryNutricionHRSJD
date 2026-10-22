# Corrección de casos, automatización y servicio inicial

Trabajo realizado exclusivamente en `wt-qa`, rama `qa`, sobre HEAD `833a704`. Cambios locales, sin commit ni push. Se conservaron los cambios anteriores, las cuentas y sus contraseñas.

## Resultado de la corrección

- La pantalla consulta los horarios configurados: abre en la comida vigente o, durante un descanso, en la última ventana terminada. Antes del desayuno puede mostrar la cena del día anterior y consultar las marcaciones de esa fecha. El servicio cerrado se identifica como tal y no permite entregas fuera de horario. En QA se respeta el reloj elegido en el laboratorio.
- El modal también toma su servicio y hora del servidor; ya no tiene Almuerzo/12:00 preseleccionados mientras carga. Aplicar horario entre comidas del mismo día conserva las lecturas e intervenciones. Nuevo ensayo conserva su confirmación de archivo y limpieza.
- El diario conserva los casos y las revisiones por comida. Verificación, reconciliación y limpieza consideran todas las comidas y exigen propiedad exacta de las filas.
- Se recuperó la referencia perdida de la lectura 67 mediante ID, momento, comida y relaciones comprobados, con copia previa del diario. La recuperación no modificó filas de negocio. Después, el inicio de los ensayos automáticos archivó y limpió los ensayos previos mediante el procedimiento protegido.
- Playwright exige respuestas de negocio correctas, asistencia válida para una entrega y ausencia de asistencia en un rechazo. La comprobación de la jefa exige la intervención de la lectura exacta, el comensal 900102, `cocinera2`, resultado `registrada` y correspondencia de asistencia. Una tabla vacía falla. Se corrigieron selector y orden de columnas.
- Los scripts ya no contienen contraseñas o tokens fijos. Admiten entrada oculta o variables del proceso. No se guardan claves ni tokens en la matriz de resultados.

## Ensayo real contra QA y navegador

Fecha de negocio explícita del ensayo: 19/10/2026. Captura y lector simulados; API, autenticación, MySQL y operaciones del navegador reales, sin interceptar respuestas HTTP.

| Control | Evidencia obtenida | Resultado |
|---|---|---|
| Desayuno normal, QA 01 | Lectura 96, asistencia 77 | PASA |
| Segunda ración del mismo desayuno | Lectura 97, `duplicado`, sin asistencia | PASA |
| Descanso a las 10:30 | Desayuno cerrado visible; lectura 98, `fuera_horario`, sin asistencia | PASA |
| Almuerzo normal, QA 01 | Lectura 99, asistencia 78 | PASA |
| Alta de Administrativo y Enfermería | Ausentes del padrón; API devuelve 403 para ambos perfiles sintéticos | PASA |
| Huella no reconocida, QA 02 | Lectura 100; cocinera2 confirma entrega manual | PASA |
| Té, QA 03 | Lectura 101, asistencia 80 | PASA |
| Cena, QA 01 | Lectura 102, asistencia 81 | PASA |
| Consulta de la jefa | API y tabla muestran la intervención de lectura 100 por cocinera2 y conservan el rechazo original | PASA |
| Consolidado de Supervisión | Entregas de cada comida y rechazo por duplicado presentes | PASA |

La prueba adicional del panel cambió Cena → Desayuno → Almuerzo → Cena usando Aplicar horario: no solicitó `/nuevo`, conservó las lecturas enroladas y mantuvo la referencia 100 de Almuerzo. El laboratorio quedó en Cena, 19:00, reloj pausado.

La limpieza final se ejecutó solo en simulacro: identificó exactamente **7 lecturas, 5 asistencias y 1 intervención**, sin borrar ni modificar el diario. Se conservaron los resultados para revisión del operador. El checksum de las 36 tablas protegidas siguió siendo `989d8629d14c377fc800b920eab4b8021bacba4e3932b74c244a303e16701cd9`.

## Validación offline

- **300 pruebas QA aprobadas**. Incluyen SQL real sobre SQLite temporal: categorías excluidas con huella previa, rechazo de la identificación manual que intenta eludir la exclusión, turnos de 8 y 11 horas rechazados y límite de 12 horas aceptado. También cubren horarios, medianoche, versiones de horarios, conservación por comida, recuperación y limpieza. Estos controles se distinguen de la prueba de consumo contra MySQL.
- **265 pruebas del frontend aprobadas**: selección inicial de las cuatro comidas, consulta del último servicio y estado cerrado incluidos.
- **2 regresiones del verificador Playwright aprobadas**: tabla vacía/lectura ajena y cuenta/persona/resultado incorrectos fallan.
- Build completado: 948 módulos. Se conserva el aviso de bundles mayores de 500 kB. Pytest informa 13 avisos de deprecación de dependencias.
- `git diff --check` sin errores; Git informa conversiones LF/CRLF pendientes en algunos archivos del worktree.

## Evidencias y repetición

- `evidencias/revision-4comidas-resultados.json`: matriz e IDs reales del último circuito completo.
- `evidencias/revision-4comidas-supervision.png`: captura de Supervisión.
- `evidencias/panel-servicios-conservados.png`: panel después de cambiar entre comidas conservando el ensayo.
- `test_servicios_diario.py`, `test_perfiles_lectura.py`, `soporte_playwright.test.cjs` y `comedorfront/tests/servicio-inicial.test.js`: regresiones reproducibles.

Con laboratorio y frontend activos, desde `wt-qa`:

```powershell
node qa/prueba-basica/flujo_completo_4comidas_playwright.cjs --visible
```

El comando inicia otro ensayo y archiva/limpia el anterior mediante las guardas. Pide las contraseñas definitivas de forma oculta si no están en variables del proceso. La matriz distingue `APROBADO OFFLINE` de las verificaciones reales contra QA. La aprobación manual del operador y la integración con lector físico siguen siendo verificaciones distintas.
