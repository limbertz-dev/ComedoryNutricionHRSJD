# Plan de Implementación: Migración del conteo a `raciones_servicio_dia`

## 1. Resumen y Objetivo

El backend de nutrición hospitalaria deja de registrar y contar raciones cama por cama (`dietas_cama`) y pasa a registrar y consolidar las raciones diarias directamente como una matriz de servicios × tipos de dieta en `raciones_servicio_dia`.

Esta tarea comprende:
1. Crear el endpoint `GET /pacientes/raciones-dia?fecha=YYYY-MM-DD` que entrega la matriz del día (16 servicios × 9 columnas del informe + totales).
2. Crear el endpoint `PUT /pacientes/raciones-dia` para guardar la matriz del día, insertando únicamente hechos para aquellas celdas cuyo valor haya cambiado respecto a la celda vigente (política estricta *insert-only*).
3. Modificar `GET /pacientes/reporte-distribucion` para leer y consolidar las cantidades vigentes desde `raciones_servicio_dia`, quitando la fila `SIN CLASIFICAR` (al cargar por servicio, no hay camas sin clasificar).
4. Eliminar `GET /pacientes/reporte-hospitalizacion` junto con sus esquemas, funciones auxiliares y pruebas, ya que dependía de la asignación de sexo por cama.
5. Marcar como `LEGADO` los módulos, modelos y endpoints de la etapa anterior (`/pacientes/control`, `asignar`, `suspender`, `reanudar`, `raciones-manuales`, `censo.py`, `db_sih.py` y `dietas_cama`).
6. Crear las nuevas pruebas unitarias en `tests/test_raciones_dia.py` y actualizar `tests/test_reportes_pacientes.py` y `tests/test_raciones_manuales.py`.

---

## 2. Contrato exacto de los endpoints

### 2.1 `GET /pacientes/raciones-dia`

- **Método y ruta**: `GET /pacientes/raciones-dia`
- **Parámetros Query**:
  - `fecha`: `date` (opcional, formato `YYYY-MM-DD`, por defecto la fecha actual `date.today()`).
- **Respuesta exitosa (`200 OK`)**:
  ```json
  {
    "fecha": "2026-09-24",
    "columnas": [
      {"codigo": "corriente", "etiqueta": "CORRIENTE"},
      {"codigo": "blanda", "etiqueta": "BLANDA"},
      {"codigo": "hiposodica", "etiqueta": "HIPOSODICA"},
      {"codigo": "hiposograsa", "etiqueta": "HIPOSOGRASA"},
      {"codigo": "diabetico", "etiqueta": "DIABETICO"},
      {"codigo": "licuadas", "etiqueta": "LICUADAS"},
      {"codigo": "quimioterapias", "etiqueta": "QUIMIOTERAPIAS"},
      {"codigo": "sondas_liquidas", "etiqueta": "SONDAS Y LIQUIDAS"},
      {"codigo": "otros", "etiqueta": "OTROS"}
    ],
    "filas": [
      {
        "codigo": "cirugia_mujeres",
        "etiqueta": "H. CIRUGIA MUJERES",
        "celdas": [0, 0, 0, 0, 0, 0, 0, 0, 0],
        "total": 0
      },
      ... // 16 filas exactas en el orden de FILAS_DISTRIBUCION
    ],
    "total": {
      "celdas": [0, 0, 0, 0, 0, 0, 0, 0, 0],
      "total": 0
    },
    "actualizado": "2026-09-24T10:30:00" // null si el día no tiene registros
  }
  ```
- **Reglas**:
  - Toda celda sin registro previo vale `0`.
  - El orden de las filas corresponde exactamente a las 16 filas de `FILAS_DISTRIBUCION` (desde `cirugia_mujeres` hasta `oncologia`).
  - Las 9 columnas corresponden exactamente a `COLUMNAS_DISTRIBUCION`.
  - `actualizado` es el `momento` máximo entre los registros de ese día (o `null` si no hay registros).

### 2.2 `PUT /pacientes/raciones-dia`

- **Método y ruta**: `PUT /pacientes/raciones-dia`
- **Cuerpo de la petición (`Request Body`)**:
  ```json
  {
    "fecha": "2026-09-24",
    "celdas": [
      {
        "fila": "pediatria_gral",
        "columna": "corriente",
        "cantidad": 15
      }
    ]
  }
  ```
- **Validaciones (`422 Unprocessable Entity`)**:
  - `fecha`: No puede ser futura (`fecha <= date.today()`). Mensaje: `"La fecha no puede ser futura."`
  - `fila`: Debe existir en los 16 códigos de `FILAS_DISTRIBUCION`. Mensaje: `"Fila de distribución inválida: '{fila}'."`
  - `columna`: Debe existir en los 9 códigos de `COLUMNAS_DISTRIBUCION`. Mensaje: `"Columna de distribución inválida: '{columna}'."`
  - `cantidad`: Entero mayor o igual a 0. Mensaje: `"La cantidad debe ser un entero mayor o igual a 0."`
- **Comportamiento en base de datos**:
  - Resuelve el valor vigente actual para cada celda `(fecha, fila, columna)` (último por `momento`, o 0 si no existe).
  - Si `cantidad == valor_vigente`: **no inserta nada**.
  - Si `cantidad != valor_vigente`: inserta una nueva fila en `raciones_servicio_dia` con el `momento` actual.
- **Respuesta exitosa (`200 OK`)**:
  - Devuelve la matriz completa actualizada del día, con la misma estructura del `GET /pacientes/raciones-dia`.

### 2.3 `GET /pacientes/reporte-distribucion`

- **Método y ruta**: `GET /pacientes/reporte-distribucion`
- **Parámetros Query**:
  - `desde`: `date` (obligatorio, `YYYY-MM-DD`).
  - `hasta`: `date` (obligatorio, `YYYY-MM-DD`).
- **Respuesta exitosa (`200 OK`)**:
  ```json
  {
    "desde": "2026-07-01",
    "hasta": "2026-07-31",
    "dias": 31,
    "titulo": "INFORME MENSUAL DE RACIONES SERVIDAS A PACIENTES",
    "columnas": [ ... ], // 9 columnas
    "filas": [ ... ],    // 16 filas exactas (se elimina SIN CLASIFICAR)
    "total": {
      "valores": [ ... ], // 9 totales
      "total": 4680
    },
    "criterio": {
      "ultima_del_dia_manda": true,
      "fuente": "raciones_servicio_dia",
      "pendiente_confirmar": []
    }
  }
  ```
- **Cambios respecto a la versión anterior**:
  - Ya no consulta `dietas_cama` ni `tipos_dieta`.
  - Agrupa y suma la última cantidad registrada por cada día `d` en `[desde, hasta]`, fila `f` y columna `c`.
  - Se retira la fila `SIN CLASIFICAR` de la lista de filas (pasa de 17 a 16 filas).
  - Se actualiza `criterio` señalando la nueva fuente.

### 2.4 Eliminación de `GET /pacientes/reporte-hospitalizacion`

- Se elimina la ruta completa `GET /pacientes/reporte-hospitalizacion`.
- Se eliminan de `app/esquemas/pacientes.py`:
  - `ReporteHospitalizacionOut`
  - `CriterioHospitalizacionOut`
  - `FilaHospitalizacionOut`
  - `TotalHospitalizacionOut`
  - `FilaSinFuenteOut`
  - `SeccionReporteOut`
- Se eliminan de `app/consultas/reportes_pacientes.py`:
  - Función `reporte_hospitalizacion`
  - Constantes `FILAS_HOSPITALIZACION`, `SECCIONES_SIN_FUENTE`, `M_F_ES_SEXO`, `PENDIENTES_HOSPITALIZACION`
  - Dataclasses `FilaHospitalizacion`, `ReporteHospitalizacion`

---

## 3. Lista de archivos a modificar y crear

| Archivo | Acción | Descripción del cambio |
|---|---|---|
| `app/esquemas/pacientes.py` | Modificar | Agregar esquemas `CeldaMatrizIn`, `GuardarRacionesDiaIn`, `ColumnaMatrizOut`, `FilaMatrizOut`, `TotalMatrizOut`, `MatrizRacionesDiaOut`. Actualizar `CriterioReporteOut`. Eliminar esquemas de `reporte-hospitalizacion`. |
| `app/consultas/reportes_pacientes.py` | Modificar | Agregar funciones de consulta y persistencia para la matriz diaria (`obtener_matriz_dia`, `guardar_matriz_dia`). Reescribir `reporte_distribucion` para leer de `raciones_servicio_dia` sin `sin_clasificar`. Eliminar `reporte_hospitalizacion` y sus constantes asociadas. |
| `app/api/pacientes.py` | Modificar | Exponer `GET /pacientes/raciones-dia` y `PUT /pacientes/raciones-dia`. Eliminar endpoint `GET /pacientes/reporte-hospitalizacion`. Marcar rutas de control y raciones manuales con `# LEGADO`. |
| `app/consultas/control.py` | Modificar | Agregar comentario `# LEGADO` en el encabezado. |
| `app/consultas/censo.py` | Modificar | Agregar comentario `# LEGADO` en el encabezado. |
| `app/core/db_sih.py` | Modificar | Agregar comentario `# LEGADO` en el encabezado. |
| `app/consultas/raciones_manuales.py` | Modificar | Agregar comentario `# LEGADO` en el encabezado. |
| `tests/test_raciones_dia.py` | Crear | Pruebas de `GET` y `PUT` `/pacientes/raciones-dia`: lectura con matriz vacía (0s), inserción de cambios, validación de celda repetida sin cambios (no inserta), validación de fecha futura, filas o columnas inválidas y cantidades negativas. |
| `tests/test_reportes_pacientes.py` | Modificar | Adaptar suite de prueba para alimentar `raciones_servicio_dia` en lugar de `dietas_cama`. Actualizar prueba de julio para verificar 16 filas (sin `sin_clasificar`). Eliminar pruebas de `reporte-hospitalizacion`. |
| `tests/test_raciones_manuales.py` | Modificar | Ajustar o retirar `test_lo_cargado_sale_en_los_dos_reportes` (que invocaba `reporte-hospitalizacion` y asumía que `reporte-distribucion` leía de `dietas_cama`). |

---

## 4. Plan detallado de cambios en Tests

### 4.1 `tests/test_reportes_pacientes.py`
- **¿Qué cambia?**:
  - `_crear_base()`: Añade `RacionServicioDia.__table__` a las tablas creadas en SQLite.
  - Generación de datos de Julio: En lugar de crear miles de objetos `DietasCama`, crea directamente las filas en `RacionServicioDia` distribuidas a lo largo del mes de julio para cada fila y columna según `INFORMES_JULIO`.
  - Pruebas de distribución:
    - Se verifica que la matriz sume 4680 raciones como en el Excel.
    - Se verifica que `len(filas) == 16` (en lugar de 17, ya que se retira `sin_clasificar`).
    - `d["criterio"]` se valida contra la nueva definición.
  - Pruebas de hospitalización eliminadas:
    - `test_hospitalizacion_julio_reproduce_la_hoja_servicio_de_nutricion`
    - `test_hospitalizacion_m_f_y_sin_dato`
    - `test_hospitalizacion_orden_exacto_y_secciones_sin_fuente`
    - Aserciones de `reporte_hospitalizacion` en `test_huecos_del_mapeo_van_a_sin_clasificar` y `test_desde_posterior_a_hasta_es_422`.

### 4.2 `tests/test_raciones_manuales.py`
- **¿Qué cambia?**:
  - `test_lo_cargado_sale_en_los_dos_reportes`: Se elimina la llamada a `/pacientes/reporte-hospitalizacion`. Como `/pacientes/reporte-distribucion` ahora lee de `raciones_servicio_dia`, las cargas manuales a `dietas_cama` pertenecen al subsistema legado. Se actualiza el test para verificar las rutas de raciones manuales sin llamar a los reportes eliminados/migrados.

### 4.3 `tests/test_raciones_dia.py` (Nuevo)
- Pruebas dedicadas:
  1. `test_get_matriz_dia_vacia`: Retorna 16 filas × 9 columnas en cero, totales en cero y `actualizado = null`.
  2. `test_put_matriz_dia_inserta_solo_cambios`: Inserta celda con valor 10; un segundo PUT con valor 10 no inserta nada; un tercer PUT con valor 15 inserta una segunda fila en BD.
  3. `test_put_matriz_dia_con_cero`: Permite explícitamente guardar 0 raciones.
  4. `test_put_fecha_futura_422`: Retorna 422 si la fecha es de mañana o posterior.
  5. `test_put_fila_invalida_422`: Retorna 422 con mensaje descriptivo si la fila no existe.
  6. `test_put_columna_invalida_422`: Retorna 422 si el código de columna no existe.
  7. `test_put_cantidad_negativa_422`: Retorna 422 si la cantidad es menor a 0.
  8. `test_matriz_dia_actualizado_refleja_ultimo_momento`: El campo `actualizado` refleja la estampa de tiempo más reciente de las celdas del día.

---

## 5. Puntos Pendientes y Preguntas de Negocio

1. **Pediatría UTI y Coloproctología**: En el censo hospitalario del SIH existían salas para Pediatría UTI (sala 221) y Coloproctología (208) que no tenían fila propia en la planilla de 16 servicios (anteriormente caían en `SIN CLASIFICAR`). Al registrar ahora directamente por fila de la planilla, nutrición elegirá la fila correspondiente (por ejemplo Pediatría Gral. o Cirugía). Se deja registrado como **PENDIENTE** para validar con nutrición si requerirán filas adicionales en el futuro.
2. **Compatibilidad con `comedorfront/src/api.js`**: En el frontend actual, `CODIGOS_FILAS_DISTRIBUCION` en `api.js` incluye `'sin_clasificar'`. Dado que CLAUDE.md prohíbe modificar el frontend sin indicación expresa, el backend entregará las 16 filas solicitadas y se dejará asentado para la siguiente tarea de frontend la remoción de `'sin_clasificar'` en `api.js`.
