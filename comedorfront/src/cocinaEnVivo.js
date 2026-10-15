/*
 * cocinaEnVivo.js — actualización de la pantalla de cocina desde la API.
 *
 * Sin JSX, para probarlo con `node --test`. La pantalla consulta la ventana
 * de marcaciones recientes y el estado del comedor en ciclos: el siguiente
 * empieza 3 s después de que termina el anterior. Un registro hecho en otro
 * puesto (por ejemplo, la ración manual de la jefa) llega a cocina así.
 *
 * La lista es una ventana de hasta 100 registros, no un cursor: solo se
 * presenta como «recién llegado» el registro más reciente que no estaba en la
 * consulta anterior, nunca una cola de avisos atrasados.
 */

/** Pausa entre el fin de un ciclo y el inicio del siguiente. */
export const MS_CICLO_COCINA = 3000;

/** Tamaño de la ventana de marcaciones que consulta cocina. */
export const LIMITE_MARCACIONES_COCINA = 100;

/**
 * Compara una respuesta con la anterior.
 *
 * - `conocidas` null (primera carga, regreso a la pestaña, fallo previo o
 *   cambio de reloj): la respuesta solo fija la referencia, sin novedad.
 * - Con referencia: la novedad es la primera fila (la más reciente, en el
 *   orden del servidor) cuya `clave` no estaba antes ni es `propia` (la
 *   marcación que esta misma pantalla acaba de enviar y ya mostró).
 *
 * Devuelve `{ conocidas, nueva }`: la referencia siguiente (las claves de
 * esta respuesta) y la fila nueva o null.
 */
export function detectarNueva(conocidas, filas, propias = new Set()) {
  const claves = new Set(filas.map((fila) => fila.clave));
  if (conocidas === null) return { conocidas: claves, nueva: null };
  const nueva = filas.find((fila) => !conocidas.has(fila.clave) && !propias.has(fila.clave)) ?? null;
  return { conocidas: claves, nueva };
}

/**
 * Programa los ciclos de cocina.
 *
 * - `consultarMarcaciones({ signal })` devuelve las filas o lanza.
 * - `refrescarEstado({ origen, signal })` relee el estado del comedor;
 *   maneja su propio error (App conserva el último estado con su aviso) y
 *   con `signal` abortado no publica nada. `origen` es 'inicial', 'ciclo',
 *   'solicitado' o 'regreso': App ya pide el estado al montar, así que quien
 *   llama puede omitir el inicial.
 *
 * Las dos consultas son lecturas (GET) y comparten la `signal` del ciclo:
 * descartar un ciclo (regreso a la pestaña o desmontaje) aborta ambas y
 * ninguna publica su respuesta tardía.
 * - `alActualizar({ filas, error, nueva })` recibe cada resultado: con éxito,
 *   `filas` y la `nueva` detectada; con fallo, solo `error` (las filas
 *   anteriores quedan a la vista y la referencia se reinicia).
 * - `puedeDetectar()` false (una marcación local en curso) actualiza la lista
 *   sin tocar la referencia, para no anunciar dos veces la propia.
 * - `consultarPendientes({ signal })`, opcional (solo cocinera): las huellas
 *   no reconocidas que se pueden identificar ahora
 *   (GET /pantalla/lecturas-por-identificar). Va en el mismo ciclo, con la
 *   misma `signal`, porque la ventana de marcaciones corta en 100 filas y
 *   por fecha: no sirve para seguir el servicio nocturno.
 *   `alActualizarPendientes({ resultado, error })` recibe su resultado aparte:
 *   un fallo suyo no tapa la lista, ni al revés.
 *
 * Sin solapes: `solicitar()` durante un ciclo pide uno más al terminar, sin
 * esperar los 3 s. Con la pestaña oculta no se programa ni se inicia nada
 * (tampoco con `solicitar()`); al volver se descarta el ciclo en vuelo, se
 * reinicia la referencia y se consulta.
 */
export function programarCicloCocina({
  consultarMarcaciones,
  refrescarEstado = async () => {},
  alActualizar = () => {},
  puedeDetectar = () => true,
  consultarPendientes = null,
  alActualizarPendientes = () => {},
  intervaloMs = MS_CICLO_COCINA,
  documento = globalThis.document,
  temporizador = globalThis,
}) {
  let conocidas = null;
  const propias = new Set();
  let controlador = null;
  let espera = null;
  let repetir = false;
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
      ejecutar('ciclo');
    }, intervaloMs);
  }

  async function ciclo(signal, origen) {
    const [lista, , pendientes] = await Promise.all([
      consultarMarcaciones({ signal }).then(
        (filas) => ({ filas }),
        (fallo) => ({ fallo }),
      ),
      Promise.resolve().then(() => refrescarEstado({ origen, signal })).catch(() => {}),
      consultarPendientes
        ? Promise.resolve().then(() => consultarPendientes({ signal })).then(
          (resultado) => ({ resultado }),
          (fallo) => ({ fallo }),
        )
        : null,
    ]);
    if (signal.aborted || cancelado) return;
    if (pendientes) {
      alActualizarPendientes(pendientes.fallo
        ? { error: pendientes.fallo?.message || 'No se pudieron cargar las huellas por identificar.' }
        : { resultado: pendientes.resultado, error: '' });
    }
    if (lista.fallo) {
      conocidas = null;
      alActualizar({ error: lista.fallo?.message || 'No se pudieron cargar las marcaciones.' });
      return;
    }
    let nueva = null;
    if (puedeDetectar() || conocidas === null) {
      ({ conocidas, nueva } = detectarNueva(conocidas, lista.filas, propias));
    }
    alActualizar({ filas: lista.filas, error: '', nueva });
  }

  function ejecutar(origen = 'solicitado') {
    if (cancelado) return;
    // Oculta, nada empieza: el regreso consulta y fija la referencia.
    if (oculto() && origen !== 'regreso') return;
    if (controlador) {
      repetir = true;
      return;
    }
    detenerEspera();
    repetir = false;
    const propio = new AbortController();
    controlador = propio;
    ciclo(propio.signal, origen).catch(() => {}).finally(() => {
      // Un ciclo descartado (regreso o cancelación) no reprograma nada.
      if (controlador !== propio) return;
      controlador = null;
      if (repetir && !cancelado && !oculto()) ejecutar('solicitado');
      else programar();
    });
  }

  function descartarEnCurso() {
    controlador?.abort();
    controlador = null;
    repetir = false;
  }

  function alCambiarVisibilidad() {
    if (cancelado) return;
    if (oculto()) {
      detenerEspera();
      return;
    }
    conocidas = null;
    descartarEnCurso();
    ejecutar('regreso');
  }

  documento?.addEventListener?.('visibilitychange', alCambiarVisibilidad);
  ejecutar('inicial');

  return {
    /** Ciclo inmediato, o uno más al terminar el que está en vuelo. */
    solicitar: () => ejecutar('solicitado'),
    /** Clave de una marcación enviada desde esta pantalla: nunca es novedad. */
    registrarPropia(clave) {
      if (clave) propias.add(clave);
    },
    cancelar() {
      cancelado = true;
      detenerEspera();
      descartarEnCurso();
      documento?.removeEventListener?.('visibilitychange', alCambiarVisibilidad);
    },
  };
}
