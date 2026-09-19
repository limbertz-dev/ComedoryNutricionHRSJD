import { useState } from 'react';
import HistorialComidas from './HistorialComidas.jsx';
import './Historial.css';

export default function Historial({ personal }) {
  const [hoy] = useState(() => new Date());

  return (
    <article className="historial-vista" aria-label="Historial individual de comidas">
      <HistorialComidas personal={personal} hoy={hoy} />
    </article>
  );
}
