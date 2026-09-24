import { useCallback, useState } from 'react';
import { obtenerReporteDistribucion } from '../../api.js';
import useConsultaApi from '../../hooks/useConsultaApi.js';
import {
  exportarReportePacientesExcel,
  exportarReportePacientesPdf,
  notasDeInforme,
} from '../../exportaciones.js';
import Boton from '../ui/Boton.jsx';
import Etiqueta from '../ui/Etiqueta.jsx';
import FiltroRangoFechas from '../ui/FiltroRangoFechas.jsx';
import { IconoDocumentoPdf, IconoHojaCalculo } from '../ui/Iconos.jsx';
import TablaPlanilla from '../ui/TablaPlanilla.jsx';
import './ReportesPacientes.css';

/*
 * Reportes de pacientes: la planilla de distribución de raciones a pacientes
 * para un rango de fechas, con los mismos controles que el reporte del personal.
 *
 * La tabla, el Excel y el PDF salen del MISMO objeto que arma api.js: acá no
 * se calcula ninguna cifra, solo se pinta.
 */

/** Rango por defecto: del primer día de este mes a hoy, como en el personal. */
function rangoInicial(hoy) {
  const dos = (numero) => String(numero).padStart(2, '0');
  const mes = `${hoy.getFullYear()}-${dos(hoy.getMonth() + 1)}`;
  return { desde: `${mes}-01`, hasta: `${mes}-${dos(hoy.getDate())}` };
}

export default function ReportesPacientes() {
  const [hoy] = useState(() => new Date());
  const [rango, setRango] = useState(() => rangoInicial(hoy));
  /* Nombre del último archivo generado: confirma la descarga sin interrumpir. */
  const [descargado, setDescargado] = useState(null);

  const consultar = useCallback(
    (signal) => obtenerReporteDistribucion({ desde: rango.desde, hasta: rango.hasta, hoy, signal }),
    [rango.desde, rango.hasta, hoy],
  );
  const { datos: reporte, cargando, error, recargar } = useConsultaApi(consultar);

  const vacio = reporte?.totalGeneral === 0;
  const notas = notasDeInforme(reporte);

  function actualizarRango({ desde, hasta }) {
    setRango({ desde, hasta });
    setDescargado(null);
  }

  return (
    <article className="reportes-pacientes">
      <FiltroRangoFechas
        fechaInicio={rango.desde}
        fechaFin={rango.hasta}
        onActualizar={actualizarRango}
      />

      <header className="reportes-pacientes__cabecera">
        <div>
          <h2 className="reportes-pacientes__titulo">
            {reporte?.titulo ?? 'INFORME MENSUAL DE RACIONES SERVIDAS A PACIENTES'}
          </h2>
          <p className="reportes-pacientes__nota">Servicios × tipos de dieta · raciones servidas a pacientes</p>
        </div>

        <div className="reportes-pacientes__acciones">
          {reporte ? (
            <Etiqueta tono="acento">{reporte.periodo.principal} · {reporte.periodo.secundario}</Etiqueta>
          ) : null}
          <Boton
            variante="secundario"
            disabled={!reporte || vacio}
            icono={<IconoHojaCalculo tamano={19} />}
            onClick={() => setDescargado(exportarReportePacientesExcel(reporte))}
          >
            Excel
          </Boton>
          <Boton
            variante="primario"
            disabled={!reporte || vacio}
            icono={<IconoDocumentoPdf tamano={19} />}
            onClick={() => setDescargado(exportarReportePacientesPdf(reporte))}
          >
            PDF
          </Boton>
        </div>
      </header>

      {cargando ? <p className="reportes-pacientes__estado" role="status">Cargando reporte…</p> : null}
      {error ? (
        <div className="reportes-pacientes__error" role="alert">
          <p>{error}</p>
          <Boton variante="secundario" onClick={() => recargar()}>Reintentar</Boton>
        </div>
      ) : null}

      {descargado ? (
        <p className="reportes-pacientes__descarga" role="status">
          Archivo generado: <strong>{descargado}</strong>
        </p>
      ) : null}

      {vacio ? (
        <p className="reportes-pacientes__vacio">No hay raciones registradas en este período.</p>
      ) : null}

      {reporte && !vacio ? (
        <>
          <TablaPlanilla reporte={reporte} />
          {notas.length > 0 ? (
            <ul className="reportes-pacientes__notas">
              {notas.map((nota) => <li key={nota}>{nota}</li>)}
            </ul>
          ) : null}
        </>
      ) : null}
    </article>
  );
}
