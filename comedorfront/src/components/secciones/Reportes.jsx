import { useState } from 'react';
import InformeRaciones from './InformeRaciones.jsx';
import ReportesPacientes from './ReportesPacientes.jsx';
import './Reportes.css';

/**
 * Selector entre los reportes del personal y de pacientes. El del personal
 * muestra el formulario digitalizado; el de pacientes, la planilla de
 * nutrición (distribución).
 */
export default function Reportes() {
  const [vistaActiva, setVistaActiva] = useState('personal');

  return (
    <div className="reportes">
      <div className="reportes__selector" aria-label="Tipo de reporte">
        <button
          id="selector-reporte-personal"
          type="button"
          className={`reportes__selector-opcion${
            vistaActiva === 'personal' ? ' reportes__selector-opcion--activa' : ''
          }`}
          aria-pressed={vistaActiva === 'personal'}
          onClick={() => setVistaActiva('personal')}
        >
          <strong>Reportes del personal</strong>
          <span>Marcaciones, consumo y exportaciones</span>
        </button>

        <button
          id="selector-reporte-pacientes"
          type="button"
          className={`reportes__selector-opcion${
            vistaActiva === 'pacientes' ? ' reportes__selector-opcion--activa' : ''
          }`}
          aria-pressed={vistaActiva === 'pacientes'}
          onClick={() => setVistaActiva('pacientes')}
        >
          <strong>Reportes de pacientes</strong>
          <span>Raciones y servicios hospitalarios</span>
        </button>
      </div>

      {vistaActiva === 'personal' ? <InformeRaciones /> : <ReportesPacientes />}
    </div>
  );
}
