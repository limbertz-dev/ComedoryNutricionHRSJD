import './Boton.css';

/**
 * Botón único de la app. Ningún `<button>` suelto debe quedar con el estilo
 * nativo del navegador: todo pasa por aquí.
 *
 * @param {'primario'|'secundario'|'fantasma'} variante
 * @param {'md'|'lg'} tamano
 */
export default function Boton({
  children,
  variante = 'primario',
  tamano = 'md',
  icono = null,
  anchoCompleto = false,
  type = 'button',
  className = '',
  title = null,
  tooltip = null,
  tooltipPos = 'top',
  ...resto
}) {
  const textoTooltip = tooltip || title;
  const clases = [
    'boton',
    `boton--${variante}`,
    `boton--${tamano}`,
    anchoCompleto ? 'boton--ancho' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <button
      type={type}
      className={clases}
      data-tooltip={textoTooltip || undefined}
      data-tooltip-pos={textoTooltip ? tooltipPos : undefined}
      {...resto}
    >
      {icono ? <span className="boton__icono">{icono}</span> : null}
      <span className="boton__texto">{children}</span>
    </button>
  );
}
