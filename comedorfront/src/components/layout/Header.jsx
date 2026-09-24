import { IconoCalendario, IconoReloj } from '../ui/Iconos.jsx';
import './Header.css';

/* Fecha corta, como en el panel original: "mié., 03 sept. 2026". */
const FORMATO_FECHA = new Intl.DateTimeFormat('es-BO', {
  weekday: 'short',
  day: '2-digit',
  month: 'short',
  year: 'numeric',
});

/**
 * Barra superior transparente: título y descripción de la sección abierta a
 * la izquierda, turno y fecha a la derecha. El usuario no se repite aquí: vive
 * en la ficha de sesión, al pie del sidebar.
 *
 * `children`, cuando llega, se pinta entre los títulos y las pastillas, en la
 * misma fila: es donde Control Biométrico monta su simulador de lector, como
 * una herramienta más de la barra y no como una franja aparte que empuje el
 * resto de la pantalla hacia abajo.
 */
export default function Header({ seccion, turno, children }) {
  const fecha = FORMATO_FECHA.format(new Date());

  return (
    <header className="header">
      <div className="header__titulos">
        <h1 className="header__titulo">{seccion.titulo}</h1>
        <p className="header__descripcion">{seccion.descripcion}</p>
      </div>

      {children ? <div className="header__herramientas">{children}</div> : null}

      <div className="header__contexto">
        {turno ? (
          <span className="header__pastilla header__pastilla--turno">
            <IconoReloj tamano={18} />
            Turno {turno}
          </span>
        ) : null}

        <span className="header__pastilla">
          <IconoCalendario tamano={18} />
          {fecha}
        </span>
      </div>
    </header>
  );
}
