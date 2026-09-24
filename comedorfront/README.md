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

La URL de la API está en src/config.js: http://127.0.0.1:8000.
El backend debe permitir por CORS el origen de Vite (http://localhost:5173 o
http://127.0.0.1:5173). Su instalación se explica en ../comedorback/README.md.

## Integración disponible

| Función | Endpoint | Uso |
|---|---|---|
| obtenerPersonal | GET /personal | Reúne páginas de 200 comensales para el selector |
| marcarAsistencia | GET /personal/{id} + POST /asistencias | metodo biometrico desde el simulador del lector, manual desde el registro a mano |
| obtenerEstadoPantalla | GET /pantalla/estado | Comida vigente, cupo, totales del día y gráfico |
| obtenerUltimasMarcaciones | GET /pantalla/ultimas-marcaciones | Lecturas guardadas de hoy, incluidos los rechazos |
| obtenerDiaPersonal | GET /historial/diario | Detalle del día de un comensal bajo la marcación |
| obtenerHistorialDiarioPersonal | GET /historial/diario | Historial diario, 50 registros por página |
| obtenerHistorialMensualPersonal | GET /historial/mensual | Totales mensuales, 50 registros por página |
| obtenerInformeRaciones | GET /reportes/informe | Informe de Estadística por rango de fechas (Reportes) |

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
ese mismo informe (exportarInformeExcel / exportarInformePdf).

useConsultaApi cancela lecturas obsoletas al cambiar de período o desmontar una
vista. Carga, respuesta vacía y error son estados distintos. Hay reintento manual
para lecturas; no hay reintentos automáticos del POST ni datos ficticios de respaldo.

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
