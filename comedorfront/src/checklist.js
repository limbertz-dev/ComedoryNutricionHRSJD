/*
 * checklist.js — lógica del checklist de cocina, sin JSX para probarla con
 * `node --test`.
 *
 * Quién aparece en la lista lo decide el servidor (turno de 12 h o más,
 * categorías permitidas, sin novedad): aquí solo se filtra lo que llegó y se
 * calcula cuánto queda para deshacer una marca.
 */
import { fechaHoraDelServidor } from './api.js';

export const FILTROS_CHECKLIST = [
  ['pendientes', 'Pendientes'],
  ['entregadas', 'Entregadas'],
  ['todas', 'Todas'],
];

/** Pausa entre consultas: así llegan las marcas de otra cocinera o del lector. */
export const MS_CICLO_CHECKLIST = 15000;

const ETIQUETAS_METODO = {
  checklist: 'Checklist',
  biometrico: 'Huella',
  manual: 'Jefatura',
};

export function etiquetaDeMetodo(metodo) {
  return ETIQUETAS_METODO[metodo] ?? 'Registrada';
}

function normalizar(texto) {
  return String(texto ?? '')
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .trim();
}

export function contarChecklist(personas = []) {
  const entregadas = personas.filter((p) => p.servida).length;
  return { total: personas.length, entregadas, pendientes: personas.length - entregadas };
}

/** Servicios presentes en la lista, ordenados, para el filtro. */
export function serviciosDeChecklist(personas = []) {
  return [...new Set(personas.map((p) => p.servicio).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, 'es'));
}

/** Personas que pasan los filtros; pendientes primero en «Todas». */
export function filtrarChecklist(personas = [], { estado = 'pendientes', busqueda = '', servicio = 'todos' } = {}) {
  const termino = normalizar(busqueda);
  const filtradas = personas.filter((p) => {
    if (estado === 'pendientes' && p.servida) return false;
    if (estado === 'entregadas' && !p.servida) return false;
    if (servicio !== 'todos' && p.servicio !== servicio) return false;
    if (termino && !normalizar(p.nombre).includes(termino)) return false;
    return true;
  });
  if (estado !== 'todas') return filtradas;
  return [...filtradas.filter((p) => !p.servida), ...filtradas.filter((p) => p.servida)];
}

/**
 * Desfase entre el reloj del servidor y el de esta PC, en ms. El plazo para
 * deshacer se cuenta con la hora del servidor (en QA puede ser otra fecha).
 */
export function desfaseConServidor(momentoServidor, recibidoEn = Date.now()) {
  const servidor = fechaHoraDelServidor(momentoServidor);
  return servidor ? recibidoEn - servidor.getTime() : 0;
}

/** Segundos que quedan para deshacer; 0 si ya venció o no se puede. */
export function segundosParaDeshacer(anulableHasta, desfase, ahora = Date.now()) {
  const limite = fechaHoraDelServidor(anulableHasta);
  if (!limite) return 0;
  return Math.max(0, Math.ceil((limite.getTime() - (ahora - desfase)) / 1000));
}

export function formatoCuentaRegresiva(segundos) {
  const m = Math.floor(segundos / 60);
  const s = segundos % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

/** "12:31" de un datetime del servidor. */
export function horaDeEntrega(fechaHora) {
  const momento = fechaHoraDelServidor(fechaHora);
  if (!momento) return '';
  return `${String(momento.getHours()).padStart(2, '0')}:${String(momento.getMinutes()).padStart(2, '0')}`;
}

/** Texto del aviso tras marcar, según la respuesta del servidor. */
export function avisoDeMarca(respuesta, nombre) {
  if (respuesta?.valido) return { tipo: 'exito', texto: `Ración entregada a ${nombre}.` };
  const motivos = {
    duplicado: `${nombre} ya recibió esta comida.`,
    sin_derecho: `${nombre} no tiene derecho a esta comida con su turno.`,
    fuera_horario: 'La comida ya cerró: no se pueden registrar más raciones.',
  };
  return { tipo: 'error', texto: motivos[respuesta?.motivo] ?? respuesta?.detalle ?? 'No se registró la ración.' };
}
