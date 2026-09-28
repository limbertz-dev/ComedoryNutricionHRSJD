/*
 * permisos.js — qué puede abrir cada rol.
 *
 * Sin JSX ni iconos, para que la guardia se pruebe con `node --test`;
 * `navegacion.js` lo cruza con el menú. El backend sigue siendo quien
 * decide: esto solo evita ofrecer lo que respondería 403.
 */

/** Ids de las secciones, en el orden del menú lateral. */
export const IDS_SECCIONES = ['vivo', 'supervision', 'dashboard', 'historial', 'reportes'];

/*
 * La cocinera opera el lector: solo Control Biométrico y sin el «Modo
 * manual», que autoriza raciones saltándose la huella. Jefa y sistemas
 * supervisan el comedor ('supervision') y ven además resumen, historial y
 * reportes. Un rol que no esté aquí no ve nada: se niega por defecto.
 */
const SECCIONES_JEFATURA = ['supervision', 'dashboard', 'historial', 'reportes'];

const PERMISOS = {
  cocinera: { etiqueta: 'Cocinera', secciones: ['vivo'], marcacionManual: false, reloj: false },
  jefa: { etiqueta: 'Jefa de nutrición', secciones: SECCIONES_JEFATURA, marcacionManual: true, reloj: true },
  sistemas: { etiqueta: 'Sistemas', secciones: SECCIONES_JEFATURA, marcacionManual: true, reloj: true },
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

/*
 * Mover el reloj de simulación (/simulacion/*) es de jefatura, igual que en
 * el backend. A la cocinera no se le ofrece: su 403 vedaría la sección.
 */
export function puedeOperarReloj(rol) {
  return permisosDe(rol)?.reloj === true;
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
