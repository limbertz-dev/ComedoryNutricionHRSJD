import Boton from '../ui/Boton.jsx';
import { IconoCandado } from '../ui/Iconos.jsx';
import './SinPermiso.css';

/**
 * Lo único que se pinta cuando el rol no alcanza para una sección, o cuando
 * el backend respondió 403: nunca la sección con datos a medias.
 * `onVolver` lleva a una sección permitida; `onSalir`, al Login.
 */
export default function SinPermiso({ onVolver, onSalir }) {
  return (
    <section className="sin-permiso" role="alert" aria-labelledby="sin-permiso-titulo">
      <span className="sin-permiso__icono" aria-hidden="true">
        <IconoCandado tamano={40} />
      </span>
      <h2 id="sin-permiso-titulo">Sin permiso</h2>
      <p>Su usuario no tiene acceso a esta sección. Si lo necesita, pídalo a la jefatura de nutrición.</p>
      <div className="sin-permiso__acciones">
        {onVolver ? <Boton onClick={onVolver}>Ir a mi sección</Boton> : null}
        {onSalir ? <Boton variante="fantasma" onClick={onSalir}>Cerrar sesión</Boton> : null}
      </div>
    </section>
  );
}
