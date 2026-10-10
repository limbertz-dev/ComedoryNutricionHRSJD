/*
 * simulacion.js — de dónde sale el reloj de simulación y cómo se muestra.
 *
 * Sin JSX, para probarlo con `node --test`. El reloj llega siempre del
 * servidor (GET /salud o /simulacion/reloj, ver api.js): acá solo se decide
 * a cuál preguntar y se le da forma para mostrarlo. Fuera de simulación el
 * reloj es null y nada de esto se monta. Aparte, si el simulador del lector
 * puede habilitarse lo decide solo una confirmación vigente de /salud.
 */
import { confirmarEntornoSalud, obtenerReloj } from './api.js';
import { datoVigente, medirAhora, programarRefrescoMonitoreo } from './monitoreo.js';

/** Pausa entre el fin de una confirmación del entorno y la siguiente. */
export const MS_REVALIDAR_SIMULACION = 30000;

/**
 * Una vuelta de consulta del reloj. Cada vuelta pregunta a /salud si la API
 * corre en simulación; si no, termina ahí y nunca toca /simulacion/*, que
 * fuera de simulación ni existe. En simulación, quien puede mover el reloj
 * (`operaReloj`) lo lee además de GET /simulacion/reloj, que dice si está
 * congelado; si esa lectura falla, queda la hora de /salud.
 *
 * `confirmada` es true solo si /salud respondió 200 con entorno
 * 'simulacion': un 503 deja ver el reloj, pero no confirma el entorno.
 *
 * @returns {Promise<{ simulacion: boolean, confirmada: boolean, reloj: object | null }>}
 */
export async function consultarSimulacion({ operaReloj = false, signal } = {}) {
  const salud = await confirmarEntornoSalud({ signal });
  if (!salud.simulacion) return { simulacion: false, confirmada: false, reloj: null };
  const confirmada = salud.confirmaSimulacion;
  if (!operaReloj) return { simulacion: true, confirmada, reloj: salud.reloj };
  try {
    return { simulacion: true, confirmada, reloj: await obtenerReloj({ signal }) };
  } catch (error) {
    if (signal?.aborted) throw error;
    return { simulacion: true, confirmada, reloj: salud.reloj };
  }
}

/**
 * Vigila el entorno para el simulador del lector. El simulador solo se
 * habilita con una confirmación de /salud (200, entorno 'simulacion')
 * recibida hace no más de 90 s según los dos relojes de este equipo
 * (`datoVigente`): ni el reloj mostrado ni el rol cuentan como permiso.
 *
 * - Las consultas no se solapan: la siguiente sale 30 s después de que
 *   termina la anterior (`programarRefrescoMonitoreo`).
 * - Un fallo, un 503, una respuesta inválida o un entorno distinto retiran
 *   la confirmación; el último reloj se conserva solo para mostrarlo.
 * - Con la pestaña oculta no se consulta; al volver, la confirmación se
 *   retira de inmediato y se pide otra.
 *
 * `alCambiar` avisa cada vez que cambian el reloj o la confirmación.
 */
export function vigilarSimulacion({
  operaReloj = false,
  alCambiar = () => {},
  consultar = consultarSimulacion,
  medir = medirAhora,
  documento,
  temporizador,
} = {}) {
  let reloj = null;
  let recepcion = null;

  const refresco = programarRefrescoMonitoreo({
    intervaloMs: MS_REVALIDAR_SIMULACION,
    documento,
    temporizador,
    consultar: async ({ signal }) => {
      try {
        const resultado = await consultar({ operaReloj, signal });
        if (signal.aborted) return;
        reloj = resultado.reloj;
        recepcion = resultado.confirmada === true ? medir() : null;
      } catch {
        if (signal.aborted) return;
        // Sin respuesta válida no hay confirmación; el reloj queda para mostrarlo.
        recepcion = null;
      }
      alCambiar();
    },
    alVolver: () => {
      recepcion = null;
      alCambiar();
    },
  });

  return {
    reloj: () => reloj,
    vigente: (ahora = medir()) => datoVigente(recepcion, ahora),
    cancelar: refresco.cancelar,
  };
}

/**
 * Envuelve una acción del simulador: si `permitido()` es false en el momento
 * de usarla (confirmación vencida, retirada o rechazo del servidor), no hace
 * nada. Así un botón que quedó a la vista nunca llega a la API.
 */
export function protegerAccionSimulador(permitido, accion) {
  return (...argumentos) => (permitido() ? accion(...argumentos) : undefined);
}

const FORMATO_RELOJ = new Intl.DateTimeFormat('es-BO', {
  weekday: 'short',
  day: '2-digit',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

/** "lun., 10 ago., 12:05": la hora que ve el sistema, legible. */
export function textoDelReloj(reloj) {
  return FORMATO_RELOJ.format(reloj.ahora);
}

/** Si el reloj sigue a la hora real, corre desde una hora fijada o está quieto. */
export function estadoDelReloj(reloj) {
  if (!reloj.simulado) return 'Hora real';
  return reloj.congelado ? 'Congelado' : 'Simulado';
}

/**
 * Día del servidor ("2026-08-10") para usar como `key`: Historial y Reportes
 * arman su "hoy" al montarse, así que cuando el reloj cambia de día se
 * vuelven a montar con el día nuevo. Fuera de simulación la clave no cambia
 * nunca y esas secciones se comportan como siempre.
 */
export function claveDelDia(reloj) {
  if (!reloj) return 'real';
  const dos = (numero) => String(numero).padStart(2, '0');
  const { ahora } = reloj;
  return `${ahora.getFullYear()}-${dos(ahora.getMonth() + 1)}-${dos(ahora.getDate())}`;
}
