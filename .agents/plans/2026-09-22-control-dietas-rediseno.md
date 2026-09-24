## Goal

Rediseñar la pantalla Control de Dietas para que el trabajo diario pase de
recorrer ~142 filas a atender solo las excepciones, sin perder la tabla
completa para auditoría. Lo que hoy se ve en la captura (142 filas, 141 con
"Sin dieta asignada", scroll interminable) debe quedar en una vista secundaria.

## Success Criteria

- Al abrir la pantalla, lo primero visible son solo las camas que necesitan
  acción (sin dieta, cambios de hoy, suspendidas, sin clasificar); el resto
  queda a un toggle de distancia.
- Repetir las dietas estables de un servicio cuesta 1 clic, no N cargas
  manuales; cada repetición sigue siendo un hecho INSERT con motivo trazable.
- Ninguna dieta NPO ni suspendida se perpetúa por una acción masiva: las
  decisiones clínicas sensibles siempre son explícitas, una por una.
- Build limpio, tests en verde y captura con la pantalla nueva pintando datos
  reales.

## Context And Current Facts

- Pantalla actual: `comedorfront/src/components/secciones/ControlDeDietas.jsx`
  (+ `.css`), datos de `obtenerControlDietas` en `comedorfront/src/api.js`
  (valida y adapta `GET /pacientes/control`). Contadores del día completo ya
  existen (`total_camas, con_dieta, cambios_hoy` derivado, `sin_clasificar`).
  Filtros fecha + servicio con `useConsultaApi` y cancelación.
- Backend: `comedorback/app/consultas/control.py` (censo ∪ hechos del día,
  INSERT siempre, nunca UPDATE), `comedorback/app/api/pacientes.py`,
  `comedorback/app/esquemas/pacientes.py`. Tabla `dietas_cama`: una fila por
  hecho (fecha, momento, copias congeladas, `suspendida`, `motivo`).
- Datos reales verificados: 142 camas, 16 sin clasificar (6 filas de
  `servicios_nutricion` con `hoja_informe` NULL). Regla de conteo: ni
  suspendidas ni NPO suman al libro.
- Respuesta del hospital (2026-09-22): la continuidad de dietas **depende del
  servicio**. Unidad de carga y dispositivo no respondidos (van como supuestos).

## Constraints And Non-goals

- No se tocan Módulo 1 ni tablas del SIH / `bd_proyecto_backend` (solo
  lectura). En `dietas_cama` solo INSERT, jamás UPDATE (filosofía de hechos).
- Reglas visuales del repo: todo por `src/api.js`, tokens de
  `src/styles/tokens.css`, `Boton/AppSelect/Tarjeta/Etiqueta`, un `.css` por
  componente, castellano.
- No-go: continuidad implícita (asumir dieta sin hecho), NPO o suspensiones
  masivas implícitas, edición de datos del hospital, app móvil.

## Key Decisions

1. **Vista por defecto = pendientes, no inventario.** Cuatro grupos en orden:
   Sin dieta / Cambios de hoy / Suspendidas / Sin clasificar, con los
   contadores existentes. Toggle "Todas las camas" para auditoría.
   (Supuesto reversible: si la licenciada prefiere todo visible, el default se
   cambia en una línea.)
2. **Continuar por servicio, no global ni cama por cama.** Como la continuidad
   depende del servicio, la acción masiva es "Continuar dietas de [servicio]":
   inserta un hecho por cama con la última dieta vigente y motivo automático
   ("continúa dieta del DD/MM"). Excluye camas con hecho hoy, suspendidas, NPO
   y fuera de censo; informa qué se copió y qué quedó pendiente.
3. **Filas de 3 bloques, no 7 columnas.** Ubicación (servicio · pieza/sala ·
   cama) / Paciente (nombre + insignia M/F + historia) / Dieta (nombre +
   prescripción + nota + acción). La tabla de 7 columnas sobrevive solo en la
   vista "Todas" de escritorio.
4. **Búsqueda siempre visible** por cama o paciente ("¿qué tiene la cama 12?"),
   sobre lo ya cargado, sin consultas nuevas.

## Recommended Approach

Frontend primero en lo visual (vista pendientes + filas de 3 bloques +
búsqueda, todo con datos ya disponibles: ningún endpoint nuevo), endpoint
masivo después, y al final el botón "Continuar servicio" cableado al endpoint.
La vista nueva no cambia la forma del adaptador de `api.js`, solo cómo
`ControlDeDietas.jsx` agrupa y muestra lo que ya recibe.

## Work Plan

1. **Front — vista pendientes.** Agrupar filas en los 4 grupos con contadores,
   toggle "Todas", búsqueda local por cama/paciente. Solo
   `ControlDeDietas.jsx` + `.css`.
2. **Front — filas de 3 bloques.** Reestructurar la fila (ubicación /
   paciente / dieta) manteniendo la forma del adaptador. Responsive: tarjeta
   en angosto.
3. **Back — `POST /pacientes/control/continuar`.** Body `{fecha?,
   servicio_nutricion_id}`. Por cada cama del servicio sin hecho hoy, con
   dieta vigente no-NPO, no suspendida y en censo: INSERT con
   `momento=now()`, motivo "continúa dieta del DD/MM". Responde
   `{continuadas, omitidas, detalle}`. Esquema en `esquemas/pacientes.py`,
   lógica en `consultas/control.py`, ruta en `api/pacientes.py`.
4. **Front — botón Continuar.** Por grupo de servicio, con confirmación que
   liste cuántas se copiarán y cuáles quedan fuera (y por qué). Recarga el día
   al terminar.
5. **Limpieza.** Verificar que `Dietas.jsx` y Reportes no necesitan cambios;
   captura final con datos reales.

## Validation Plan

- `npm test` (33/33) y `vite build` limpio en cada unidad de front.
- Back: ciclo contra SIH real en un servicio chico — continuar, verificar N
  INSERT / 0 UPDATE, verificar que NPO/suspendidas/fuera-de-censo quedaron
  fuera, reintento idempotente (segunda llamada copia 0).
- Manual: captura con 142 camas reales mostrando que la vista por defecto
  contiene solo pendientes; probar búsqueda "cama 12"; probar toggle "Todas".
- El check de mayor riesgo es el de idempotencia del endpoint masivo (doble
  clic no duplica hechos del día).

## Risks / Rollback

- **Perpetuar dietas vencidas** (el riesgo clínico): mitigado excluyendo
  NPO/suspendidas y mostrando lo copiado; la licenciada confirma con la
  captura antes de usarlo a diario.
- **Doble ejecución del masivo**: mitigado por "sin hecho hoy → se omite";
  rollback = borrar los hechos con ese motivo y fecha (DELETE acotado +
  control, documentado en la etapa, nunca parte del flujo normal).
- Si la licenciada rechaza la vista pendientes, rollback de front = volver al
  toggle invertido (default "Todas"); una línea.

## Open Questions

- Unidad de carga (¿por servicio recorriendo u oficina global?) y dispositivo
  (¿celular en recorrida u oficina en PC?): sin respuesta — se asumió diseño
  que sirve a ambos (grupos por servicio + responsive). Confirmar con la
  licenciada antes de pulir móvil.
- ¿Algún servicio donde ni siquiera el masivo sirva (dietas 100 % nuevas a
  diario)? Si existe, ese servicio queda fuera del botón.
- Todo lo demás se resolvió con evidencia del repo (ver Context).
