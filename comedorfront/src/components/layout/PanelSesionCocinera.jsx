import { useEffect, useRef, useState } from 'react';
import useSesion from '../../hooks/useSesion.js';
import { SECCION_INICIAL, guardarSeccionActiva } from '../../navegacion.js';
import { etiquetaDeRol } from '../../permisos.js';
import Boton from '../ui/Boton.jsx';
import { IconoCerrarSesion, IconoHuella, IconoLista, IconoUsuario } from '../ui/Iconos.jsx';
import './PanelSesionCocinera.css';

/** True si el navegador ofrece la Fullscreen API. */
export function admitePantallaCompleta() {
  return typeof document !== 'undefined'
    && typeof document.documentElement?.requestFullscreen === 'function';
}

/** Entra o sale de pantalla completa; si el navegador lo niega, no hace nada. */
export async function alternarPantallaCompleta() {
  if (typeof document === 'undefined') return;
  try {
    if (document.fullscreenElement) {
      await document.exitFullscreen();
    } else {
      await document.documentElement.requestFullscreen();
    }
  } catch {
    // El navegador negó el cambio: la app se queda como está.
  }
}

/*
 * Las dos pantallas de la cocinera. El checklist es la principal mientras no
 * esté el lector; el botón del panel lleva a la otra.
 */
const PANTALLAS_COCINA = {
  checklist: { destino: 'vivo', etiqueta: 'Ir a Control Biométrico', Icono: IconoHuella },
  vivo: { destino: 'checklist', etiqueta: 'Ir al Checklist de comida', Icono: IconoLista },
};

/** Panel de usuario, cambio de pantalla, pantalla completa y cierre de sesion. */
export default function PanelSesionCocinera({ abiertoInicial = false, seccionActiva = null, onCambiarSeccion = null }) {
  const { rol, usuario, logout } = useSesion();
  const [abierto, setAbierto] = useState(abiertoInicial);
  const cajaRef = useRef(null);

  useEffect(() => {
    if (!abierto) return undefined;
    function alTeclado(evento) {
      if (evento.key === 'Escape') setAbierto(false);
    }
    function alClicFuera(evento) {
      if (cajaRef.current && !cajaRef.current.contains(evento.target)) setAbierto(false);
    }
    document.addEventListener('keydown', alTeclado);
    document.addEventListener('mousedown', alClicFuera);
    return () => {
      document.removeEventListener('keydown', alTeclado);
      document.removeEventListener('mousedown', alClicFuera);
    };
  }, [abierto]);

  function manejarCerrarSesion() {
    // Igual que el sidebar: quien entre después empieza en su primera sección.
    guardarSeccionActiva(SECCION_INICIAL);
    logout();
  }

  return (
    <CajaSesionCocinera
      cajaRef={cajaRef}
      abierto={abierto}
      onAlternar={() => setAbierto((valor) => !valor)}
      usuario={usuario}
      rol={rol}
      onCerrarSesion={manejarCerrarSesion}
      seccionActiva={seccionActiva}
      onCambiarSeccion={onCambiarSeccion ? (id) => {
        setAbierto(false);
        onCambiarSeccion(id);
      } : null}
    />
  );
}

/**
 * Presentación del botón flotante y el panel, sin enganchar la sesión: así se
 * prueba el contenido (usuario, rol, acciones) sin montar el
 * proveedor ni la sesión.
 */
export function CajaSesionCocinera({
  cajaRef,
  abierto,
  onAlternar,
  usuario,
  rol,
  onCerrarSesion,
  seccionActiva = null,
  onCambiarSeccion = null,
}) {
  const cambio = onCambiarSeccion ? PANTALLAS_COCINA[seccionActiva] : null;
  return (
    <div className="panel-sesion" ref={cajaRef}>
      <button
        type="button"
        className="panel-sesion__flotante"
        aria-label="Menú de sesión"
        aria-expanded={abierto}
        onClick={onAlternar}
      >
        <IconoUsuario tamano={20} />
      </button>
      {abierto ? (
        <div className="panel-sesion__panel" role="dialog" aria-label="Sesión">
          <div className="panel-sesion__usuario">
            <strong className="panel-sesion__usuario-nombre">{usuario || 'Usuario'}</strong>
            <small className="panel-sesion__usuario-rol">{etiquetaDeRol(rol)}</small>
          </div>
          {cambio ? (
            <Boton variante="primario" anchoCompleto icono={<cambio.Icono tamano={18} />}
              onClick={() => onCambiarSeccion(cambio.destino)}>
              {cambio.etiqueta}
            </Boton>
          ) : null}
          {admitePantallaCompleta() ? (
            <Boton variante="secundario" anchoCompleto onClick={alternarPantallaCompleta}>
              Pantalla completa
            </Boton>
          ) : null}
          <Boton variante="secundario" anchoCompleto icono={<IconoCerrarSesion tamano={18} />} onClick={onCerrarSesion}>
            Cerrar sesión
          </Boton>
        </div>
      ) : null}
    </div>
  );
}
