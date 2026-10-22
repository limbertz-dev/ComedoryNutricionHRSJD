import { useCallback, useState } from 'react';
import { obtenerInformeRaciones } from '../../api.js';
import useConsultaApi from '../../hooks/useConsultaApi.js';
import { exportarInformeExcel, exportarInformePdf, notasDeInforme } from '../../exportaciones.js';
import Boton from '../ui/Boton.jsx';
import FiltroRangoFechas from '../ui/FiltroRangoFechas.jsx';
import { IconoDocumentoPdf, IconoHojaCalculo } from '../ui/Iconos.jsx';
import './InformeRaciones.css';

/*
 * El formulario del Servicio de Estadística, digitalizado: tiempos de comida
 * en las filas, categorías del personal en las columnas, y al pie la
 * reducción a ración completa con los coeficientes oficiales.
 *
 * Hay una sola vista. Antes eran tres (registro diario, mes y gestión), cada
 * una atada a su calendario; el rango de fechas las cubre a todas —«este mes»
 * y «esta gestión» no son más que rangos— y evita que el mismo dato se
 * presente de tres formas distintas.
 */

const ENTERO = new Intl.NumberFormat('es-BO');
const DECIMAL = new Intl.NumberFormat('es-BO', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const COEFICIENTE = new Intl.NumberFormat('es-BO', { minimumFractionDigits: 2 });

/** Rango por defecto: del primer día de este mes a hoy. */
function rangoInicial(hoy) {
  const dos = (numero) => String(numero).padStart(2, '0');
  const mes = `${hoy.getFullYear()}-${dos(hoy.getMonth() + 1)}`;
  return { desde: `${mes}-01`, hasta: `${mes}-${dos(hoy.getDate())}` };
}

/* En el papel, la casilla sin servicio se marca con un guion. */
function cifra(valor) {
  return valor > 0 ? ENTERO.format(valor) : '—';
}

/** Formulario del Servicio de Estadística: tiempos de comida × personal. */
function TablaInforme({ informe }) {
  return (
    <div className="informe__tabla-caja">
      <table className="informe__tabla">
        <caption className="solo-lectores">
          Raciones servidas al personal por tiempo de comida y categoría — {informe.periodo.principal}
        </caption>

        <thead>
          <tr>
            <th className="informe__col-tiempo" rowSpan={2} scope="col">
              Tiempo de comida
            </th>
            <th className="informe__col-grupo" colSpan={informe.categorias.length} scope="colgroup">
              Personal
            </th>
            <th className="informe__col-total" rowSpan={2} scope="col">
              Total
            </th>
          </tr>
          <tr>
            {informe.categorias.map((categoria) => (
              <th key={categoria} scope="col">
                {categoria}
              </th>
            ))}
          </tr>
        </thead>

        <tbody>
          {informe.filas.map((fila) => (
            <tr key={fila.tiempo}>
              <th className="informe__col-tiempo" scope="row">
                {fila.tiempo}
              </th>
              {fila.celdas.map((valor, indice) => (
                <td
                  key={informe.categorias[indice]}
                  className={valor > 0 ? '' : 'informe__celda--vacia'}
                >
                  {cifra(valor)}
                </td>
              ))}
              <td className="informe__col-total">{cifra(fila.total)}</td>
            </tr>
          ))}
        </tbody>

        <tfoot>
          <tr>
            <th className="informe__col-tiempo" scope="row">
              Total
            </th>
            {informe.totalesPorCategoria.map((total, indice) => (
              <td key={informe.categorias[indice]}>{cifra(total)}</td>
            ))}
            <td className="informe__col-total">{ENTERO.format(informe.totalGeneral)}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

/** Cifras de cierre: la última es la que se reporta al hospital. */
function Cierre({ informe, className = '' }) {
  return (
    <section className={`informe__totales ${className}`}>
      {informe.cierre.map((dato, indice) => (
        <div
          key={dato.rotulo}
          className={`informe__total${
            indice === informe.cierre.length - 1 ? ' informe__total--reportado' : ''
          }`}
        >
          <span>{dato.rotulo}</span>
          <strong>{DECIMAL.format(dato.valor)}</strong>
          <small>{dato.detalle}</small>
        </div>
      ))}
    </section>
  );
}

/** Advertencia ámbar al pie de la tabla: informa, no bloquea. */
function AvisosInforme({ informe }) {
  const notas = notasDeInforme(informe);
  if (notas.length === 0) return null;

  return (
    <aside className="informe__avisos" aria-label="Raciones pendientes de clasificar">
      <strong>Pendiente de clasificar</strong>
      <ul>
        {notas.map((nota) => <li key={nota}>{nota}</li>)}
      </ul>
    </aside>
  );
}

/** Reducción a ración completa y las dos cifras con las que cierra el informe. */
function Coeficientes({ informe }) {
  return (
    <div className="informe__cierre">
      <section className="informe__coeficientes">
        <h3 className="informe__subtitulo">Coeficientes para reducir a ración completa</h3>

        <table className="informe__tabla informe__tabla--coeficientes">
          <thead>
            <tr>
              <th className="informe__col-tiempo" scope="col">
                Tiempo de comida
              </th>
              <th scope="col">Servidas</th>
              <th scope="col">Coeficiente</th>
              <th className="informe__col-total" scope="col">
                Equivalente
              </th>
            </tr>
          </thead>
          <tbody>
            {informe.grupos.map((grupo) => (
              <tr key={grupo.etiqueta}>
                <th className="informe__col-tiempo" scope="row">
                  {grupo.etiqueta}
                </th>
                <td>{ENTERO.format(grupo.servidas)}</td>
                <td className="informe__celda--coeficiente">
                  {grupo.coeficienteVariable ? 'Variable' : `× ${COEFICIENTE.format(grupo.coeficiente)}`}
                </td>
                <td className="informe__col-total">{DECIMAL.format(grupo.equivalente)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <Cierre informe={informe} />
    </div>
  );
}

export default function InformeRaciones({ ahora = null }) {
  const [hoy] = useState(() => ahora ?? new Date());
  const [rango, setRango] = useState(() => rangoInicial(hoy));
  /* Nombre del último archivo generado: confirma la descarga sin interrumpir. */
  const [descargado, setDescargado] = useState(null);

  const consultar = useCallback(
    (signal) => obtenerInformeRaciones({ desde: rango.desde, hasta: rango.hasta, hoy, signal }),
    [rango.desde, rango.hasta, hoy],
  );
  const { datos: informe, cargando, error, recargar } = useConsultaApi(consultar);

  const sinRegistros = informe?.totalGeneral === 0;

  function actualizarRango({ desde, hasta }) {
    setRango({ desde, hasta });
    setDescargado(null);
  }

  return (
    <article className="informe">
      <FiltroRangoFechas
        hoy={ahora}
        fechaInicio={rango.desde}
        fechaFin={rango.hasta}
        onActualizar={actualizarRango}
      />

      <header className="informe__cabecera">
        <div className="informe__encabezado">
          <h2 className="informe__titulo">Informe de raciones servidas al personal</h2>
          <p className="informe__nota">
            Consumo por tiempo de comida y categoría laboral, reducido a ración completa con los
            coeficientes oficiales.
          </p>
        </div>

        <div className="informe__acciones">
          {/* Una sola línea: el dato secundario va al lado y no agranda el control. */}
          <div className="informe__periodo" aria-label="Período del informe">
            <span className="informe__periodo-mes">{informe?.periodo.principal ?? '…'}</span>
            {informe?.periodo.secundario ? (
              <span className="informe__periodo-gestion">{informe.periodo.secundario}</span>
            ) : null}
          </div>

          <Boton
            variante="secundario"
            disabled={sinRegistros || !informe}
            icono={<IconoHojaCalculo tamano={19} />}
            onClick={() => setDescargado(exportarInformeExcel(informe))}
          >
            Excel
          </Boton>

          <Boton
            variante="primario"
            disabled={sinRegistros || !informe}
            icono={<IconoDocumentoPdf tamano={19} />}
            onClick={() => setDescargado(exportarInformePdf(informe))}
          >
            PDF
          </Boton>
        </div>
      </header>

      {cargando ? <p className="informe__estado" role="status">Cargando informe…</p> : null}
      {error ? (
        <p className="informe__error" role="alert">
          <span>{error}</span>
          <Boton variante="secundario" tamano="sm" onClick={recargar}>Reintentar informe</Boton>
        </p>
      ) : null}

      {descargado ? (
        <p className="informe__descarga" role="status">
          Archivo generado: <strong>{descargado}</strong>
        </p>
      ) : null}

      {sinRegistros ? (
        <p className="informe__vacio">No hay raciones registradas en este período.</p>
      ) : null}

      {informe && !sinRegistros ? (
        <>
          <TablaInforme informe={informe} />
          <AvisosInforme informe={informe} />
          <Coeficientes informe={informe} />
        </>
      ) : null}
    </article>
  );
}
