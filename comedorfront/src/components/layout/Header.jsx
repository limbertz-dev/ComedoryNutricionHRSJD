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
 */
export default function Header({ seccion, turno }) {
  const fecha = FORMATO_FECHA.format(new Date());

  return (
    <header className="header">
      <div className="header__titulos">
        <h1 className="header__titulo">{seccion.titulo}</h1>
        <p className="header__descripcion">{seccion.descripcion}</p>
      </div>

      <div className="header__contexto">
        {turno === null ? null : (
          <span className="header__pastilla header__pastilla--turno">
            <IconoReloj tamano={18} />
            Turno {turno}
          </span>
        )}

        <span className="header__pastilla">
          <IconoCalendario tamano={18} />
          {fecha}
        </span>
      </div>
    </header>
  );
}
