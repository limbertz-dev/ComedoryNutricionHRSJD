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
  casillaFormulario,
  celda,
  columna,
  configurarImpresion,
  filaDatos,
  filaTotales,
  formula,
  FORMATO_CIFRA,
  FORMATO_COEFICIENTE,
  FORMATO_CONTEO,
  FORMATO_DECIMAL,
  FORMATO_DIA,
  FORMATO_ENTERO,
  FORMATO_PORCENTAJE,
  FORMATO_PROMEDIO,
  generarLibroEnSegundoPlano,
  logoFormulario,
  nuevaHoja,
  textoFormulario,
} from './excelEstilos.js';
import { LOGO_HOSPITAL } from './membrete.js';

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
    ? `${cifra} ración pendiente de clasificación. Está incluida en el total del informe.`
    : `${cifra} raciones pendientes de clasificación. Están incluidas en el total del informe.`;
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

  /* Logo del hospital a la izquierda del membrete; es lo único en color. */
  const altoLogo = 40;
  const anchoLogo = (LOGO_HOSPITAL.ancho * altoLogo) / LOGO_HOSPITAL.alto;
  doc.addImage(`data:image/png;base64,${LOGO_HOSPITAL.base64}`, 'PNG', margen, 24, anchoLogo, altoLogo);
  const xMembrete = margen + anchoLogo + 8;

  doc.setTextColor(...RGB_NEGRO);
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(9.5);
  doc.text(ENCABEZADO_FORMULARIO[0], xMembrete, 42);
  doc.setFontSize(8.5);
  doc.text(ENCABEZADO_FORMULARIO[1], xMembrete, 54);

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
    doc.text(grupo.coeficienteVariable ? 'Variable' : `X ${grupo.coeficiente.toFixed(2)}`, xCoeficiente, y);
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
 * El Excel del informe es el mismo formulario que el PDF, en una sola hoja:
 * membrete con el logo, la tabla en blanco y negro y, debajo, los
 * coeficientes de ración completa con las cifras de cierre. Lo que el Excel
 * agrega son las fórmulas nativas: quien reciba el archivo puede corregir una
 * celda y ver recalcularse la fila, la columna, el equivalente y el promedio
 * por día, sin rehacer las cuentas a mano.
 */

const HOJA_INFORME = 'Informe';

/** Días (o meses) con registro, que es entre lo que se saca el promedio. */
function registradosDelInforme(informe) {
  return informe.tipo === 'gestion' ? informe.mesesRegistrados : informe.diasRegistrados;
}

/**
 * El formulario cierra en raciones completas equivalentes, que son decimales
 * aunque un mes concreto dé redondo; las planillas cierran en raciones contadas.
 */
function formatoDeCierre(informe, valor) {
  if (esFormulario(informe)) return FORMATO_DECIMAL;
  return Number.isInteger(valor) ? FORMATO_CONTEO : FORMATO_DECIMAL;
}

/**
 * Columnas del bloque de coeficientes, alineadas a la derecha de la tabla como
 * en el PDF: servidas, «X coeficiente», «=», equivalente y la aclaración.
 * Con pocas categorías la tabla es angosta y el bloque se sale por la derecha
 * antes que pisar la columna de los rótulos.
 */
function columnasDeCierre(columnas) {
  const servidas = Math.max(2, columnas - 5);
  return {
    servidas,
    coeficiente: servidas + 1,
    igual: servidas + 2,
    equivalente: servidas + 3,
    detalle: servidas + 4,
  };
}

/** Membrete: logo, hospital y servicio; título; período y gestión. */
function membreteExcel(libro, hoja, informe, columnas) {
  logoFormulario(libro, hoja, LOGO_HOSPITAL);

  /* La sangría deja el nombre a la derecha del logo, en la misma línea. */
  hoja.getRow(1).height = 18;
  hoja.getRow(2).height = 16;
  textoFormulario(hoja.getCell(1, 1), ENCABEZADO_FORMULARIO[0], { tamano: 10, negrita: true, indent: 8 });
  textoFormulario(hoja.getCell(2, 1), ENCABEZADO_FORMULARIO[1], { tamano: 8.5, negrita: true, indent: 8 });
  hoja.getRow(3).height = 14;

  hoja.mergeCells(4, 1, 4, columnas);
  hoja.getRow(4).height = 24;
  textoFormulario(hoja.getCell(4, 1), informe.titulo.toUpperCase(), {
    tamano: 13, negrita: true, horizontal: 'center',
  });

  hoja.getRow(5).height = 22;
  textoFormulario(
    hoja.getCell(5, 1),
    `${informe.encabezado.rotulo}   ${informe.encabezado.valor}`,
    { tamano: 11, negrita: true },
  );
  /* En el resumen anual el período ya es la gestión: no se repite. */
  if (informe.tipo !== 'gestion') {
    textoFormulario(hoja.getCell(5, columnas), `GESTIÓN : ${informe.gestion}`, {
      tamano: 10, negrita: true, horizontal: 'right',
    });
  }
  hoja.getRow(6).height = 8;
  return 7;
}

/**
 * Cabecera de la tabla. El formulario lleva la del papel, en dos pisos
 * (TIEMPOS DE COMIDA | P E R S O N A L sobre las categorías | TOTAL); las
 * planillas, una sola fila. Devuelve la primera fila de datos.
 */
function cabeceraExcel(hoja, informe, desde, columnas) {
  const titulo = (celdaTitulo, texto) => casillaFormulario(celdaTitulo, texto, { tamano: 8.5, negrita: true });

  if (!esFormulario(informe)) {
    hoja.getRow(desde).height = 30;
    informe.encabezados.forEach((texto, indice) => titulo(hoja.getCell(desde, indice + 1), texto.toUpperCase()));
    return desde + 1;
  }

  hoja.getRow(desde).height = 22;
  hoja.getRow(desde + 1).height = 30;
  /* Combinar no propaga el borde: cada celda del bloque se enmarca aparte. */
  for (let col = 1; col <= columnas; col += 1) {
    titulo(hoja.getCell(desde, col), null);
    titulo(hoja.getCell(desde + 1, col), null);
  }
  hoja.mergeCells(desde, 1, desde + 1, 1);
  hoja.mergeCells(desde, 2, desde, columnas - 1);
  hoja.mergeCells(desde, columnas, desde + 1, columnas);
  hoja.getCell(desde, 1).value = 'TIEMPOS DE COMIDA';
  hoja.getCell(desde, 2).value = 'P E R S O N A L';
  hoja.getCell(desde, columnas).value = 'TOTAL';
  informe.categorias.forEach((categoria, indice) => {
    hoja.getCell(desde + 1, indice + 2).value = categoria.toUpperCase();
  });
  return desde + 2;
}

/**
 * Cuerpo y fila de totales. El total de cada fila y de cada columna son
 * `SUM()`, no cifras pegadas.
 */
function tablaExcel(hoja, informe, primera, columnas) {
  const esRegistro = informe.tipo === 'registro';
  const filas = filasDeInforme(informe);
  const filaDeTiempo = new Map();

  filas.forEach((fila, indice) => {
    const numero = primera + indice;
    hoja.getRow(numero).height = 20;
    /* Los días todavía sin registrar se dejan en blanco, como en el cuaderno. */
    const registrado = fila.registrado !== false;
    if (fila.tiempo) filaDeTiempo.set(normalizarRotulo(fila.tiempo), numero);

    /* El día va como número con formato «00» y no como el texto "01": así
       Excel no lo marca con el aviso de «número almacenado como texto». */
    casillaFormulario(hoja.getCell(numero, 1), esRegistro ? fila.dia : fila.rotulo.toUpperCase(), {
      negrita: true,
      horizontal: esRegistro ? 'center' : 'left',
      formato: esRegistro ? FORMATO_DIA : undefined,
    });
    fila.celdas.forEach((valor, indice2) => {
      casillaFormulario(hoja.getCell(numero, indice2 + 2), registrado ? valor : null, { formato: FORMATO_CIFRA });
    });
    casillaFormulario(
      hoja.getCell(numero, columnas),
      registrado ? formula(`SUM(${celda(numero, 2)}:${celda(numero, columnas - 1)})`, fila.total) : null,
      { formato: FORMATO_CIFRA },
    );
  });

  const ultima = primera + filas.length - 1;
  const filaTotal = ultima + 1;
  const sumaColumna = (col, resultado) => (filas.length > 0
    ? formula(`SUM(${columna(col)}${primera}:${columna(col)}${ultima})`, resultado)
    : resultado);

  hoja.getRow(filaTotal).height = 22;
  casillaFormulario(hoja.getCell(filaTotal, 1), 'TOTAL', { negrita: true, horizontal: 'left' });
  informe.totalesPorCategoria.forEach((valor, indice) => {
    casillaFormulario(hoja.getCell(filaTotal, indice + 2), sumaColumna(indice + 2, valor), {
      negrita: true, formato: FORMATO_CIFRA,
    });
  });
  casillaFormulario(hoja.getCell(filaTotal, columnas), sumaColumna(columnas, informe.totalGeneral), {
    negrita: true, formato: FORMATO_CONTEO,
  });

  return { filaTotal, filaDeTiempo };
}

function normalizarRotulo(texto) {
  return String(texto ?? '').trim().toLowerCase();
}

/**
 * Coeficientes (solo el formulario): cada tiempo de comida toma sus servidas
 * del total de su fila en la tabla y el equivalente es una multiplicación
 * real, así que cambiar un coeficiente recalcula el informe. Con coeficientes
 * mixtos en el período no hay una sola multiplicación posible: se deja el
 * equivalente que calculó el sistema por vigencia.
 */
function coeficientesExcel(hoja, informe, desde, columnas, tabla) {
  const pos = columnasDeCierre(columnas);
  let fila = desde;

  hoja.getRow(fila).height = 20;
  textoFormulario(
    hoja.getCell(fila, 1),
    'COEFICIENTES ASIGNADOS A LOS TIEMPOS DE COMIDA PARA REDUCIR A RACIÓN COMPLETA',
    { tamano: 9.5, negrita: true },
  );
  fila += 1;

  const primera = fila;
  informe.grupos.forEach((grupo, indice) => {
    hoja.getRow(fila).height = 18;
    textoFormulario(hoja.getCell(fila, 1), `${grupo.etiqueta.toUpperCase()} :`);

    const enTabla = tabla.filaDeTiempo.get(normalizarRotulo(grupo.etiqueta));
    textoFormulario(
      hoja.getCell(fila, pos.servidas),
      enTabla ? formula(celda(enTabla, columnas), grupo.servidas) : grupo.servidas,
      { horizontal: 'right', formato: FORMATO_CIFRA },
    );
    textoFormulario(
      hoja.getCell(fila, pos.coeficiente),
      grupo.coeficienteVariable ? 'Variable' : grupo.coeficiente,
      { horizontal: 'center', formato: FORMATO_COEFICIENTE },
    );
    textoFormulario(hoja.getCell(fila, pos.igual), '=', { horizontal: 'center' });
    textoFormulario(
      hoja.getCell(fila, pos.equivalente),
      grupo.coeficienteVariable
        ? grupo.equivalente
        : formula(`${celda(fila, pos.servidas)}*${celda(fila, pos.coeficiente)}`, grupo.equivalente),
      { negrita: true, horizontal: 'right', formato: FORMATO_DECIMAL },
    );
    /* Raya de suma bajo el último equivalente, como la del papel. */
    if (indice === informe.grupos.length - 1) {
      hoja.getCell(fila, pos.equivalente).border = { bottom: { style: 'thin', color: { argb: 'FF000000' } } };
    }
    fila += 1;
  });

  return { siguiente: fila, primera, ultima: fila - 1, pos };
}

/** TOTAL RACIONES y RACIONES DÍA, siempre calculadas por Excel. */
function cierreExcel(hoja, informe, desde, columnas, referenciaTotal) {
  const pos = columnasDeCierre(columnas);
  const registrados = registradosDelInforme(informe);
  const [total, promedio] = informe.cierre;
  const filaTotal = desde;

  const linea = (fila, dato, valor, formato) => {
    hoja.getRow(fila).height = 20;
    textoFormulario(hoja.getCell(fila, 1), dato.rotulo.toUpperCase(), { negrita: true });
    textoFormulario(hoja.getCell(fila, pos.igual), '=', { negrita: true, horizontal: 'center' });
    textoFormulario(hoja.getCell(fila, pos.equivalente), valor, { negrita: true, horizontal: 'right', formato });
    if (dato.detalle) textoFormulario(hoja.getCell(fila, pos.detalle), `(${dato.detalle})`, { tamano: 8.5 });
  };

  linea(filaTotal, total, referenciaTotal ? formula(referenciaTotal, total.valor) : total.valor,
    formatoDeCierre(informe, total.valor));
  linea(
    filaTotal + 1,
    promedio,
    /* Sin registros no hay división posible: se deja la cifra tal cual. */
    registrados > 0
      ? formula(`${celda(filaTotal, pos.equivalente)}/${registrados}`, promedio.valor)
      : promedio.valor,
    FORMATO_PROMEDIO,
  );
  return filaTotal + 2;
}

/** Notas de advertencia y el sello del sistema, fuera de la rejilla. */
function pieExcel(hoja, informe, desde, columnas) {
  let fila = desde;
  notasDeInforme(informe).forEach((nota) => {
    fila += 1;
    hoja.mergeCells(fila, 1, fila, columnas);
    textoFormulario(hoja.getCell(fila, 1), `NOTA: ${nota}`, { tamano: 8.5 });
    hoja.getCell(fila, 1).alignment = { horizontal: 'left', vertical: 'top', wrapText: true };
    hoja.getRow(fila).height = nota.length > 110 ? 26 : 15;
  });

  fila += 2;
  textoFormulario(
    hoja.getCell(fila, 1),
    `Generado automáticamente por el ${NOMBRE_SISTEMA} · ${informe.generado}`,
    { tamano: 8.5 },
  );
  return fila;
}

/**
 * Libro .xlsx del informe abierto: una sola hoja con el formulario completo,
 * en blanco y negro como el PDF.
 *
 * La generación es asíncrona (ExcelJS se carga bajo demanda), pero el nombre
 * del archivo se devuelve de inmediato: la UI lo muestra sin esperar.
 *
 * @param {object} informe  salida de cualquiera de los informes
 * @returns {string} nombre del archivo generado
 */
export function exportarInformeExcel(informe) {
  const archivo = `${informe.archivo}.xlsx`;

  generarLibroEnSegundoPlano(archivo, (libro) => {
    const columnas = informe.encabezados.length;
    const hoja = nuevaHoja(libro, HOJA_INFORME, { cuadricula: false });

    const inicioTabla = membreteExcel(libro, hoja, informe, columnas);
    const primera = cabeceraExcel(hoja, informe, inicioTabla, columnas);
    const tabla = tablaExcel(hoja, informe, primera, columnas);

    let fila = tabla.filaTotal + 2;
    let referenciaTotal = celda(tabla.filaTotal, columnas);
    if (esFormulario(informe)) {
      const tieneGrupos = Array.isArray(informe.grupos) && informe.grupos.length > 0;
      if (tieneGrupos) {
        const bloque = coeficientesExcel(hoja, informe, fila, columnas, tabla);
        const col = columna(bloque.pos.equivalente);
        referenciaTotal = `SUM(${col}${bloque.primera}:${col}${bloque.ultima})`;
        fila = bloque.siguiente + 1;
      } else {
        referenciaTotal = null;
      }
    }
    fila = cierreExcel(hoja, informe, fila, columnas, referenciaTotal);
    const ultimaFila = pieExcel(hoja, informe, fila, columnas);

    hoja.getColumn(1).width = 24;
    for (let col = 2; col < columnas; col += 1) {
      hoja.getColumn(col).width = esFormulario(informe) ? 14 : 11;
    }
    hoja.getColumn(columnas).width = 11;

    /* Como el PDF: el formulario apaisado, las planillas de días y de meses en
       vertical, y todo en una sola hoja A4. */
    configurarImpresion(hoja, {
      orientacion: esFormulario(informe) ? 'landscape' : 'portrait',
      ultimaFila,
      /* La aclaración del cierre ocupa dos columnas: si la tabla es angosta,
         el área de impresión se estira para no cortarla. */
      ultimaColumna: Math.max(columnas, columnasDeCierre(columnas).detalle + 1),
    });
  });

  return archivo;
}
