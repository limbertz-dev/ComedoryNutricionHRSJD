import { GRUPOS } from '../../navegacion';
import { IconoCerrarSesion, IconoLogo } from '../ui/Iconos.jsx';
import './Sidebar.css';

/**
 * Columna izquierda completa: marca arriba, módulos en el medio y la sesión
 * al pie — la misma estructura del panel del que se recicla el estilo.
 */
export default function Sidebar({ seccionActiva, onCambiarSeccion, onCerrarSesion }) {
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
        {GRUPOS.map((grupo) => (
          <div className="sidebar__grupo" key={grupo.id}>
            <p className="sidebar__grupo-titulo" id={`grupo-${grupo.id}`}>
              {grupo.etiqueta}
            </p>

            <div className="sidebar__grupo-items" role="group" aria-labelledby={`grupo-${grupo.id}`}>
              {grupo.secciones.map(({ id, etiqueta, descripcion, Icono }) => {
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
            </div>
          </div>
        ))}
      </nav>

      <div className="sidebar__pie">
        <div className="sidebar__sesion">
          <strong className="sidebar__sesion-nombre">Lic. Norma Tarifa Castillo</strong>
          <small className="sidebar__sesion-cargo">Licenciada en Nutrición</small>

          <button type="button" className="sidebar__cerrar-sesion" onClick={onCerrarSesion}>
            <IconoCerrarSesion tamano={18} />
            <span>Cerrar sesión</span>
          </button>
        </div>
      </div>
    </aside>
  );
}
