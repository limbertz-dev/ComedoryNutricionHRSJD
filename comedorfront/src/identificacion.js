/*
 * identificacion.js — la cocinera identifica una huella no reconocida y
 * confirma la entrega.
 *
 * Sin JSX, para probarlo con `node --test`. Aquí vive lo que no puede fallar:
 *
 *  - Un INTENTO es (lectura, persona, clave). La clave de idempotencia nace
 *    al confirmar a una persona para una lectura y se reutiliza SOLO para
 *    repetir esa misma decisión. Solo un resultado definitivo (entrega,
 *    rechazo, conflicto o un rechazo de sesión) cierra el intento.
 *  - Mientras el resultado es incierto o hay otra intervención en curso, el
 *    intento se conserva aunque se cierre el panel o la huella salga de la
 *    lista de pendientes (salir de la lista no prueba la entrega: pudo
 *    terminar el servicio). No se puede elegir a otra persona para esa huella
 *    hasta verificarlo, y verificarlo repite la misma clave y la misma persona.
 *  - El intento guarda los datos mínimos de la persona y de la huella: la
 *    verificación no depende de que la persona siga en el padrón visible.
 *  - Un solo envío a la vez: mientras un POST está en vuelo, otro clic no hace
 *    nada.
 *  - Nada de nota ni motivo: solo se envía la persona elegida.
 *
 * El servidor decide todo (derecho, servicio, duplicado); el front no adivina.
 */
import { identificarLectura, nuevaClaveIdempotencia } from './api.js';

/** Estados en los que hay que repetir la MISMA decisión con la MISMA clave. */
export const ESTADOS_PARA_REPETIR = ['incierto', 'en_curso'];

const idValido = (valor) => Number.isInteger(valor) && valor > 0;

/** Lo mínimo de la persona para mostrarla y repetir sin el padrón. */
function copiaDePersona(persona) {
  return {
    id: persona.id,
    nombre: persona.nombre ?? null,
    categoria: persona.categoria ?? null,
    legajo: persona.legajo ?? null,
  };
}

/** Lo mínimo de la huella para listarla aunque salga de los pendientes. */
function copiaDeLectura(lectura) {
  return {
    id: lectura.id,
    clave: lectura.clave ?? null,
    hora: lectura.hora ?? null,
    comida: lectura.comida ?? null,
  };
}

/**
 * Crea el identificador de cocina. `identificar(lecturaId, usuarioId, {clave})`
 * es el POST (inyectable para las pruebas) y `nuevaClave()` da un UUID v4.
 *
 * - `confirmar(lectura, persona)` abre un intento nuevo y lo envía. Si esa
 *   huella ya tiene un intento sin resolver, no envía nada y devuelve
 *   `{ estado: 'bloqueado' }`: primero hay que verificarlo.
 * - `verificar(lecturaId)` repite el intento sin resolver con su misma clave
 *   y su misma persona.
 * - Los dos devuelven null si ya hay un envío en vuelo.
 * - `pendiente(lecturaId)` / `pendientes()`: los intentos sin resolver
 *   ({ lecturaId, usuarioId, clave, persona, lectura, estado }), en copia.
 *
 * No hay forma de descartar un intento sin resolver: cerrar el panel solo lo
 * deja a la vista para verificarlo después.
 */
export function crearIdentificador({
  identificar = identificarLectura,
  nuevaClave = nuevaClaveIdempotencia,
} = {}) {
  const intentos = new Map();
  let enVuelo = false;

  async function enviar(intento) {
    enVuelo = true;
    let resultado;
    try {
      resultado = await identificar(intento.lecturaId, intento.usuarioId, { clave: intento.clave });
    } catch (error) {
      /* La petición ya había empezado: no se sabe qué quedó. */
      resultado = {
        estado: 'incierto',
        detalle: `No se pudo leer el resultado (${error?.message ?? 'error inesperado'}).`,
      };
    } finally {
      enVuelo = false;
    }
    if (!resultado || typeof resultado.estado !== 'string') {
      resultado = { estado: 'incierto', detalle: 'El resultado no se pudo leer.' };
    }
    if (ESTADOS_PARA_REPETIR.includes(resultado.estado)) {
      intento.estado = resultado.estado;
    } else {
      intentos.delete(intento.lecturaId);
    }
    return resultado;
  }

  async function confirmar(lectura, persona) {
    if (enVuelo) return null;
    if (!idValido(lectura?.id) || !idValido(persona?.id)) {
      return { estado: 'invalido', detalle: 'Elija una huella y una persona del padrón.' };
    }
    if (intentos.has(lectura.id)) return { estado: 'bloqueado' };
    const intento = {
      lecturaId: lectura.id,
      usuarioId: persona.id,
      clave: nuevaClave(),
      persona: copiaDePersona(persona),
      lectura: copiaDeLectura(lectura),
      estado: 'enviando',
    };
    intentos.set(lectura.id, intento);
    return enviar(intento);
  }

  async function verificar(lecturaId) {
    if (enVuelo) return null;
    const intento = intentos.get(lecturaId);
    return intento ? enviar(intento) : null;
  }

  const copia = (intento) => ({
    ...intento,
    persona: { ...intento.persona },
    lectura: { ...intento.lectura },
  });

  return {
    confirmar,
    verificar,
    enVuelo: () => enVuelo,
    pendiente: (lecturaId) => {
      const intento = intentos.get(lecturaId);
      return intento ? copia(intento) : null;
    },
    pendientes: () => [...intentos.values()].map(copia),
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
 * verificar con la misma clave) o 'error'. `repetir` dice si se ofrece
 * «Verificar entrega» con la misma persona; `cerrar`, si la lectura dejó de
 * ser identificable y el panel se cierra. Un estado que no se reconoce se
 * trata como incierto: nunca se afirma que no hubo entrega.
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
        detalle: 'Verifique la entrega: se repite la misma solicitud y no se duplica.',
        repetir: true,
        cerrar: false,
      };
    case 'incierto':
      return {
        tipo: 'aviso',
        titulo: 'No se pudo confirmar si quedó registrada',
        detalle: 'Verifique la entrega: se repite la misma solicitud con la misma persona y, si ya quedó, se recupera sin duplicarla.',
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
    case 'bloqueado':
      return {
        tipo: 'aviso',
        titulo: 'Hay una confirmación sin verificar',
        detalle: 'Esta huella tiene una entrega por verificar. Verifíquela antes de elegir a otra persona.',
        repetir: true,
        cerrar: false,
      };
    case 'invalido':
      /* No se envió nada: faltaba la huella o la persona. */
      return {
        tipo: 'error',
        titulo: 'Falta elegir a la persona',
        detalle: resultado.detalle,
        repetir: false,
        cerrar: false,
      };
    case 'error':
      /* 401, 403 o 428: el servidor la rechazó antes de procesarla. */
      return {
        tipo: 'error',
        titulo: 'La confirmación no se procesó',
        detalle: resultado.detalle || 'Revise la sesión y vuelva a intentarlo.',
        repetir: false,
        cerrar: false,
      };
    default:
      return {
        tipo: 'aviso',
        titulo: 'No se pudo confirmar si quedó registrada',
        detalle: 'Verifique la entrega con la misma persona antes de hacer otra cosa con esta huella.',
        repetir: true,
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
