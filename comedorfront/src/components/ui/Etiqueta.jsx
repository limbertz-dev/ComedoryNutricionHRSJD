import './Etiqueta.css';

/** Píldora de categoría / estado. `tono` se limita a la paleta del sistema. */
export default function Etiqueta({ children, tono = 'neutro', icono = null }) {
  return (
    <span className={`etiqueta etiqueta--${tono}`}>
      {icono ? <span className="etiqueta__icono">{icono}</span> : null}
      {children}
    </span>
  );
}
