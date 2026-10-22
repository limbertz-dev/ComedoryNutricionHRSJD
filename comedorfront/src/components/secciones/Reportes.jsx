import InformeRaciones from './InformeRaciones.jsx';

/**
 * Reportes del personal: el informe de raciones por rango de fechas, con sus
 * exportaciones a Excel y PDF. `ahora` fija el «hoy» de la vista (por
 * omisión, la hora de la PC).
 */
export default function Reportes({ ahora = null }) {
  return <InformeRaciones ahora={ahora} />;
}
