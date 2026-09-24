# Contexto del módulo Pacientes y Dietas

Sistema Comedor y Nutrición Hospitalaria. Hospital Regional San Juan de Dios, Tarija. Práctica Pre Profesional (SIS-361), área de Sistemas. Estado al 23/09/2026.

## 0. Cómo leer este documento

Este documento reúne el contexto del módulo de pacientes y dietas y la interfaz que se quiere construir. Cada decisión lleva una etiqueta de estado. Quien implemente, sea una persona o un agente de código, no debe convertir lo propuesto o lo pendiente en reglas definitivas ni inventar datos, cifras, horarios o nombres que no estén aquí. Si algo pendiente bloquea una tarea, se deja configurable o se pregunta antes de seguir.

| Etiqueta | Significado |
|---|---|
| EXISTE | Ya está en la interfaz actual (capturas del 22/09/2026). |
| DECIDIDO | Lo decidió Limbert o el hospital. |
| PROPUESTO | Recomendado en el análisis, todavía sin validar con nutrición o con Sistemas. |
| PENDIENTE | Depende de una respuesta de nutrición, de Sistemas o de una prueba en campo. |

## 1. Qué resuelve el módulo

El módulo registra cada día qué dieta recibe cada paciente hospitalizado, incluidos los cambios durante el día, por ejemplo una comida cancelada porque el paciente entra a cirugía y restituida si la cirugía se suspende. Con eso el comedor prepara las dietas correctas por servicio y nutrición obtiene, sin sumar a mano, las planillas e informes de raciones servidas a pacientes, exportables a Excel y PDF (DECIDIDO).

Forma parte del sistema Comedor y Nutrición Hospitalaria, que también cubre al personal (Control Biométrico, Resumen, Historial de comidas). La parte del personal queda fuera de este documento.

| Parte | Qué hace | Estado |
|---|---|---|
| Pacientes y dietas | Muestra el censo de camas con la dieta del día (Control de Dietas) y administra el catálogo de dietas (Dietas). Lo único complejo es la edición: cancelar la comida por cirugía y restituirla. | EXISTE la visualización; falta la edición |
| Módulo 2 | Cálculos de los reportes de pacientes. | DECIDIDO; falta implementar |
| Módulo 3 | Automatizar la captura de los pedidos de dieta desde las salas, incluida la captura desde el celular. | DECIDIDO el flujo; PROPUESTA la implementación |

## 2. Proceso actual en papel

### 2.1 El Parte de Dietas

Cada servicio llena a mano un formulario preimpreso del hospital llamado PARTE DE DIETAS (en el comedor le dicen "hojita"). Tiene los campos Servicio y Fecha, una tabla con las columnas PIEZA, CAMA, DIETA y OBSERVACIONES, y un espacio de Responsables donde firma y sella enfermería o nutrición. No lleva nombres de pacientes.

### 2.2 Cómo llega al comedor

El flujo es irregular. A veces la sala manda a alguien al comedor con el parte; otras veces el personal del comedor recorre las salas preguntando qué dietas necesitan.

### 2.3 Consolidación

Nutrición pasa los partes de cada día a una Planilla de Distribución Diaria de Pacientes (matriz de servicios por tipos de dieta, llenada a mano). Cada servicio lleva además un cuaderno de conteo diario por tipo de dieta, con los días del 1 al 31 y un total. A fin de mes todo se consolida en el informe mensual en Excel. El archivo de referencia es INFORME_MENSUAL_julio.xlsx, con una hoja por servicio, las hojas consolidadas INFORMES y SERVICIO DE NUTRICION, y una planilla aparte de refrigerios de hemodiálisis por turno. Los informes oficiales los firma la Nutricionista Dietista del hospital. Limbert supone que después el informe pasa a otras áreas (insumos y estadística); esas áreas no forman parte de este sistema.

### 2.4 Regla de conteo

En los reportes de pacientes cada ración cuenta como 1, sin importar la dieta. A diferencia de los reportes del personal, no se aplican coeficientes por tiempo de comida (DECIDIDO, observado en los formatos).

### 2.5 Casos observados en los partes del 02/09/2026

| Caso | Dónde se vio | Qué implica para el sistema |
|---|---|---|
| Abreviaturas y variantes de escritura | Medicina Mujeres: Bl, DIAB, Hg, QMT, NPO, Astring | Catálogo con sinónimos |
| Cambio durante el día | Ginecología, cama 17: dice NPO y al lado, en rojo, "Blanda" | Historial de cambios por paciente |
| Dieta tachada y reemplazada | Medicina Mujeres, cama 30: "QMT" tachado y "Sonda" al lado | Historial de cambios |
| Dietas combinadas | "Hg - licuada", "QMT - Astring", "Licuada - Astring", "Bl + s/AB", "DIAB + s/ab" | Regla de qué columna cuenta (PENDIENTE) |
| Indicaciones detalladas | Servicio "Lorenzo Tolay", pieza 214: licuadas con ml, kcal, gramos de proteína, número de tomas y vía (SNG, a caída libre); "corriente a tolerancia asistido semisentado" | Texto libre de indicación, no dietas nuevas en el catálogo |
| Camas tachadas | Medicina Mujeres, cama 9 | No cuentan (PENDIENTE confirmar) |
| Raciones sin cama | Maternidad: línea de pre-parto sin pieza ni cama. Otros partes: raciones para acompañantes (padres, familiares) | Raciones sueltas por servicio |
| Correcciones en rojo y resaltadores de colores por tipo de dieta | Maternidad, Ginecología, Medicina Mujeres | Interpretación probable: hoy se cuenta a mano; el sistema debe dar el conteo |
| Notas al pie | "Lorenzo Tolay": "7. Albúmina 100 ml" | Campo de observaciones |

## 3. Restricciones y decisiones

| Tema | Decisión | Estado |
|---|---|---|
| Red | El sistema corre en un servidor del hospital y se usa desde las PCs por la red local. El hospital no tiene Wi-Fi: toda la red es cableada. | DECIDIDO |
| Stack | React en el frontend, FastAPI con SQLAlchemy en el backend y MySQL. Sin Docker. Ya existe un canal SSE (/api/eventos) usado por la pantalla en vivo del personal. | DECIDIDO |
| Acceso | Login con usuario y contraseña. | DECIDIDO |
| Costo | Ningún servicio pagado. | DECIDIDO |
| Censo | Camas y pacientes se leen del SIH en solo lectura; la interfaz muestra la hora de la última lectura. | EXISTE |
| Excel | El sistema exporta reportes a Excel y PDF. Nutrición no carga planillas al sistema. La única importación es el CSV de la mini app. | DECIDIDO |
| OCR y fotos | Descartados. | DECIDIDO |
| Captura móvil | Requisito del hospital. Sin Wi-Fi, el celular usa datos móviles y escribe en Google Drive. El puente hacia el servidor es un archivo que alguien arrastra en la PC, así que el servidor no necesita internet ni abrir puertos. | DECIDIDO |
| Datos que salen del hospital | Solo servicio, pieza, cama, dieta, indicación, motivo, hora y capturista (y, en raciones sin cama, concepto y cantidad). Sin nombres ni historia clínica. El sistema une cama y paciente con el censo al importar. | PROPUESTO |
| Cuenta de Google | Del hospital o del comedor, nunca personal, para que el sistema no dependa de quien lo desarrolló. | PROPUESTO |
| Autorización | Aprobación escrita del hospital para usar Drive. | PENDIENTE |
| Datos de prueba | Ficticios. No copiar nombres ni historias clínicas del censo real. | PROPUESTO |
| Alcance visual | Limbert considera que el diseño actual tiene sobreingeniería para un proceso simple. Lo nuevo debe ser mínimo y no se agregan pantallas fuera de este documento. | PROPUESTO, a partir de esa observación |

## 4. Flujo objetivo de punta a punta

| Paso | Dónde | Quién | Resultado | Estado |
|---|---|---|---|---|
| 1. Captura en la sala | Mini app en el celular, con datos móviles | Personal del comedor durante la ronda | Una fila nueva en la hoja de registros del Drive del comedor | DECIDIDO |
| 2. Captura del parte en papel | Control de Dietas, en la PC | Personal del comedor o nutrición | El mismo tipo de registro, con origen PC | PROPUESTO |
| 3. Descarga | PC del comedor | Personal del comedor | CSV de la hoja de registros, con un marcador de exportación | PROPUESTO |
| 4. Importación | Sistema, arrastrando el CSV | Personal del comedor o nutrición | Lo válido entra solo; las excepciones quedan marcadas | DECIDIDO el arrastre; PROPUESTA la vista previa |
| 5. Revisión | Sistema | Jefa de nutrición | Corrige en el sistema lo que no le cuadra | DECIDIDO |
| 6. Operación del día | Control de Dietas | Comedor y cocina | Dieta vigente por cama y conteo por dieta y servicio | PROPUESTO el conteo |
| 7. Cierre | Reportes de pacientes | Jefa de nutrición | Excel y PDF; cierre del mes | DECIDIDO los reportes; PROPUESTO el cierre |

## 5. Modelo conceptual

Principios (PROPUESTO). La dieta se ata al paciente (historia clínica) y a la fecha, no a la cama, porque los pacientes se trasladan y las camas se reocupan. Ningún cambio sobrescribe a otro: cada cambio es un evento nuevo y el estado vigente es el último. Cancelar por cirugía es registrar NPO con su motivo; restituir es volver a la dieta anterior del historial. El reporte toma la dieta vigente según la regla de corte que defina nutrición (PENDIENTE).

| Entidad | Contenido | Origen | Estado |
|---|---|---|---|
| Censo | Cama, pieza, sala, servicio, paciente, sexo, historia clínica y hora de lectura | SIH, solo lectura | EXISTE |
| Dieta | Nombre oficial, sinónimos ("cómo la escriben"), columna del libro y si está activa | Pantalla Dietas | EXISTE |
| Modificador | Complemento que informa a cocina sin contar como dieta aparte (ejemplos observados: astringente, sonda, a tolerancia) | Catálogo | PENDIENTE, depende de la regla de dietas combinadas |
| Evento de dieta | Id único, fecha y hora, servicio, pieza, cama, paciente (resuelto con el censo a la hora de captura), dieta, indicación libre, motivo (por ejemplo cirugía), capturista y origen (móvil, PC o corrección de nutrición) | Mini app, PC o revisión | PROPUESTO |
| Ración sin cama | Fecha, servicio, concepto (acompañante, pre-parto, refrigerio de hemodiálisis con su turno), dieta y cantidad | Mini app o PC | PROPUESTO |
| Importación | Archivo, fecha y hora, usuario, registros nuevos, ya importados y excepciones | Pantalla de importación | PROPUESTO |
| Cierre de mes | Mes, fecha y usuario. Bloquea los cambios del mes; reabrirlo exige motivo y queda registrado | Reportes de pacientes | PROPUESTO |

## 6. Interfaz

### 6.1 Estructura general (EXISTE)

Barra lateral con la marca "Comedor y Nutrición" y el subtítulo "Hospitalaria", y tres secciones: PERSONAL (Control Biométrico, Resumen, Historial de comidas), PACIENTES (Control de Dietas, Dietas) y COMÚN (Reportes). Abajo, la tarjeta del usuario con nombre, cargo y el botón Cerrar sesión. Cada página tiene título, subtítulo y un chip con la fecha actual arriba a la derecha. Estilo claro con acento verde: tarjetas blancas con bordes redondeados, encabezados de tabla en mayúsculas pequeñas, chips y etiquetas tipo píldora, y botones principales en verde.

### 6.2 Control de Dietas

Lo que existe (EXISTE):

| Elemento | Detalle |
|---|---|
| Filtro de fecha | "Fecha seleccionada: Hoy · 22 Sept 2026" |
| Filtro de servicio | "Todos los servicios" |
| Chips de estado | "SIH · leído 12:33", "142 camas", "0 con dieta", "142 sin dieta", "16 sin clasificar" |
| Buscador | "Buscar por cama, paciente, historia o sala…" |
| Pestañas | "Pendientes (142)" y "Todas las camas (142)" |
| Sección | "Sin dieta asignada", con contador de camas |
| Tabla | UBICACIÓN (cama, servicio, pieza y sala), PACIENTE (nombre, sexo y H.C.) y DIETA DE HOY (etiqueta "Sin dieta asignada") |

Las cifras son de la captura del 22/09/2026 y solo ilustran el estado de ese momento.

Lo que falta (PROPUESTO):

| Elemento | Comportamiento |
|---|---|
| Edición de "Dieta de hoy" | Al tocar la celda se abre un panel con botones para las dietas frecuentes y NPO, un buscador que acepta sinónimos (escribir "DAB" encuentra Diabético), un campo de indicación libre y, si es NPO, el motivo. Guardar crea un evento nuevo. Si lo hace nutrición, el origen es corrección de nutrición. |
| Restituir | Botón visible cuando la dieta vigente es NPO. Vuelve a la dieta anterior del historial con un toque. |
| Historial del día | Por cama: hora, dieta anterior y nueva, motivo, quién y origen. |
| Modo transcripción | Para el parte en papel. Elegido el servicio, las camas aparecen en el orden del papel (pieza, cama) y se avanza cama por cama con el teclado. Origen PC. |
| Raciones sin cama | Botón para registrar concepto, dieta y cantidad por servicio. |
| Importar registros | Botón que abre la pantalla de importación (6.4). |
| Última importación | Chip "Última importación: hace X", con aviso si no hubo importación antes de la hora de corte (hora PENDIENTE). |
| Resumen para cocina | Conteo de la dieta vigente por tipo y por servicio, sin contar NPO. |
| Actualización en vivo | Tras importar o editar, la pantalla se refresca con el canal SSE existente. |
| Dieta de ayer | Mostrarla como sugerencia a confirmar, solo si nutrición confirma que las dietas suelen repetirse de un día a otro (PENDIENTE). |

### 6.3 Dietas (EXISTE)

Página "Dietas", subtítulo "Catálogo y códigos de las hojitas". Una tarjeta con el texto "Relación de las dietas oficiales de nutrición, sinónimos de enfermería y correspondencia con el libro mensual" y el botón "+ Nueva dieta". Tabla con DIETA (nombre y enlace "Editar nombre o columna"), CÓMO LA ESCRIBEN (sinónimos como chips con íconos ⇄ y ×, más "+ Agregar"), COLUMNA DEL LIBRO y ACTIVA (interruptor).

Filas visibles en la captura (puede haber más):

| Dieta | Cómo la escriben | Columna del libro |
|---|---|---|
| Corriente | Corriente, Corriente a tolerancia | CORRIENTE |
| Blanda | BI, Bl, Blanda a tolerancia | BLANDA |
| Hiposodica | Hiposod, s/sal | HIPOSODICA |
| Hiposograsa | Hg, Hipograsa | HIPOSOGRASA |
| Diabetico | DAB, DIAB | DIABETICO |
| Licuada | Dieta licuada, Licuada | LICUADAS |

| Tema | Detalle | Estado |
|---|---|---|
| NPO | Entrada especial que no cuenta como ración | PENDIENTE confirmar |
| Columna del libro | Debe seguir el juego de columnas oficial vigente (ver sección 7) | PENDIENTE |
| Exportar para la mini app | Botón que genera el catálogo activo (dietas y sinónimos) para la pestaña catalogo de la hoja | PROPUESTO |

### 6.4 Importar registros (PROPUESTO)

Se abre desde Control de Dietas. Tiene una zona para arrastrar el CSV y un botón para elegirlo. Antes de guardar muestra una vista previa con tres conteos: registros nuevos, ya importados (se ignoran) y con problemas. Lo válido entra solo; la jefa de nutrición revisa únicamente las excepciones y en cada una puede corregir o descartar. Al confirmar, el sistema muestra un resumen y avisa qué camas ocupadas del censo quedaron sin dieta.

| Excepción | Cuándo ocurre |
|---|---|
| Cama fuera del censo | La pieza y la cama no existen en el censo del SIH a la hora de captura |
| Dieta fuera del catálogo | El texto no coincide con ninguna dieta ni sinónimo |
| Registros en conflicto | La misma cama tiene dietas distintas casi a la misma hora |
| Capturista no reconocido | El capturista no está registrado |
| Mes cerrado | La fecha del registro pertenece a un mes ya cerrado |

La importación es idempotente: cada fila trae un id único, y reimportar el mismo archivo no duplica nada ni pisa las correcciones hechas en el sistema. Las correcciones se hacen siempre en el sistema, nunca en la hoja de Drive ni en el Excel exportado.

### 6.5 Reportes de pacientes

Lo que existe (EXISTE): la pestaña "Reportes de pacientes" (subtítulo "Raciones y servicios hospitalarios") junto a "Reportes del personal", con el espacio reservado. La pestaña del personal ya tiene los controles que se reutilizan: Período rápido (Hoy, Últimos 7 días, Este mes), Fecha inicial, Fecha final, el botón "Actualizar informe", un chip con el rango y el número de días, los botones Excel y PDF, y el estado vacío "No hay raciones registradas en este período."

Lo que falta (DECIDIDO que se hace; el cálculo es el módulo 2): las vistas y planillas siguientes, con los mismos controles y con exportación a Excel y PDF en el formato que ya usa nutrición.

Vista 1. Raciones por día del mes y tipo de dieta, con filas del 1 al 31 y TOTAL. Corresponde al formato de las hojas por servicio del informe mensual (PENDIENTE: si se genera por servicio, consolidada o ambas).

| FECHA | CORRIENTE | BLANDA | HIPOSODICA | HIPOSOGRASA | HP-HC | DIABETICO | ULCERA | LIQUIDO | OTROS | TOTAL |
|---|---|---|---|---|---|---|---|---|---|---|

Vista 2. Raciones por servicio y tipo de dieta, con las mismas columnas de la Vista 1 pero con SERVICIOS como primera columna. Filas de la plantilla: MATERNIDAD, GINECOLOGIA, EMERGENCIAS, BRONCO PULMONAR, MEDICINA MUJERES, MEDICINA VARONES, CIRUGIA MUJERES, CIRUGIA VARONES, QUEMADO, PEDIATRIA, ONEOLOGIA, EMERGENCIAS y TOTAL. EMERGENCIAS aparece dos veces y ONEOLOGIA está escrito así en la plantilla.

Planilla 3. Informe mensual de raciones servidas a pacientes. Título "INFORME MENSUAL DE RACIONES SERVIDAS A PACIENTES" y encabezado agrupador "TIPOS DE DIETAS".

| SERVICIOS | CORRIENTE | BLANDA | HIPOSODICA | HIPOSOGRASA | DIABETICO | LICUADAS | QUIMIOTERAPIAS | SONDAS Y LIQUIDAS | OTROS | TOTAL |
|---|---|---|---|---|---|---|---|---|---|---|

Filas: H. CIRUGIA MUJERES, H. CIRUGIA VARONES, H. GINECOLOGIA, H. INFECTOLOGIA, H. MEDICINA MUJERES, H. MEDICINA VARONES, H. OBSTETRICIA, H. HEMODIALISIS, H. NEONATOLOGIA UCIN, H. U.T.I, H. TRAUMATOLOGIA, H. QUEMADOS, H. EMERGENCIAS, H. PEDIATRIA UCI, H. PEDIATRIA GRAL., H. ONCOLOGIA y TOTAL.

Planilla 4. Planilla de distribución de refrigerio a la Unidad de Hemodiálisis, con filas del 1 al 31 y TOTAL.

| FECHA | TURNO MAÑANA | TURNO TARDE | TURNO NOCHE | TOTAL |
|---|---|---|---|---|

Planilla 5. Servicios de hospitalización. Columnas SERVICIOS y No. DE RACIONES, esta última dividida en M y F. Filas: H. CIRUGIA GENERAL, H. GINECOLOGIA, H. INFECTOLOGIA, H. MEDICINA INTERNA, H. OBSTETRICIA, H. NEONATOLOGIA UTI, H. HEMODIALISIS, H. U.T.I., H. TRAUMATOLOGIA, H. QUEMADOS, H. PEDIATRIA UTI, H. PEDIATRIA UCI, H. PEDIATRIA GRAL., H. ONCOLOGIA, EMERGENCIAS y TOTAL. Después vienen la sección EMERGENCICAS, con la fila "refrigerios hemodialisis", y la sección OTROS SERVICIOS, con la fila DIRECCION-ADMINISTACION (escritas así en la plantilla).

Agrupaciones verificadas con el ejemplo de nutrición: H. CIRUGIA GENERAL es la suma de Cirugía Mujeres y Cirugía Varones (362 + 414 = 776), H. MEDICINA INTERNA es la suma de Medicina Mujeres y Medicina Varones (563 + 781 = 1344), y el TOTAL (4680) coincide con el del informe mensual. En el ejemplo todos los valores están en la columna M, incluidos Ginecología y Obstetricia (PENDIENTE: significado de M y F).

Cierre de mes (PROPUESTO): botón "Cerrar mes" en esta pestaña, una vez generado el informe oficial. El mes cerrado se marca con un candado; reabrirlo exige motivo y queda registrado. El PDF deja un bloque de firma con nombre y cargo configurables, porque los informes oficiales los firma la Nutricionista Dietista.

### 6.6 Mini app móvil

La idea es de Limbert (DECIDIDO): una mini app en el celular que sube los registros a una cuenta de Google Drive. En la PC se arrastra el archivo al sistema y todo se actualiza; si algo no le cuadra a la jefa de nutrición, lo corrige, y el sistema entrega Excel y PDF.

Implementación (PROPUESTO). Una web hecha con Google Apps Script, vinculada a una hoja de Google de la cuenta del comedor y publicada para ejecutarse como esa cuenta. Los celulares solo abren un enlace, guardado como acceso directo en la pantalla de inicio: nadie comparte la contraseña ni manda correos. No se hace app nativa, porque exigiría repartir e instalar el APK en cada celular, en iPhone prácticamente no se puede instalar sin tienda, y no resuelve el problema de la cuenta. Para un piloto rápido sirve un Google Form con los mismos campos. Solo si la prueba de señal muestra salas sin datos móviles se pasa a una web instalable con modo sin conexión, hospedada gratis (por ejemplo en GitHub Pages), que envía al mismo Apps Script cuando vuelve la señal.

Hoja de Google (PROPUESTO):

| Pestaña | Contenido | Quién la llena |
|---|---|---|
| catalogo | Dietas activas y sus sinónimos | Se exporta desde el sistema cuando cambia el catálogo |
| camas | Servicio, pieza y cama, sin nombres | Se exporta desde el sistema cuando cambia la distribución de camas |
| registros | Una fila por evento: id (lo genera la mini app), fecha y hora, servicio, pieza, cama, dieta, indicación, motivo, capturista, tipo (cama o ración sin cama), concepto y cantidad | Solo la mini app, agregando filas |

Pantallas de la mini app (PROPUESTO):

| Paso | Pantalla |
|---|---|
| 1 | PIN del capturista |
| 2 | Elegir servicio con botones grandes |
| 3 | Camas del servicio en el orden del papel (pieza, cama). Se muestran todas; el sistema verifica al importar cuáles están ocupadas |
| 4 | Por cama: botones grandes para las dietas frecuentes (a definir con nutrición) y NPO, buscador con sinónimos para el resto, campo de indicación y motivo si es NPO. Guardar agrega una fila |
| 5 | Ración sin cama: concepto, dieta y cantidad |

Principios: no muestra ni guarda nombres; solo escribe y no ofrece lectura de registros; nunca edita ni borra filas, porque cada cambio es una fila nueva; funciona igual en Android y en iPhone.

Lado de la PC (PROPUESTO). Una hoja de Google no es un archivo que se pueda arrastrar: en Drive para escritorio aparece como un acceso directo .gsheet, no como datos. En la PC del comedor se deja un marcador al enlace de exportación CSV de la pestaña registros; un clic descarga el archivo y se arrastra al sistema. Las filas se archivan o se borran de la hoja al cerrar el mes, según lo que diga la autorización.

## 7. Preguntas pendientes

| # | Pregunta | Para | Ejemplo observado |
|---|---|---|---|
| 1 | Si la dieta cambia en el día, ¿cuál cuenta: la primera, la última o la vigente a una hora de corte? | Nutrición | Ginecología, cama 17: NPO y "Blanda" en rojo |
| 2 | ¿Hay hora de corte por tiempo de comida, pasada la cual el cambio aplica a la comida siguiente? | Nutrición | |
| 3 | ¿En qué servicio cuenta un paciente trasladado a media jornada? | Nutrición | |
| 4 | ¿En qué columna cuenta cada dieta combinada? | Nutrición | "Hg - licuada", "QMT - Astring", "licuada para diabético y renal crónico" |
| 5 | ¿Qué significan las abreviaturas que no están en el catálogo? | Nutrición | QMT (¿quimioterapia?), Astring, s/AB, s/ab |
| 6 | ¿NPO y las camas tachadas cuentan cero? | Nutrición | Medicina Mujeres, cama 9 |
| 7 | ¿En qué servicio y columna entran las raciones sin cama? | Nutrición | Pre-parto, acompañantes, refrigerios de hemodiálisis |
| 8 | ¿Qué juego de columnas es el vigente? | Nutrición | Vistas 1 y 2: HP-HC, ULCERA, LIQUIDO. Informe mensual: LICUADAS, QUIMIOTERAPIAS, SONDAS Y LIQUIDAS |
| 9 | ¿Cómo se corresponden los nombres de servicio del SIH, del parte y de los informes? | Nutrición y Sistemas | "Med. Mujeres" en el parte; MATERNIDAD en la Vista 2 y H. OBSTETRICIA en el informe mensual; listas de servicios distintas entre plantillas |
| 10 | La Vista 1, ¿por servicio, consolidada o ambas? | Nutrición | Hojas por servicio en INFORME_MENSUAL_julio.xlsx |
| 11 | ¿Qué significan M y F en Servicios de hospitalización? | Nutrición | Todos los valores del ejemplo están en M |
| 12 | ¿Se corrigen en la exportación los errores de tipeo de las plantillas? | Nutrición | DISTRUBUCION, ONEOLOGIA, EMERGENCICAS, ADMINISTACION; EMERGENCIAS repetida |
| 13 | ¿Las dietas suelen repetirse de un día a otro? | Nutrición | |
| 14 | ¿Cuáles son las dietas frecuentes para los botones grandes? | Nutrición | |
| 15 | ¿El SIH guarda la indicación de dieta? | Sistemas | |
| 16 | Autorización escrita para usar Drive: qué datos pasan, de quién es la cuenta, quién accede, cuánto tiempo se guardan y cuál es el plan B | Supervisión de Sistemas | |
| 17 | ¿Con qué celulares y con qué datos móviles se captura? | Supervisión de Sistemas | |
| 18 | ¿Hay señal de datos móviles en todas las salas del recorrido? | Prueba en campo | |

## 8. Validación (PROPUESTO)

Piloto de una o dos semanas en uno o dos servicios, en paralelo con el papel. Cada día se comparan los totales del sistema con la Planilla de Distribución Diaria que nutrición llena a mano, y se explica cada diferencia. También se mide cuánto toma cerrar el informe mensual a mano y cuánto con el sistema. El criterio de éxito es que la jefa de nutrición deje de llenar la planilla manual porque confía en el sistema.

## 9. Fuera de alcance (DECIDIDO)

| Tema | Motivo |
|---|---|
| OCR o fotos de los partes | Descartado: los partes tienen texto libre, resaltadores y tachones |
| Importar el Excel de nutrición | El sistema exporta; nutrición no carga planillas |
| Detección de anomalías | Descartada para pacientes: los números por sala son pequeños |
| Planificación de menús | La maneja otro departamento |
| Insumos y porciones de cocina | Fuera del alcance actual |
| Áreas que reciben el informe después (insumos, estadística) | No forman parte de este sistema |

## Glosario

| Término | Significado |
|---|---|
| Parte de Dietas u hojita | Formulario diario en papel por servicio: pieza, cama, dieta y observaciones |
| Pieza | Habitación |
| NPO | Nada por vía oral: el paciente no recibe comida |
| SNG | Sonda nasogástrica |
| H.C. | Historia clínica |
| SIH | Sistema del hospital del que se lee el censo de camas |
| Columna del libro | Columna del informe mensual en la que cuenta una dieta |
| Capturista | Persona del comedor que registra las dietas en la mini app o en la PC |
