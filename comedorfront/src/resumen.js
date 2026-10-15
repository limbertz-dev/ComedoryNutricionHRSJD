/*
 * resumen.js — a qué período corresponde cada cifra del Resumen.
 *
 * Sin JSX, para probarlo con `node --test`. Todas las cifras salen de
 * `GET /pantalla/estado` tal cual; aquí solo se decide cómo rotularlas. Son
 * tres conteos distintos y no se suman entre sí:
 *
 *  - Turno actual (`cupo`): raciones de la comida en curso, contra las
 *    previstas por derecho.
 *  - Raciones del día (`totales_del_dia.raciones_servidas` y `por_categoria`):
 *    todas las comidas de la fecha de comida, de cualquier método.
 *  - Lecturas del lector (`aceptadas`, `rechazadas`, `lecturas`): toques de
 *    dedo del día del reloj. No son raciones: las manuales no pasan por el
 *    lector, y el día del reloj puede no ser la fecha de comida.
 *
 * Lo que no hay en el endpoint (comparaciones con otros días, ritmo por hora,
 * cobertura del día completo) no se aproxima desde el front: ver README,
 * «Resumen: métricas propuestas».
 */
import { diaLegible } from './dias.js';

/** Hora "HH:MM" de un `momento` del servidor ("2026-09-28T12:05:00"); '' si no la trae. */
export function horaDelEstado(momento) {
  const coincidencia = typeof momento === 'string' ? /T(\d{2}:\d{2})/.exec(momento) : null;
  return coincidencia ? coincidencia[1] : '';
}

/** Rótulo de período de cada bloque del Resumen. */
export function periodosDeResumen(pantalla) {
  const diaComida = diaLegible(pantalla?.fecha_comida);
  const diaReloj = diaLegible(pantalla?.momento);
  const hora = horaDelEstado(pantalla?.momento);
  return {
    turno: diaComida ? `Solo esta comida · ${diaComida}` : 'Solo esta comida',
    raciones: diaComida ? `Todas las comidas · ${diaComida}` : 'Todas las comidas del día',
    lecturas: diaReloj ? `Día del reloj · ${diaReloj}` : 'Día del reloj',
    corte: hora ? `Datos de las ${hora}` : 'Datos del servidor',
  };
}

/**
 * El cupo tal como se dibuja. `previstas` nulo significa que no hay cupo
 * cargado para esa comida: no hay límite, y no se inventa un porcentaje.
 * `supera` avisa cuando ya se sirvió más de lo previsto.
 */
export function cupoLegible(cupo) {
  if (!cupo) return null;
  const sinLimite = !Number.isInteger(cupo.previstas);
  return {
    servidas: cupo.servidas,
    previstas: sinLimite ? null : cupo.previstas,
    restantes: sinLimite || !Number.isInteger(cupo.restantes) ? null : cupo.restantes,
    porcentaje: sinLimite || !Number.isFinite(cupo.porcentaje) ? null : cupo.porcentaje,
    supera: !sinLimite && cupo.servidas > cupo.previstas,
  };
}

/** Ancho del medidor (0–100): solo geométrico, el texto muestra el porcentaje real. */
export function anchoDeMedidor(porcentaje) {
  return Number.isFinite(porcentaje) ? Math.min(100, Math.max(0, porcentaje)) : 0;
}
