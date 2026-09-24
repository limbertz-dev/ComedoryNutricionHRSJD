# CLAUDE.md — Frontend React: Sistema de Comedor y Nutrición Hospitalaria (Módulo Personal)

## Contexto

Aplicación principal del Sistema de Comedor y Nutrición Hospitalaria, cuyo usuario final es
la **jefa de nutrición** del hospital. Stack de producción: **React (frontend) + FastAPI
(backend, en `../comedorback`) + MySQL**.

Nació como mockup de alta fidelidad y ya no lo es: todas las pantallas consultan FastAPI y no
hay datos ficticios ni de respaldo. Cubre **únicamente el Módulo Personal / Comensales**
(control de acceso al comedor del personal). El módulo de Pacientes existe en el plan del
sistema pero todavía no se implementa.

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

1. **Control Biométrico** — marcaciones en vivo. El simulador del lector vive en el header y
   envía la misma marcación que el lector real (`POST /asistencias`, `metodo: 'biometrico'`);
   el registro a mano usa `metodo: 'manual'`.
2. **Resumen** — cupo del turno y consumo por categoría (`GET /pantalla/estado`).
3. **Historial de comidas** — historial diario y mensual por comensal, paginado.
4. **Reportes** — formulario de Estadística por rango de fechas (`GET /reportes/informe`)
   con exportación a Excel y PDF. «Reportes de pacientes» queda como pendiente hasta que
   exista ese módulo.

El acceso es real (`POST /auth/login`, `GET /auth/yo`, `POST /auth/cambio-password`): la
sesión vive en `src/sesion.js` + `src/hooks/useSesion.js`, `api.js` firma cada petición con
`Authorization: Bearer` y convierte 401 en «Sesión expirada», 403 en «Sin permiso» y 428 en
cambio obligatorio de contraseña. Qué ve cada rol está solo en `src/permisos.js`: la
cocinera ve Control Biométrico sin el «Modo manual»; jefa y sistemas, todo; un rol
desconocido, nada. Ninguna sección se monta sin pasar por esa guardia.

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
