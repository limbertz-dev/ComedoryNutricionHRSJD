/*
 * excelEstilos.js — lenguaje visual de los libros .xlsx.
 *
 * Estos archivos se imprimen, se archivan y circulan por el hospital junto a
 * los que el Servicio de Estadística ya llena a mano, así que se parecen a
 * esos y no a la pantalla: el modelo es «INFORME MENSUAL», el libro real del
 * hospital. De ahí salen la tipografía (Aptos Narrow), la rejilla fina negra
 * en cada celda, las bandas verdes de cabecera, las filas altas y el todo
 * centrado. No hay cebrado ni tipografía de color: el papel no los tiene.
 *
 * ExcelJS se carga con `import()` dentro de `generarLibro()` a propósito: la
 * librería pesa y solo hace falta cuando alguien pulsa «Excel», y así los
 * tests de Node pueden importar exportaciones.js sin arrastrar un bundle de
 * navegador.
 */

/*
 * Paleta en ARGB. Los tres verdes son los del libro del hospital —tintas del
 * mismo verde, al 60 % y al 40 %—, no colores nuevos: así el archivo que sale
 * del sistema se confunde con los que ya usa Estadística.
 *
 * El original pinta la fila de totales de celeste; aquí esa fila usa el verde
 * más intenso de la misma familia, que es el único cambio deliberado: el
 * sistema es verde de punta a punta.
 */
export const ARGB = {
  banda: 'FFB8DCAB' /* cabeceras y títulos de sección */,
  bandaTotal: 'FF95CA82' /* fila de totales */,
  bandaColumna: 'FFA3C4A7' /* columna «Total», como en el original */,
  blanco: 'FFFFFFFF',
  negro: 'FF000000' /* texto y rejilla: el papel es en negro */,
  texto2: 'FF595959' /* notas al pie, en gris */,
};

/* La del libro del hospital. Las alternativas cubren equipos sin Aptos. */
export const FUENTE = 'Aptos Narrow';

export const FORMATO_ENTERO = '#,##0';
export const FORMATO_DECIMAL = '#,##0.00';
export const FORMATO_PROMEDIO = '0.00';
export const FORMATO_PORCENTAJE = '0%';
/* Día del mes con cero delante: «01», pero como número, no como texto. */
export const FORMATO_DIA = '00';
/* Planillas de pacientes: el cero se lee «—», como en pantalla y en el PDF,
   pero la celda sigue siendo el número 0 y las sumas funcionan. */
export const FORMATO_CERO_GUION = '0;-0;"—"';

/* Alturas de fila del original: la tabla respira, no es una lista apretada. */
export const ALTO_CABECERA = 42;
export const ALTO_FILA = 24;

/** Letra de columna de Excel a partir del índice 1. */
export function columna(indice) {
  let n = indice;
  let letra = '';
  while (n > 0) {
    const resto = (n - 1) % 26;
    letra = String.fromCharCode(65 + resto) + letra;
    n = Math.floor((n - resto) / 26);
  }
  return letra;
}

function borde(color = ARGB.negro, estilo = 'thin') {
  return { style: estilo, color: { argb: color } };
}

/* Rejilla fina en las cuatro caras: en el original no hay una sola celda de
   tabla sin borde, y eso es lo que hace que la hoja se lea impresa. */
export const BORDE_TABLA = {
  top: borde(),
  left: borde(),
  bottom: borde(),
  right: borde(),
};

export function relleno(argb) {
  return { type: 'pattern', pattern: 'solid', fgColor: { argb } };
}

/** Texto negro sobre la rejilla, el único color de letra de la hoja. */
function tipografia({ tamano = 11, negrita = false, cursiva = false, color = ARGB.negro } = {}) {
  return { name: FUENTE, size: tamano, bold: negrita, italic: cursiva, color: { argb: color } };
}

function pintar(celda, { fondo, fuente, alineacion, formato }) {
  if (fondo) celda.fill = relleno(fondo);
  celda.font = fuente;
  celda.alignment = alineacion;
  celda.border = BORDE_TABLA;
  if (formato) celda.numFmt = formato;
}

const CENTRADO = { horizontal: 'center', vertical: 'middle', wrapText: true };
const IZQUIERDA = { horizontal: 'left', vertical: 'middle', indent: 1 };

/**
 * Membrete de tres líneas —hospital, informe, período— en banda verde, como
 * los títulos de sección del libro del hospital. Devuelve la fila donde puede
 * empezar la tabla.
 */
export function banner(hoja, columnas, { sistema, titulo, subtitulo }) {
  const lineas = [
    { texto: sistema, tamano: 14, alto: 30, negrita: true },
    { texto: titulo, tamano: 12, alto: 26, negrita: true },
    { texto: subtitulo, tamano: 10, alto: 20, negrita: false },
  ];

  lineas.forEach((linea, indice) => {
    const fila = indice + 1;
    hoja.mergeCells(fila, 1, fila, columnas);
    /* La banda se pinta celda a celda: combinar no propaga el borde, y sin
       eso el recuadro del título sale partido al imprimir. */
    for (let col = 1; col <= columnas; col += 1) {
      pintar(hoja.getCell(fila, col), {
        fondo: ARGB.banda,
        fuente: tipografia({ tamano: linea.tamano, negrita: linea.negrita }),
        alineacion: CENTRADO,
      });
    }
    hoja.getCell(fila, 1).value = linea.texto;
    hoja.getRow(fila).height = linea.alto;
  });

  hoja.getRow(lineas.length + 1).height = 10;
  return lineas.length + 2;
}

/** Fila de encabezados: banda verde, negrita, centrada y alta. */
export function cabecera(hoja, fila, titulos, { alto = ALTO_CABECERA } = {}) {
  const row = hoja.getRow(fila);
  row.height = alto;
  titulos.forEach((titulo, indice) => {
    const celdaTitulo = row.getCell(indice + 1);
    celdaTitulo.value = titulo;
    pintar(celdaTitulo, {
      fondo: ARGB.banda,
      fuente: tipografia({ negrita: true }),
      alineacion: CENTRADO,
    });
  });
  return row;
}

/**
 * Cabecera de dos filas, como en las planillas de nutrición: la primera
 * columna (y la de TOTAL, si hay) ocupa las dos filas, y un rótulo agrupa las
 * columnas del medio («TIPOS DE DIETAS», «No. DE RACIONES»). Devuelve la
 * segunda fila de la cabecera: los datos empiezan en la siguiente.
 */
export function cabeceraAgrupada(hoja, fila, { primera, grupo, columnas, ultima = null }) {
  const colUltima = columnas.length + 2;
  cabecera(hoja, fila, [primera, grupo, ...columnas.slice(1).map(() => null), ...(ultima ? [ultima] : [])], {
    alto: 24,
  });
  cabecera(hoja, fila + 1, [null, ...columnas, ...(ultima ? [null] : [])], { alto: 30 });
  hoja.mergeCells(fila, 1, fila + 1, 1);
  if (columnas.length > 1) hoja.mergeCells(fila, 2, fila, columnas.length + 1);
  if (ultima) hoja.mergeCells(fila, colUltima, fila + 1, colUltima);
  return fila + 1;
}

/**
 * Fila de datos. `valores[0]` es el rótulo, en negrita y a la izquierda como
 * en el original; el resto son cifras o fórmulas (`{ formula, result }`),
 * centradas dentro de su casilla.
 *
 * `columnaDestacada` pinta esa columna —la de «Total»— con la banda que el
 * libro del hospital le reserva. `rotuloCentrado` es para la columna de días:
 * en el original las fechas van centradas y los nombres, a la izquierda.
 */
export function filaDatos(hoja, fila, valores, {
  formato = FORMATO_ENTERO, formatoRotulo, columnaDestacada, alto = ALTO_FILA,
  rotuloCentrado = false,
} = {}) {
  const row = hoja.getRow(fila);
  row.height = alto;
  valores.forEach((valor, indice) => {
    const celdaDato = row.getCell(indice + 1);
    if (valor !== null && valor !== undefined) celdaDato.value = valor;
    pintar(celdaDato, {
      fondo: indice + 1 === columnaDestacada ? ARGB.bandaColumna : undefined,
      fuente: tipografia({ negrita: indice === 0 }),
      alineacion: indice === 0 && !rotuloCentrado ? IZQUIERDA : CENTRADO,
      formato: indice === 0 ? formatoRotulo : formato,
    });
  });
  return row;
}

/** Fila de totales: la banda verde intensa, en negrita y centrada. */
export function filaTotales(hoja, fila, valores, { formato = FORMATO_ENTERO, alto = 26 } = {}) {
  const row = hoja.getRow(fila);
  row.height = alto;
  valores.forEach((valor, indice) => {
    const celdaTotal = row.getCell(indice + 1);
    if (valor !== null && valor !== undefined) celdaTotal.value = valor;
    pintar(celdaTotal, {
      fondo: ARGB.bandaTotal,
      fuente: tipografia({ negrita: true }),
      alineacion: indice === 0 ? IZQUIERDA : CENTRADO,
      formato: indice === 0 ? undefined : formato,
    });
  });
  return row;
}

/**
 * Cifra de cierre al pie de la tabla: rótulo en banda verde, valor —casi
 * siempre una fórmula— en su casilla, y la aclaración en gris al costado,
 * fuera de la rejilla.
 */
export function tarjetaCierre(hoja, fila, {
  rotulo, valor, detalle, formato = FORMATO_DECIMAL, columnaValor = 2, alto = ALTO_FILA,
}) {
  const row = hoja.getRow(fila);
  row.height = alto;

  const celdaRotulo = row.getCell(1);
  celdaRotulo.value = rotulo;
  pintar(celdaRotulo, {
    fondo: ARGB.banda,
    fuente: tipografia({ negrita: true }),
    alineacion: IZQUIERDA,
  });

  const celdaValor = row.getCell(columnaValor);
  if (valor !== null && valor !== undefined) celdaValor.value = valor;
  pintar(celdaValor, {
    fuente: tipografia({ negrita: true }),
    alineacion: CENTRADO,
    formato,
  });

  if (detalle) {
    const celdaDetalle = row.getCell(columnaValor + 1);
    celdaDetalle.value = detalle;
    celdaDetalle.font = tipografia({ tamano: 9, cursiva: true, color: ARGB.texto2 });
    celdaDetalle.alignment = IZQUIERDA;
  }
  return row;
}

/** Nota al pie, fuera de la tabla oficial y por lo tanto fuera de la rejilla. */
export function notaAlPie(hoja, fila, texto, columnas) {
  hoja.mergeCells(fila, 1, fila, Math.max(columnas, 2));
  const celdaNota = hoja.getCell(fila, 1);
  celdaNota.value = texto;
  celdaNota.font = tipografia({ tamano: 9, cursiva: true, color: ARGB.texto2 });
  celdaNota.alignment = { vertical: 'top', horizontal: 'left', wrapText: true, indent: 1 };
  hoja.getRow(fila).height = 26;
}

/**
 * Ancho por columna a partir del texto más largo que va a caer en ella, con
 * holgura: ninguna cifra debe quedar en `###`.
 *
 * `maximo` es el tope de las columnas de cifras: sin él, un encabezado largo
 * («Administrativo») ensancharía toda la tabla y la impresión saldría
 * encogida. Con tope, ese encabezado se parte en dos líneas —la cabecera es
 * alta justamente para eso— y las cifras siguen sobrando de sitio.
 */
export function ajustarAnchos(hoja, textosPorColumna, { minimo = 14, primera = 26, maximo } = {}) {
  textosPorColumna.forEach((textos, indice) => {
    const largo = textos.reduce((max, texto) => Math.max(max, String(texto ?? '').length), 0);
    const holgado = Math.max(indice === 0 ? primera : minimo, largo + 4);
    hoja.getColumn(indice + 1).width = indice > 0 && maximo ? Math.min(holgado, maximo) : holgado;
  });
}

/* ------------------------------------------------------------- Impresión */

/*
 * El Excel también se imprime, y cuando se imprime tiene que salir como el
 * formulario de papel: una hoja A4, la tabla entera, sin una columna huérfana
 * en una segunda página. De eso se encarga `fitToPage`, que deja que Excel
 * reduzca la escala hasta que todo entre.
 */

const A4 = 9; /* Código de tamaño de papel de OOXML. */

const MARGENES_A4 = {
  left: 0.4,
  right: 0.4,
  top: 0.5,
  bottom: 0.5,
  header: 0.2,
  footer: 0.2,
};

/**
 * Deja la hoja lista para imprimir en A4.
 *
 * `enUnaHoja` es lo normal (el formulario cabe entero); las listas que crecen
 * sin techo —el detalle nominal— ajustan solo el ancho y repiten la cabecera
 * en cada página, porque encogerlas a una hoja las volvería ilegibles.
 */
export function configurarImpresion(hoja, {
  orientacion = 'portrait',
  ultimaFila,
  ultimaColumna,
  filaCabecera,
  pie,
  enUnaHoja = true,
} = {}) {
  hoja.pageSetup = {
    paperSize: A4,
    orientation: orientacion,
    fitToPage: true,
    fitToWidth: 1,
    fitToHeight: enUnaHoja ? 1 : 0,
    horizontalCentered: true,
    margins: MARGENES_A4,
    printArea: `A1:${columna(ultimaColumna)}${ultimaFila}`,
  };

  /* Sin esto, una tabla larga deja las páginas siguientes sin encabezado. */
  if (!enUnaHoja && filaCabecera) {
    hoja.pageSetup.printTitlesRow = `${filaCabecera}:${filaCabecera}`;
  }

  if (pie) {
    /* &9 = cuerpo 9; &K…= color del texto (el gris de las notas). */
    hoja.headerFooter = {
      oddFooter: `&L&9&K64748B${pie}${enUnaHoja ? '' : '&R&9&K64748BPágina &P de &N'}`,
    };
  }
}

/** Referencia de celda: `celda(2, 9)` → `"I2"`. */
export function celda(fila, col) {
  return `${columna(col)}${fila}`;
}

/** Fórmula con su valor ya calculado, para que Excel muestre algo al abrir. */
export function formula(texto, resultado) {
  return { formula: texto, result: resultado };
}

/** Hoja nueva con la cuadrícula visible, como el resto del sistema. */
export function nuevaHoja(libro, nombre) {
  return libro.addWorksheet(nombre, { views: [{ showGridLines: true }] });
}

/**
 * Construye el libro con `armar(workbook)` y lo descarga. Devuelve una
 * promesa; quien llama ya devolvió el nombre del archivo de forma síncrona.
 */
export async function generarLibro(nombreArchivo, armar) {
  /* El bundle de navegador es CommonJS: según quién lo empaquete llega como
     `default` o como el módulo entero. */
  const modulo = await import('exceljs/dist/exceljs.min.js');
  const ExcelJS = modulo.default ?? modulo;
  const libro = new ExcelJS.Workbook();
  libro.creator = 'Sistema de Comedor y Nutrición Hospitalaria';
  libro.created = new Date();

  armar(libro);

  const buffer = await libro.xlsx.writeBuffer();
  const blob = new Blob([buffer], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
  const url = URL.createObjectURL(blob);
  const enlace = document.createElement('a');
  enlace.href = url;
  enlace.download = nombreArchivo;
  document.body.appendChild(enlace);
  enlace.click();
  document.body.removeChild(enlace);
  URL.revokeObjectURL(url);
}

/**
 * Igual que `generarLibro()`, pero pensada para llamarse sin `await`: deja el
 * fallo en la consola en vez de convertirlo en una promesa rechazada suelta.
 */
export function generarLibroEnSegundoPlano(nombreArchivo, armar) {
  generarLibro(nombreArchivo, armar).catch((error) => {
    console.error(`No se pudo generar ${nombreArchivo}:`, error);
  });
}
