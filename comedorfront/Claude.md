# CLAUDE.md — Frontend React: Sistema de Comedor y Nutrición Hospitalaria (Módulo Personal)

## Contexto

Aplicación principal del Sistema de Comedor y Nutrición Hospitalaria, cuyo usuario final es
la **jefa de nutrición** del hospital. Stack de producción: **React (frontend) + FastAPI
(backend, en `../comedorback`) + MySQL**.

Nació como mockup de alta fidelidad y ya no lo es: todas las pantallas consultan FastAPI y no
hay datos ficticios ni de respaldo. Cubre **únicamente el Módulo Personal / Comensales**
(control de acceso al comedor del personal).

La referencia de endpoints, adaptadores y reglas de presentación es `README.md`.

## Stack técnico

- React con Vite, componentes funcionales con hooks. Nada de componentes de clase.
- **Todo acceso HTTP pasa por `src/api.js`** (fetch nativo; la URL base está en
  `src/config.js`). Ningún componente hace peticiones directamente. `api.js` adapta el
  snake_case de la API a la forma que consume la UI y valida cada respuesta.
- Las reglas de negocio (derecho al turno, duplicados, horario, cupo, coeficientes de ración
  completa) las decide el backend. El frontend no las calcula ni guarda copias de ellas.
- Recharts para el gráfico de Resumen; ExcelJS y jsPDF (`src/exportaciones.js`) para las
  exportaciones de Reportes.
- `src/mockApi.js` solo re-exporta `api.js` por compatibilidad.

## Estructura funcional (sidebar + main)

Secciones del sidebar (`src/navegacion.js`):

0. **Checklist de comida** — pantalla principal de la cocinera mientras no esté
   el lector, a pantalla completa. Lista a quienes tienen derecho a la comida
   en curso (`GET /pantalla/checklist`: turno de 12 h o más, categorías
   permitidas; lo decide el servidor) y marca la entrega con
   `POST /asistencias/checklist` (`metodo='checklist'`, mismas reglas que la
   huella). Solo la misma cocinera deshace su marca, dentro de 5 minutos y con
   la comida abierta (`DELETE /asistencias/checklist/{id}`). El panel flotante
   cambia entre el checklist y Control Biométrico.
1. **Control Biométrico** — marcaciones en vivo, solo para la cocinera, en
   pantalla completa sin sidebar ni header. Las lecturas las registra el
   lector autorizado; el navegador nunca declara una marcación biométrica.
   «Huellas por identificar» (solo cocinera) sigue el
   servicio actual con `GET /pantalla/lecturas-por-identificar` y confirma la
   entrega con `POST /asistencias/lecturas/{id}/identificar` e
   `Idempotency-Key` (`src/identificacion.js`), sin nota ni motivo. La huella
   de un policía (vía libre, sin persona del padrón) llega como origen
   `racion_policia` y se muestra como «Policía registrado», con check.
2. **Supervisión del comedor** — tabla en vivo para la jefa: pestañas
   por comida (estado, aceptadas, rechazos, manuales), resumen de la pestaña
   con su período y las marcaciones del día (hasta 1000) con filtros por resultado
   (incluye «Manuales») y nombre, refresco cada 30 s y botón Actualizar.
   Sin «Autorizar» sobre las filas: la huella no reconocida la identifica la
   cocinera; aquí se ve su resultado final y, al pie, la consulta de
   intervenciones de cocina (`GET /intervenciones-cocina`), sin aprobaciones.
   Las raciones de policía van en su propio apartado «Policías», fuera de la
   tabla del personal; no aparecen en el Historial.
   Solo lectura: ningún control registra, autoriza ni modifica raciones.
3. **Resumen** — cupo del turno, raciones del día por categoría y lecturas del
   lector, cada conteo con su período (`GET /pantalla/estado`, `src/resumen.js`).
4. **Historial de comidas** — historial diario y mensual por comensal, paginado.
5. **Reportes** — formulario de Estadística por rango de fechas (`GET /reportes/informe`)
   con exportación a Excel y PDF.
6. **Reglas del sistema** — solo para sistemas: pestañas Horarios de comida y
   Derecho a comer para programar cambios con «vigente desde» (hoy o futuro) y
   motivo; solo se elimina lo programado (`GET|POST|DELETE /reglas/*`).
7. **Administración de cuentas** — solo para sistemas: tabla de cuentas
   (usuario, nombre, rol, vínculo, estado, último ingreso) con «Cambiar
   clave» y «Desactivar»/«Reactivar» con confirmación; «Nueva cuenta» desde el
   padrón o sin vínculo (`GET|POST /admin/*`). Root escribe la contraseña
   definitiva: la cuenta entra sin cambio obligatorio.
8. **Cuentas** — solo lectura para la jefa: usuario, nombre, rol, estado y
   último ingreso, sin las cuentas de sistemas (`GET /cuentas`).

El acceso es real (`POST /auth/login`, `GET /auth/yo`, `POST /auth/cambio-password`): la
sesión vive en `src/sesion.js` + `src/hooks/useSesion.js`, `api.js` firma cada petición con
`Authorization: Bearer` y convierte 401 en «Sesión expirada», 403 en «Sin permiso» y 428 en
cambio obligatorio de contraseña. Qué ve cada rol está solo en `src/permisos.js`: la
cocinera ve el Checklist de comida (su principal) y Control Biométrico, en pantalla
completa con su panel flotante de sesión (usuario, rol, cambio de pantalla, pantalla
completa y cierre de sesión); la jefa ve Supervisión, Resumen, Historial, Reportes y Cuentas (solo
lectura); sistemas ve Supervisión, Resumen, Historial, Reportes, Reglas del
sistema y Administración de cuentas; nadie ve Control Biométrico salvo la
cocinera, y un rol desconocido no ve nada. Ninguna sección se monta sin pasar
por esa guardia.

## Calidad visual (obligatorio, no negociable)

- Ningún control de formulario nativo (inputs, selects, botones, `input type="file"`) puede
  quedar visible sin estilizar.
- Todo botón: color de acento del sistema, estado `:hover` distinto, transición suave, cursor
  pointer.
- Paleta consistente en todas las secciones y en el header, a partir de
  `src/styles/tokens.css` — no introducir colores nuevos sin razón.
- La persona que usará esta app no es necesariamente técnica: texto legible (tamaños de
  fuente generosos), iconos claros y una interfaz que no se sienta recargada.

## Qué revisar antes de dar por terminado un cambio

- `npm test` (pruebas de contrato con fetch controlado) y `npm run build` en verde.
- La app corre con `npm run dev` sin errores ni warnings en la consola del navegador.
- Cada sección del sidebar es su propio componente; el estado compartido vive en `App.jsx`.
- Carga, respuesta vacía y error se muestran como estados distintos; nunca se rellenan con
  cifras de demostración.
