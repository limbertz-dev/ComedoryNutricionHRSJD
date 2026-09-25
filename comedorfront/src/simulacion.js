/*
 * simulacion.js — de dónde sale el reloj de simulación y cómo se muestra.
 *
 * Sin JSX, para probarlo con `node --test`. El reloj llega siempre del
 * servidor (GET /salud o /simulacion/reloj, ver api.js): acá solo se decide
 * a cuál preguntar y se le da forma para mostrarlo. Fuera de simulación el
 * reloj es null y nada de esto se monta.
 */
import { obtenerReloj, obtenerSalud } from './api.js';

/**
 * Una vuelta de consulta del reloj. Primero /salud dice si la API corre en
 * simulación; si no, termina ahí y nunca toca /simulacion/*, que fuera de
 * simulación ni existe. En simulación, quien puede mover el reloj
 * (`operaReloj`) lo lee de GET /simulacion/reloj, que además dice si está
 * congelado; si esa lectura falla, queda la hora de /salud. Con
 * `yaEnSimulacion` (vueltas siguientes) se salta /salud: el entorno no
 * cambia en caliente.
 *
 * @returns {Promise<{ simulacion: boolean, reloj: object | null }>}
 */
export async function consultarSimulacion({ operaReloj = false, yaEnSimulacion = false, signal } = {}) {
  if (yaEnSimulacion && operaReloj) {
    return { simulacion: true, reloj: await obtenerReloj({ signal }) };
  }
  const salud = await obtenerSalud({ signal });
  if (!salud.simulacion) return { simulacion: false, reloj: null };
  if (!operaReloj) return { simulacion: true, reloj: salud.reloj };
  try {
    return { simulacion: true, reloj: await obtenerReloj({ signal }) };
  } catch (error) {
    if (signal?.aborted) throw error;
    return { simulacion: true, reloj: salud.reloj };
  }
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
