import {
  IconoAlerta,
  IconoDashboard,
  IconoHistorial,
  IconoHuella,
  IconoOjo,
  IconoReloj,
  IconoReportes,
  IconoUsuario,
} from './components/ui/Iconos.jsx';
import { resolverSeccionGuardada, seccionInicialDeRol, seccionesPermitidas } from './permisos.js';

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
    id: 'supervision',
    etiqueta: 'Supervisión',
    titulo: 'Supervisión del comedor',
    descripcion: 'Control y supervisión del comedor',
    Icono: IconoOjo,
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
  {
    id: 'reglas',
    etiqueta: 'Reglas del sistema',
    titulo: 'Reglas del sistema',
    descripcion: 'Horarios y derecho a comer',
    Icono: IconoReloj,
  },
  {
    id: 'admin',
    etiqueta: 'Administración',
    titulo: 'Administración de cuentas',
    descripcion: 'Cuentas del comedor',
    Icono: IconoUsuario,
  },
  {
    id: 'monitoreo',
    etiqueta: 'Salud del sistema',
    titulo: 'Salud del sistema',
    descripcion: 'Diagnóstico técnico del sistema',
    Icono: IconoAlerta,
  },
  {
    id: 'cuentas',
    etiqueta: 'Cuentas',
    titulo: 'Cuentas',
    descripcion: 'Cuentas del comedor (solo lectura)',
    Icono: IconoUsuario,
  },
];

export const SECCION_INICIAL = 'vivo';

/** Sección abierta, o la primera si el id no existe. */
export function buscarSeccion(id) {
  return SECCIONES.find((seccion) => seccion.id === id) ?? SECCIONES[0];
}

/** Lo que la barra superior muestra en lugar de una sección vedada. */
export const SECCION_SIN_PERMISO = {
  id: 'sin-permiso',
  titulo: 'Sin permiso',
  descripcion: 'Esta sección no está habilitada para su usuario',
};

/** Secciones del sidebar para el rol, en el orden del menú. */
export function seccionesDeRol(rol) {
  const permitidas = seccionesPermitidas(rol);
  return SECCIONES.filter(({ id }) => permitidas.includes(id));
}

const CLAVE_SECCION_ACTIVA = 'comedor_seccion_activa';

/**
 * Sección con la que abrir la app: la de la última visita si sigue siendo
 * válida para este rol, para que un F5 no devuelva siempre a Control
 * Biométrico.
 */
export function leerSeccionGuardada(rol) {
  try {
    return resolverSeccionGuardada(rol, localStorage.getItem(CLAVE_SECCION_ACTIVA));
  } catch {
    return seccionInicialDeRol(rol);
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
