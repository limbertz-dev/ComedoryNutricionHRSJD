/*
 * dias.js — cómo se escribe un día en las pantallas de jefatura.
 *
 * Sin JSX, para probarlo con `node --test`. Las fechas de la API llegan como
 * "2026-09-28" o como fecha y hora sin zona ("2026-09-28T12:05:00"); se leen
 * con el calendario local para no mover el día por la zona horaria.
 */

const FORMATO_DIA_LARGO = new Intl.DateTimeFormat('es-BO', {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
  year: 'numeric',
});

/** "lunes 28 de septiembre de 2026"; '' si el texto no empieza con una fecha. */
export function diaLegible(valor) {
  const coincidencia = typeof valor === 'string' ? /^(\d{4})-(\d{2})-(\d{2})/.exec(valor) : null;
  if (!coincidencia) return '';
  const [, gestion, mes, dia] = coincidencia.map(Number);
  const fecha = new Date(gestion, mes - 1, dia, 12);
  /* 2026-02-31 no existe: JS lo corre a marzo, y aquí se prefiere no mostrarlo. */
  if (fecha.getMonth() !== mes - 1) return '';
  return FORMATO_DIA_LARGO.format(fecha);
}
