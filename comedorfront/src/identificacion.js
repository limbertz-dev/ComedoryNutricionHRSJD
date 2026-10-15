/*
 * identificacion.js — la cocinera identifica una huella no reconocida y
 * confirma la entrega.
 *
 * Sin JSX, para probarlo con `node --test`. Aquí vive lo que no puede fallar:
 *
 *  - Un INTENTO es (lectura, persona, clave). La clave de idempotencia se
 *    genera la primera vez que se confirma esa persona para esa lectura y se
 *    reutiliza SOLO para repetir esa misma decisión (resultado incierto o
 *    intervención en curso). Elegir otra persona, o un resultado definitivo
 *    (entrega, rechazo, conflicto), cierra el intento: el próximo lleva otra.
 *  - Un solo envío a la vez: mientras un POST está en vuelo, otro clic no hace
 *    nada.
 *  - Nada de nota ni motivo: solo se envía la persona elegida.
 *
 * El servidor decide todo (derecho, servicio, duplicado); el front no adivina.
 */
import { identificarLectura, nuevaClaveIdempotencia } from './api.js';

/** Estados en los que hay que repetir la MISMA decisión con la MISMA clave. */
export const ESTADOS_PARA_REPETIR = ['incierto', 'en_curso'];

/**
 * Crea el identificador de cocina. `identificar(lecturaId, usuarioId, {clave})`
 * es el POST (inyectable para las pruebas) y `nuevaClave()` da un UUID v4.
 *
 * Devuelve `{ confirmar, pendiente, olvidar }`:
 *  - `confirmar(lecturaId, usuarioId)` envía (o repite) el intento y resuelve
 *    con el resultado de `identificarLectura`, o null si ya había uno en vuelo.
 *  - `pendiente(lecturaId)` es el intento que quedó por repetir de esa lectura
 *    ({ usuarioId, clave }) o null.
 *  - `olvidar(lecturaId)` descarta el intento pendiente (la lectura salió de la
 *    lista o la cocinera cerró el panel).
 */
export function crearIdentificador({
  identificar = identificarLectura,
  nuevaClave = nuevaClaveIdempotencia,
} = {}) {
  const intentos = new Map();
  let enVuelo = false;

  async function confirmar(lecturaId, usuarioId) {
    if (enVuelo) return null;
    let intento = intentos.get(lecturaId);
    /* Otra persona es otra decisión: nunca se reutiliza la clave. */
    if (!intento || intento.usuarioId !== usuarioId) {
      intento = { usuarioId, clave: nuevaClave() };
      intentos.set(lecturaId, intento);
    }
    enVuelo = true;
    try {
      const resultado = await identificar(lecturaId, usuarioId, { clave: intento.clave });
      if (!ESTADOS_PARA_REPETIR.includes(resultado.estado)) intentos.delete(lecturaId);
      return resultado;
    } catch (error) {
      /* Un fallo antes de enviar (datos inválidos) no deja nada por repetir. */
      intentos.delete(lecturaId);
      throw error;
    } finally {
      enVuelo = false;
    }
  }

  return {
    confirmar,
    pendiente: (lecturaId) => {
      const intento = intentos.get(lecturaId);
      return intento ? { ...intento } : null;
    },
    olvidar: (lecturaId) => intentos.delete(lecturaId),
  };
}

const TEXTO_CONFLICTO = {
  lectura_ya_resuelta: 'Esta huella ya tiene una entrega registrada.',
  lectura_no_resoluble: 'Esta lectura ya no es una huella no reconocida pendiente.',
  servicio_distinto: 'Esta huella es de otro servicio: ya no se puede identificar.',
  servicio_no_determinable: 'No se pudo determinar el servicio de esta huella: no se puede identificar.',
  reloj_inconsistente: 'El reloj del servidor está antes de la hora de la huella: no se puede identificar.',
  clave_reutilizada_con_otro_contenido: 'Esta confirmación ya se había usado con otra persona. Elija de nuevo y confirme.',
  comensal_inexistente: 'Esa persona ya no está en el padrón.',
  lectura_inexistente: 'Esa lectura no existe.',
};

/**
 * El aviso que ve la cocinera para un resultado. `tipo` es 'exito' (solo una
 * entrega registrada), 'rechazo' (intento sin entrega), 'aviso' (hay que
 * repetir con la misma clave) o 'error'. `repetir` dice si se ofrece «Volver a
 * confirmar» con la misma persona; `cerrar`, si la lectura dejó de ser
 * identificable y el panel se cierra.
 */
export function avisoDeIdentificacion(resultado, persona = null) {
  const quien = resultado?.nombre || persona?.nombre || '';
  switch (resultado?.estado) {
    case 'registrada':
      return {
        tipo: 'exito',
        titulo: 'Entrega registrada',
        detalle: [quien, resultado.comida].filter(Boolean).join(' · ')
          + (resultado.reintento ? ' · confirmada en un intento anterior' : ''),
        repetir: false,
        cerrar: true,
      };
    case 'rechazada':
      return {
        tipo: 'rechazo',
        titulo: 'Intento rechazado: no se registró entrega',
        detalle: resultado.detalle,
        repetir: false,
        cerrar: false,
      };
    case 'en_curso':
      return {
        tipo: 'aviso',
        titulo: 'Otra confirmación está en curso',
        detalle: 'Vuelva a confirmar: se usa la misma solicitud y no se duplica la entrega.',
        repetir: true,
        cerrar: false,
      };
    case 'incierto':
      return {
        tipo: 'aviso',
        titulo: 'No se pudo confirmar si quedó registrada',
        detalle: 'Vuelva a confirmar con la misma persona: si la entrega ya quedó, se recupera sin duplicarla.',
        repetir: true,
        cerrar: false,
      };
    case 'conflicto': {
      const yaResuelta = resultado.motivo === 'lectura_ya_resuelta';
      return {
        tipo: yaResuelta && resultado.resueltaPorMi ? 'exito' : 'error',
        titulo: yaResuelta
          ? (resultado.resueltaPorMi ? 'Ya la registró usted' : 'Ya fue resuelta')
          : 'No se puede identificar',
        detalle: TEXTO_CONFLICTO[resultado.motivo] ?? resultado.detalle,
        repetir: false,
        cerrar: CONFLICTO_CIERRA.includes(resultado.motivo),
      };
    }
    default:
      return {
        tipo: 'error',
        titulo: 'No se registró la entrega',
        detalle: resultado?.detalle || 'Revise la sesión y vuelva a intentarlo.',
        repetir: false,
        cerrar: false,
      };
  }
}

/* Conflictos tras los que la lectura ya no es identificable. */
const CONFLICTO_CIERRA = [
  'lectura_ya_resuelta',
  'lectura_no_resoluble',
  'servicio_distinto',
  'servicio_no_determinable',
  'reloj_inconsistente',
  'lectura_inexistente',
];

/**
 * Claves de las filas cuya `intervencion.revision` subió respecto de la
 * consulta anterior. `revision` solo crece: sube cuando alguien (también otra
 * cocinera) registra una entrega de esa lectura, aunque la fila ya existiera.
 * Devuelve `{ revisiones, cambiadas }`: la referencia siguiente y las claves.
 */
export function revisionesCambiadas(anteriores, filas = []) {
  const revisiones = new Map();
  const cambiadas = [];
  for (const fila of filas) {
    const revision = fila.intervencion?.revision;
    if (!Number.isInteger(revision)) continue;
    revisiones.set(fila.clave, revision);
    const previa = anteriores?.get(fila.clave);
    if (Number.isInteger(previa) && revision > previa) cambiadas.push(fila.clave);
  }
  return { revisiones, cambiadas };
}

/** "HH:MM" de una fecha y hora del servidor ("2026-09-28T23:58:00"); '' si no la trae. */
export function horaCortaServidor(texto) {
  const coincidencia = typeof texto === 'string' ? /T(\d{2}:\d{2})/.exec(texto) : null;
  return coincidencia ? coincidencia[1] : '';
}
