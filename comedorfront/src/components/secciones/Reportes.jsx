import InformeRaciones from './InformeRaciones.jsx';

/**
 * Reportes del personal: el informe de raciones por rango de fechas, con sus
 * exportaciones a Excel y PDF. Los reportes de pacientes no se ofrecen en esta
 * vista; llegarán con su módulo. `ahora` es la hora del servidor en
 * simulación (null fuera de ella).
 */
export default function Reportes({ ahora = null }) {
  return <InformeRaciones ahora={ahora} />;
}
