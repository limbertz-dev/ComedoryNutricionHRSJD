/*
 * exportaciones.js — generación de los archivos descargables de «Reportes».
 *
 * `exportarInformeExcel()` y `exportarInformePdf()` reciben el informe que
 * arma `obtenerInformeRaciones()` (api.js) a partir de FastAPI y no calculan
 * nada por su cuenta: el Excel y el PDF salen siempre con las mismas cifras.
 *
 * `exportarReporteExcel()` y `exportarReportePdf()` son del reporte del día
 * de la maqueta: hoy ninguna pantalla los importa.
 */
import { jsPDF } from 'jspdf';
import autoTable from 'jspdf-autotable';
import {
  ajustarAnchos,
  banner,
  cabecera,
  celda,
  columna,
  configurarImpresion,
  filaDatos,
  filaTotales,
  formula,
  FORMATO_DECIMAL,
  FORMATO_DIA,
  FORMATO_ENTERO,
  FORMATO_PORCENTAJE,
  FORMATO_PROMEDIO,
  generarLibroEnSegundoPlano,
  notaAlPie,
  nuevaHoja,
  tarjetaCierre,
} from './excelEstilos.js';

const NOMBRE_SISTEMA = 'Sistema de Comedor y Nutrición Hospitalaria';

/*
 * «Formulario» es la hoja de Estadística: tiempos de comida en las filas y la
 * reducción a ración completa al pie. La trae el informe por rango (`informe`)
 * y también el mensual cerrado (`mensual`), que es el mismo papel acotado a un
 * mes. Las otras dos formas —registro diario y gestión— son planillas.
 */
function esFormulario(informe) {
  return informe.tipo === 'informe' || informe.tipo === 'mensual';
}

/* Paleta del sistema en RGB: jsPDF no entiende variables CSS. */
const RGB_ACENTO = [0, 180, 115]; /* --c-acento */
const RGB_ACENTO_FUERTE = [0, 143, 93]; /* --c-acento-fuerte */
const RGB_TEXTO = [18, 35, 61]; /* --c-texto */
const RGB_TEXTO_2 = [100, 116, 139]; /* --c-texto-2 */
const RGB_BORDE = [228, 233, 231]; /* --c-borde */
const RGB_FILA = [239, 251, 245]; /* --c-acento-tenue */

function nombreArchivo(reporte, extension) {
  const turno = reporte.turno.toLowerCase();
  return `reporte-comedor-${reporte.fechaArchivo}-${turno}.${extension}`;
}

/** Filas del bloque de resumen, compartidas por Excel y PDF. */
function filasResumen({ resumen, turno }) {
  return [
    ['Turno', turno],
    ['Personal en el padrón', resumen.padron],
    ['Raciones previstas para el turno', resumen.racionesPrevistas],
    ['Raciones servidas', resumen.servidas],
    ['Raciones restantes', resumen.restantes],
    ['Cupo del turno utilizado', `${resumen.porcentaje}%`],
    ['Marcaciones válidas', resumen.validas],
    ['Marcaciones rechazadas', resumen.rechazadas],
  ];
}

/* ------------------------------------------------------------------ Excel */

/*
 * Nada que tenga pinta de número puede viajar como texto: Excel lo marca con
 * el triángulo de «número almacenado como texto» y la hoja sale con avisos.
 * Por eso los porcentajes que el reporte trae ya formateados ("72%") vuelven a
 * ser la fracción que eran, con formato de porcentaje encima.
 */
function comoPorcentaje(texto) {
  const numero = Number(String(texto).replace('%', '').trim());
  return Number.isFinite(numero) ? numero / 100 : texto;
}

/** Hoja «Resumen»: cabecera del turno y corte por categoría con su total. */
function hojaResumenTurno(libro, reporte) {
  const hoja = nuevaHoja(libro, 'Resumen');
  const COLUMNAS = 3;

  let fila = banner(hoja, COLUMNAS, {
    sistema: NOMBRE_SISTEMA,
    titulo: reporte.titulo,
    subtitulo: `${reporte.subtitulo}  |  ${reporte.fecha}  |  Generado a las ${reporte.generadoEn}`,
  });

  cabecera(hoja, fila, ['Indicador del turno', 'Valor', '']);
  const primeraDelResumen = fila + 1;
  filasResumen(reporte).forEach(([rotulo, valor], indice) => {
    const porcentaje = typeof valor === 'string' && valor.endsWith('%');
    filaDatos(hoja, primeraDelResumen + indice, [
      rotulo,
      porcentaje ? comoPorcentaje(valor) : valor,
    ], {
      /* El turno es texto de verdad; el cupo utilizado, un porcentaje. */
      formato: porcentaje ? FORMATO_PORCENTAJE : (typeof valor === 'number' ? FORMATO_ENTERO : '@'),
    });
  });

  fila = primeraDelResumen + filasResumen(reporte).length + 1;
  cabecera(hoja, fila, ['Raciones por categoría', 'Raciones', 'Participación']);

  const primeraCategoria = fila + 1;
  reporte.porCategoria.forEach((linea, indice) => {
    const numero = primeraCategoria + indice;
    filaDatos(hoja, numero, [
      linea.categoria,
      linea.raciones,
      comoPorcentaje(linea.participacion),
    ]);
    hoja.getCell(numero, 3).numFmt = FORMATO_PORCENTAJE;
  });

  const ultimaCategoria = primeraCategoria + reporte.porCategoria.length - 1;
  filaTotales(hoja, ultimaCategoria + 1, [
    'Total',
    formula(`SUM(B${primeraCategoria}:B${ultimaCategoria})`, reporte.totalCategorias),
    1,
  ]);
  hoja.getCell(ultimaCategoria + 1, 3).numFmt = FORMATO_PORCENTAJE;

  ajustarAnchos(hoja, [
    [...filasResumen(reporte).map(([rotulo]) => rotulo), ...reporte.porCategoria.map((l) => l.categoria)],
    ['Raciones previstas', ...filasResumen(reporte).map(([, valor]) => valor)],
    ['Participación'],
  ], { primera: 34 });

  configurarImpresion(hoja, {
    ultimaFila: ultimaCategoria + 1,
    ultimaColumna: COLUMNAS,
    pie: `Generado automáticamente por el ${NOMBRE_SISTEMA} · ${reporte.fecha}, ${reporte.generadoEn}`,
  });
}

/** Hoja «Detalle»: una fila por comensal, con autofiltro listo para usar. */
function hojaDetalleTurno(libro, reporte) {
  const hoja = nuevaHoja(libro, 'Detalle');
  const encabezados = ['Legajo', 'Nombre completo', 'Categoría', 'Turno', 'Estado'];

  const filaCabecera = banner(hoja, encabezados.length, {
    sistema: NOMBRE_SISTEMA,
    titulo: `${reporte.titulo} · detalle por comensal`,
    subtitulo: `${reporte.fecha}  |  Turno ${reporte.turno}`,
  });
  cabecera(hoja, filaCabecera, encabezados);

  /* Si todos los legajos son dígitos sin cero delante, van como número y la
     columna queda sin el aviso de texto; si alguno lleva letras o un cero a la
     izquierda, se respeta tal cual: el legajo manda sobre el aviso. */
  const legajosNumericos = reporte.detalle.length > 0
    && reporte.detalle.every((linea) => /^[1-9]\d*$/.test(String(linea.legajo)));

  const primera = filaCabecera + 1;
  reporte.detalle.forEach((linea, indice) => {
    filaDatos(hoja, primera + indice, [
      legajosNumericos ? Number(linea.legajo) : linea.legajo,
      linea.nombre,
      linea.categoria,
      linea.turno,
      linea.estado,
    ], { formato: '@' });
  });

  hoja.autoFilter = {
    from: { row: filaCabecera, column: 1 },
    to: { row: Math.max(primera + reporte.detalle.length - 1, filaCabecera), column: encabezados.length },
  };

  ajustarAnchos(hoja, encabezados.map((titulo, indice) => [
    titulo,
    ...reporte.detalle.map((linea) => [linea.legajo, linea.nombre, linea.categoria, linea.turno, linea.estado][indice]),
  ]), { primera: 14 });

  /* El detalle nominal no tiene techo de filas: se ajusta al ancho de la hoja
     y repite la cabecera, en vez de encogerse hasta no poder leerse. */
  configurarImpresion(hoja, {
    ultimaFila: Math.max(primera + reporte.detalle.length - 1, filaCabecera),
    ultimaColumna: encabezados.length,
    filaCabecera,
    enUnaHoja: false,
    pie: `Generado automáticamente por el ${NOMBRE_SISTEMA} · ${reporte.fecha}, ${reporte.generadoEn}`,
  });
}

/**
 * Libro .xlsx con dos hojas: «Resumen» (cabecera + corte por categoría) y
 * «Detalle» (una fila por comensal). Descarga directa en el navegador.
 *
 * La generación es asíncrona (ExcelJS se carga bajo demanda), pero el nombre
 * del archivo se devuelve de inmediato: la UI lo muestra sin esperar.
 *
 * @param {object} reporte  reporte del día: turno, fechaArchivo, resumen, porCategoria y detalle
 * @returns {string} nombre del archivo generado
 */
export function exportarReporteExcel(reporte) {
  const archivo = nombreArchivo(reporte, 'xlsx');
  generarLibroEnSegundoPlano(archivo, (libro) => {
    hojaResumenTurno(libro, reporte);
    hojaDetalleTurno(libro, reporte);
  });
  return archivo;
}

/* -------------------------------------------------------------------- PDF */

function cabeceraPdf(doc, reporte, margen) {
  const ancho = doc.internal.pageSize.getWidth();

  doc.setFillColor(...RGB_ACENTO_FUERTE);
  doc.rect(0, 0, ancho, 76, 'F');

  doc.setTextColor(255, 255, 255);
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(15);
  doc.text(NOMBRE_SISTEMA, margen, 34);

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(10.5);
  doc.text(`${reporte.titulo} · ${reporte.subtitulo}`, margen, 54);

  doc.setTextColor(...RGB_TEXTO);
  doc.setFontSize(11);
  doc.text(`Turno: ${reporte.turno}`, margen, 108);

  doc.setTextColor(...RGB_TEXTO_2);
  doc.setFontSize(10);
  doc.text(reporte.fecha, margen, 126);
  doc.text(`Generado a las ${reporte.generadoEn}`, margen, 142);

  return 168; /* Y donde puede empezar el primer bloque. */
}

function pieDePagina(doc, margen) {
  const ancho = doc.internal.pageSize.getWidth();
  const alto = doc.internal.pageSize.getHeight();
  const pagina = doc.internal.getNumberOfPages();

  doc.setDrawColor(...RGB_BORDE);
  doc.setLineWidth(0.7);
  doc.line(margen, alto - 46, ancho - margen, alto - 46);

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(9);
  doc.setTextColor(...RGB_TEXTO_2);
  doc.text('Datos simulados — mockup de validación', margen, alto - 30);
  doc.text(`Página ${pagina}`, ancho - margen, alto - 30, { align: 'right' });
}

/**
 * Estilos comunes de todas las tablas del PDF.
 * `paginasConPie` evita repintar el pie cuando dos tablas caen en la misma
 * página: sin ese control el texto se dibujaría dos veces encima de sí mismo.
 */
function estilosTabla(doc, margen, paginasConPie) {
  return {
    didDrawPage: () => {
      const pagina = doc.internal.getNumberOfPages();
      if (paginasConPie.has(pagina)) return;
      paginasConPie.add(pagina);
      pieDePagina(doc, margen);
    },
    margin: { left: margen, right: margen, bottom: 62 },
    styles: {
      font: 'helvetica',
      fontSize: 10,
      cellPadding: 6,
      textColor: RGB_TEXTO,
      lineColor: RGB_BORDE,
      lineWidth: 0.5,
    },
    headStyles: {
      fillColor: RGB_ACENTO,
      textColor: [255, 255, 255],
      fontStyle: 'bold',
    },
    alternateRowStyles: { fillColor: RGB_FILA },
  };
}

/**
 * PDF A4 con el mismo contenido del Excel: resumen del turno, raciones por
 * categoría y detalle nominal, con pie de página numerado.
 *
 * @param {object} reporte  reporte del día: turno, fechaArchivo, resumen, porCategoria y detalle
 * @returns {string} nombre del archivo generado
 */
export function exportarReportePdf(reporte) {
  const doc = new jsPDF({ unit: 'pt', format: 'a4', orientation: 'portrait' });
  const margen = 40;
  const comun = estilosTabla(doc, margen, new Set());

  let y = cabeceraPdf(doc, reporte, margen);

  function tituloBloque(texto) {
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(11.5);
    doc.setTextColor(...RGB_ACENTO_FUERTE);
    doc.text(texto, margen, y);
    y += 12;
  }

  tituloBloque('Resumen del turno');
  autoTable(doc, {
    ...comun,
    startY: y,
    theme: 'grid',
    body: filasResumen(reporte).map(([rotulo, valor]) => [rotulo, String(valor)]),
    columnStyles: {
      0: { cellWidth: 260, textColor: RGB_TEXTO_2 },
      1: { fontStyle: 'bold', halign: 'right' },
    },
  });
  y = doc.lastAutoTable.finalY + 30;

  tituloBloque('Raciones por categoría');
  autoTable(doc, {
    ...comun,
    startY: y,
    head: [['Categoría', 'Raciones', 'Participación']],
    body: reporte.porCategoria.map((fila) => [
      fila.categoria,
      String(fila.raciones),
      `${fila.participacion}%`,
    ]),
    foot: [['Total', String(reporte.totalCategorias), '100%']],
    footStyles: {
      fillColor: RGB_FILA,
      textColor: RGB_TEXTO,
      fontStyle: 'bold',
      lineColor: RGB_BORDE,
      lineWidth: 0.5,
    },
    columnStyles: {
      1: { halign: 'right', cellWidth: 90 },
      2: { halign: 'right', cellWidth: 110 },
    },
  });
  y = doc.lastAutoTable.finalY + 30;

  tituloBloque('Detalle por comensal');
  autoTable(doc, {
    ...comun,
    startY: y,
    head: [['Legajo', 'Nombre completo', 'Categoría', 'Turno', 'Estado']],
    body: reporte.detalle.map((fila) => [
      fila.legajo,
      fila.nombre,
      fila.categoria,
      fila.turno,
      fila.estado,
    ]),
    columnStyles: {
      0: { cellWidth: 66 },
      2: { cellWidth: 78 },
      3: { cellWidth: 66 },
      4: { cellWidth: 72 },
    },
  });

  const archivo = nombreArchivo(reporte, 'pdf');
  doc.save(archivo);
  return archivo;
}

/* ------------------------------------ Formulario de raciones (día y mes) */

/*
 * Este PDF no sigue el estilo de la app, sigue el del papel: el formulario que
 * hasta ahora se llenaba a mano en el Servicio de Estadística. Por eso va en
 * A4 apaisado, en blanco y negro y con la rejilla completa.
 *
 * Lo que sí desaparece del papel son las líneas de puntos: existían para
 * escribir encima. Aquí las cifras las pone el sistema.
 *
 * La misma función sirve para el reporte del día y para el informe del mes:
 * cambia el rótulo del período y las cifras de cierre, no la hoja.
 */

const RGB_NEGRO = [0, 0, 0];
const RGB_BLANCO = [255, 255, 255];

const ENCABEZADO_FORMULARIO = [
  'HOSPITAL UNIVERSITARIO "SAN JUAN DE DIOS"',
  'SERVICIO DE ESTADÍSTICA',
];

/* Cifras como en el papel: sin separador de miles y con coma decimal. */
const NUMERO_FORMULARIO = new Intl.NumberFormat('es-BO', {
  useGrouping: false,
  maximumFractionDigits: 2,
});

function cifraFormulario(valor) {
  return valor > 0 ? NUMERO_FORMULARIO.format(valor) : '-';
}

/* Coeficientes y equivalentes con dos decimales fijos: en una columna de
   cuatro resultados, «0.5» junto a «0.15» se lee como si fueran de distinta
   escala, y lo mismo pasa con 54 junto a 11,25. */
const DOS_DECIMALES = new Intl.NumberFormat('es-BO', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/* ----------------------- Advertencias pendientes de clasificar ----------------------- *
 * `sin_clasificar` y `sin_coeficiente` miden lo que falta, no un error: mientras
 * sean mayores que cero, el informe no cuadra 100 % con el papel. Se muestran
 * como advertencia (banner en pantalla, nota al pie en los archivos), nunca en
 * silencio y nunca bloqueando la vista ni la exportación.
 * --------------------------------------------------------------------------------- */

const FORMATO_AVISO = new Intl.NumberFormat('es-BO');

function textoSinClasificar(cantidad) {
  const cifra = FORMATO_AVISO.format(cantidad);
  return cantidad === 1
    ? `${cifra} ración servida a personal sin categoría asignada en el formulario. No está incluida en las columnas de arriba — queda pendiente de clasificar.`
    : `${cifra} raciones servidas a personal sin categoría asignada en el formulario. No están incluidas en las columnas de arriba — quedan pendientes de clasificar.`;
}

function textoSinCoeficiente(cantidad) {
  const cifra = FORMATO_AVISO.format(cantidad);
  return cantidad === 1
    ? `${cifra} ración de un tiempo de comida sin coeficiente asignado. No se incluyó en el total de raciones completas equivalentes.`
    : `${cifra} raciones de un tiempo de comida sin coeficiente asignado. No se incluyeron en el total de raciones completas equivalentes.`;
}

/**
 * Notas al pie del informe, fuera de la tabla oficial: la tabla sigue siendo
 * el formulario calcado del papel y la advertencia viaja con el archivo.
 * `sin_coeficiente` solo aplica al informe mensual, que es el único con
 * reducción a ración completa.
 *
 * @param {object} informe  salida de obtenerInformeRaciones() o de cualquiera de los informes por período
 * @returns {string[]} cero, una o dos notas
 */
export function notasDeInforme(informe) {
  if (!informe) return [];
  const notas = [];
  if (informe.sinClasificar > 0) notas.push(textoSinClasificar(informe.sinClasificar));
  if (esFormulario(informe) && informe.sinCoeficiente > 0) {
    notas.push(textoSinCoeficiente(informe.sinCoeficiente));
  }
  return notas;
}

/**
 * Filas de la tabla con el mismo aspecto para las tres vistas: cambia el
 * rótulo de la primera columna (día, mes o tiempo de comida), no el resto.
 */function filasDeInforme(informe) {
  if (esFormulario(informe)) {
    return informe.filas.map((fila) => ({ rotulo: fila.tiempo, ...fila, registrado: true }));
  }

  if (informe.tipo === 'gestion') {
    return informe.filas.map((fila) => ({ rotulo: fila.mes, ...fila }));
  }

  return informe.filas.map((fila) => ({ rotulo: String(fila.dia).padStart(2, '0'), ...fila }));
}

function cabeceraFormulario(doc, informe, margen) {
  const ancho = doc.internal.pageSize.getWidth();

  doc.setTextColor(...RGB_NEGRO);
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(9.5);
  doc.text(ENCABEZADO_FORMULARIO[0], margen, 44);
  doc.setFontSize(8.5);
  doc.text(ENCABEZADO_FORMULARIO[1], margen, 56);

  /* El título va en su propia línea: centrado a la altura del membrete se
     solapaba con el nombre del hospital. */
  const apaisado = ancho > 700;
  doc.setFontSize(apaisado ? 13.5 : 11.5);
  doc.text(informe.titulo.toUpperCase(), ancho / 2, 80, { align: 'center' });

  /* En vertical el título ocupa casi todo el ancho, así que la gestión baja a
     la línea del período en vez de pelearse con él. En el resumen anual el
     período ya es la gestión, y repetirla sería decir dos veces lo mismo. */
  if (informe.tipo !== 'gestion') {
    doc.setFontSize(10);
    doc.text(`GESTIÓN : ${informe.gestion}`, ancho - margen, apaisado ? 80 : 106, {
      align: 'right',
    });
  }

  doc.setFontSize(11);
  doc.text(informe.encabezado.rotulo, margen, 106);
  /* El rótulo cambia de largo según el informe («MES :», «PERÍODO :»), así que
     el valor se coloca midiéndolo y no a una distancia fija. */
  doc.text(informe.encabezado.valor, margen + doc.getTextWidth(informe.encabezado.rotulo) + 12, 106);

  return 118;
}

/** Bloque de coeficientes y las cifras de cierre, al pie de la tabla. */
function coeficientesFormulario(doc, informe, margen, desdeY) {
  let y = desdeY;

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(9.5);
  doc.text(
    'COEFICIENTES ASIGNADOS A LOS TIEMPOS DE COMIDA PARA REDUCIR A RACIÓN COMPLETA',
    margen,
    y,
  );

  /* Columnas fijas: los valores, los coeficientes y los resultados quedan en
     la misma vertical aunque el rótulo sea más corto. */
  const xServidas = margen + 330;
  const xCoeficiente = margen + 360;
  const xIgual = margen + 435;
  const xEquivalente = margen + 510;

  y += 24;
  doc.setFontSize(10);

  informe.grupos.forEach((grupo) => {
    doc.setFont('helvetica', 'normal');
    doc.text(`${grupo.etiqueta.toUpperCase()} :`, margen, y);

    doc.text(cifraFormulario(grupo.servidas), xServidas, y, { align: 'right' });
    doc.text(`X ${grupo.coeficiente.toFixed(2)}`, xCoeficiente, y);
    doc.text('=', xIgual, y);

    doc.setFont('helvetica', 'bold');
    doc.text(DOS_DECIMALES.format(grupo.equivalente), xEquivalente, y, { align: 'right' });

    y += 19;
  });

  /* Raya de suma sobre las cifras de cierre, como la del papel. */
  doc.setDrawColor(...RGB_NEGRO);
  doc.setLineWidth(0.8);
  doc.line(xEquivalente - 62, y - 12, xEquivalente, y - 12);

  y += 8;

  informe.cierre.forEach((dato) => {
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(10);
    doc.text(dato.rotulo.toUpperCase(), margen, y);
    doc.text('=', xIgual, y);
    doc.text(NUMERO_FORMULARIO.format(dato.valor), xEquivalente, y, { align: 'right' });

    if (dato.detalle) {
      doc.setFont('helvetica', 'normal');
      doc.setFontSize(8.5);
      doc.text(`(${dato.detalle})`, xEquivalente + 12, y);
    }

    y += 19;
  });

  return y;
}

/**
 * Notas de advertencia al pie de la hoja, fuera de la tabla oficial: la tabla
 * sigue siendo el formulario calcado del papel y la advertencia viaja con el
 * archivo si alguien lo imprime o lo archiva.
 */
function notasFormulario(doc, informe, margen, desdeY) {
  const notas = notasDeInforme(informe);
  if (notas.length === 0) return desdeY;

  const ancho = doc.internal.pageSize.getWidth() - margen * 2;
  const alto = doc.internal.pageSize.getHeight();
  let y = desdeY;

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(8.5);
  doc.setTextColor(...RGB_NEGRO);

  notas.forEach((nota) => {
    const lineas = doc.splitTextToSize(`NOTA: ${nota}`, ancho);
    if (y + lineas.length * 11 > alto - 52) {
      doc.addPage();
      y = 60;
    }
    doc.text(lineas, margen, y);
    y += lineas.length * 11 + 8;
  });

  return y;
}

/** Pie: el formulario ya no se firma a mano, lo emite el sistema. */
function pieFormulario(doc, informe, margen) {
  const alto = doc.internal.pageSize.getHeight();

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(8.5);
  doc.setTextColor(...RGB_NEGRO);
  doc.text(
    `Generado automáticamente por el ${NOMBRE_SISTEMA} · ${informe.generado}`,
    margen,
    alto - 34,
  );
}

/** Formulario mensual: tiempos de comida × personal, con los coeficientes. */
function hojaFormulario(informe) {
  const doc = new jsPDF({ unit: 'pt', format: 'a4', orientation: 'landscape' });
  const margen = 40;

  const y = cabeceraFormulario(doc, informe, margen);

  autoTable(doc, {
    startY: y,
    margin: { left: margen, right: margen },
    theme: 'grid',
    styles: {
      font: 'helvetica',
      fontSize: 9,
      cellPadding: 7,
      textColor: RGB_NEGRO,
      lineColor: RGB_NEGRO,
      lineWidth: 0.8,
      halign: 'center',
      valign: 'middle',
    },
    headStyles: {
      fillColor: RGB_BLANCO,
      textColor: RGB_NEGRO,
      fontStyle: 'bold',
      fontSize: 8.5,
      lineColor: RGB_NEGRO,
      lineWidth: 0.8,
    },
    footStyles: {
      fillColor: RGB_BLANCO,
      textColor: RGB_NEGRO,
      fontStyle: 'bold',
      lineColor: RGB_NEGRO,
      lineWidth: 0.8,
    },
    columnStyles: { 0: { halign: 'left', fontStyle: 'bold', cellWidth: 150 } },
    head: [
      [
        { content: 'TIEMPOS DE COMIDA', rowSpan: 2 },
        { content: 'P E R S O N A L', colSpan: informe.categorias.length },
        { content: 'TOTAL', rowSpan: 2 },
      ],
      informe.categorias.map((categoria) => categoria.toUpperCase()),
    ],
    body: informe.filas.map((fila) => [
      fila.tiempo.toUpperCase(),
      ...fila.celdas.map(cifraFormulario),
      cifraFormulario(fila.total),
    ]),
    foot: [
      [
        { content: 'TOTAL', styles: { halign: 'left' } },
        ...informe.totalesPorCategoria.map(cifraFormulario),
        NUMERO_FORMULARIO.format(informe.totalGeneral),
      ],
    ],
  });

  const trasCoeficientes = coeficientesFormulario(doc, informe, margen, doc.lastAutoTable.finalY + 30);
  notasFormulario(doc, informe, margen, trasCoeficientes + 14);
  pieFormulario(doc, informe, margen);

  const archivo = `${informe.archivo}.pdf`;
  doc.save(archivo);
  return archivo;
}

/**
 * Planilla del cuaderno: una fila por día (registro diario) o por mes
 * (gestión). Va en vertical, como el cuaderno.
 */
function hojaPlanilla(informe) {
  const doc = new jsPDF({ unit: 'pt', format: 'a4', orientation: 'portrait' });
  const margen = 40;

  const y = cabeceraFormulario(doc, informe, margen);

  autoTable(doc, {
    startY: y,
    margin: { left: margen, right: margen },
    theme: 'grid',
    styles: {
      font: 'helvetica',
      fontSize: 8,
      cellPadding: 4,
      textColor: RGB_NEGRO,
      lineColor: RGB_NEGRO,
      lineWidth: 0.7,
      halign: 'center',
      valign: 'middle',
    },
    headStyles: {
      fillColor: RGB_BLANCO,
      textColor: RGB_NEGRO,
      fontStyle: 'bold',
      fontSize: 7,
      lineColor: RGB_NEGRO,
      lineWidth: 0.7,
    },
    footStyles: {
      fillColor: RGB_BLANCO,
      textColor: RGB_NEGRO,
      fontStyle: 'bold',
      lineColor: RGB_NEGRO,
      lineWidth: 0.7,
    },
    columnStyles: { 0: { fontStyle: 'bold', cellWidth: informe.tipo === 'gestion' ? 74 : 48 } },
    head: [informe.encabezados.map((titulo) => titulo.toUpperCase())],
    body: filasDeInforme(informe).map((fila) => [
      fila.rotulo.toUpperCase(),
      ...fila.celdas.map(cifraFormulario),
      cifraFormulario(fila.total),
    ]),
    foot: [
      [
        'TOTAL',
        ...informe.totalesPorCategoria.map(cifraFormulario),
        NUMERO_FORMULARIO.format(informe.totalGeneral),
      ],
    ],
  });

  notasFormulario(doc, informe, margen, doc.lastAutoTable.finalY + 22);
  pieFormulario(doc, informe, margen);

  const archivo = `${informe.archivo}.pdf`;
  doc.save(archivo);
  return archivo;
}

/**
 * Registro diario, informe mensual o resumen de gestión en PDF, calcados del
 * papel que ya se usa en el hospital. La hoja se elige por el tipo.
 *
 * @param {object} informe  salida de obtenerInformeRaciones() o de cualquiera de los informes por período
 * @returns {string} nombre del archivo generado
 */
export function exportarInformePdf(informe) {
  return esFormulario(informe) ? hojaFormulario(informe) : hojaPlanilla(informe);
}

/* ------------------------------------------------- Excel de los informes */

/*
 * El Excel del informe no es una copia del PDF: el PDF es el formulario en
 * papel, y esta hoja es la herramienta de trabajo del Servicio de Estadística.
 * Por eso lleva la identidad verde del sistema y, sobre todo, fórmulas nativas
 * en todos los totales: quien reciba el archivo puede corregir una celda y ver
 * recalcularse la columna, el total del mes y el promedio por día, sin que
 * nadie tenga que rehacer las cuentas a mano.
 */

const HOJA_RACIONES = 'Raciones';
const HOJA_COEFICIENTES = 'Coeficientes';

/* El mismo sello que cierra el PDF del formulario. */
function pieImpreso(generado) {
  return `Generado automáticamente por el ${NOMBRE_SISTEMA} · ${generado}`;
}

/** Días (o meses) con registro, que es entre lo que se saca el promedio. */
function registradosDelInforme(informe) {
  return informe.tipo === 'gestion' ? informe.mesesRegistrados : informe.diasRegistrados;
}

/**
 * El mensual cierra en raciones completas equivalentes, que son decimales
 * aunque un mes concreto dé redondo; el resto cierra en raciones contadas.
 */
function formatoDeCierre(informe, valor) {
  if (esFormulario(informe)) return FORMATO_DECIMAL;
  return Number.isInteger(valor) ? FORMATO_ENTERO : FORMATO_DECIMAL;
}

/**
 * Las dos tarjetas de cierre, siempre calculadas por Excel:
 * la primera apunta a la celda que ya tiene el total (el total general de la
 * tabla, o el equivalente de la hoja de coeficientes) y la segunda divide esa
 * misma celda entre los días o meses registrados.
 */
function cierreConFormulas(hoja, desdeFila, informe, referenciaTotal, columnas) {
  const registrados = registradosDelInforme(informe);
  const [total, promedio] = informe.cierre;

  tarjetaCierre(hoja, desdeFila, {
    rotulo: total.rotulo,
    valor: formula(referenciaTotal, total.valor),
    detalle: total.detalle,
    formato: formatoDeCierre(informe, total.valor),
  });

  tarjetaCierre(hoja, desdeFila + 1, {
    rotulo: promedio.rotulo,
    /* Sin registros no hay división posible: se deja la cifra tal cual. */
    valor: registrados > 0
      ? formula(`${celda(desdeFila, 2)}/${registrados}`, promedio.valor)
      : promedio.valor,
    detalle: promedio.detalle,
    formato: FORMATO_PROMEDIO,
  });

  let fila = desdeFila + 2;
  const notas = notasDeInforme(informe);
  if (notas.length > 0) {
    fila += 1;
    notaAlPie(hoja, fila, 'Notas:', columnas);
    notas.forEach((nota) => {
      fila += 1;
      notaAlPie(hoja, fila, nota, columnas);
    });
  }
  return fila;
}

/**
 * Hoja principal: la tabla del informe con la misma forma que en pantalla.
 * El total de cada fila y de cada columna son `SUM()`, no cifras pegadas.
 */
function hojaDelInforme(libro, informe) {
  const encabezados = informe.encabezados;
  const columnas = encabezados.length;
  const colTotal = columnas;
  const filas = filasDeInforme(informe);

  const hoja = nuevaHoja(libro, HOJA_RACIONES);
  const filaCabecera = banner(hoja, columnas, {
    sistema: NOMBRE_SISTEMA.toUpperCase(),
    titulo: informe.titulo,
    subtitulo: `${informe.periodo.principal} · ${informe.periodo.secundario}  |  Generado: ${informe.generado}`,
  });
  cabecera(hoja, filaCabecera, encabezados);

  /* El día va como número con formato «00» y no como el texto "01": así Excel
     no lo marca con el aviso de «número almacenado como texto». */
  const esRegistro = informe.tipo === 'registro';
  const primera = filaCabecera + 1;
  filas.forEach((fila, indice) => {
    const numero = primera + indice;
    /* Los días todavía sin registrar se dejan en blanco, como en el cuaderno. */
    const registrado = fila.registrado !== false;
    filaDatos(hoja, numero, [
      esRegistro ? fila.dia : fila.rotulo,
      ...fila.celdas.map((valor) => (registrado ? valor : null)),
      registrado
        ? formula(`SUM(${celda(numero, 2)}:${celda(numero, colTotal - 1)})`, fila.total)
        : null,
    ], {
      formatoRotulo: esRegistro ? FORMATO_DIA : undefined,
      rotuloCentrado: esRegistro,
      /* La columna «Total» va en su propia banda, como en el original. */
      columnaDestacada: colTotal,
    });
  });

  const ultima = primera + filas.length - 1;
  const sumaColumna = (indice, resultado) =>
    formula(`SUM(${columna(indice)}${primera}:${columna(indice)}${ultima})`, resultado);

  const filaTotal = ultima + 1;
  filaTotales(hoja, filaTotal, [
    'Total',
    ...informe.totalesPorCategoria.map((valor, indice) => sumaColumna(indice + 2, valor)),
    sumaColumna(colTotal, informe.totalGeneral),
  ]);

  hoja.autoFilter = {
    from: { row: filaCabecera, column: 1 },
    to: { row: ultima, column: columnas },
  };

  /* Angosto a propósito: la tabla tiene que caber en un A4 al imprimirse. */
  ajustarAnchos(hoja, encabezados.map((titulo, indice) => [
    titulo,
    ...(indice === 0 ? filas.map((fila) => fila.rotulo) : []),
  ]), { minimo: 10, maximo: 12, primera: 18 });

  return { hoja, columnas, filaTotal, colTotal, primera };
}

/**
 * Hoja de coeficientes (solo el informe mensual): la reducción a ración
 * completa, con las servidas tomadas de la hoja anterior y el equivalente
 * como multiplicación real. Cambiar un coeficiente aquí recalcula el mes.
 */
function hojaDeCoeficientes(libro, informe, racionesInfo) {
  const encabezados = ['Tiempo de comida', 'Servidas', 'Coeficiente', 'Equivalente'];
  const hoja = nuevaHoja(libro, HOJA_COEFICIENTES);

  const filaCabecera = banner(hoja, encabezados.length, {
    sistema: NOMBRE_SISTEMA.toUpperCase(),
    titulo: 'Coeficientes para reducir a ración completa',
    subtitulo: `${informe.periodo.principal} · ${informe.periodo.secundario}`,
  });
  cabecera(hoja, filaCabecera, encabezados);

  const normalizar = (texto) => String(texto ?? '').trim().toLowerCase();
  const primera = filaCabecera + 1;

  informe.grupos.forEach((grupo, indice) => {
    const numero = primera + indice;
    /* Las servidas son el total de ese tiempo de comida en la otra hoja: se
       enlazan en vez de repetirse, para que las dos hojas no se separen. */
    const enTabla = informe.filas.findIndex((fila) => normalizar(fila.tiempo) === normalizar(grupo.etiqueta));
    const servidas = enTabla >= 0
      ? formula(
        `${HOJA_RACIONES}!${celda(racionesInfo.primera + enTabla, racionesInfo.colTotal)}`,
        grupo.servidas,
      )
      : grupo.servidas;

    filaDatos(hoja, numero, [
      grupo.etiqueta,
      servidas,
      grupo.coeficiente,
      formula(`${celda(numero, 2)}*${celda(numero, 3)}`, grupo.equivalente),
    ]);
    hoja.getCell(numero, 3).numFmt = FORMATO_PROMEDIO;
    hoja.getCell(numero, 4).numFmt = FORMATO_DECIMAL;
  });

  const ultima = primera + informe.grupos.length - 1;
  const filaTotal = ultima + 1;
  const [total, promedio] = informe.cierre;
  const registrados = registradosDelInforme(informe);

  filaTotales(hoja, filaTotal, [
    total.rotulo,
    null,
    null,
    formula(`SUM(D${primera}:D${ultima})`, total.valor),
  ], { formato: FORMATO_DECIMAL });

  tarjetaCierre(hoja, filaTotal + 1, {
    rotulo: promedio.rotulo,
    valor: registrados > 0
      ? formula(`D${filaTotal}/${registrados}`, promedio.valor)
      : promedio.valor,
    formato: FORMATO_PROMEDIO,
    /* Debajo del equivalente, que es de donde sale. */
    columnaValor: 4,
  });

  configurarImpresion(hoja, {
    ultimaFila: filaTotal + 1,
    ultimaColumna: encabezados.length,
    pie: pieImpreso(informe.generado),
  });

  ajustarAnchos(hoja, [
    [...encabezados.slice(0, 1), ...informe.grupos.map((grupo) => grupo.etiqueta), total.rotulo, promedio.rotulo],
    ['Servidas'],
    ['Coeficiente'],
    ['Equivalente'],
  ], { minimo: 14, primera: 28 });

  return { filaTotal };
}

/**
 * Libro .xlsx del informe abierto: una hoja con la tabla tal cual se ve y,
 * cuando el informe los tiene, otra con los coeficientes de ración completa.
 *
 * La generación es asíncrona (ExcelJS se carga bajo demanda), pero el nombre
 * del archivo se devuelve de inmediato: la UI lo muestra sin esperar.
 *
 * @param {object} informe  salida de cualquiera de los tres informes
 * @returns {string} nombre del archivo generado
 */
export function exportarInformeExcel(informe) {
  const archivo = `${informe.archivo}.xlsx`;

  generarLibroEnSegundoPlano(archivo, (libro) => {
    const raciones = hojaDelInforme(libro, informe);
    const tieneCoeficientes = Array.isArray(informe.grupos) && informe.grupos.length > 0;
    const coeficientes = tieneCoeficientes ? hojaDeCoeficientes(libro, informe, raciones) : null;

    /* El cierre del mensual cuelga de la hoja de coeficientes; el del registro
       diario y el de la gestión, del total general de su propia tabla. */
    const referenciaTotal = coeficientes
      ? `${HOJA_COEFICIENTES}!D${coeficientes.filaTotal}`
      : celda(raciones.filaTotal, raciones.colTotal);

    const ultimaFila = cierreConFormulas(
      raciones.hoja, raciones.filaTotal + 2, informe, referenciaTotal, raciones.columnas,
    );

    /* Como el formulario de papel: el mensual apaisado, las planillas de días
       y de meses en vertical, y todo en una sola hoja A4. */
    configurarImpresion(raciones.hoja, {
      orientacion: esFormulario(informe) ? 'landscape' : 'portrait',
      ultimaFila,
      ultimaColumna: raciones.columnas,
      pie: pieImpreso(informe.generado),
    });
  });

  return archivo;
}
