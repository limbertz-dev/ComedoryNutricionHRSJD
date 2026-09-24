import {
  IconoCama,
  IconoDashboard,
  IconoDieta,
  IconoHistorial,
  IconoHuella,
  IconoReportes,
} from './components/ui/Iconos.jsx';

/**
 * Definición única del menú lateral, ordenado en grupos.
 *
 * Los grupos son los dos comedores que atiende el sistema — el del personal y
 * el de los pacientes internados — más lo que sirve a ambos. El rótulo del
 * grupo es lo que separa "Historial de comidas" (personal) de "Control de
 * Dietas" (camas), que de otro modo se leerían como la misma lista.
 *
 * `etiqueta` es lo que se lee en el sidebar (una sola línea, como en el
 * sistema del que se recicla el estilo) y `titulo` / `descripcion` son lo que
 * la barra superior muestra de la sección abierta.
 */
export const GRUPOS = [
  {
    id: 'personal',
    etiqueta: 'Personal',
    secciones: [
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
    ],
  },
  {
    id: 'pacientes',
    etiqueta: 'Pacientes',
    secciones: [
      {
        id: 'control-dietas',
        etiqueta: 'Control de Dietas',
        titulo: 'Control de Dietas',
        descripcion: 'Raciones del día por servicio y tipo de dieta',
        Icono: IconoCama,
      },
      {
        id: 'dietas',
        etiqueta: 'Dietas',
        titulo: 'Dietas',
        descripcion: 'Catálogo oficial de dietas de nutrición',
        Icono: IconoDieta,
      },
    ],
  },
  {
    id: 'comun',
    etiqueta: 'Común',
    secciones: [
      {
        id: 'reportes',
        etiqueta: 'Reportes',
        titulo: 'Reportes',
        descripcion: 'Planillas y estadísticas',
        Icono: IconoReportes,
      },
    ],
  },
];

/** Todas las secciones en orden de sidebar, sin la agrupación. */
export const SECCIONES = GRUPOS.flatMap((grupo) => grupo.secciones);

export const SECCION_INICIAL = 'vivo';

/** Sección abierta, o la primera si el id no existe. */
export function buscarSeccion(id) {
  return SECCIONES.find((seccion) => seccion.id === id) ?? SECCIONES[0];
}

/**
 * Grupo al que pertenece una sección ('personal', 'pacientes', 'comun').
 *
 * Lo usa App para saber qué avisos de estado corresponden: el padrón y el
 * cupo del turno son del comedor del personal, y no tienen nada que decir
 * sobre las pantallas de pacientes.
 */
export function grupoDeSeccion(id) {
  return GRUPOS.find((grupo) => grupo.secciones.some((seccion) => seccion.id === id))?.id ?? null;
}

const CLAVE_SECCION_ACTIVA = 'comedor_seccion_activa';

/**
 * Sección con la que abrir la app: la de la última visita si sigue siendo
 * válida, para que un F5 no devuelva siempre a Control Biométrico.
 */
export function leerSeccionGuardada() {
  try {
    if (typeof window !== 'undefined' && window.location?.search) {
      const params = new URLSearchParams(window.location.search);
      const desdeUrl = params.get('seccion');
      if (desdeUrl && SECCIONES.some((seccion) => seccion.id === desdeUrl)) {
        return desdeUrl;
      }
    }
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
