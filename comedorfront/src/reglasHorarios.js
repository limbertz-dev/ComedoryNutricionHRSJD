/*
 * reglasHorarios.js — lógica de la pantalla «Reglas del sistema».
 *
 * Sin JSX, para probarla con `node --test` y respuestas sintéticas. La
 * pantalla edita el horario de cada comida con efecto inmediato:
 * `POST /reglas/horarios` lleva `base_horario_id`, la versión ABIERTA que se
 * editó, y el servidor rechaza con 409 si ya no es esa. Por eso:
 *
 * - La base sale del servidor, nunca se inventa. Si el listado trae la
 *   versión abierta ('vigente'), esa es la base. Si trae otra (el reloj del
 *   sistema puede estar atrasado y devolver una versión 'anterior'), se
 *   consulta el historial de esa comida para encontrar la abierta. Si el historial falla, esa comida no se puede guardar: no se
 *   manda null solo porque la consulta falló.
 * - Un envío a la vez y sin reintentos automáticos.
 * - Ante un resultado incierto (red, tiempo agotado, 5xx) no se afirma que no
 *   se guardó: se bloquea todo guardado hasta recargar y comprobar.
 * - Tras un éxito se recarga la lista, pero un fallo de esa recarga no borra
 *   el resultado del guardado.
 */
import {
  ErrorGuardadoHorario,
  guardarHorario,
  obtenerHistorialHorario,
  obtenerHorariosVigentes,
} from './api.js';

// ------------------------------------------------------------------
// Horas y momentos (presentación)
// ------------------------------------------------------------------

/** "11:30" → "11:30:00"; "11:30:15" queda igual; algo inválido → null. */
export function normalizarHora(valor) {
  const partes = typeof valor === 'string' ? /^(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(valor) : null;
  if (!partes || Number(partes[1]) > 23 || Number(partes[2]) > 59 || Number(partes[3] ?? 0) > 59) return null;
  return `${partes[1]}:${partes[2]}:${partes[3] ?? '00'}`;
}

/** "11:30:00" → "11:30"; con segundos distintos de cero se conservan. */
export function formatoHora(valor) {
  const completa = normalizarHora(valor);
  if (completa === null) return typeof valor === 'string' ? valor : '';
  return completa.endsWith(':00') ? completa.slice(0, 5) : completa;
}

/** Valor para un <input type="time">: HH:MM, o HH:MM:SS si hay segundos. */
export const valorDeHora = formatoHora;

/** El input necesita step=1 solo si alguna hora trae segundos. */
export function horasConSegundos(...horas) {
  return horas.some((hora) => {
    const completa = normalizarHora(hora);
    return completa !== null && !completa.endsWith(':00');
  });
}

/**
 * La franja cruza la medianoche cuando termina antes de empezar (mismo
 * criterio que `cruza_medianoche` del servidor). Es una pista de pantalla: el
 * servidor decide.
 */
export function cruzaMedianoche(inicio, fin) {
  const desde = normalizarHora(inicio);
  const hasta = normalizarHora(fin);
  return desde !== null && hasta !== null && hasta < desde;
}

/**
 * "2026-10-14T08:30:15.123456" → "14/10/2026 08:30", tal como lo manda el
 * servidor: sin zona y sin conversión.
 */
export function textoMomento(texto) {
  const partes = typeof texto === 'string'
    ? /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(texto) : null;
  if (!partes) return '—';
  return `${partes[3]}/${partes[2]}/${partes[1]} ${partes[4]}:${partes[5]}`;
}

export const nombreDeComida = (comida) => comida.horario.comida ?? `Comida n.º ${comida.comidaId}`;

// ------------------------------------------------------------------
// Carga: una tarjeta por comida, con su versión abierta resuelta
// ------------------------------------------------------------------

const abierta = (horario) => horario.estado === 'vigente' && horario.vigenteHasta === null;

/**
 * Qué versión se edita. `tipo`:
 * - 'abierta': hay una; `horario` es esa (su id viaja como base).
 * - 'ninguna': el historial no tiene ninguna abierta; la base legítima es null.
 * - 'multiple': hay más de una abierta; el servidor rechazaría el guardado.
 * - 'error': no se pudo comprobar; no se guarda (no se manda null a ciegas).
 */
export async function resolverBase(listado, { historial = obtenerHistorialHorario, signal } = {}) {
  if (abierta(listado)) return { tipo: 'abierta', horario: listado };
  try {
    const versiones = await historial(listado.comidaId, { signal });
    const abiertas = versiones.filter(abierta);
    if (abiertas.length === 1) return { tipo: 'abierta', horario: abiertas[0] };
    if (abiertas.length === 0) return { tipo: 'ninguna' };
    return { tipo: 'multiple' };
  } catch (error) {
    if (signal?.aborted) throw error;
    return { tipo: 'error', mensaje: error.message };
  }
}

/**
 * GET /reglas/horarios + la base de cada comida. Una fila por comida, en el
 * orden del servidor. Lista vacía → [] (no se inventa ninguna comida).
 */
export async function cargarComidas({
  listar = obtenerHorariosVigentes,
  historial = obtenerHistorialHorario,
  signal,
} = {}) {
  const listado = await listar({ signal });
  const comidas = [];
  for (const horario of listado) {
    const base = await resolverBase(horario, { historial, signal });
    comidas.push({
      comidaId: horario.comidaId,
      horario: base.tipo === 'abierta' ? base.horario : horario,
      listado: horario,
      base,
    });
  }
  return comidas;
}

// ------------------------------------------------------------------
// Estado de la pantalla
// ------------------------------------------------------------------

export function estadoInicialReglas() {
  return {
    fase: 'cargando', // 'cargando' | 'listo' | 'error'
    comidas: null,
    error: '',
    fallaRefresco: '',
    actualizando: false,
    guardando: null, // comidaId con un envío en vuelo
    avisos: {}, // comidaId → { tipo: 'exito' | 'error' | 'incierto' | 'aviso', titulo, detalle }
    incierto: false, // hay un resultado sin comprobar: nada se guarda hasta recargar
    bloqueadas: [], // comidaIds que piden recargar antes de otro guardado
  };
}

const AVISO_TRAS_RECARGA = {
  tipo: 'aviso',
  titulo: 'Horarios recargados',
  detalle: 'Revise los valores de esta comida para saber si el cambio quedó guardado.',
};

export function reductorReglas(estado, accion) {
  switch (accion.tipo) {
    case 'CARGA_INICIO':
      return estado.comidas
        ? { ...estado, actualizando: true, fallaRefresco: '' }
        : { ...estado, fase: 'cargando', error: '', actualizando: true };
    case 'CARGA_OK': {
      /* Una recarga exitosa deja comprobar: lo incierto ya se puede revisar. */
      const avisos = Object.fromEntries(Object.entries(estado.avisos)
        .map(([id, aviso]) => [id, aviso.tipo === 'incierto' ? AVISO_TRAS_RECARGA : aviso]));
      return {
        ...estado, fase: 'listo', comidas: accion.comidas, error: '', fallaRefresco: '',
        actualizando: false, incierto: false, bloqueadas: [], avisos,
      };
    }
    case 'CARGA_ERROR':
      return estado.comidas
        ? { ...estado, fase: 'listo', actualizando: false, fallaRefresco: accion.mensaje }
        : { ...estado, fase: 'error', actualizando: false, error: accion.mensaje };
    case 'GUARDADO_INICIO': {
      const { [accion.comidaId]: _anterior, ...avisos } = estado.avisos;
      return { ...estado, guardando: accion.comidaId, avisos };
    }
    case 'GUARDADO_OK':
      return {
        ...estado,
        guardando: null,
        avisos: { ...estado.avisos, [accion.comidaId]: { tipo: 'exito', titulo: accion.titulo, detalle: accion.detalle } },
        /* La base de esta tarjeta ya quedó cerrada: pide recargar para seguir. */
        bloqueadas: [...new Set([...estado.bloqueadas, accion.comidaId])],
      };
    case 'GUARDADO_FALLO':
      return {
        ...estado,
        guardando: null,
        avisos: {
          ...estado.avisos,
          [accion.comidaId]: { tipo: accion.incierto ? 'incierto' : 'error', titulo: accion.titulo, detalle: accion.detalle },
        },
        incierto: estado.incierto || accion.incierto === true,
        bloqueadas: accion.recargar ? [...new Set([...estado.bloqueadas, accion.comidaId])] : estado.bloqueadas,
      };
    case 'AVISO_CERRADO': {
      const { [accion.comidaId]: _cerrado, ...avisos } = estado.avisos;
      return { ...estado, avisos };
    }
    default:
      return estado;
  }
}

/**
 * Por qué una tarjeta no puede guardar ahora, o null si puede. El orden
 * importa: es el motivo que se le explica a la persona.
 */
export function motivoSinGuardar(estado, comida, borrador) {
  if (estado.guardando !== null) {
    return estado.guardando === comida.comidaId ? 'guardando' : 'otro-envio';
  }
  if (estado.actualizando) return 'actualizando';
  if (estado.incierto) return 'incierto';
  if (estado.bloqueadas.includes(comida.comidaId)) return 'recargar';
  if (comida.base.tipo === 'error') return 'sin-base';
  if (comida.base.tipo === 'multiple') return 'multiple';
  const inicio = normalizarHora(borrador.inicio);
  const fin = normalizarHora(borrador.fin);
  if (inicio === null || fin === null) return 'incompleto';
  if (inicio === fin) return 'iguales';
  if (inicio === normalizarHora(comida.horario.horaInicio) && fin === normalizarHora(comida.horario.horaFin)) {
    return 'sin-cambios';
  }
  return null;
}

// ------------------------------------------------------------------
// Acciones: guardar y recargar
// ------------------------------------------------------------------

/** Recarga la lista. No lanza: el resultado llega como acciones del reductor. */
export async function recargarComidas({ despachar, cargar = cargarComidas, signal } = {}) {
  despachar({ tipo: 'CARGA_INICIO' });
  try {
    const comidas = await cargar({ signal });
    if (signal?.aborted) return false;
    despachar({ tipo: 'CARGA_OK', comidas });
    return true;
  } catch (error) {
    if (signal?.aborted) return false;
    despachar({ tipo: 'CARGA_ERROR', mensaje: error.message });
    return false;
  }
}

/** Envía el borrador de una tarjeta. Devuelve el resultado, sin lanzar. */
export async function ejecutarGuardado({ comida, borrador, guardar = guardarHorario }) {
  const { base } = comida;
  if (base.tipo === 'error' || base.tipo === 'multiple') {
    return { tipo: 'sin-base', mensaje: 'No se sabe qué versión del horario se está editando.' };
  }
  try {
    const creado = await guardar({
      comidaId: comida.comidaId,
      horaInicio: borrador.inicio,
      horaFin: borrador.fin,
      baseHorarioId: base.tipo === 'abierta' ? base.horario.horarioId : null,
    });
    return { tipo: 'ok', creado };
  } catch (error) {
    if (error instanceof ErrorGuardadoHorario) {
      return {
        tipo: error.incierto ? 'incierto' : 'rechazado',
        mensaje: error.message,
        motivo: error.motivo,
        recargar: error.recargar,
      };
    }
    return {
      tipo: 'incierto',
      mensaje: `${error.message} No sabemos si el cambio se guardó. Recargue los horarios y compruebe cómo quedaron antes de volver a guardar.`,
      motivo: null,
      recargar: true,
    };
  }
}

const textoFranja = (horario) => `${formatoHora(horario.horaInicio)} a ${formatoHora(horario.horaFin)}`;

/**
 * Guardar una comida de punta a punta: un envío a la vez (`candado`), sin
 * reintentos, y recarga después de un éxito sin que su fallo tape el
 * resultado. Devuelve el tipo de resultado, para quien quiera reaccionar.
 */
export async function guardarComida({
  comida,
  borrador,
  despachar,
  recargar,
  candado,
  guardar = guardarHorario,
}) {
  if (candado.ocupado) return 'ocupado';
  candado.ocupado = true;
  const nombre = nombreDeComida(comida);
  despachar({ tipo: 'GUARDADO_INICIO', comidaId: comida.comidaId });
  try {
    const resultado = await ejecutarGuardado({ comida, borrador, guardar });
    if (resultado.tipo === 'ok') {
      const { creado } = resultado;
      despachar({
        tipo: 'GUARDADO_OK',
        comidaId: comida.comidaId,
        titulo: `${nombre}: horario guardado`,
        detalle: `Ahora rige de ${textoFranja(creado)}`
          + `${creado.cruzaMedianoche ? ' (termina al día siguiente)' : ''}`
          + ` desde el ${textoMomento(creado.vigenteDesde)}.`,
      });
    } else {
      despachar({
        tipo: 'GUARDADO_FALLO',
        comidaId: comida.comidaId,
        incierto: resultado.tipo === 'incierto',
        recargar: resultado.recargar === true,
        titulo: resultado.tipo === 'incierto'
          ? `${nombre}: resultado incierto`
          : `${nombre}: no se guardó`,
        detalle: resultado.mensaje,
      });
    }
    if (resultado.tipo === 'ok') await recargar();
    return resultado.tipo;
  } finally {
    candado.ocupado = false;
  }
}
