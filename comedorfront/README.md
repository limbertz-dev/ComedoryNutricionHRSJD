# Sistema de Comedor y Nutrición Hospitalaria

Frontend React + Vite del módulo Personal / Comensales. Usa fetch nativo y
centraliza el acceso HTTP en src/api.js. No requiere librería HTTP adicional.

## Ejecutar

Desde comedorfront:

```powershell
npm.cmd install
npm.cmd run dev
npm.cmd run build
npm.cmd test
```

La URL de la API sale de src/config.js: por omisión http://127.0.0.1:8000, o la
de la variable VITE_API_URL si se define (por ejemplo, para el backend de
simulación en otro puerto):

```powershell
$env:VITE_API_URL = 'http://127.0.0.1:8001'; npm.cmd run dev
```

El backend debe permitir por CORS el origen de Vite (http://localhost:5173 o
http://127.0.0.1:5173). Su instalación se explica en ../comedorback/README.md.

## Integración disponible

| Función | Endpoint | Uso |
|---|---|---|
| iniciarSesion | POST /auth/login | 200 guarda tokens; 401 credencial, 423 bloqueo con reintento_en, 428 cambio obligatorio |
| cambiarContrasena | POST /auth/cambio-password + POST /auth/login | Cambio de contraseña temporal y reingreso con la nueva |
| obtenerUsuarioActual | GET /auth/yo | Rol de la sesión guardada al abrir la app |
| obtenerCuentas | GET /admin/cuentas | Todas las cuentas, con vínculo, nombre y último ingreso (Administración) |
| buscarCandidatos | GET /admin/candidatos | Personas del padrón para vincular, búsqueda de 2+ letras |
| crearCuenta | POST /admin/cuentas | Crea la cuenta desde el padrón {rol, usuario_turnos_id} o sin vínculo {rol, username, nombre}; 201 con clave_temporal |
| desactivarCuenta | POST /admin/cuentas/{id}/desactivar | Da de baja la cuenta y cierra sus sesiones |
| reactivarCuenta | POST /admin/cuentas/{id}/reactivar | Reactiva la cuenta |
| reiniciarClaveCuenta | POST /admin/cuentas/{id}/reiniciar-clave | Clave temporal nueva, se muestra una sola vez |
| obtenerCuentasLectura | GET /cuentas | Cuentas para la vista de solo lectura de la jefa (sin cuentas sistemas) |
| obtenerReglasDerecho | GET /reglas/derecho | Versión vigente y todas las versiones de parámetros |
| obtenerNovedadesDisponibles | GET /reglas/derecho/novedades | Tipos de novedad que se pueden marcar |
| programarReglasDerecho | POST /reglas/derecho | Programa una versión nueva (201) |
| eliminarReglasDerechoProgramadas | DELETE /reglas/derecho/{id} | Borra una versión programada (204) |
| obtenerHorariosVigentes | GET /reglas/horarios?fecha= | Horario vigente de cada comida en esa fecha |
| obtenerHistorialHorario | GET /reglas/horarios/historial?comida_id= | Todas las versiones de una comida |
| programarHorario | POST /reglas/horarios | Programa un horario nuevo, cierra el anterior (201) |
| eliminarHorarioProgramado | DELETE /reglas/horarios/{horario_id} | Borra un horario programado, reabre el anterior (204) |
| obtenerPersonal | GET /personal | Reúne páginas de 200 comensales para el selector |
| marcarAsistencia | GET /personal/{id} + POST /asistencias | metodo biometrico desde el simulador del lector, manual desde el registro a mano |
| autorizarMarcacionManual | POST /asistencias | Autoriza una huella no reconocida con {usuario_id, metodo: 'manual'} sin momento; muestra la respuesta del servidor |
| obtenerEstadoPantalla | GET /pantalla/estado | Comida vigente, cupo, totales del día y gráfico |
| obtenerUltimasMarcaciones | GET /pantalla/ultimas-marcaciones | Lecturas guardadas de hoy, incluidos los rechazos |
| obtenerDiaPersonal | GET /pantalla/dia-personal | Detalle del día de un comensal bajo la marcación |
| obtenerComidasDelDia | GET /pantalla/comidas-del-dia | Comidas del día con estado, servidas y rechazos por motivo (pestañas de Supervisión) |
| obtenerHistorialDiarioPersonal | GET /historial/diario | Historial diario, 50 registros por página |
| obtenerHistorialMensualPersonal | GET /historial/mensual | Totales mensuales, 50 registros por página |
| obtenerInformeRaciones | GET /reportes/informe | Informe de Estadística por rango de fechas (Reportes) |
| obtenerSalud | GET /salud | Entorno de la API y, en simulación, la hora del servidor |
| obtenerReloj | GET /simulacion/reloj | Hora del sistema y si está congelada (solo simulación, jefatura) |
| fijarReloj | PUT /simulacion/reloj | Fija fecha y hora, corriendo o congelada |
| avanzarReloj | POST /simulacion/reloj/avanzar | Adelanta el reloj (el simulador usa +15 min) |
| saltarAProximaFranja | POST /simulacion/reloj/proxima-franja | Salta al inicio de la próxima comida; 409 se muestra como mensaje |
| volverARelojReal | DELETE /simulacion/reloj | Devuelve el sistema a la hora real |

Supervisión (solo jefa y sistemas) muestra una pestaña por comida con su
estado, raciones servidas y rechazos, y una tabla en vivo con las últimas 100
marcaciones. Filtra por resultado y por nombre, se refresca cada 30 s y tiene
botón Actualizar con la hora del último refresco. «Autorizar» aparece solo en
la huella no reconocida: abre el selector del padrón y envía
autorizarMarcacionManual, mostrando el éxito o el rechazo que responda el
servidor.

Administración (solo sistemas) muestra la tabla de cuentas —usuario, nombre,
rol, vínculo, estado y último ingreso— con «Reiniciar clave» y
«Desactivar»/«Reactivar», cada acción con confirmación; en la propia cuenta no
aparece «Desactivar». «Nueva cuenta» se crea desde el padrón (el usuario es el
login del sistema de turnos, en solo lectura) o sin vínculo (usuario y nombre
a mano). La clave temporal se muestra una sola vez en el diálogo, con botón
Copiar, y nunca se guarda en el navegador.

Reglas del sistema (solo sistemas) edita horarios y parámetros del derecho
con vigencia por fecha: dos pestañas, Horarios de comida y Derecho a comer.
Horarios muestra lo que rige por comida, con «Programar cambio» («vigente
desde» hoy o futuro, con motivo) e historial por comida; Derecho a comer
lista las versiones (turno mínimo, novedades que anulan, enfermería) con la
vigente marcada. Solo se puede eliminar lo programado, con confirmación; el
pasado nunca se edita ni se borra.

## Modo simulación

Solo cuando GET /salud responde `entorno: "simulacion"`. En cualquier otro
entorno no se dibuja nada de esto y nunca se llama a /simulacion/*.

- El header muestra la franja SIMULACIÓN con la hora del servidor (jefa y
  sistemas; la cocinera no tiene header en su pantalla completa).
- Jefa y sistemas tienen además el reloj en el header de Supervisión: fijar
  fecha y hora, +15 min, próxima franja y volver a la hora real. Ya no está en
  Control Biométrico, que ahora solo ve la cocinera; el backend reserva
  /simulacion/* a jefatura.
- La fecha del header y el "hoy" de Control Biométrico, Historial y Reportes
  salen del reloj del servidor, nunca de la PC. Fuera de simulación siguen
  como siempre.

Adaptadores con pruebas pero sin pantalla que los use hoy: simularMarcacion
(alias de marcarAsistencia), obtenerPeriodos (GET /reportes/periodos),
obtenerRegistroDiario (GET /reportes/registro-diario), obtenerInformeMensual
(GET /reportes/mensual) y obtenerResumenGestion (GET /reportes/gestion).

**Registrar asistencia guarda datos reales.** Envía usuario_id (users.id), sin
seleccionar personas al azar. La API decide derechos, duplicados, horario y cupo.
La política de turnos de al menos 12 horas se valida en el backend, mediante
turnos.duracion_horas; el frontend no calcula ese derecho.

App.jsx mantiene el padrón y las marcaciones observadas en esta sesión. Consulta
el estado al entrar a las secciones y después de cada intento de marcación,
incluso tras rechazo o error de transporte. Ya no resta raciones ni usa el cupo
fijo de 8. **Actualizar datos** vuelve a consultar padrón y estado.

- previstas: null se presenta como **Sin límite cargado**; no equivale a cero.
- restantes: 0 se presenta como cupo agotado. El servidor decide el rechazo.
- fuera_de_horario: true muestra el aviso y deshabilita el registro.
- El gráfico conserva todas las categorías entregadas, incluida Sin clasificar.
- Lecturas aceptadas/rechazadas usa totales_del_dia; son lecturas biométricas.
  Las asistencias manuales sí suman a las raciones servidas, pero no a las lecturas.
- La lista lateral sale de /pantalla/ultimas-marcaciones y se vuelve a pedir
  tras cada marcación. La hora de la marcación recién enviada es la recepción
  local porque el POST no devuelve la hora.

## Sesión y roles

Los tokens van en sessionStorage (la PC es compartida: cerrar la pestaña cierra la
sesión). Toda petición lleva `Authorization: Bearer <access>`. Fuera del Login, un 401
borra la sesión y vuelve al Login con «Sesión expirada»; un 403 reemplaza la sección por
«Sin permiso» (nunca con datos); un 428 lleva al cambio de contraseña. El contrato no
trae endpoint de refresh ni de logout: `refresh` se guarda sin usarse y cerrar sesión
solo olvida los tokens.

| Rol | Secciones | Modo manual |
|---|---|---|
| cocinera | solo Control Biométrico, en pantalla completa | oculto |
| jefa | Supervisión, Resumen, Historial, Reportes y Cuentas (sin Control Biométrico) | — |
| sistemas | Supervisión, Resumen, Historial, Reportes, Reglas del sistema y Administración (sin Control Biométrico) | — |
| cualquier otro | ninguna («Sin permiso») | — |

La cocinera no tiene sidebar ni header: Control Biométrico ocupa toda la
ventana. Un botón flotante abajo a la derecha abre su panel de sesión: usuario
y rol, el simulador del lector, «Pantalla completa» (si el navegador la
soporta) y «Cerrar sesión». El «Modo manual» vive en Control Biométrico y
sigue oculto para ella; jefa y sistemas autorizan desde Supervisión con
«Autorizar».

Los nombres de los campos del cuerpo de login y de cambio de contraseña no están en el
contrato: viven solos en `cuerpoLogin` / `cuerpoCambio` de `src/api.js`.

## Historial y períodos

Los historiales usan las columnas comidas de cada respuesta, su paginación y
sus totales. El adaptador convierte recibida/no_recibida/pendiente/no_aplica al
formato visual existente, conservando también estadoApi. El mes se envía de 1 a
12; las fechas conservan el calendario local. No se inventan turnos ni comidas.

Los filtros de nombre, categoría y estado operan sobre la **página visible**;
los endpoints actuales no aceptan esos filtros. Los controles Anterior/Siguiente
muestran el total del servidor. Al cambiar período se vuelve a la primera página.
El detalle bajo una marcación busca al usuario entre las páginas del historial
diario, usando fecha_comida cuando está disponible.

Reportes muestra una sola vista, el formulario de Estadística, pedida por rango
de fechas a /reportes/informe: «este mes» y «esta gestión» son rangos. Un rango
sin raciones se presenta vacío, sin cifras de demostración. Excel y PDF salen de
ese mismo informe (exportarInformeExcel / exportarInformePdf). La vista no ofrece
pestaña ni acceso a «Reportes de pacientes»: llegarán con su módulo. El selector de
fechas, el período, Excel y PDF miden lo mismo (`--alto-control` en tokens.css) y la
línea secundaria del período (días o gestión) va en la misma fila: no agranda el control.

useConsultaApi cancela lecturas obsoletas al cambiar de período o desmontar una
vista. Carga, respuesta vacía y error son estados distintos. Hay reintento manual
para lecturas; no hay reintentos automáticos del POST ni datos ficticios de respaldo.

## Interfaz de jefatura

Supervisión, Resumen, Reportes y Cuentas comparten el lenguaje visual de
laaguilarsilva en verde: superficies planas de borde fino, controles compactos
(`--alto-control` de 46 px en las barras de reporte y `--alto-control-compacto` de
40 px en las de filtro), foco visible (el global, más `--s-foco` en los campos),
transiciones cortas y `prefers-reduced-motion`. No se agregó ninguna dependencia.

**Supervisión.** Las pestañas por comida traen aceptadas, rechazadas y manuales;
debajo, un resumen de la pestaña activa con su período. Las manuales ya están
dentro de las aceptadas (`servidas` incluye `manuales`): se muestran aparte, no se
suman. La barra de filtros suma el segmento «Manuales» (por `origen`) y cada fila
manual lleva su marca. Registro manual y «Autorizar» no cambiaron.

*Intervenciones de cocina: pendientes del contrato de A3.* No hay interfaz ni
llamadas. Cuando llegue el contrato se incorporarán en dos puntos de
`Supervision.jsx` (un comentario los marca): un panel «Intervenciones» entre el
resumen y la barra de filtros, acotado a la pestaña activa, y acciones por
marcación en la columna «Acción», junto a «Autorizar».

**Resumen.** Tres conteos distintos, cada uno con su período (`src/resumen.js`):

| Bloque | Campo de /pantalla/estado | Período |
|---|---|---|
| Turno actual | cupo (servidas, previstas, restantes, porcentaje) | solo la comida en curso, en su fecha de comida |
| Raciones servidas del día y gráfico por categoría | totales_del_dia.raciones_servidas, por_categoria | todas las comidas de la fecha de comida |
| Lecturas del lector | aceptadas, rechazadas, lecturas | día del reloj; son toques de dedo, no raciones |

Un cupo sin previstas se dice («sin cupo cargado») y no se le inventa porcentaje.

*Métricas propuestas para el Resumen (no se aproximan en el front):* comparación
con el día o la semana anterior y ritmo de servidas por hora dentro de la franja
necesitan backend nuevo. La cobertura del día completo (servidas contra previstas
de todas las comidas) y los rechazos del día por motivo ya salen por comida de
`/pantalla/comidas-del-dia` (Supervisión), pero llevarlos al Resumen es una
decisión de producto, no un cambio de presentación.

**Cuentas.** Solo lectura: buscador, conteo por estado, tabla y, en pantallas
pequeñas, una tarjeta por cuenta. Administración de cuentas (sistemas) no se tocó.

## Pendiente de mapeo

Los coeficientes de ración completa llegan del backend con cada informe; el
frontend no guarda una copia. sin_clasificar y sin_coeficiente se muestran como advertencia ámbar al pie de
la tabla y como nota al pie en Excel/PDF: mientras sean mayores que cero, el
informe no cuadra 100 % con el papel.

No se incorporaron pantallas de configuración, mapeo de categorías ni carga de cupos.

## Validación

npm.cmd test ejecuta las pruebas de contrato con respuestas controladas, sin
escribir en la API real. Se verifican identidad, errores, cancelación, estados de
cupo, paginación, estados de comidas, totales mensuales y selección de períodos.
