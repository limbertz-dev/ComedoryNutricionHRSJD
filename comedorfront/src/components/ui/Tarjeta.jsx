import './Tarjeta.css';

/** Contenedor visual base de la app (paneles, tarjetas de dato, gráficos). */
export default function Tarjeta({ titulo, accesorio, children, className = '', ...resto }) {
  return (
    <section className={`tarjeta ${className}`} {...resto}>
      {titulo ? (
        <header className="tarjeta__cabecera">
          <h2 className="tarjeta__titulo">{titulo}</h2>
          {accesorio ? <div className="tarjeta__accesorio">{accesorio}</div> : null}
        </header>
      ) : null}
      <div className="tarjeta__cuerpo">{children}</div>
    </section>
  );
}
