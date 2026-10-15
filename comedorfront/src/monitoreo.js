/*
 * monitoreo.js — refresco y vigencia de la consulta de «Lector biométrico».
 *
 * Sin JSX, para probarlo con `node --test`. La vigencia se mide con los
 * relojes de este equipo desde que llegó la respuesta, nunca con la hora de
 * negocio ni con las horas que manda el servidor.
 */

/** Pausa entre el fin de una consulta y el inicio de la siguiente. */
export const MS_REFRESCO_MONITOREO = 30000;

/** Edad máxima de una consulta, desde su recepción, para mostrarse reciente. */
export const MS_ANTIGUEDAD_MAXIMA = 90000;

/*
 * Diferencia aceptada entre lo que avanzó el reloj de pared y el monotónico.
 * Más que esto es una suspensión o un salto del reloj: el dato no se puede
 * fechar con certeza y se trata como antiguo.
 */
export const MS_DESFASE_TOLERADO = 2000;

/** Cada cuánto se vuelve a calcular la vigencia; el tick no la prueba. */
export const MS_REEVALUAR_VIGENCIA = 5000;

/** Lectura de los dos relojes del equipo en el mismo instante. */
export function medirAhora() {
  const mono = globalThis.performance?.now?.();
  return { pared: Date.now(), mono: typeof mono === 'number' ? mono : Number.NaN };
}

/**
 * true solo si los dos relojes avanzaron hacia adelante, casi lo mismo y
 * no más de MS_ANTIGUEDAD_MAXIMA desde `recepcion`. Ante la duda (sin
 * recepción, reloj ausente, retroceso, suspensión), false.
 */
export function datoVigente(recepcion, ahora = medirAhora()) {
  if (!recepcion || !ahora) return false;
  const pared = ahora.pared - recepcion.pared;
  const mono = ahora.mono - recepcion.mono;
  if (!Number.isFinite(pared) || !Number.isFinite(mono)) return false;
  if (pared < 0 || mono < 0) return false;
  if (Math.abs(pared - mono) > MS_DESFASE_TOLERADO) return false;
  return Math.max(pared, mono) <= MS_ANTIGUEDAD_MAXIMA;
}

/**
 * Estado que muestra la sección. Solo 'vigente' admite indicadores verdes:
 * un fallo, el regreso a la pestaña o la antigüedad los retiran aunque los
 * datos anteriores sigan a la vista. Las horas del diagnóstico (momento real
 * y reloj de negocio) no intervienen.
 */
export function estadoDeVista({ diagnostico, recepcion, error, pendiente }, ahora = medirAhora()) {
  if (!diagnostico) return error ? 'sin-diagnostico' : 'cargando';
  if (error) return 'fallo-con-datos';
  if (pendiente) return 'revalidando';
  return datoVigente(recepcion, ahora) ? 'vigente' : 'antiguo';
}

/**
 * Programa las consultas del diagnóstico:
 * - una consulta inicial inmediata;
 * - la siguiente, `intervaloMs` después de que termine la anterior, así
 *   nunca se solapan; `actualizar()` durante una consulta se une a ella;
 * - al ocultar la pestaña no se programa nada más;
 * - al volver, `alVolver()` marca lo mostrado como pendiente, se descarta
 *   la consulta en vuelo y se pide una nueva;
 * - `cancelar()` aborta la petición y quita temporizador y listener.
 * `consultar` maneja sus propios errores; aquí solo se ignoran.
 */
export function programarRefrescoMonitoreo({
  consultar,
  alVolver = () => {},
  intervaloMs = MS_REFRESCO_MONITOREO,
  documento = globalThis.document,
  temporizador = globalThis,
}) {
  let controlador = null;
  let enCurso = null;
  let espera = null;
  let cancelado = false;
  const oculto = () => documento?.visibilityState === 'hidden';

  function detenerEspera() {
    if (espera !== null) {
      temporizador.clearTimeout(espera);
      espera = null;
    }
  }

  function programar() {
    detenerEspera();
    if (cancelado || oculto()) return;
    espera = temporizador.setTimeout(() => {
      espera = null;
      ejecutar('automatico');
    }, intervaloMs);
  }

  function ejecutar(origen) {
    if (cancelado) return Promise.resolve();
    if (enCurso) return enCurso;
    detenerEspera();
    const propio = new AbortController();
    controlador = propio;
    let promesa;
    try {
      promesa = Promise.resolve(consultar({ signal: propio.signal, origen }));
    } catch {
      promesa = Promise.resolve();
    }
    enCurso = promesa.catch(() => {}).finally(() => {
      // Una consulta descartada (regreso o cancelación) no reprograma nada.
      if (controlador !== propio) return;
      controlador = null;
      enCurso = null;
      programar();
    });
    return enCurso;
  }

  function descartarEnCurso() {
    controlador?.abort();
    controlador = null;
    enCurso = null;
  }

  function alCambiarVisibilidad() {
    if (cancelado) return;
    if (oculto()) {
      detenerEspera();
      return;
    }
    alVolver();
    descartarEnCurso();
    ejecutar('regreso');
  }

  documento?.addEventListener?.('visibilitychange', alCambiarVisibilidad);
  ejecutar('inicial');

  return {
    actualizar: () => ejecutar('manual'),
    cancelar() {
      cancelado = true;
      detenerEspera();
      descartarEnCurso();
      documento?.removeEventListener?.('visibilitychange', alCambiarVisibilidad);
    },
  };
}

const FECHA_HORA = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/;
const dos = (numero) => String(numero).padStart(2, '0');

/**
 * "2026-10-09T14:03:10" → "09/10/2026 14:03:10", tal como lo manda el
 * servidor: sin zona, sin conversión.
 */
export function textoFechaHoraServidor(texto) {
  const partes = typeof texto === 'string' ? FECHA_HORA.exec(texto) : null;
  if (!partes) return '—';
  const [anio, mes, dia, hora, minuto, segundo] = partes.slice(1);
  return `${dia}/${mes}/${anio} ${hora}:${minuto}${segundo ? `:${segundo}` : ''}`;
}

/** "2026-10-09" → "09/10/2026". */
export function textoFechaServidor(texto) {
  const partes = typeof texto === 'string' ? /^(\d{4})-(\d{2})-(\d{2})$/.exec(texto) : null;
  return partes ? `${partes[3]}/${partes[2]}/${partes[1]}` : '—';
}

/** Hora de este equipo (reloj de pared) en que llegó la respuesta. */
export function textoHoraLocal(pared) {
  if (!Number.isFinite(pared)) return '—';
  const momento = new Date(pared);
  return `${dos(momento.getHours())}:${dos(momento.getMinutes())}:${dos(momento.getSeconds())}`;
}
