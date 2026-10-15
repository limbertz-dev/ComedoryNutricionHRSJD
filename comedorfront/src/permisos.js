/*
 * permisos.js — qué puede abrir cada rol.
 *
 * Sin JSX ni iconos, para que la guardia se pruebe con `node --test`;
 * `navegacion.js` lo cruza con el menú. El backend sigue siendo quien
 * decide: esto solo evita ofrecer lo que respondería 403.
 */

/** Ids de las secciones, en el orden del menú lateral. */
export const IDS_SECCIONES = ['vivo', 'supervision', 'dashboard', 'historial', 'reportes', 'reglas', 'admin', 'monitoreo', 'cuentas'];

/*
 * La cocinera opera el lector: solo Control Biométrico y sin el «Modo
 * manual», que autoriza raciones saltándose la huella. La jefa supervisa el
 * comedor ('supervision') y ve además resumen, historial, reportes y las
 * cuentas en solo lectura ('cuentas'). Sistemas (root) ya no opera el
 * comedor: edita los horarios ('reglas'), administra cuentas ('admin') y
 * mira el lector biométrico ('monitoreo'); no registra a mano.
 * Un rol que no esté aquí no ve nada: se niega por defecto.
 */
const SECCIONES_JEFATURA = ['supervision', 'dashboard', 'historial', 'reportes'];

/* Secciones que consultan el padrón y el cupo del turno. */
const SECCIONES_DEL_COMEDOR = ['vivo', ...SECCIONES_JEFATURA];

/*
 * Intervenciones de cocina (huella no reconocida): solo la cocinera
 * identifica a la persona y confirma la entrega (`identificaLecturas`); solo
 * la jefa consulta lo que se hizo (`consultaIntervenciones`), sin aprobar ni
 * ejecutar nada. Sistemas queda fuera de las dos, igual que en el backend
 * (comedorback/app/core/permisos.py).
 */
const PERMISOS = {
  cocinera: {
    etiqueta: 'Cocinera', secciones: ['vivo'], marcacionManual: false,
    identificaLecturas: true, consultaIntervenciones: false,
  },
  jefa: {
    etiqueta: 'Jefa de nutrición', secciones: [...SECCIONES_JEFATURA, 'cuentas'], marcacionManual: true,
    identificaLecturas: false, consultaIntervenciones: true,
  },
  sistemas: {
    etiqueta: 'Sistemas', secciones: ['reglas', 'admin', 'monitoreo'], marcacionManual: false,
    identificaLecturas: false, consultaIntervenciones: false,
  },
};

const permisosDe = (rol) => (typeof rol === 'string' ? PERMISOS[rol.trim().toLowerCase()] : undefined);

export function etiquetaDeRol(rol) {
  return permisosDe(rol)?.etiqueta ?? 'Sin rol reconocido';
}

/** Ids que el rol puede abrir, en el orden del menú. */
export function seccionesPermitidas(rol) {
  const propias = permisosDe(rol)?.secciones ?? [];
  return IDS_SECCIONES.filter((id) => propias.includes(id));
}

export function puedeVerSeccion(rol, id) {
  return seccionesPermitidas(rol).includes(id);
}

export function puedeMarcarManual(rol) {
  return permisosDe(rol)?.marcacionManual === true;
}

/** Identificar una huella no reconocida y confirmar la entrega: solo cocinera. */
export function puedeIdentificarLecturas(rol) {
  return permisosDe(rol)?.identificaLecturas === true;
}

/** Consultar las intervenciones de cocina (sin aprobar nada): solo jefa. */
export function puedeConsultarIntervenciones(rol) {
  return permisosDe(rol)?.consultaIntervenciones === true;
}


/**
 * El rol tiene alguna sección que usa el padrón o el cupo del turno. Sistemas
 * no: no se le pide el padrón ni se le muestra el turno.
 */
export function usaDatosDelComedor(rol) {
  const propias = seccionesPermitidas(rol);
  return SECCIONES_DEL_COMEDOR.some((id) => propias.includes(id));
}

/** Primera sección del rol, o null si no tiene ninguna. */
export function seccionInicialDeRol(rol) {
  return seccionesPermitidas(rol)[0] ?? null;
}

/**
 * Sección con la que abrir el panel a partir de la guardada. La PC es
 * compartida: si la jefa dejó guardado Reportes, la cocinera que entra
 * después cae en su primera sección y no en Reportes.
 */
export function resolverSeccionGuardada(rol, guardada) {
  return puedeVerSeccion(rol, guardada) ? guardada : seccionInicialDeRol(rol);
}
