import {
  IconoDashboard,
  IconoHistorial,
  IconoHuella,
  IconoReportes,
} from './components/ui/Iconos.jsx';

/**
 * Definición única del menú lateral.
 *
 * `etiqueta` es lo que se lee en el sidebar (una sola línea, como en el
 * sistema del que se recicla el estilo) y `titulo` / `descripcion` son lo que
 * la barra superior muestra de la sección abierta.
 */
export const SECCIONES = [
  {
    id: 'vivo',
    etiqueta: 'Control Biométrico',
    titulo: 'Control Biométrico',
    descripcion: 'Marcaciones en vivo',
    Icono: IconoHuella,
  },
  {
    id: 'dashboard',
    etiqueta: 'Resumen',
    titulo: 'Resumen',
    descripcion: 'Consumo y cupo del turno',
    Icono: IconoDashboard,
  },
  {
    id: 'historial',
    etiqueta: 'Historial de comidas',
    titulo: 'Historial de comidas',
    descripcion: 'Registro por comensal',
    Icono: IconoHistorial,
  },
  {
    id: 'reportes',
    etiqueta: 'Reportes',
    titulo: 'Reportes',
    descripcion: 'Planillas y estadísticas',
    Icono: IconoReportes,
  },
];

export const SECCION_INICIAL = 'vivo';

/** Sección abierta, o la primera si el id no existe. */
export function buscarSeccion(id) {
  return SECCIONES.find((seccion) => seccion.id === id) ?? SECCIONES[0];
}

const CLAVE_SECCION_ACTIVA = 'comedor_seccion_activa';

/**
 * Sección con la que abrir la app: la de la última visita si sigue siendo
 * válida, para que un F5 no devuelva siempre a Control Biométrico.
 */
export function leerSeccionGuardada() {
  try {
    const guardada = localStorage.getItem(CLAVE_SECCION_ACTIVA);
    return SECCIONES.some((seccion) => seccion.id === guardada) ? guardada : SECCION_INICIAL;
  } catch {
    return SECCION_INICIAL;
  }
}

/** Persiste la sección activa para que sobreviva a la próxima carga. */
export function guardarSeccionActiva(id) {
  try {
    localStorage.setItem(CLAVE_SECCION_ACTIVA, id);
  } catch (error) {
    console.warn('No se pudo guardar la sección activa:', error);
  }
}
