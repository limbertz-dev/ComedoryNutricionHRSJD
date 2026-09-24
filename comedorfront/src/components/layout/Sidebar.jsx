import useSesion from '../../hooks/useSesion.js';
import { SECCION_INICIAL, guardarSeccionActiva, seccionesDeRol } from '../../navegacion.js';
import { etiquetaDeRol } from '../../permisos.js';
import { IconoCerrarSesion, IconoLogo } from '../ui/Iconos.jsx';
import './Sidebar.css';

/**
 * Columna izquierda completa: marca arriba, módulos en el medio y la sesión
 * al pie — la misma estructura del panel del que se recicla el estilo.
 * Solo lista las secciones que el rol de la sesión puede abrir.
 */
export default function Sidebar({ seccionActiva, onCambiarSeccion }) {
  const { rol, usuario, logout } = useSesion();

  function manejarCerrarSesion() {
    // Quien entre después empieza en Control Biométrico, no donde quedó esta sesión.
    guardarSeccionActiva(SECCION_INICIAL);
    logout();
  }

  return (
    <aside className="sidebar">
      <div className="sidebar__marca">
        <span className="sidebar__marca-icono">
          <IconoLogo tamano={27} />
        </span>
        <div>
          <strong>Comedor y Nutrición</strong>
          <small>Hospitalaria</small>
        </div>
      </div>

      <nav className="sidebar__nav" aria-label="Módulos del sistema">
        {seccionesDeRol(rol).map(({ id, etiqueta, descripcion, Icono }) => {
          const activa = id === seccionActiva;

          return (
            <button
              key={id}
              type="button"
              className={`sidebar__item${activa ? ' sidebar__item--activa' : ''}`}
              onClick={() => onCambiarSeccion(id)}
              aria-current={activa ? 'page' : undefined}
              data-tooltip={descripcion}
            >
              <Icono tamano={21} />
              <span>{etiqueta}</span>
            </button>
          );
        })}
      </nav>

      <div className="sidebar__pie">
        <div className="sidebar__sesion">
          <strong className="sidebar__sesion-nombre">{usuario || 'Usuario'}</strong>
          <small className="sidebar__sesion-cargo">{etiquetaDeRol(rol)}</small>

          <button type="button" className="sidebar__cerrar-sesion" onClick={manejarCerrarSesion}>
            <IconoCerrarSesion tamano={18} />
            <span>Cerrar sesión</span>
          </button>
        </div>
      </div>
    </aside>
  );
}
