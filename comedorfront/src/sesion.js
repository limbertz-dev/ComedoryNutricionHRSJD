/*
 * sesion.js — tokens de la sesión y máquina de estados del ingreso.
 *
 * No importa React ni hace peticiones: `api.js` lo usa para firmar cada
 * petición y para avisar de un 401 / 403 / 428, y `useSesion` para decidir
 * qué pantalla se ve. Así las dos piezas se prueban con `node --test`.
 *
 * Los tokens van en sessionStorage y no en localStorage: la PC del comedor es
 * compartida, y cerrar la pestaña debe bastar para cerrar la sesión.
 */

const CLAVE_TOKENS = 'comedor_sesion';

/* Copia en memoria: manda sobre sessionStorage y cubre el caso en que el
   navegador lo bloquea (modo privado, políticas del hospital). */
let tokensEnMemoria = null;
const oyentes = new Set();

/** `{ access, refresh, usuario }` de la sesión en curso, o null. */
export function leerTokens() {
  if (tokensEnMemoria) return tokensEnMemoria;
  try {
    const guardados = JSON.parse(sessionStorage.getItem(CLAVE_TOKENS));
    if (typeof guardados?.access === 'string' && guardados.access) {
      tokensEnMemoria = guardados;
      return guardados;
    }
  } catch {
    // Sin sessionStorage o con un valor corrupto: no hay sesión que restaurar.
  }
  return null;
}

export function guardarTokens({ access, refresh, usuario }) {
  tokensEnMemoria = { access, refresh, usuario };
  try {
    sessionStorage.setItem(CLAVE_TOKENS, JSON.stringify(tokensEnMemoria));
  } catch (error) {
    console.warn('La sesión no sobrevivirá a un F5: no se pudo guardar.', error);
  }
}

export function borrarTokens() {
  tokensEnMemoria = null;
  try {
    sessionStorage.removeItem(CLAVE_TOKENS);
  } catch {
    // Nada que borrar si el almacenamiento no está disponible.
  }
}

/**
 * Avisos que `api.js` emite al recibir la respuesta, vengan de la sección que
 * vengan: `expirada` (401), `prohibido` (403) y `cambio_requerido` (428).
 */
export function avisarSesion(aviso) {
  oyentes.forEach((oyente) => oyente(aviso));
}

/** Devuelve la función que deja de escuchar. */
export function escucharSesion(oyente) {
  oyentes.add(oyente);
  return () => oyentes.delete(oyente);
}

/*
 * Fases del ingreso:
 * - `verificando`: hay tokens guardados y se espera GET /auth/yo.
 * - `anonima`: se ve el Login; `aviso` explica por qué (`expirada`, `sin_conexion`).
 * - `cambio`: contraseña temporal; se ve el Login con el formulario de cambio.
 * - `activa`: se ve el panel, filtrado por `rol`.
 */
export const SESION_INICIAL = { fase: 'verificando', rol: null, usuario: null, aviso: null };

const ANONIMA = { fase: 'anonima', rol: null, usuario: null, aviso: null };

export function reductorSesion(estado, accion) {
  switch (accion.tipo) {
    case 'SIN_SESION':
      return ANONIMA;
    case 'INGRESO':
      return { fase: 'activa', rol: accion.rol, usuario: accion.usuario ?? null, aviso: null };
    case 'CAMBIO_REQUERIDO':
      return { fase: 'cambio', rol: null, usuario: accion.usuario ?? estado.usuario, aviso: null };
    case 'EXPIRADA':
      // Un 401 rezagado de una petición anterior no pisa el Login ya visible.
      return estado.fase === 'anonima' ? estado : { ...ANONIMA, aviso: 'expirada' };
    case 'SIN_CONEXION':
      return { ...ANONIMA, aviso: 'sin_conexion' };
    default:
      return estado;
  }
}

/** Traduce un aviso de `api.js` a la acción del reductor (o null si no le toca). */
export function accionDeAviso(aviso) {
  if (aviso?.tipo === 'expirada') return { tipo: 'EXPIRADA' };
  if (aviso?.tipo === 'cambio_requerido') return { tipo: 'CAMBIO_REQUERIDO' };
  return null;
}

const FORMATO_HORA = new Intl.DateTimeFormat('es-BO', { hour: '2-digit', minute: '2-digit' });

/**
 * Texto del bloqueo (423) a partir de `reintentoEn` (Date o null): a qué hora
 * y en cuánto se podrá volver a intentar. Cadena vacía si ya se puede.
 */
export function textoDeReintento(reintentoEn, ahora = new Date()) {
  if (!(reintentoEn instanceof Date)) return 'Intente de nuevo más tarde.';
  const segundos = Math.ceil((reintentoEn.getTime() - ahora.getTime()) / 1000);
  if (segundos <= 0) return '';
  const falta = segundos < 60
    ? `${segundos} ${segundos === 1 ? 'segundo' : 'segundos'}`
    : `${Math.ceil(segundos / 60)} ${Math.ceil(segundos / 60) === 1 ? 'minuto' : 'minutos'}`;
  return `Podrá intentar de nuevo a las ${FORMATO_HORA.format(reintentoEn)} (en ${falta}).`;
}

/**
 * Acción que corresponde a la respuesta de POST /auth/login, ya adaptada por
 * `iniciarSesion`. Credencial errónea y cuenta bloqueada no cambian de fase:
 * el Login las muestra en su propio formulario.
 */
export function accionDeIngreso(resultado, usuario) {
  if (resultado.tipo === 'ok') {
    return resultado.debeCambiar
      ? { tipo: 'CAMBIO_REQUERIDO', usuario }
      : { tipo: 'INGRESO', rol: resultado.rol, usuario };
  }
  if (resultado.tipo === 'cambio') return { tipo: 'CAMBIO_REQUERIDO', usuario };
  return null;
}
