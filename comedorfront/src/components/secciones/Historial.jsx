import { useState } from 'react';
import HistorialComidas from './HistorialComidas.jsx';
import './Historial.css';

/* `ahora`: el «hoy» de la vista; por omisión, la hora de la PC. */
export default function Historial({ personal, ahora = null }) {
  const [hoy] = useState(() => ahora ?? new Date());

  return (
    <article className="historial-vista" aria-label="Historial individual de comidas">
      <HistorialComidas personal={personal} hoy={hoy} />
    </article>
  );
}
