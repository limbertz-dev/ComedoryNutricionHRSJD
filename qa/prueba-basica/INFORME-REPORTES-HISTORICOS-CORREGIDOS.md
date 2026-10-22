# Reportes históricos y comprobación offline

Corregido en `wt-qa`, rama `qa`, el 2026-10-20. Sin commit ni push. Se conservaron los cambios locales anteriores.

## Resultado

Desactivar una categoría de reporte o comida ya no oculta las raciones servidas del período. Diario, mensual, anual y rango conservan su clasificación y totales. La consulta incluye catálogos activos y los inactivos referenciados por las asistencias del período; no arrastra categorías inactivas usadas únicamente en otros períodos.

También se corrigió la exportación de períodos con varias versiones de coeficiente. El backend indica `coeficientes_mixtos`; pantalla y PDF muestran «Variable», y Excel conserva el equivalente calculado por vigencia. Antes podía mostrar un resultado correcto almacenado en caché pero recalcularlo mal al abrirse, usando el coeficiente máximo para todas las raciones.

La nota de raciones sin clasificar ahora informa que están incluidas en el total del informe. Las lecturas rechazadas siguen sin sumar raciones.

## Paquete offline disponible

- [Abrir informe sin conexión](evidencias/reportes-offline-2026-10-20T23-54-19-765Z/index.html).
- [Paquete ZIP completo](evidencias/reportes-offline-2026-10-20T23-54-19-765Z.zip).
- [Resultados de la comprobación](evidencias/reportes-offline-2026-10-20T23-54-19-765Z/resultado.json).
- [Datos originales y consultas comparadas](evidencias/reportes-offline-2026-10-20T23-54-19-765Z/datos.json).
- [Manifiesto SHA-256](evidencias/reportes-offline-2026-10-20T23-54-19-765Z/sha256.json).

Contiene 10 PDF y 10 Excel, correspondientes a cinco consultas antes y después de la desactivación. El HTML, PDF y Excel guardados se abren sin backend, MySQL ni conexión. Los datos son sintéticos, identificados como tales en el informe.

## Evidencia obtenida

| Consulta | Antes | Categoría inactiva | Categoría y Almuerzo inactivos |
|---|---:|---:|---:|
| Registro diario de septiembre | 6 | 6 | 6 |
| Mensual de septiembre | 6 | 6 | 6 |
| Resumen anual 2026 | 8 | 8 | 8 |
| Rango de septiembre | 6 | 6 | 6 |
| Rango septiembre–octubre | 8 | 8 | 8 |

El equivalente de septiembre se conserva en 4,75 y el del rango ampliado en 6,95. Las nueve asistencias de la base fixture incluyen una de 2025, que no se mezcla con 2026. Se añadieron lecturas rechazadas sin asistencia y una entrega manual para contrastar que la fuente de conteo sean las raciones efectivas.

Se verificaron las fórmulas y los resultados numéricos leyendo los libros XLSX con ExcelJS y el texto de los PDF reales con `pdftotext`. Los contenidos de los PDF y las matrices del Excel coinciden antes/después de desactivar los catálogos. Los exportadores son los mismos que usa la aplicación; el transporte de datos se sustituye por las consultas obtenidas del SQL fixture.

El navegador se dejó completamente sin conexión después de precargar los exportadores. Se verificó también la apertura del HTML desde un archivo local, sin servidor. La integridad de los 24 archivos del manifiesto pasa; una regresión comprueba que editar un archivo provoca fallo.

## Pruebas

- Suite QA offline: **322 passed**, con 13 advertencias de dependencias. Las cuatro regresiones nuevas de historial también se repitieron tras completar el fixture.
- Frontend: **270 pruebas aprobadas**, incluida conservación del equivalente con coeficientes variables.
- Exportaciones offline: **10 comprobaciones PDF/XLSX aprobadas**, 20 archivos generados.
- Build de producción: correcto, 950 módulos; se conserva el aviso de tamaño de algunos paquetes.
- Sin cambios en el esquema ni en catálogos reales. Las desactivaciones de prueba se ejecutaron exclusivamente en SQLite en memoria.

## Reproducir

Desde `wt-qa`, sin credenciales ni servicios QA encendidos:

```powershell
node qa/prueba-basica/verificar_exportaciones_offline.mjs
```

Para verificar una copia guardada:

```powershell
& ./comedorback/.venv/Scripts/python.exe -B qa/prueba-basica/reportes_historicos_offline.py --verificar 'qa/prueba-basica/evidencias/reportes-offline-2026-10-20T23-54-19-765Z'
```

## Alcance de la conservación

Las copias emitidas en el paquete son archivos fijos y su modificación se detecta comparándolos con el manifiesto. El manifiesto no es una firma digital ni una protección contra alguien que pueda reemplazar simultáneamente archivos y hashes.

Las consultas del sistema siguen reflejando las asistencias y los datos almacenados. Esta corrección garantiza conservación ante activación/desactivación del catálogo; no incorpora un cierre administrativo firmado ni instantáneas históricas de nombres, orden del catálogo o ediciones retroactivas de coeficientes. No debe interpretarse el campo de calendario `cerrado` como una firma de aprobación de jefatura.

El paquete demuestra los casos descritos con datos sintéticos y SQL real offline. No prueba rendimiento de MySQL, funcionamiento sin base de datos del sistema completo ni integración con el lector físico.
