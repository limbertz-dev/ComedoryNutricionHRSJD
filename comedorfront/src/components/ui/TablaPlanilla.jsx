import { cifraPacientes } from '../../exportaciones.js';
import './TablaPlanilla.css';

/**
 * Celda numérica de solo lectura: formatea con guion en 0 y destaca los totales.
 */
function Celda({ valor, destacada = false }) {
  const clases = ['tabla-planilla__cifra'];
  if (valor === 0) clases.push('tabla-planilla__cifra--cero');
  if (valor === null || valor === undefined) clases.push('tabla-planilla__cifra--sin-fuente');
  if (destacada) clases.push('tabla-planilla__cifra--total');
  return <td className={clases.join(' ')}>{cifraPacientes(valor)}</td>;
}

/**
 * TablaPlanilla: la planilla del hospital en pantalla.
 *
 * Utilizada tanto en Reportes de Pacientes (solo lectura) como en Control de
 * Dietas (con celdas editables).
 *
 * @param {object} props
 * @param {object} props.reporte Estructura de la planilla ({ titulo, primeraColumna, grupoColumnas, columnas, conTotal, filas, total, secciones })
 * @param {boolean} [props.editable=false] Si las celdas de dieta son inputs editables
 * @param {function} [props.onCambioCelda] Callback (filaCodigo, colCodigo, nuevoValor) cuando cambia una celda editable
 * @param {function} [props.esCeldaModificada] Función (filaCodigo, colCodigo) => boolean para destacar celdas con cambios
 */
export default function TablaPlanilla({
  reporte,
  editable = false,
  onCambioCelda,
  esCeldaModificada,
}) {
  if (!reporte) return null;

  const columnasNormalizadas = reporte.columnas.map((col, indice) => {
    if (typeof col === 'string') {
      return { codigo: col, etiqueta: col, clave: col };
    }
    return {
      codigo: col.codigo ?? String(indice),
      etiqueta: col.etiqueta ?? col.codigo ?? String(indice),
      clave: col.codigo ?? col.etiqueta ?? String(indice),
    };
  });

  const conTotal = reporte.conTotal !== false;
  const ancho = 1 + columnasNormalizadas.length + (conTotal ? 1 : 0);

  const fila = (datos, clave, esCuerpo = true) => (
    <tr key={clave}>
      <th scope="row">{datos.etiqueta}</th>
      {datos.celdas.map((valor, indice) => {
        const col = columnasNormalizadas[indice];
        if (editable && esCuerpo) {
          const modificado = typeof esCeldaModificada === 'function'
            ? esCeldaModificada(datos.codigo, col.codigo)
            : false;
          return (
            <td key={col.clave} className="tabla-planilla__celda--editable">
              <input
                type="number"
                min="0"
                step="1"
                className={`tabla-planilla__input${modificado ? ' tabla-planilla__input--modificado' : ''}`}
                value={valor === null || valor === undefined ? '' : valor}
                onChange={(e) => onCambioCelda?.(datos.codigo, col.codigo, e.target.value)}
                aria-label={`${datos.etiqueta} – ${col.etiqueta}`}
              />
            </td>
          );
        }
        return <Celda key={col.clave} valor={valor} />;
      })}
      {conTotal ? <Celda valor={datos.total} destacada /> : null}
    </tr>
  );

  return (
    <div className="tabla-planilla-caja">
      <table className="tabla-planilla">
        <caption className="solo-lectores">{reporte.titulo}</caption>
        <thead>
          <tr>
            <th scope="col" rowSpan={2} className="tabla-planilla__col-servicio">
              {reporte.primeraColumna || 'SERVICIOS'}
            </th>
            <th scope="colgroup" colSpan={columnasNormalizadas.length}>
              {reporte.grupoColumnas || 'TIPOS DE DIETAS'}
            </th>
            {conTotal ? <th scope="col" rowSpan={2}>TOTAL</th> : null}
          </tr>
          <tr>
            {columnasNormalizadas.map((col) => (
              <th key={col.clave} scope="col">{col.etiqueta}</th>
            ))}
          </tr>
        </thead>
        <tbody>{reporte.filas.map((datos) => fila(datos, datos.codigo || datos.etiqueta, true))}</tbody>
        {/* TOTAL como tbody y no tfoot: el navegador dibuja tfoot al final de
            la tabla, y en la planilla el TOTAL va antes de las secciones. */}
        <tbody className="tabla-planilla__total">{fila(reporte.total, 'total', false)}</tbody>
        {reporte.secciones?.map((seccion) => (
          <tbody key={seccion.etiqueta} className="tabla-planilla__seccion">
            <tr>
              <th scope="colgroup" colSpan={ancho}>{seccion.etiqueta}</th>
            </tr>
            {seccion.filas.map((datos) => fila(datos, datos.codigo || datos.etiqueta, true))}
          </tbody>
        ))}
      </table>
    </div>
  );
}
