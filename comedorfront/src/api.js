/*
 * api.js — cliente HTTP y adaptadores de datos para FastAPI.
 *
 * Padrón, marcación, estado, historiales, reportes y períodos consultan
 * FastAPI con fetch nativo. App espera las promesas y presenta los errores
 * de transporte.
 *
 * Este archivo centraliza las llamadas a la API y adapta las respuestas
 * (snake_case del backend) a los formatos y props consumidos por la UI.
 * Ningún componente hace peticiones directamente.
 */

import { API_BASE_URL } from './config.js';
import { avisarSesion, borrarTokens, guardarTokens, leerTokens } from './sesion.js';

/**
 * Estado autoritativo: el cupo previsto sale siempre del conteo real de
 * comensales con turno asignado, nunca de un límite cargado a mano.
 *
 * `fecha` es opcional (Date o "YYYY-MM-DD"): sin ella el estado es el de hoy;
 * con ella se consulta ese día con la hora actual del reloj, igual que hace
 * el historial diario con su fecha. Solo la usa Control Biométrico para
 * consultar otros días; la marcación siempre opera sobre el turno vigente.
 */
export async function obtenerEstadoPantalla({ fecha, signal } = {}) {
  try {
    const estado = await solicitarApi(
      `/pantalla/estado${fecha === undefined ? '' : `?fecha=${formatearFechaEstado(fecha)}`}`,
      { signal },
    );
    if (typeof estado?.fuera_de_horario !== 'boolean' || !Array.isArray(estado.por_categoria)
      || !estado.totales_del_dia || (!estado.fuera_de_horario && !estado.cupo)) {
      throw new Error('La API devolvió un estado de pantalla inválido.');
    }
    return estado;
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(`No se pudo actualizar el estado del comedor. ${error.message}`);
  }
}

/** Fecha del estado en formato API, siempre local para no mover el día. */
function formatearFechaEstado(fecha) {
  if (fecha instanceof Date) return fechaArchivo(fecha);
  if (typeof fecha === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(fecha)) return fecha;
  throw new Error('Fecha inválida para consultar el estado.');
}

/** Motivos de rechazo del lector, con el texto que se lee en la tarjeta. */
const MOTIVOS_LEGIBLES = {
  duplicado: 'Ya recibió su comida',
  sin_derecho: 'Sin derecho en este turno',
  fuera_horario: 'Fuera de horario',
  /* El motivo guardado de una huella sin usuario (antes llegaba sin texto). */
  no_identificado: 'Huella no reconocida',
  desconocida: 'Huella no reconocida',
};

function horaDeMarcacion(fechaHora) {
  const momento = new Date(fechaHora);
  return Number.isNaN(momento.getTime()) ? '--:--:--' : horaLegible(momento);
}

/** Orígenes de una fila de GET /pantalla/ultimas-marcaciones. */
export const ORIGENES_MARCACION = ['lectura_biometrica', 'asistencia_manual', 'racion_policia'];

/**
 * Identidad de un evento persistido: "<origen>:<id>". El `id` numérico solo
 * es único dentro de su tabla (una lectura y una asistencia manual pueden
 * compartirlo), así que filas, selección y deduplicación usan esta clave.
 */
export function claveDeEvento(origen, id) {
  return `${origen}:${id}`;
}

/** Por dónde terminó en ración una fila (`resultado_final.via`). */
export const VIAS_RESULTADO_FINAL = ['lector', 'identificacion_manual', 'registro_manual', 'policia', 'identificacion_policia'];
const VIAS_POLICIA = ['policia', 'identificacion_policia'];
const ESTADOS_FINALES = ['racion_servida', 'sin_racion'];

/** Texto o null: la API manda null en lo que no aplica. */
const textoONull = (valor) => (typeof valor === 'string' && valor.length > 0 ? valor : null);

/*
 * Bloques de intervenciones de cocina en una marcación (contrato de
 * comedorback/app/esquemas/pantalla.py). Son aditivos: una API sin ellos
 * deja los valores por omisión y la fila se ve como siempre.
 *
 * - `decisionOriginal`: lo que decidió el lector. Inmutable.
 * - `estadoFinal` / `resultadoFinal`: si la fila terminó en una ración y por
 *   qué vía, aparte de `valido` (que sigue siendo la decisión del lector).
 * - `intervencion`: lo que el ROL ve de los intentos. La cocinera recibe
 *   revision/resuelta/resueltaPorMi; la jefa además registradaPor e
 *   intentosRechazados; sistemas, null. `revision` solo crece.
 */
function adaptarBloquesIntervencion(dato) {
  const decision = dato.decision_original;
  if (decision != null && (typeof decision !== 'object' || typeof decision.resultado !== 'string')) {
    throw new Error('La API devolvió una decisión original inválida.');
  }
  const estadoFinal = dato.estado_final ?? 'sin_racion';
  if (!ESTADOS_FINALES.includes(estadoFinal)) {
    throw new Error('La API devolvió un estado final inválido.');
  }
  const final = dato.resultado_final;
  // Una ración de policía no tiene asistencia: va a raciones_policia.
  if (final != null && (!VIAS_RESULTADO_FINAL.includes(final.via)
    || (VIAS_POLICIA.includes(final.via) ? final.asistencia_id != null : !Number.isInteger(final.asistencia_id)))) {
    throw new Error('La API devolvió un resultado final inválido.');
  }
  if ((final != null) !== (estadoFinal === 'racion_servida')) {
    throw new Error('La API devolvió un resultado final que no coincide con su estado.');
  }
  const bloque = dato.intervencion;
  if (bloque != null && (!Number.isInteger(bloque.revision) || bloque.revision < 0
    || typeof bloque.resuelta !== 'boolean' || typeof bloque.resuelta_por_mi !== 'boolean')) {
    throw new Error('La API devolvió una intervención inválida.');
  }
  return {
    comidaOrigen: dato.comida_origen ?? null,
    decisionOriginal: decision == null ? null : {
      resultado: decision.resultado,
      motivo: decision.motivo ?? null,
      fechaHora: decision.fecha_hora ?? null,
      dispositivo: decision.dispositivo ?? null,
    },
    estadoFinal,
    resultadoFinal: final == null ? null : {
      via: final.via,
      asistenciaId: final.asistencia_id,
      comensal: {
        usuarioId: final.comensal?.usuario_id ?? null,
        nombre: textoONull(final.comensal?.nombre),
      },
      comida: final.comida ?? null,
      fechaComida: final.fecha_comida ?? null,
      momento: final.momento ?? null,
    },
    puedeIdentificar: dato.puede_identificar === true,
    motivoNoIdentificable: dato.motivo_no_identificable ?? null,
    identificableHasta: dato.identificable_hasta ?? null,
    intervencion: bloque == null ? null : {
      revision: bloque.revision,
      actualizadoEn: bloque.actualizado_en ?? null,
      resuelta: bloque.resuelta,
      resueltaPorMi: bloque.resuelta_por_mi,
      /* Solo los recibe la jefa; para la cocinera quedan en null. */
      registradaPor: bloque.registrada_por
        ? {
          cuentaId: bloque.registrada_por.cuenta_id ?? null,
          usuario: textoONull(bloque.registrada_por.usuario),
          nombre: textoONull(bloque.registrada_por.nombre),
        }
        : null,
      intentosRechazados: Number.isInteger(bloque.intentos_rechazados) ? bloque.intentos_rechazados : null,
    },
  };
}

/**
 * Una fila de marcación del servidor, con la forma de la tarjeta de
 * marcaciones (`persona`, `hora`, `valido`, `titulo`) más los bloques de
 * intervención. La usan `ultimas-marcaciones` y `lecturas-por-identificar`,
 * que comparten forma.
 */
function adaptarMarcacion(dato) {
  if (!Number.isInteger(dato?.id)) {
    throw new Error('La API devolvió una marcación sin identificador.');
  }
  if (!ORIGENES_MARCACION.includes(dato.origen)
    || dato.clave_evento !== claveDeEvento(dato.origen, dato.id)) {
    throw new Error('La API devolvió una marcación sin origen válido.');
  }
  const valido = typeof dato.valido === 'boolean' ? dato.valido : dato.resultado === 'aceptada';
  return {
    id: dato.id,
    origen: dato.origen,
    clave: dato.clave_evento,
    usuarioId: dato.usuario_id ?? null,
    valido,
    titulo: valido ? 'Marcación válida'
      : MOTIVOS_LEGIBLES[dato.motivo] ?? (dato.motivo || 'Marcación rechazada'),
    motivo: dato.motivo ?? null,
    dispositivo: dato.dispositivo ?? null,
    hora: horaDeMarcacion(dato.fecha_hora),
    fechaHora: dato.fecha_hora ?? null,
    // Sin comida: el lector no llegó a resolver ningún turno para esa hora
    // (fuera de horario) o la lectura es de una huella no reconocida.
    comidaId: dato.comida_id ?? null,
    comida: dato.comida ?? null,
    persona: {
      id: dato.usuario_id ?? null,
      nombre: dato.nombre || 'Desconocido',
      categoria: dato.categoria || 'Sin clasificar',
    },
    ...adaptarBloquesIntervencion(dato),
  };
}

/** Adapta una lista de marcaciones; dos filas con la misma clave la vuelven inconsistente. */
function adaptarListaMarcaciones(marcaciones) {
  if (!Array.isArray(marcaciones)) {
    throw new Error('La API devolvió una lista de marcaciones inválida.');
  }
  const claves = new Set();
  return marcaciones.map((dato) => {
    const fila = adaptarMarcacion(dato);
    if (claves.has(fila.clave)) {
      throw new Error('La API devolvió marcaciones con la misma clave de evento: la lista es inconsistente.');
    }
    claves.add(fila.clave);
    return fila;
  });
}

/**
 * GET /pantalla/ultimas-marcaciones: el hilo real del lector, ya persistido.
 *
 * Incluye los rechazos, porque son justo lo que hay que ver frente al lector.
 * Sin `fecha` devuelve el día de hoy. La respuesta se adapta a la misma forma
 * que ya usa la tarjeta de marcaciones (`persona`, `hora`, `valido`, `titulo`),
 * para que la lista del servidor y la marcación recién enviada se pinten con
 * el mismo componente.
 *
 * Cada fila trae `origen` ('lectura_biometrica' | 'asistencia_manual') y
 * `clave_evento` ("<origen>:<id>"), que se validan y se exponen como
 * `origen` y `clave`. Es una ventana de los registros más recientes (hasta
 * `limite`), no un cursor: entre dos consultas pueden quedar eventos fuera.
 * Dos filas con la misma `clave_evento` vuelven inconsistente la respuesta:
 * se rechaza entera, sin elegir una fila ni inventar otra clave.
 *
 * Por eso NO sirve para seguir lo que cocina puede identificar: una lectura
 * de las 23:58 sigue en el servicio a las 00:30 pero ya es de «ayer». Eso es
 * `obtenerLecturasPorIdentificar`.
 */
export async function obtenerUltimasMarcaciones({ fecha, comidaId, limite = 20, signal } = {}) {
  try {
    const parametros = new URLSearchParams({ limite: String(limite) });
    if (fecha !== undefined && fecha !== null) parametros.set('fecha', formatearFechaEstado(fecha));
    if (comidaId !== undefined && comidaId !== null) parametros.set('comida_id', String(comidaId));
    return adaptarListaMarcaciones(
      await solicitarApi(`/pantalla/ultimas-marcaciones?${parametros}`, { signal }),
    );
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(`No se pudieron cargar las últimas marcaciones. ${error.message}`, { cause: error });
  }
}

/**
 * GET /pantalla/lecturas-por-identificar (solo cocinera): las huellas no
 * reconocidas que se pueden identificar AHORA, en el servicio actual, de ayer
 * o de hoy si el servicio cruza la medianoche. No depende de la fecha ni de
 * las 100 filas de `ultimas-marcaciones`.
 *
 * Devuelve `{ servicio, total, truncado, lecturas }`. `servicio` es null si no
 * hay un servicio determinable (la lista va vacía). Una lectura que sale de la
 * lista dejó de ser identificable: la resolvió alguien o terminó el servicio.
 */
export async function obtenerLecturasPorIdentificar({ signal } = {}) {
  try {
    const dato = await solicitarApi('/pantalla/lecturas-por-identificar', { signal });
    const servicio = dato?.servicio;
    if (!dato || typeof dato !== 'object' || !Number.isInteger(dato.total) || dato.total < 0
      || typeof dato.truncado !== 'boolean' || !Array.isArray(dato.lecturas)
      || (servicio != null && (!Number.isInteger(servicio.comida_id) || typeof servicio.comida !== 'string'
        || typeof servicio.fecha_comida !== 'string' || typeof servicio.inicio !== 'string'
        || typeof servicio.fin !== 'string'))
      || (servicio == null && dato.lecturas.length > 0)) {
      throw new Error('La API devolvió lecturas por identificar inválidas.');
    }
    const lecturas = adaptarListaMarcaciones(dato.lecturas);
    if (lecturas.some((fila) => fila.origen !== 'lectura_biometrica' || !fila.puedeIdentificar)) {
      throw new Error('La API devolvió una lectura que no se puede identificar.');
    }
    return {
      servicio: servicio == null ? null : {
        comidaId: servicio.comida_id,
        comida: servicio.comida,
        fechaComida: servicio.fecha_comida,
        inicio: servicio.inicio,
        fin: servicio.fin,
      },
      total: dato.total,
      truncado: dato.truncado,
      lecturas,
    };
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(`No se pudieron cargar las huellas por identificar. ${error.message}`, { cause: error });
  }
}
/** Estados de una comida del día según GET /pantalla/comidas-del-dia. */
const ESTADOS_COMIDA_DEL_DIA = ['pendiente', 'en_curso', 'cerrada'];

/**
 * GET /pantalla/comidas-del-dia: las comidas del día con su estado, servidas
 * y rechazos por motivo. Sin `fecha` el servidor usa su hoy; con ella se
 * consulta ese día. No acepta hora: el estado lo decide el backend.
 */
export async function obtenerComidasDelDia({ fecha, signal } = {}) {
  try {
    const ruta = fecha === undefined || fecha === null
      ? '/pantalla/comidas-del-dia'
      : `/pantalla/comidas-del-dia?fecha=${formatearFechaEstado(fecha)}`;
    return adaptarComidasDelDia(await solicitarApi(ruta, { signal }));
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(`No se pudieron cargar las comidas del día. ${error.message}`);
  }
}

function adaptarComidasDelDia(dato) {
  if (!dato || typeof dato !== 'object' || typeof dato.fecha !== 'string' || !Array.isArray(dato.comidas)
    || !Number.isInteger(dato.rechazos_sin_comida) || dato.rechazos_sin_comida < 0) {
    throw new Error('La API devolvió comidas del día inválidas.');
  }
  return {
    fecha: dato.fecha,
    comidas: dato.comidas.map((comida) => {
      const rechazos = comida?.rechazos_por_motivo;
      if (!Number.isInteger(comida?.comida_id) || typeof comida.comida !== 'string' || comida.comida.length === 0
        || !ESTADOS_COMIDA_DEL_DIA.includes(comida.estado)
        || (comida.hora_inicio != null && typeof comida.hora_inicio !== 'string')
        || (comida.hora_fin != null && typeof comida.hora_fin !== 'string')
        || (comida.previstas !== null && (!Number.isInteger(comida.previstas) || comida.previstas < 0))
        || !Number.isInteger(comida.servidas) || comida.servidas < 0
        || !Number.isInteger(comida.manuales) || comida.manuales < 0
        || !Number.isInteger(rechazos?.no_identificado) || rechazos.no_identificado < 0
        || !Number.isInteger(rechazos?.sin_derecho) || rechazos.sin_derecho < 0
        || !Number.isInteger(rechazos?.duplicado) || rechazos.duplicado < 0) {
        throw new Error('La API devolvió una comida del día inválida.');
      }
      return {
        comidaId: comida.comida_id,
        comida: comida.comida,
        horaInicio: comida.hora_inicio ?? null,
        horaFin: comida.hora_fin ?? null,
        estado: comida.estado,
        previstas: comida.previstas,
        servidas: comida.servidas,
        manuales: comida.manuales,
        // Raciones de policía de la comida, aparte de las servidas al personal.
        policias: Number.isInteger(comida.policias) && comida.policias > 0 ? comida.policias : 0,
        rechazos: {
          noIdentificado: rechazos.no_identificado,
          sinDerecho: rechazos.sin_derecho,
          duplicado: rechazos.duplicado,
        },
      };
    }),
    rechazosSinComida: dato.rechazos_sin_comida,
  };
}

/** Una sola consulta devuelve años y meses; las selecciones siguientes son locales. */
export async function obtenerPeriodos({ signal } = {}) {
  try {
    const periodos = await solicitarApi('/reportes/periodos', { signal });
    if (!Array.isArray(periodos) || periodos.some((periodo) => !Number.isInteger(periodo.gestion)
      || !Array.isArray(periodo.meses) || periodo.meses.length !== 12
      || new Set(periodo.meses.map((mes) => mes.mes)).size !== 12
      || periodo.meses.some((mes) => !Number.isInteger(mes.mes) || mes.mes < 1 || mes.mes > 12
        || typeof mes.cerrado !== 'boolean' || !Number.isInteger(mes.raciones) || mes.raciones < 0))) {
      throw new Error('La API devolvió períodos inválidos.');
    }
    return periodos;
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(`No se pudieron cargar los períodos. ${error.message}`);
  }
}

/** Perfiles permitidos para enrolar, con su servicio vigente. Solo QA. */
export async function obtenerPersonasEnrolamiento({ signal } = {}) {
  const personas = await solicitarApi('/_qa/enrolamiento/personas', { signal });
  if (!Array.isArray(personas) || personas.some(p => !Number.isSafeInteger(p?.id) || p.id <= 0
    || typeof p.nombre !== 'string' || typeof p.legajo !== 'string'
    || typeof p.categoria !== 'string' || typeof p.huella_registrada !== 'boolean')) {
    throw new Error('No se pudo leer el padrón para registrar la huella. Vuelve a cargarlo.');
  }
  return personas.map(p => ({ ...p, servicio: p.servicio ?? 'Sin servicio' }));
}

/** Registro de vinculos de huella: consulta de la jefa en el laboratorio. */
export async function obtenerRegistrosHuellas({ busqueda = '', limite = 50, desplazamiento = 0, fecha = null, signal } = {}) {
  if (typeof busqueda !== 'string' || busqueda.trim().length > 100
    || (fecha !== null && !FECHA_API.test(fecha))
    || !Number.isInteger(limite) || limite < 1 || limite > 100
    || !Number.isInteger(desplazamiento) || desplazamiento < 0) {
    throw new Error('Revisa la búsqueda del registro de huellas.');
  }
  const consulta = new URLSearchParams({ busqueda: busqueda.trim(), limite: String(limite), desplazamiento: String(desplazamiento) });
  // Un solo día, en hora de Bolivia; sin fecha, todas las altas.
  if (fecha !== null) consulta.set('fecha', fecha);
  try {
    const pagina = await solicitarApi(`/_qa/enrolamiento/registros?${consulta}`, { signal });
    const id = valor => Number.isSafeInteger(valor) && valor > 0;
    const texto = valor => valor === null || typeof valor === 'string';
    if (!pagina || pagina.modo !== 'simulado' || !Array.isArray(pagina.datos)
      || !Number.isSafeInteger(pagina.total) || pagina.total < 0
      || pagina.limite !== limite || pagina.desplazamiento !== desplazamiento
      || pagina.datos.length > limite || pagina.datos.length > Math.max(0, pagina.total - desplazamiento)
      || pagina.datos.some(f => (f?.tipo === 'policia'
        ? f.comensal?.usuario_id != null || !(f.cuenta?.id == null || id(f.cuenta.id))
        : !id(f?.comensal?.usuario_id) || !id(f?.cuenta?.id))
        || typeof f.comensal.disponible !== 'boolean' || typeof f.cuenta.disponible !== 'boolean'
        || !['nombre', 'legajo', 'categoria', 'servicio'].every(c => texto(f.comensal[c]))
        || !texto(f.cuenta.usuario) || !texto(f.cuenta.nombre)
        || typeof f.registrada_en !== 'string' || !/(Z|[+-]\d{2}:\d{2})$/.test(f.registrada_en)
        || !Number.isFinite(Date.parse(f.registrada_en)))) {
      throw new Error('La respuesta del registro de huellas no es válida.');
    }
    return pagina;
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(`No se pudo consultar el registro de huellas. ${error.message}`, { cause: error });
  }
}

/** Captura sintética autenticada e idempotente. No registra ninguna ración. */
export async function capturarHuellaQa(usuarioId, clave, { signal } = {}) {
  if (!Number.isSafeInteger(usuarioId) || usuarioId <= 0 || !esClaveIdempotencia(clave)) {
    throw new Error('Selecciona una persona antes de capturar la huella.');
  }
  try {
    const dato = await solicitarApi('/_qa/enrolamiento/capturas', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': clave },
      body: JSON.stringify({ usuario_id: usuarioId }), signal, motivosLocales: ['perfil_no_autorizado'],
    });
    if (dato?.usuario_id !== usuarioId || dato.modo !== 'simulado'
      || typeof dato.referencia !== 'string' || !dato.referencia.startsWith('SIM-HUELLA-')
      || !esClaveIdempotencia(dato.referencia.slice(11)) || typeof dato.ya_registrada !== 'boolean') {
      throw new Error('No se pudo confirmar el vínculo. Verifica el registro de la misma persona.');
    }
    return dato;
  } catch (error) {
    if (error instanceof ErrorApi && typeof error.datos?.detail === 'string') {
      error.message = error.datos.detail;
    }
    throw error;
  }
}

/**
 * Alta simulada de la huella de un policía (QA): no está en el padrón, así
 * que se escribe su nombre y, opcional, su CI o placa. No registra comida.
 */
export async function registrarPoliciaQa({ nombre, documento = '' }, clave, { signal } = {}) {
  const limpio = typeof nombre === 'string' ? nombre.split(/\s+/).filter(Boolean).join(' ') : '';
  const doc = typeof documento === 'string' ? documento.trim() : '';
  if (limpio.length < 3 || limpio.length > 100) throw new Error('Escribe el nombre completo del policía.');
  if (doc.length > 30 || !/^[A-Za-z0-9 ./-]*$/.test(doc)) throw new Error('El CI o la placa solo lleva letras, números, espacios, puntos, guiones o barras.');
  if (!esClaveIdempotencia(clave)) throw new Error('Clave de idempotencia inválida.');
  try {
    const dato = await solicitarApi('/_qa/enrolamiento/policias', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': clave },
      body: JSON.stringify({ nombre: limpio, documento: doc || null }), signal,
    });
    if (dato?.modo !== 'simulado' || !Number.isSafeInteger(dato.vinculo_id) || dato.vinculo_id <= 0
      || dato.nombre !== limpio || typeof dato.ya_registrada !== 'boolean') {
      throw new Error('No se pudo confirmar el registro del policía. Verifica con la misma solicitud.');
    }
    return dato;
  } catch (error) {
    if (error instanceof ErrorApi && typeof error.datos?.detail === 'string') error.message = error.datos.detail;
    throw error;
  }
}

/** Lectura simulada de la huella de un policía, por la lógica real del lector. Solo QA. */
export async function leerPoliciaQa(vinculoId, clave) {
  if (!Number.isSafeInteger(vinculoId) || vinculoId <= 0) throw new Error('Primero registra la huella del policía.');
  if (!esClaveIdempotencia(clave)) throw new Error('Clave de idempotencia inválida.');
  const dato = await solicitarApi(`/_qa/enrolamiento/policias/${vinculoId}/lecturas`, {
    method: 'POST', headers: { 'Idempotency-Key': clave },
  });
  if (dato?.modo !== 'simulado' || typeof dato.valido !== 'boolean') {
    throw new Error('No se pudo confirmar la lectura. Verifica con la misma solicitud.');
  }
  return dato;
}

/** Lee la referencia registrada y deja que el servidor decida derecho y duplicados. Solo QA. */
export async function leerHuellaQa(referencia, clave) {
  if (typeof referencia !== 'string' || !referencia.startsWith('SIM-HUELLA-')
    || !esClaveIdempotencia(referencia.slice(11)) || !esClaveIdempotencia(clave)) {
    throw new Error('Primero registra la huella de prueba de la persona.');
  }
  const dato = await solicitarApi('/_qa/enrolamiento/lecturas', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': clave },
    body: JSON.stringify({ referencia }),
  });
  if (dato?.modo !== 'simulado' || typeof dato.valido !== 'boolean'
    || !Number.isSafeInteger(dato.usuario_id) || dato.usuario_id <= 0
    || !Number.isSafeInteger(dato.lectura_id) || dato.lectura_id <= 0
    || (dato.valido && (!Number.isSafeInteger(dato.asistencia_id) || dato.asistencia_id <= 0))) {
    throw new Error('No se pudo confirmar la lectura. Verifica con la misma solicitud.');
  }
  return dato;
}

/** Error HTTP con el código y el cuerpo JSON de la respuesta, si lo trae. */
export class ErrorApi extends Error {
  constructor(mensaje, status, datos, retryAfter = null) {
    super(mensaje);
    this.name = 'ErrorApi';
    this.status = status;
    this.datos = datos;
    this.retryAfter = retryAfter;
  }
}

/*
 * Toda petición lleva el token de la sesión. Un 401 con motivo token_expirado
 * renueva con POST /auth/refresh y reintenta UNA vez; si el refresh falla, la
 * sesión expiró. Otro 401 vacía la sesión y devuelve al Login; un 403 con
 * motivo cambio_password_pendiente o un 428 pide el cambio de contraseña
 * temporal; otro 403 avisa «Sin permiso». `manejoPropio` apaga avisos y
 * reintento en /auth/login, /auth/cambio-password y /auth/refresh, donde esos
 * códigos hablan de la credencial tecleada y los resuelve el formulario.
 * `motivosLocales` lista los motivos de 403 que resuelve quien llama, sin
 * aviso central: el resto de 401, 403 y 428 sigue el manejo de siempre.
 */
async function solicitarApi(ruta, {
  signal, manejoPropio = false, motivosLocales = [], reintentoRefresh = true, ...opciones
} = {}) {
  const controlador = new AbortController();
  const cancelar = () => controlador.abort();
  const temporizador = setTimeout(cancelar, 15000);
  signal?.addEventListener('abort', cancelar, { once: true });
  if (signal?.aborted) cancelar();

  const token = leerTokens()?.access;
  try {
    const respuesta = await fetch(`${API_BASE_URL.replace(/\/$/, '')}${ruta}`, {
      ...opciones,
      headers: {
        Accept: 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...opciones.headers,
      },
      signal: controlador.signal,
    });
    if (!respuesta.ok) {
      const datos = await respuesta.json().catch(() => null);
      const retryAfter = respuesta.headers?.get?.('Retry-After') ?? null;
      const motivo = datos?.motivo;
      if (!manejoPropio && respuesta.status === 401 && motivo === 'token_expirado'
        && reintentoRefresh && ruta !== '/auth/refresh' && leerTokens()?.refresh) {
        try {
          await renovarSesion({ signal });
        } catch {
          if (signal?.aborted) throw new DOMException('Cancelado', 'AbortError');
          borrarTokens();
          avisarSesion({ tipo: 'expirada' });
          throw new ErrorApi(mensajeDeStatus(401), 401, datos, retryAfter);
        }
        if (signal?.aborted) throw new DOMException('Cancelado', 'AbortError');
        return solicitarApi(ruta, { signal, manejoPropio, motivosLocales, reintentoRefresh: false, ...opciones });
      }
      const local = respuesta.status === 403 && motivosLocales.includes(motivo);
      if (!manejoPropio && !local) avisarPorMotivo(respuesta.status, motivo, datos);
      throw new ErrorApi(mensajeDeStatus(respuesta.status), respuesta.status, datos, retryAfter);
    }
    if (respuesta.status === 204) return null;
    return await respuesta.json();
  } catch (error) {
    if (signal?.aborted) throw error;
    if (controlador.signal.aborted) throw new Error('La API tardó demasiado en responder.');
    if (error instanceof TypeError) throw new Error('No se pudo conectar con la API.');
    if (error instanceof SyntaxError) throw new Error('La API devolvió una respuesta inválida.');
    throw error;
  } finally {
    clearTimeout(temporizador);
    signal?.removeEventListener('abort', cancelar);
  }
}

function mensajeDeStatus(status) {
  if (status === 401) return 'La sesión expiró.';
  if (status === 403) return 'No tiene permiso para ver esta información.';
  if (status === 428) return 'Debe cambiar su contraseña temporal.';
  return `La API respondió con error HTTP ${status}.`;
}

function avisarPorMotivo(status, motivo, datos) {
  if (status === 401) {
    borrarTokens();
    avisarSesion({ tipo: 'expirada' });
  } else if (status === 403 && motivo === 'cambio_password_pendiente') {
    avisarSesion({ tipo: 'cambio_requerido' });
  } else if (status === 403) {
    avisarSesion({ tipo: 'prohibido' });
  } else if (status === 428) {
    if (typeof datos?.temporal === 'string' && datos.temporal) {
      const actual = leerTokens();
      guardarTokens({ access: datos.temporal, refresh: null, usuario: actual?.usuario ?? null });
    }
    avisarSesion({ tipo: 'cambio_requerido' });
  }
}

/*
 * --- Autenticación (contrato real comedorback/app/api/auth.py) ---
 * POST /auth/login → 200 {access, refresh, rol, debe_cambiar}
 *                  | 401 {detail, motivo} | 423 {detail, motivo, reintento_en}
 *                  | 428 {detail, motivo, temporal}
 * POST /auth/cambio-password {password_nueva, password_actual?} con Bearer
 *   temporal o access → 200 como login (sesión nueva, sin segundo login)
 * POST /auth/refresh {refresh} → 200 como login, con el MISMO refresh
 * GET  /auth/yo → {id, username, rol, debe_cambiar}
 */
const cuerpoLogin = (usuario, contrasena) => ({ username: usuario, password: contrasena });

/** La identidad del cambio viaja siempre en el header Authorization. */
const cuerpoCambio = ({ actual, nueva }) => ({
  password_nueva: nueva,
  ...(actual ? { password_actual: actual } : {}),
});

/** Texto humano del error, venga con `detail`, `Detail` o el `detalle` viejo. */
function detalleDe(datos, alternativa) {
  return datos?.detail ?? datos?.detail ?? datos?.detalle ?? alternativa;
}

/**
 * POST /auth/login. Devuelve lo que el Login tiene que mostrar:
 * `{ tipo: 'ok', rol, debeCambiar }` (los tokens ya quedan guardados),
 * `{ tipo: 'credencial', detalle }`, `{ tipo: 'bloqueada', detalle, reintentoEn }`
 * o `{ tipo: 'cambio' }` (el temporal ya queda guardado como access para
 * firmar el cambio). Los errores de red o de servidor se lanzan.
 */
export async function iniciarSesion(usuario, contrasena, { signal } = {}) {
  let datos;
  try {
    datos = await solicitarApi('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cuerpoLogin(usuario, contrasena)),
      manejoPropio: true,
      signal,
    });
  } catch (error) {
    if (error.status === 401) {
      return { tipo: 'credencial', detalle: detalleDe(error.datos, 'Usuario o contraseña incorrectos.') };
    }
    if (error.status === 423) {
      return {
        tipo: 'bloqueada',
        detalle: detalleDe(error.datos, 'La cuenta está bloqueada temporalmente.'),
        reintentoEn: momentoDeReintento(error.datos?.reintento_en ?? error.retryAfter),
      };
    }
    if (error.status === 428) {
      if (typeof error.datos?.temporal === 'string' && error.datos.temporal) {
        guardarTokens({ access: error.datos.temporal, refresh: null, usuario });
      }
      return { tipo: 'cambio' };
    }
    if (signal?.aborted) throw error;
    throw new Error(`No se pudo iniciar sesión. ${error.message}`);
  }
  if (typeof datos?.access !== 'string' || !datos.access || typeof datos.rol !== 'string'
    || typeof datos.debe_cambiar !== 'boolean') {
    throw new Error('No se pudo iniciar sesión. La API devolvió una sesión inválida.');
  }
  guardarTokens({ access: datos.access, refresh: datos.refresh ?? null, usuario });
  return { tipo: 'ok', rol: datos.rol, debeCambiar: datos.debe_cambiar };
}

/**
 * `reintento_en` (ISO) o el header Retry-After (segundos) como Date. null si
 * no se puede interpretar; el Login muestra entonces solo el `detalle`.
 */
export function momentoDeReintento(reintentoEn, ahora = new Date()) {
  if (typeof reintentoEn === 'number' || (typeof reintentoEn === 'string' && /^\d+$/.test(reintentoEn.trim()))) {
    return new Date(ahora.getTime() + Number(reintentoEn) * 1000);
  }
  if (typeof reintentoEn === 'string') {
    const momento = new Date(reintentoEn);
    if (!Number.isNaN(momento.getTime())) return momento;
  }
  return null;
}

/**
 * POST /auth/cambio-password firmado con el temporal del 428 (sin actual) o
 * con el access (cambio voluntario, con actual). El 200 trae forma de login:
 * hidrata la sesión sin segundo login. Un 423 se devuelve como `bloqueada`
 * para que el formulario lo pinte; el resto se lanza con el `detail`.
 */
export async function cambiarContrasena({ usuario, actual, nueva, signal }) {
  let datos;
  try {
    datos = await solicitarApi('/auth/cambio-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cuerpoCambio({ actual, nueva })),
      manejoPropio: true,
      signal,
    });
  } catch (error) {
    if (error.status === 423) {
      return {
        tipo: 'bloqueada',
        detalle: detalleDe(error.datos, 'La cuenta está bloqueada temporalmente.'),
        reintentoEn: momentoDeReintento(error.datos?.reintento_en ?? error.retryAfter),
      };
    }
    if (signal?.aborted) throw error;
    throw new Error(detalleDe(error.datos, `No se pudo cambiar la contraseña. ${error.message}`));
  }
  if (typeof datos?.access !== 'string' || !datos.access || typeof datos.rol !== 'string'
    || typeof datos.debe_cambiar !== 'boolean') {
    throw new Error('No se pudo cambiar la contraseña. La API devolvió una sesión inválida.');
  }
  guardarTokens({ access: datos.access, refresh: datos.refresh ?? null, usuario });
  return { tipo: 'ok', rol: datos.rol, debeCambiar: datos.debe_cambiar };
}

/**
 * POST /auth/refresh: access nuevo con el MISMO refresh. Lo usa el reintento
 * automático de `solicitarApi`; si falla, quien llama decide (sesión expirada).
 */
export async function renovarSesion({ signal } = {}) {
  const actual = leerTokens();
  if (!actual?.refresh) throw new Error('No hay sesión para renovar.');
  const datos = await solicitarApi('/auth/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh: actual.refresh }),
    manejoPropio: true,
    reintentoRefresh: false,
    signal,
  });
  if (typeof datos?.access !== 'string' || !datos.access || typeof datos.rol !== 'string'
    || typeof datos.debe_cambiar !== 'boolean') {
    throw new Error('La API devolvió una sesión inválida al renovar.');
  }
  guardarTokens({ access: datos.access, refresh: datos.refresh ?? actual.refresh, usuario: actual.usuario });
  return { rol: datos.rol, debeCambiar: datos.debe_cambiar };
}

/** GET /auth/yo: la cuenta de la sesión guardada, al abrir la app. */
export async function obtenerUsuarioActual({ signal } = {}) {
  const yo = await solicitarApi('/auth/yo', { signal });
  if (typeof yo?.rol !== 'string' || !yo.rol) {
    throw new Error('La API devolvió un usuario sin rol.');
  }
  return {
    id: Number.isInteger(yo.id) ? yo.id : null,
    username: typeof yo.username === 'string' ? yo.username : null,
    rol: yo.rol,
    debeCambiar: yo.debe_cambiar === true,
  };
}

function adaptarPersona(dato) {
  if (!Number.isInteger(dato?.usuario_id) || dato.usuario_id <= 0) {
    throw new Error('La API devolvió un comensal sin usuario_id válido.');
  }
  return {
    ...dato,
    id: dato.usuario_id,
    nombre: dato.nombre_completo || `Usuario ${dato.usuario_id} (sin ficha)`,
    categoria: dato.categoria_reporte || 'Sin clasificar',
    categoriaHospital: dato.categoria,
    legajo: dato.numero_item || dato.carnet_identidad || 'Sin legajo',
    // Campo legado para los informes de demostración. Las vistas reales usan
    // /pantalla/estado e /historial; nunca autoriza una marcación.
    yaMarcoHoy: false,
  };
}

/** Motivos de rechazo. El componente decide el texto visual a partir de esto. */
export const MOTIVOS = {
  OK: 'ok',
  YA_MARCO: 'ya_marco',
};

let secuenciaEvento = 0;

/** GET /personal: reúne las páginas y conserva la lista que espera el front. */
export async function obtenerPersonal({ signal } = {}) {
  try {
    const personal = [];
    let desplazamiento = 0;
    let total;
    do {
      const pagina = await solicitarApi(`/personal?limite=200&desplazamiento=${desplazamiento}`, { signal });
      if (!Array.isArray(pagina?.datos) || !Number.isInteger(pagina.total) || pagina.total < 0) {
        throw new Error('La API devolvió un padrón inválido.');
      }
      total = pagina.total;
      if (pagina.datos.length === 0 && desplazamiento < total) {
        throw new Error('La API devolvió una página incompleta del padrón.');
      }
      personal.push(...pagina.datos.map(adaptarPersona));
      desplazamiento += pagina.datos.length;
    } while (desplazamiento < total);
    return personal;
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(`No se pudo cargar el padrón. ${error.message}`);
  }
}

function horaLegible(fecha) {
  return fecha.toLocaleTimeString('es-BO', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

/**
 * POST /asistencias con `metodo: 'manual'`: el servidor resuelve todas las
 * reglas de la marcación. `personaId` corresponde a users.id (usuario_id en
 * la API). Desde el navegador solo se registra a mano: la marcación
 * biométrica la registra el lector autorizado.
 *
 * La respuesta suma `origen` y `claveEvento`, la misma clave con que la fila
 * aparece en GET /pantalla/ultimas-marcaciones: con `lectura_id` es la
 * lectura (una asistencia ligada a una lectura solo aparece como lectura);
 * sin ella, la asistencia manual; sin ninguna, null (un rechazo manual no
 * deja fila). Un fallo conserva su causa en `cause`: sin ErrorApi no hubo
 * respuesta del servidor y el resultado es incierto.
 */
export async function marcarAsistencia(personaId, { persona, ahora = new Date(), signal } = {}) {
  try {
    if (!Number.isInteger(personaId) || personaId <= 0) {
      throw new Error('Seleccione un comensal del padrón.');
    }
    const ficha = persona?.id === personaId
      ? persona
      : adaptarPersona(await solicitarApi(`/personal/${personaId}`, { signal }));
    const respuesta = await solicitarApi('/asistencias', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ usuario_id: personaId, metodo: 'manual' }),
      signal,
    });
    if (typeof respuesta?.valido !== 'boolean' || typeof respuesta.titulo !== 'string'
      || typeof respuesta.detalle !== 'string'
      || (respuesta.usuario_id != null && respuesta.usuario_id !== personaId)) {
      throw new Error('La API devolvió una marcación inválida.');
    }
    const origen = Number.isInteger(respuesta.lectura_id) ? 'lectura_biometrica'
      : Number.isInteger(respuesta.asistencia_id) ? 'asistencia_manual' : null;
    return {
      ...respuesta,
      id: (secuenciaEvento += 1),
      origen,
      claveEvento: origen === null ? null
        : claveDeEvento(origen, origen === 'lectura_biometrica' ? respuesta.lectura_id : respuesta.asistencia_id),
      // La respuesta actual no trae hora: esta es la hora de recepción local.
      hora: horaLegible(ahora),
      persona: { ...ficha, nombre: respuesta.nombre || ficha.nombre },
      tiempo: respuesta.comida,
      motivo: respuesta.valido ? MOTIVOS.OK
        : respuesta.motivo === 'duplicado' ? MOTIVOS.YA_MARCO : respuesta.motivo,
    };
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(
      `No se pudo confirmar la marcación. ${error.message} Verifique el registro antes de volver a enviarla.`,
      { cause: error },
    );
  }
}

/** Fecha compacta para el nombre del archivo exportado: "2026-09-03". */
function fechaArchivo(fecha) {
  const dos = (n) => String(n).padStart(2, '0');
  return `${fecha.getFullYear()}-${dos(fecha.getMonth() + 1)}-${dos(fecha.getDate())}`;
}

/* ------------------------------------------------------------------ *
 * Informes de Estadística: del día al mes
 *
 * Digitalización del formulario del Servicio de Estadística. Los tres salen
 * de la misma tabla del backend (`asistencias`) con distinto agrupamiento y
 * por eso el total del registro diario tiene que dar igual al del mensual:
 * son la misma suma abierta por criterios distintos.
 *
 *   GET /reportes/registro-diario?gestion=…&mes=…   una fila por día
 *   GET /reportes/mensual?gestion=…&mes=…           una fila por tiempo
 *   GET /reportes/gestion?gestion=…                 una fila por mes
 *
 * La API habla snake_case y este archivo la adapta a la forma que ya consumen
 * InformeRaciones.jsx y exportaciones.js (ver cada adaptador). `titulo` y
 * `archivo` son literales de la UI y `generado` es la hora del navegador:
 * ninguno viene de la API y se siguen armando aquí.
 *
 * Dos números se exponen a propósito en vez de esconderlos, porque miden lo
 * que falta: `sin_clasificar` (sin columna en el papel) y `sin_coeficiente`
 * (no suma al equivalente). Mientras sean mayores que cero, el informe no
 * cuadra 100 % con el papel: la UI los muestra como advertencia, nunca en
 * silencio.
 * ------------------------------------------------------------------ */

/** Fecha corta del formulario: "04/09/2026". */
function fechaCorta(fecha) {
  const dos = (n) => String(n).padStart(2, '0');
  return `${dos(fecha.getDate())}/${dos(fecha.getMonth() + 1)}/${fecha.getFullYear()}`;
}

/** Sello de emisión: sustituye a la firma y la fecha escritas a mano. */
function selloDeGeneracion(fecha) {
  return `${fechaCorta(fecha)} ${horaLegible(fecha)}`;
}

/* ---------------------------- Periodos ----------------------------- *
 * Los tres informes se piden por período: un mes concreto de la gestión o la
 * gestión entera. Un mes anterior está cerrado; el mes en curso mezcla los
 * días cerrados con lo que va del día de hoy; un mes posterior todavía no
 * tiene nada, y se muestra en blanco como las hojas sin llenar del cuaderno.
 * ------------------------------------------------------------------- */

/** Selecciones derivadas de /reportes/periodos, sin inventar años ni meses. */
export function obtenerGestiones(periodos = []) {
  return periodos;
}

/** Nombres de los meses de una gestión, para el selector de período. */
export function obtenerMesesDeGestion(gestion, periodos = []) {
  return (periodos.find((periodo) => periodo.gestion === gestion)?.meses ?? []).map((mes) => ({
    ...mes,
    mes: mes.nombre,
    indice: mes.mes - 1,
  }));
}

/* ------------------------- Validación y adaptación ------------------------- *
 * La API habla snake_case y devuelve la forma `Informe`; la UI consume
 * camelCase con literales propios (títulos, nombres de archivo, sello de
 * generación). Cada endpoint valida y adapta aquí, igual que
 * obtenerEstadoPantalla y obtenerPeriodos más arriba.
 * ------------------------------------------------------------------- */

function esEnteroNoNegativo(valor) {
  return Number.isInteger(valor) && valor >= 0;
}

function validarFilaInforme(fila, columnas) {
  if (typeof fila?.etiqueta !== 'string' || fila.etiqueta.length === 0
    || !Array.isArray(fila.celdas) || fila.celdas.length !== columnas
    || !fila.celdas.every(esEnteroNoNegativo)
    || !esEnteroNoNegativo(fila.total) || typeof fila.registrado !== 'boolean'
    || fila.total !== fila.celdas.reduce((suma, n) => suma + n, 0)) {
    throw new Error('La API devolvió una fila de informe inválida.');
  }
}

function validarGrupoCoeficiente(grupo) {
  if (typeof grupo?.grupo !== 'string' || grupo.grupo.length === 0
    || !esEnteroNoNegativo(grupo.servidas)
    || typeof grupo.coeficiente !== 'number' || Number.isNaN(grupo.coeficiente) || grupo.coeficiente < 0
    || typeof grupo.equivalente !== 'number' || Number.isNaN(grupo.equivalente) || grupo.equivalente < 0
    || (grupo.coeficientes_mixtos !== undefined && typeof grupo.coeficientes_mixtos !== 'boolean')) {
    throw new Error('La API devolvió un grupo de coeficiente inválido.');
  }
}

/** Valida la forma `Informe` y la coherencia de sus totales con sus filas. */
function validarInforme(dato, tipoEsperado, { conMes }) {
  if (!dato || typeof dato !== 'object' || dato.tipo !== tipoEsperado
    || !Number.isInteger(dato.gestion)
    || typeof dato.desde !== 'string' || Number.isNaN(Date.parse(dato.desde))
    || typeof dato.hasta !== 'string' || Number.isNaN(Date.parse(dato.hasta))
    || !['cerrado', 'curso', 'futuro'].includes(dato.situacion)
    || typeof dato.cerrado !== 'boolean'
    || !Array.isArray(dato.categorias) || dato.categorias.length === 0
    || dato.categorias.some((categoria) => typeof categoria !== 'string' || categoria.length === 0)
    || !Array.isArray(dato.filas)
    || !Array.isArray(dato.totales_por_categoria)
    || dato.totales_por_categoria.length !== dato.categorias.length
    || !dato.totales_por_categoria.every(esEnteroNoNegativo)
    || !esEnteroNoNegativo(dato.total_general)
    || !esEnteroNoNegativo(dato.sin_clasificar)
    || !esEnteroNoNegativo(dato.sin_coeficiente)
    || !Array.isArray(dato.grupos)
    || (dato.total_equivalente !== null
      && (typeof dato.total_equivalente !== 'number' || Number.isNaN(dato.total_equivalente)
        || dato.total_equivalente < 0))) {
    throw new Error('La API devolvió un informe inválido.');
  }
  if (conMes) {
    if (!Number.isInteger(dato.mes) || dato.mes < 1 || dato.mes > 12
      || typeof dato.mes_nombre !== 'string' || dato.mes_nombre.length === 0) {
      throw new Error('La API devolvió un informe inválido.');
    }
  } else if (dato.mes !== null || dato.mes_nombre !== null) {
    throw new Error('La API devolvió un informe inválido.');
  }
  dato.filas.forEach((fila) => validarFilaInforme(fila, dato.categorias.length));
  dato.grupos.forEach(validarGrupoCoeficiente);
  const columnas = dato.categorias.map((_, columna) =>
    dato.filas.reduce((suma, fila) => suma + fila.celdas[columna], 0));
  if (columnas.some((total, columna) => total !== dato.totales_por_categoria[columna])
    || dato.total_general !== dato.totales_por_categoria.reduce((suma, n) => suma + n, 0)) {
    throw new Error('La API devolvió un informe con totales que no cuadran.');
  }
  return dato;
}

/**
 * Claves comunes que ya esperan InformeRaciones.jsx y exportaciones.js.
 * `titulo`, `archivo` y `generado` no vienen de la API: son literales de la
 * UI y el sello con la hora del navegador.
 */
function baseAdaptada(dato, hoy) {
  return {
    gestion: dato.gestion,
    generado: selloDeGeneracion(hoy),
    categorias: dato.categorias,
    totalesPorCategoria: dato.totales_por_categoria,
    totalGeneral: dato.total_general,
    sinClasificar: dato.sin_clasificar,
    sinCoeficiente: dato.sin_coeficiente,
    situacion: dato.situacion,
    /* Visto bueno de la jefatura: distinto de que el mes ya pasó. */
    cerrado: dato.cerrado,
    desde: dato.desde,
    hasta: dato.hasta,
  };
}

/** Días que trae el mes según el rango `hasta` de la API ("2026-09-30"). */
function diasDelRango(hasta) {
  const dias = Number(hasta.slice(8, 10));
  if (!Number.isInteger(dias) || dias < 1 || dias > 31) {
    throw new Error('La API devolvió un informe inválido.');
  }
  return dias;
}

/**
 * Registro diario del mes: la planilla del cuaderno, una fila por día.
 *
 * GET /reportes/registro-diario?gestion=…&mes=… (mes de 1 a 12).
 */
export async function obtenerRegistroDiario({
  mesIndice = new Date().getMonth(),
  gestion = new Date().getFullYear(),
  hoy = new Date(),
  signal,
} = {}) {
  try {
    const dato = validarInforme(
      await solicitarApi(`/reportes/registro-diario?gestion=${gestion}&mes=${mesIndice + 1}`, { signal }),
      'registro_diario',
      { conMes: true },
    );
    if (dato.gestion !== gestion || dato.mes !== mesIndice + 1) {
      throw new Error('La API devolvió un informe de otro período.');
    }
    const dias = diasDelRango(dato.hasta);
    const esMesEnCurso = dato.situacion === 'curso'
      && gestion === hoy.getFullYear() && dato.mes === hoy.getMonth() + 1;
    const filas = dato.filas.map((fila) => {
      const dia = Number(fila.etiqueta);
      if (!Number.isInteger(dia) || dia < 1 || dia > dias) {
        throw new Error('La API devolvió un día fuera del mes.');
      }
      return {
        dia,
        celdas: fila.celdas,
        total: fila.total,
        registrado: fila.registrado,
        esHoy: esMesEnCurso && dia === hoy.getDate(),
      };
    });
    const registrados = filas.filter((fila) => fila.registrado).length;
    const mes = dato.mes_nombre;

    return {
      ...baseAdaptada(dato, hoy),
      tipo: 'registro',
      titulo: 'Registro diario de raciones servidas al personal',
      mes,
      mesIndice,
      dias,
      diasRegistrados: registrados,
      encabezados: ['Fecha', ...dato.categorias, 'Total'],
      filas,
      periodo: { principal: mes, secundario: `Gestión ${gestion}` },
      encabezado: { rotulo: 'MES :', valor: mes.toUpperCase() },
      cierre: [
        {
          rotulo: 'Raciones del mes',
          valor: dato.total_general,
          detalle: `${registrados} de ${dias} días registrados`,
        },
        {
          rotulo: 'Promedio por día',
          valor: registrados > 0 ? dato.total_general / registrados : 0,
          detalle: 'Sobre los días ya registrados',
        },
      ],
      archivo: `registro-diario-raciones-${mes.toLowerCase()}-${gestion}`,
    };
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(`No se pudo cargar el registro diario. ${error.message}`);
  }
}

/**
 * Informe del mes: el mismo registro abierto por tiempo de comida y reducido
 * a ración completa con los coeficientes del formulario.
 *
 * GET /reportes/mensual?gestion=…&mes=… (mes de 1 a 12).
 */
export async function obtenerInformeMensual({
  mesIndice = new Date().getMonth(),
  gestion = new Date().getFullYear(),
  hoy = new Date(),
  signal,
} = {}) {
  try {
    const dato = validarInforme(
      await solicitarApi(`/reportes/mensual?gestion=${gestion}&mes=${mesIndice + 1}`, { signal }),
      'mensual',
      { conMes: true },
    );
    if (dato.gestion !== gestion || dato.mes !== mesIndice + 1) {
      throw new Error('La API devolvió un informe de otro período.');
    }
    const dias = diasDelRango(dato.hasta);
    /* El mensual no trae el día a día: los registrados salen del calendario. */
    const enEsteMes = gestion === hoy.getFullYear() && dato.mes === hoy.getMonth() + 1;
    const registrados = dato.situacion === 'cerrado' ? dias
      : dato.situacion === 'futuro' ? 0
        : enEsteMes ? Math.min(hoy.getDate(), dias) : dias;
    const filas = dato.filas.map((fila) => ({
      tiempo: fila.etiqueta,
      celdas: fila.celdas,
      total: fila.total,
      registrado: fila.registrado,
    }));
    const grupos = dato.grupos.map((grupo) => ({
      etiqueta: grupo.grupo,
      servidas: grupo.servidas,
      coeficiente: grupo.coeficiente,
      ...(grupo.coeficientes_mixtos ? { coeficienteVariable: true } : {}),
      equivalente: grupo.equivalente,
    }));
    const totalEquivalente = dato.total_equivalente ?? 0;
    const mes = dato.mes_nombre;

    return {
      ...baseAdaptada(dato, hoy),
      tipo: 'mensual',
      titulo: 'Informe mensual de raciones servidas al personal',
      mes,
      mesIndice,
      dias,
      diasRegistrados: registrados,
      encabezados: ['Tiempo de comida', ...dato.categorias, 'Total'],
      filas,
      grupos,
      totalEquivalente,
      periodo: { principal: mes, secundario: `Gestión ${gestion}` },
      encabezado: { rotulo: 'MES :', valor: mes.toUpperCase() },
      cierre: [
        {
          rotulo: 'Total raciones mes',
          valor: totalEquivalente,
          detalle: `${registrados} de ${dias} días registrados`,
        },
        {
          rotulo: 'Raciones día',
          valor: registrados > 0 ? totalEquivalente / registrados : 0,
          detalle: 'Promedio de los días registrados',
        },
      ],
      archivo: `informe-mensual-raciones-${mes.toLowerCase()}-${gestion}`,
    };
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(`No se pudo cargar el informe mensual. ${error.message}`);
  }
}

/**
 * Resumen de la gestión: la misma planilla, pero con un mes por fila. Cierra
 * el año y permite comparar meses entre sí de un vistazo.
 *
 * GET /reportes/gestion?gestion=…
 */
export async function obtenerResumenGestion({
  gestion = new Date().getFullYear(),
  hoy = new Date(),
  signal,
} = {}) {
  try {
    const dato = validarInforme(
      await solicitarApi(`/reportes/gestion?gestion=${gestion}`, { signal }),
      'gestion',
      { conMes: false },
    );
    if (dato.gestion !== gestion) {
      throw new Error('La API devolvió un informe de otro período.');
    }
    const filas = dato.filas.map((fila, indice) => ({
      mes: fila.etiqueta,
      mesIndice: indice,
      celdas: fila.celdas,
      total: fila.total,
      registrado: fila.registrado,
      esHoy: dato.situacion === 'curso' && gestion === hoy.getFullYear() && indice === hoy.getMonth(),
    }));
    const mesesRegistrados = filas.filter((fila) => fila.registrado).length;

    return {
      ...baseAdaptada(dato, hoy),
      tipo: 'gestion',
      titulo: 'Resumen de raciones servidas al personal por gestión',
      categorias: dato.categorias,
      encabezados: ['Mes', ...dato.categorias, 'Total'],
      filas,
      mesesRegistrados,
      periodo: { principal: `Gestión ${gestion}`, secundario: `${mesesRegistrados} meses con registro` },
      encabezado: { rotulo: 'GESTIÓN :', valor: String(gestion) },
      cierre: [
        {
          rotulo: 'Raciones de la gestión',
          valor: dato.total_general,
          detalle: `${mesesRegistrados} de 12 meses registrados`,
        },
        {
          rotulo: 'Promedio por mes',
          valor: mesesRegistrados > 0 ? dato.total_general / mesesRegistrados : 0,
          detalle: 'Sobre los meses ya registrados',
        },
      ],
      archivo: `resumen-gestion-raciones-${gestion}`,
    };
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(`No se pudo cargar el resumen de la gestión. ${error.message}`);
  }
}

/* ------------------- Informe de raciones por rango de fechas ------------- */

/*
 * Reportes es una sola vista: se elige un rango de fechas y sale el formulario
 * del Servicio de Estadística calculado sobre ese rango —tiempos de comida ×
 * categorías, reducido a ración completa con los coeficientes—. Antes había
 * tres vistas atadas al calendario (día, mes, gestión); el rango las cubre a
 * todas, porque «este mes» o «esta gestión» no son más que rangos.
 *
 * La suma la hace el backend: GET /reportes/informe?desde=…&hasta=…. Aquí solo
 * se valida la respuesta y se adapta a la forma que ya consumen
 * InformeRaciones.jsx y exportaciones.js.
 */

const FECHA_API = /^\d{4}-\d{2}-\d{2}$/;

const FORMATO_MES_CORTO = new Intl.DateTimeFormat('es-BO', { month: 'short' });

/** Fecha local desde "2026-09-16" (a mediodía, para que no la mueva la zona). */
function fechaDeValor(valor) {
  const [gestion, mes, dia] = valor.split('-').map(Number);
  return new Date(gestion, mes - 1, dia, 12);
}

/** Días del rango, ambos extremos incluidos. */
function diasEntre(desde, hasta) {
  const uno = fechaDeValor(desde).getTime();
  const dos = fechaDeValor(hasta).getTime();
  return Math.round((dos - uno) / 86400000) + 1;
}

function sinPunto(texto) {
  return texto.replace('.', '');
}

/*
 * "16 sept 2026". Se compone a mano en vez de pedirle a Intl día + mes: es-BO
 * devuelve «16 sept 2026» con año pero «16-sept» sin él, y los dos extremos
 * del rango tienen que leerse igual.
 */
function fechaCortaLegible(fecha, { conGestion }) {
  const dia = String(fecha.getDate()).padStart(2, '0');
  const mes = sinPunto(FORMATO_MES_CORTO.format(fecha));
  return conGestion ? `${dia} ${mes} ${fecha.getFullYear()}` : `${dia} ${mes}`;
}

/**
 * El rango en corto, como se lee en la insignia y en la cabecera del PDF:
 * "16 sep 2026" un solo día, "01 sep – 16 sep 2026" dentro de la misma
 * gestión, y con los dos años cuando el rango las cruza.
 *
 * @param {string} desde  fecha API "YYYY-MM-DD"
 * @param {string} hasta  fecha API "YYYY-MM-DD"
 */
export function etiquetaDeRango(desde, hasta) {
  const inicio = fechaDeValor(desde);
  const fin = fechaDeValor(hasta);
  const cierre = fechaCortaLegible(fin, { conGestion: true });
  if (desde === hasta) return cierre;
  /* La gestión se dice una sola vez cuando el rango no la cruza. */
  const apertura = fechaCortaLegible(inicio, {
    conGestion: inicio.getFullYear() !== fin.getFullYear(),
  });
  return `${apertura} – ${cierre}`;
}

/**
 * Valida la respuesta de /reportes/informe. Es la misma forma `Informe` que
 * los otros reportes —filas, totales por categoría y grupos de coeficiente—,
 * pero acotada por fechas en vez de por mes y gestión.
 */
function validarInformeDeRango(dato, { desde, hasta }) {
  if (!dato || typeof dato !== 'object'
    || (dato.tipo !== 'informe' && dato.tipo !== 'mensual')
    || typeof dato.desde !== 'string' || !FECHA_API.test(dato.desde)
    || typeof dato.hasta !== 'string' || !FECHA_API.test(dato.hasta)
    || !Array.isArray(dato.categorias) || dato.categorias.length === 0
    || dato.categorias.some((categoria) => typeof categoria !== 'string' || categoria.length === 0)
    || !Array.isArray(dato.filas)
    || !Array.isArray(dato.totales_por_categoria)
    || dato.totales_por_categoria.length !== dato.categorias.length
    || !dato.totales_por_categoria.every(esEnteroNoNegativo)
    || !esEnteroNoNegativo(dato.total_general)
    || !esEnteroNoNegativo(dato.sin_clasificar)
    || !esEnteroNoNegativo(dato.sin_coeficiente)
    || !Array.isArray(dato.grupos)
    || (dato.total_equivalente !== null && dato.total_equivalente !== undefined
      && (typeof dato.total_equivalente !== 'number' || Number.isNaN(dato.total_equivalente)
        || dato.total_equivalente < 0))) {
    throw new Error('La API devolvió un informe inválido.');
  }
  if (dato.desde !== desde || dato.hasta !== hasta) {
    throw new Error('La API devolvió un informe de otro período.');
  }
  dato.filas.forEach((fila) => validarFilaInforme(fila, dato.categorias.length));
  dato.grupos.forEach(validarGrupoCoeficiente);
  const columnas = dato.categorias.map((_, columna) =>
    dato.filas.reduce((suma, fila) => suma + fila.celdas[columna], 0));
  if (columnas.some((total, columna) => total !== dato.totales_por_categoria[columna])
    || dato.total_general !== dato.totales_por_categoria.reduce((suma, n) => suma + n, 0)) {
    throw new Error('La API devolvió un informe con totales que no cuadran.');
  }
  return dato;
}

/**
 * Días del rango que ya tienen registro. Lo natural es que lo diga el backend
 * (`dias_registrados`), porque es el único que sabe qué días tienen datos; si
 * no viene, se cuentan los días del rango ya transcurridos, que es lo que se
 * puede afirmar sin inventar nada.
 */
function diasRegistradosDelRango(dato, { desde, hasta, dias, hoy }) {
  if (esEnteroNoNegativo(dato.dias_registrados)) return Math.min(dato.dias_registrados, dias);
  const tope = fechaArchivo(hoy);
  if (tope < desde) return 0;
  return tope >= hasta ? dias : diasEntre(desde, tope);
}

/**
 * Informe del rango: el formulario de Estadística acotado por fechas.
 *
 * GET /reportes/informe?desde=YYYY-MM-DD&hasta=YYYY-MM-DD
 *
 * @returns {Promise<object>} informe listo para la tabla y para los exportadores
 */
export async function obtenerInformeRaciones({ desde, hasta, hoy = new Date(), signal } = {}) {
  if (typeof desde !== 'string' || !FECHA_API.test(desde)
    || typeof hasta !== 'string' || !FECHA_API.test(hasta)) {
    throw new Error('Rango de fechas inválido.');
  }
  if (desde > hasta) {
    throw new Error('La fecha inicial no puede ser posterior a la final.');
  }

  try {
    const dato = validarInformeDeRango(
      await solicitarApi(`/reportes/informe?desde=${desde}&hasta=${hasta}`, { signal }),
      { desde, hasta },
    );

    const dias = diasEntre(desde, hasta);
    const diasRegistrados = diasRegistradosDelRango(dato, { desde, hasta, dias, hoy });
    const filas = dato.filas.map((fila) => ({
      tiempo: fila.etiqueta,
      celdas: fila.celdas,
      total: fila.total,
      registrado: fila.registrado,
    }));
    const grupos = dato.grupos.map((grupo) => ({
      etiqueta: grupo.grupo,
      servidas: grupo.servidas,
      coeficiente: grupo.coeficiente,
      ...(grupo.coeficientes_mixtos ? { coeficienteVariable: true } : {}),
      equivalente: grupo.equivalente,
    }));
    const totalEquivalente = dato.total_equivalente ?? 0;
    const rango = etiquetaDeRango(desde, hasta);

    return {
      tipo: 'informe',
      titulo: 'Informe de raciones servidas al personal',
      generado: selloDeGeneracion(hoy),
      /* La gestión del cierre del rango: es la que se escribe en el papel. */
      gestion: fechaDeValor(hasta).getFullYear(),
      categorias: dato.categorias,
      encabezados: ['Tiempo de comida', ...dato.categorias, 'Total'],
      filas,
      grupos,
      totalesPorCategoria: dato.totales_por_categoria,
      totalGeneral: dato.total_general,
      totalEquivalente,
      sinClasificar: dato.sin_clasificar,
      sinCoeficiente: dato.sin_coeficiente,
      desde,
      hasta,
      dias,
      diasRegistrados,
      rango,
      periodo: {
        principal: rango,
        secundario: dias === 1 ? '1 día' : `${dias} días`,
      },
      encabezado: { rotulo: 'PERÍODO :', valor: rango.toUpperCase() },
      cierre: [
        {
          rotulo: 'Total raciones',
          valor: totalEquivalente,
          detalle: `${diasRegistrados} de ${dias} días con registro`,
        },
        {
          rotulo: 'Raciones día',
          valor: diasRegistrados > 0 ? totalEquivalente / diasRegistrados : 0,
          detalle: 'Promedio de los días registrados',
        },
      ],
      archivo: `informe-raciones-${desde}-a-${hasta}`,
    };
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(`No se pudo cargar el informe. ${error.message}`);
  }
}

/**
 * Ración manual desde Supervisión: autorizar una lectura no identificada o
 * registrar a un comensal elegido del padrón. Envía solo
 * { usuario_id, metodo: 'manual' }: sin momento, dispositivo ni operador
 * (la cuenta sale del token). Con `persona` del padrón no vuelve a pedir
 * su ficha antes del POST.
 */
export async function autorizarMarcacionManual(usuarioId, { persona, signal } = {}) {
  if (!Number.isInteger(usuarioId) || usuarioId <= 0) {
    throw new Error('Seleccione un comensal del padrón.');
  }
  return marcarAsistencia(usuarioId, { persona, metodo: 'manual', signal });
}

/**
 * true si, tras el fallo de una marcación, no se sabe si quedó registrada:
 * red, tiempo de espera, respuesta ilegible o un 5xx (que el servidor haya
 * respondido no prueba que haya revertido la escritura). Solo un 4xx
 * (salvo 408) es un rechazo de la petición antes de registrar: datos
 * inválidos, permisos o sesión, que siguen su manejo central.
 */
export function marcacionIncierta(error) {
  const causa = error?.cause;
  if (!(causa instanceof ErrorApi)) return true;
  return !(causa.status >= 400 && causa.status < 500 && causa.status !== 408);
}

/* ----------------------------- Intervenciones de cocina */

/*
 * Contrato: comedorback/app/api/asistencias.py (POST
 * /asistencias/lecturas/{id}/identificar, solo cocinera) y
 * comedorback/app/api/intervenciones.py (GET /intervenciones-cocina, solo
 * jefa). La cocinera identifica a quien está frente al lector y confirma la
 * entrega; la jefa solo consulta. Sin nota ni motivo escrito: la causa la fija
 * el servidor, la cuenta sale del token y la hora del reloj del servidor.
 */

const CLAVE_UUID4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

/**
 * Clave de idempotencia de un INTENTO: un UUID v4. Se genera con
 * getRandomValues y no con randomUUID, que el navegador solo ofrece en
 * contextos seguros (HTTPS o localhost); el puesto de cocina puede abrir la
 * app por la IP de la red del hospital.
 */
export function nuevaClaveIdempotencia(cripto = globalThis.crypto) {
  const bytes = new Uint8Array(16);
  cripto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** true si `clave` es un UUID v4 en minúsculas, como lo normaliza el servidor. */
export function esClaveIdempotencia(clave) {
  return typeof clave === 'string' && CLAVE_UUID4.test(clave);
}

/** GET /pantalla/policias (cocina): policías con huella activa, para identificarlos. */
export async function obtenerPoliciasActivos({ signal } = {}) {
  const datos = await solicitarApi('/pantalla/policias', { signal });
  if (!Array.isArray(datos) || datos.some((p) => !Number.isSafeInteger(p?.id) || p.id <= 0
    || typeof p.nombre !== 'string' || (p.documento != null && typeof p.documento !== 'string'))) {
    throw new Error('La API devolvió una lista de policías inválida.');
  }
  return datos.map((p) => ({ id: p.id, nombre: p.nombre, documento: p.documento ?? null }));
}

/** Una persona del checklist, validada. */
function adaptarPersonaChecklist(p) {
  if (!Number.isSafeInteger(p?.usuario_id) || p.usuario_id <= 0 || typeof p.servida !== 'boolean'
    || (p.asistencia_id != null && !Number.isSafeInteger(p.asistencia_id))) {
    throw new Error('La API devolvió un checklist inválido.');
  }
  return {
    id: p.usuario_id,
    nombre: p.nombre || `Comensal ${p.usuario_id}`,
    categoria: p.categoria ?? null,
    servicio: p.servicio ?? null,
    turno: p.turno ?? null,
    servida: p.servida,
    metodo: p.metodo ?? null,
    asistenciaId: p.asistencia_id ?? null,
    fechaHora: p.fecha_hora ?? null,
    anulable: p.anulable === true,
  };
}

/** Una ración de policía de la comida en curso, validada. */
function adaptarPoliciaChecklist(p) {
  if (!Number.isSafeInteger(p?.racion_id) || p.racion_id <= 0 || typeof p.nombre !== 'string') {
    throw new Error('La API devolvió un checklist inválido.');
  }
  return {
    id: p.racion_id,
    nombre: p.nombre,
    fechaHora: p.fecha_hora ?? null,
    origen: p.origen === 'checklist' ? 'checklist' : 'huella',
    anulable: p.anulable === true,
  };
}

/**
 * GET /pantalla/checklist: quiénes tienen derecho a la comida en curso (turno
 * de 12 h o más y categoría permitida, lo decide el servidor) y si ya la
 * recibieron. Fuera de horario la lista viene vacía.
 */
export async function obtenerChecklist({ signal } = {}) {
  const dato = await solicitarApi('/pantalla/checklist', { signal });
  if (typeof dato?.fuera_de_horario !== 'boolean' || !Array.isArray(dato.personas)) {
    throw new Error('La API devolvió un checklist inválido.');
  }
  return {
    momento: dato.momento ?? null,
    fueraDeHorario: dato.fuera_de_horario,
    comidaId: dato.comida_id ?? null,
    comida: dato.comida ?? null,
    fechaComida: dato.fecha_comida ?? null,
    personas: dato.personas.map(adaptarPersonaChecklist),
    policias: (Array.isArray(dato.policias) ? dato.policias : []).map(adaptarPoliciaChecklist),
  };
}

/**
 * POST /asistencias/checklist/policias (solo cocinera, desde el checklist o
 * Control Biométrico): una ración de policía, sin identidad. Vía libre, solo
 * con una comida en curso; un rechazo llega como { valido: false, motivo }.
 */
export async function registrarPoliciaEnChecklist({ signal } = {}) {
  const dato = await solicitarApi('/asistencias/checklist/policias', { method: 'POST', signal });
  if (typeof dato?.valido !== 'boolean') throw new Error('La API devolvió una respuesta inválida.');
  return dato;
}

/** DELETE /asistencias/checklist/policias/{id}: solo la marca propia, con la comida abierta. */
export async function desmarcarPoliciaEnChecklist(racionId, { signal } = {}) {
  if (!Number.isInteger(racionId) || racionId <= 0) throw new Error('Ración inválida.');
  return solicitarApi(`/asistencias/checklist/policias/${racionId}`, {
    method: 'DELETE', motivosLocales: ['otra_cuenta'], signal,
  });
}

/**
 * POST /asistencias/checklist (solo cocinera). El servidor aplica las mismas
 * reglas que la huella: un rechazo llega como { valido: false, motivo }.
 */
export async function marcarEnChecklist(usuarioId, { signal } = {}) {
  if (!Number.isInteger(usuarioId) || usuarioId <= 0) throw new Error('Persona inválida.');
  const dato = await solicitarApi('/asistencias/checklist', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ usuario_id: usuarioId }),
    signal,
  });
  if (typeof dato?.valido !== 'boolean') throw new Error('La API devolvió una marcación inválida.');
  return dato;
}

/** DELETE /asistencias/checklist/{id}: solo la marca propia, con la comida abierta. */
export async function desmarcarEnChecklist(asistenciaId, { signal } = {}) {
  if (!Number.isInteger(asistenciaId) || asistenciaId <= 0) throw new Error('Ración inválida.');
  // 403 otra_cuenta es un rechazo de esa marca, no una sección vedada.
  return solicitarApi(`/asistencias/checklist/${asistenciaId}`, {
    method: 'DELETE', motivosLocales: ['otra_cuenta'], signal,
  });
}

/**
 * POST /asistencias/lecturas/{id}/identificar-policia (solo cocinera): la
 * huella no reconocida era de un policía. `clave` se repite SOLO para
 * reintentar la misma decisión. Devuelve { estado: 'registrada' | 'conflicto'
 * | 'incierto', ... }.
 */
export async function identificarComoPolicia(lecturaId, vinculoId, { clave, signal } = {}) {
  if (!Number.isInteger(lecturaId) || lecturaId <= 0) throw new Error('Lectura inválida.');
  if (!Number.isInteger(vinculoId) || vinculoId <= 0) throw new Error('Elija al policía.');
  if (!esClaveIdempotencia(clave)) throw new Error('Clave de idempotencia inválida.');
  let dato;
  try {
    dato = await solicitarApi(`/asistencias/lecturas/${lecturaId}/identificar-policia`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': clave },
      body: JSON.stringify({ vinculo_id: vinculoId }),
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    if (error instanceof ErrorApi && error.status >= 400 && error.status < 500) {
      return { estado: 'conflicto', motivo: error.datos?.motivo ?? null,
        detalle: error.datos?.detail ?? error.message };
    }
    return { estado: 'incierto', detalle: 'No se pudo confirmar la entrega. Repita la confirmación: no se duplica.' };
  }
  if (dato?.valido !== true || dato.lectura_id !== lecturaId || !Number.isSafeInteger(dato.racion_id)) {
    return { estado: 'incierto', detalle: 'La respuesta del servidor no se pudo leer. Repita la confirmación: no se duplica.' };
  }
  return { estado: 'registrada', nombre: dato.nombre, comida: dato.comida ?? null, reintento: dato.reintento === true };
}

/** Motivos de 409 que dicen que esa lectura ya no se puede identificar. */
export const CONFLICTOS_DE_LECTURA = [
  'lectura_ya_resuelta',
  'lectura_no_resoluble',
  'servicio_distinto',
  'servicio_no_determinable',
  'reloj_inconsistente',
];

function respuestaIdentificacionValida(dato, lecturaId, usuarioId) {
  if (!dato || typeof dato.valido !== 'boolean' || !['registrada', 'rechazada'].includes(dato.resultado)
    || dato.valido !== (dato.resultado === 'registrada')
    || dato.lectura_id !== lecturaId || dato.usuario_id !== usuarioId
    || !Number.isInteger(dato.intervencion_id) || typeof dato.titulo !== 'string'
    || typeof dato.detalle !== 'string' || typeof dato.reintento !== 'boolean') {
    return false;
  }
  return dato.resultado === 'registrada' ? Number.isInteger(dato.asistencia_id) : dato.asistencia_id == null;
}

/**
 * POST /asistencias/lecturas/{lecturaId}/identificar con la cabecera
 * `Idempotency-Key`. Nunca lanza por un resultado del servidor: devuelve uno
 * de estos estados, para que cocina decida qué ofrecer.
 *
 * - `registrada`: la única ENTREGA. Trae nombre, comida y asistencia.
 * - `rechazada`: 200 con `valido: false` (sin_derecho, duplicado). Un intento
 *   sin entrega; nunca se le llama entrega.
 * - `conflicto`: 4xx sobre la lectura o la solicitud (ya resuelta, fuera del
 *   servicio, clave reutilizada, comensal inexistente…). Con `motivo` y, en
 *   `lectura_ya_resuelta`, `resueltaPorMi` (nunca quién fue).
 * - `en_curso`: 409 `intervencion_en_curso`. Repetir con la MISMA clave.
 * - `incierto`: no se sabe qué quedó (503 `resultado_incierto`, otro 5xx,
 *   red, tiempo de espera o respuesta ilegible). Repetir con la MISMA clave
 *   recupera lo confirmado, si lo hubo; nunca se afirma que no hubo entrega.
 * - `error`: sesión o permiso (401, 403, 428), que ya siguió el manejo
 *   central; el servidor no ejecutó nada.
 *
 * La misma clave con la misma persona es la misma decisión: el servidor
 * devuelve lo guardado (`reintento: true`) sin reevaluar nada.
 */
export async function identificarLectura(lecturaId, usuarioId, { clave, signal } = {}) {
  if (!Number.isInteger(lecturaId) || lecturaId <= 0) throw new Error('Lectura inválida.');
  if (!Number.isInteger(usuarioId) || usuarioId <= 0) throw new Error('Seleccione un comensal del padrón.');
  if (!esClaveIdempotencia(clave)) throw new Error('Clave de idempotencia inválida.');

  let dato;
  try {
    dato = await solicitarApi(`/asistencias/lecturas/${lecturaId}/identificar`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': clave },
      body: JSON.stringify({ usuario_id: usuarioId }),
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    return resultadoDeFalloIdentificacion(error);
  }

  if (!respuestaIdentificacionValida(dato, lecturaId, usuarioId)) {
    return {
      estado: 'incierto',
      detalle: 'La respuesta del servidor no se pudo leer. Repita la confirmación: se recupera lo que haya quedado registrado.',
    };
  }
  const comun = {
    titulo: dato.titulo,
    detalle: dato.detalle,
    reintento: dato.reintento,
    lecturaId: dato.lectura_id,
    intervencionId: dato.intervencion_id,
    usuarioId: dato.usuario_id,
    nombre: textoONull(dato.nombre),
    comida: dato.comida ?? null,
    fechaComida: dato.fecha_comida ?? null,
    momento: dato.momento ?? null,
  };
  if (dato.resultado === 'registrada') {
    return {
      estado: 'registrada',
      ...comun,
      asistenciaId: dato.asistencia_id,
      racionesRestantes: Number.isInteger(dato.raciones_restantes) ? dato.raciones_restantes : null,
    };
  }
  return { estado: 'rechazada', ...comun, motivo: dato.motivo ?? null };
}

function resultadoDeFalloIdentificacion(error) {
  if (!(error instanceof ErrorApi)) {
    return {
      estado: 'incierto',
      detalle: `No llegó una respuesta del servidor (${error.message}). Repita la confirmación: se recupera lo que haya quedado registrado.`,
    };
  }
  const datos = error.datos ?? {};
  const detalle = detalleDe(datos, error.message);
  if (error.status >= 500 || error.status === 408) {
    return {
      estado: 'incierto',
      motivo: datos.motivo ?? null,
      detalle: datos.motivo === 'resultado_incierto' ? detalle
        : `El servidor no pudo confirmar el resultado (HTTP ${error.status}). Repita la confirmación: se recupera lo que haya quedado registrado.`,
    };
  }
  if (error.status === 409 && datos.motivo === 'intervencion_en_curso') {
    return { estado: 'en_curso', motivo: datos.motivo, detalle };
  }
  if ([401, 403, 428].includes(error.status)) {
    return { estado: 'error', motivo: datos.motivo ?? null, detalle };
  }
  return {
    estado: 'conflicto',
    motivo: datos.motivo ?? null,
    detalle,
    resueltaPorMi: datos.resuelta_por_mi === true,
    reintento: datos.reintento === true,
  };
}

const RESULTADOS_INTERVENCION = ['registrada', 'rechazada'];
const ESTADOS_LECTURA = ['pendiente', 'resuelta'];

function adaptarIntervencion(dato) {
  const decision = dato?.decision_original;
  const final = dato?.resultado_final;
  if (!Number.isInteger(dato?.id) || typeof dato.clave_evento !== 'string'
    || !RESULTADOS_INTERVENCION.includes(dato.resultado) || typeof dato.momento !== 'string'
    || !Number.isInteger(decision?.lectura_id) || typeof decision.resultado !== 'string'
    || !Number.isInteger(dato.cuenta?.id) || typeof dato.cuenta.usuario !== 'string'
    || !Number.isInteger(dato.comensal?.usuario_id) || typeof dato.servicio_usado !== 'object'
    || typeof final?.entrega_registrada !== 'boolean'
    || final.entrega_registrada !== (dato.resultado === 'registrada')
    || !ESTADOS_LECTURA.includes(dato.estado_actual_lectura)) {
    throw new Error('La API devolvió una intervención de cocina inválida.');
  }
  const servicio = dato.servicio_usado ?? {};
  return {
    id: dato.id,
    clave: dato.clave_evento,
    resultado: dato.resultado,
    motivoRechazo: dato.motivo_rechazo ?? null,
    momento: dato.momento,
    decisionOriginal: {
      lecturaId: decision.lectura_id,
      resultado: decision.resultado,
      motivo: decision.motivo ?? null,
      fechaHora: decision.fecha_hora ?? null,
      dispositivo: decision.dispositivo ?? null,
    },
    cuenta: { id: dato.cuenta.id, usuario: dato.cuenta.usuario, nombre: textoONull(dato.cuenta.nombre) },
    comensal: {
      usuarioId: dato.comensal.usuario_id,
      nombre: textoONull(dato.comensal.nombre),
      categoria: textoONull(dato.comensal.categoria),
    },
    servicio: {
      comidaId: servicio.comida_id ?? null,
      comida: servicio.comida ?? null,
      fechaComida: servicio.fecha_comida ?? null,
      reconstruido: servicio.origen === 'reconstruido_por_horario',
    },
    entregaRegistrada: final.entrega_registrada,
    asistenciaId: final.asistencia_id ?? null,
    lecturaResuelta: dato.estado_actual_lectura === 'resuelta',
  };
}

/**
 * GET /intervenciones-cocina (solo jefa): los intentos de identificación del
 * rango, la más reciente primero, paginados. Solo consulta: la jefa no
 * aprueba ni ejecuta nada. Sin `desde`/`hasta` el servidor usa hoy.
 * `total` y `totales` cubren todo el filtro, no solo la página.
 */
export async function obtenerIntervencionesCocina({
  desde, hasta, resultado, comidaId, limite = 50, desplazamiento = 0, signal,
} = {}) {
  try {
    const parametros = new URLSearchParams({ limite: String(limite), desplazamiento: String(desplazamiento) });
    if (desde != null) parametros.set('desde', formatearFechaEstado(desde));
    if (hasta != null) parametros.set('hasta', formatearFechaEstado(hasta));
    if (resultado) parametros.set('resultado', resultado);
    if (comidaId != null) parametros.set('comida_id', String(comidaId));
    const pagina = await solicitarApi(`/intervenciones-cocina?${parametros}`, { signal });
    if (!pagina || typeof pagina.desde !== 'string' || typeof pagina.hasta !== 'string'
      || !Number.isInteger(pagina.total) || pagina.total < 0
      || !Number.isInteger(pagina.limite) || !Number.isInteger(pagina.desplazamiento)
      || !Number.isInteger(pagina.totales?.registradas) || !Number.isInteger(pagina.totales?.rechazadas)
      || !Array.isArray(pagina.datos)) {
      throw new Error('La API devolvió una página de intervenciones inválida.');
    }
    return {
      desde: pagina.desde,
      hasta: pagina.hasta,
      total: pagina.total,
      limite: pagina.limite,
      desplazamiento: pagina.desplazamiento,
      totales: { registradas: pagina.totales.registradas, rechazadas: pagina.totales.rechazadas },
      datos: pagina.datos.map(adaptarIntervencion),
    };
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(`No se pudieron cargar las intervenciones de cocina. ${error.message}`, { cause: error });
  }
}

/* ----------------------------- Historial nominal de la API */

function validarPagina(pagina) {
  if (!Array.isArray(pagina?.datos) || !Array.isArray(pagina.comidas)
    || !Number.isInteger(pagina.total) || pagina.total < 0
    || !Number.isInteger(pagina.limite) || pagina.limite < 1
    || !Number.isInteger(pagina.desplazamiento) || pagina.desplazamiento < 0
    || (pagina.datos.length === 0 && pagina.desplazamiento < pagina.total)) {
    throw new Error('La API devolvió una página de historial inválida.');
  }
}

function personaDeHistorial(persona) {
  if (!Number.isInteger(persona.usuario_id)) throw new Error('Usuario inválido en el historial.');
  return {
    ...persona,
    id: persona.usuario_id,
    nombre: persona.nombre_completo || `Usuario ${persona.usuario_id} (sin ficha)`,
    categoria: persona.categoria || 'Sin categoría',
    servicio: persona.servicio || 'Sin servicio',
    legajo: persona.carnet_identidad || 'Sin carnet',
    turno: persona.turno || null,
  };
}

async function consultarHistorial(ruta, parametros, signal, mensual = false) {
  try {
    const pagina = await solicitarApi(`${ruta}?${new URLSearchParams(parametros)}`, { signal });
    validarPagina(pagina);
    const comidas = pagina.comidas.map((comida) => ({ ...comida, id: comida.comida_id, etiqueta: comida.nombre }));
    return {
      ...pagina,
      comidas,
      datos: pagina.datos.map((persona) => {
        const base = personaDeHistorial(persona);
        if (mensual) {
          return {
            ...base,
            servicio: base.servicio,
            totalAsignadas: persona.total_asignadas,
            totalRecibidas: persona.total_recibidas,
            totalNoRecibidas: persona.total_no_recibidas,
            totalPendientes: persona.total_pendientes,
            totales: comidas.map((columna) => {
              const comida = persona.totales?.find((dato) => dato.comida_id === columna.id);
              if (!comida) throw new Error('Falta una comida en el historial mensual.');
              return { ...comida, id: columna.id, etiqueta: columna.etiqueta,
                noRecibidas: comida.no_recibidas };
            }),
          };
        }
        return {
          ...base,
          comidas: comidas.map((columna) => {
            const comida = persona.comidas?.find((dato) => dato.comida_id === columna.id);
            if (!comida || !['recibida', 'no_recibida', 'pendiente', 'no_aplica'].includes(comida.estado)) {
              throw new Error('Estado de comida inválido en el historial.');
            }
            return {
              ...comida, id: columna.id, etiqueta: columna.etiqueta,
              estadoApi: comida.estado,
              aplica: comida.estado !== 'no_aplica',
              estado: comida.estado === 'recibida' ? true : comida.estado === 'no_recibida' ? false : null,
            };
          }),
        };
      }),
    };
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(`No se pudo cargar el historial. ${error.message}`, { cause: error });
  }
}

export function obtenerHistorialDiarioPersonal({ fecha = new Date(), limite = 50, desplazamiento = 0, signal } = {}) {
  return consultarHistorial('/historial/diario', {
    fecha: typeof fecha === 'string' ? fecha : fechaArchivo(fecha), limite, desplazamiento,
  }, signal);
}

export function obtenerHistorialMensualPersonal({
  mesIndice = new Date().getMonth(), gestion = new Date().getFullYear(),
  limite = 50, desplazamiento = 0, signal,
} = {}) {
  return consultarHistorial('/historial/mensual', { gestion, mes: mesIndice + 1, limite, desplazamiento }, signal, true);
}

/**
 * GET /pantalla/dia-personal: la ficha del día de una persona, con la misma
 * forma que una fila de /historial/diario pero abierta también a la cocinera.
 * Sin `fecha`, el servidor usa su hoy. Devuelve null si ese día no figura
 * (`datos` vacío) o si la persona no existe (404).
 */
export async function obtenerDiaPersonal(usuarioId, { fecha, signal } = {}) {
  const parametros = { persona_id: usuarioId };
  if (fecha !== undefined && fecha !== null) {
    parametros.fecha = typeof fecha === 'string' ? fecha : fechaArchivo(fecha);
  }
  try {
    const pagina = await consultarHistorial('/pantalla/dia-personal', parametros, signal);
    return pagina.datos[0] ?? null;
  } catch (error) {
    if (error.cause?.status === 404) return null;
    throw error;
  }
}

/** Fechas del servidor en hora local. */
const FECHA_HORA_SERVIDOR = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/;

/** "2026-08-10T12:05:30.123" → Date local con esa misma hora de pared. */
export function fechaHoraDelServidor(texto) {
  const partes = typeof texto === 'string' ? FECHA_HORA_SERVIDOR.exec(texto) : null;
  if (!partes) return null;
  const [anio, mes, dia, hora, minuto, segundo = '0'] = partes.slice(1);
  const momento = new Date(Number(anio), Number(mes) - 1, Number(dia),
    Number(hora), Number(minuto), Number(segundo));
  return Number.isNaN(momento.getTime()) ? null : momento;
}

/** Valor de un <input type="datetime-local">: "2026-08-10T12:05". */
export function valorFechaHoraLocal(momento) {
  const dos = (numero) => String(numero).padStart(2, '0');
  return `${fechaArchivo(momento)}T${dos(momento.getHours())}:${dos(momento.getMinutes())}`;
}

/*
 * --- Lector biométrico (GET /monitoreo/estado, solo sistemas) ---
 * El endpoint devuelve un diagnóstico más amplio; la pantalla «Lector
 * biométrico» solo usa `lector`:
 *   {estado: 'desconocido', razon: 'sin_telemetria'}
 * Hoy el sistema no recibe señales del lector, así que ese es el único valor
 * válido: cualquier otro se rechaza en vez de mostrarse como si fuera cierto.
 * El resto del cuerpo (base, actividad, reloj, entorno) no se valida ni se
 * guarda: un campo ajeno al lector no debe impedir ver su estado.
 */
/* Hora local sin zona: una «Z» o un desfase no están confirmados y se rechazan. */
const FECHA_HORA_SIN_ZONA = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d{1,6})?)?$/;
const DIAS_POR_MES = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

const esBisiesto = (anio) => (anio % 4 === 0 && anio % 100 !== 0) || anio % 400 === 0;

/*
 * Componentes comprobados uno a uno, sin `new Date`: un 31 de febrero o una
 * hora 24 se rechazan en vez de normalizarse al día u hora siguiente.
 */
function esDiaValido(anio, mes, dia) {
  if (mes < 1 || mes > 12 || dia < 1) return false;
  return dia <= (mes === 2 && esBisiesto(anio) ? 29 : DIAS_POR_MES[mes - 1]);
}

function esFechaHora(valor) {
  const partes = typeof valor === 'string' ? FECHA_HORA_SIN_ZONA.exec(valor) : null;
  if (!partes) return false;
  const [anio, mes, dia, hora, minuto, segundo = 0] = partes.slice(1)
    .map((parte) => (parte === undefined ? undefined : Number(parte)));
  return esDiaValido(anio, mes, dia) && hora <= 23 && minuto <= 59 && segundo <= 59;
}

/**
 * Valida el cuerpo de GET /monitoreo/estado y devuelve solo lo del lector.
 * Ningún estado desconocido por el contrato se convierte en otro.
 */
export function adaptarEstadoMonitoreo(dato) {
  if (!dato || typeof dato !== 'object' || Array.isArray(dato)) {
    throw new Error('La API devolvió un estado del lector inválido (cuerpo).');
  }
  if (dato.lector?.estado !== 'desconocido' || dato.lector?.razon !== 'sin_telemetria') {
    throw new Error('La API devolvió un estado del lector inválido (lector).');
  }
  return { lector: { estado: dato.lector.estado, razon: dato.lector.razon } };
}

/**
 * GET /monitoreo/estado: estado del lector para sistemas. Pasa por
 * `solicitarApi` sin `manejoPropio`, así 401/403/428 siguen el manejo
 * central de la sesión. El error conserva su causa (con `status`).
 */
export async function obtenerEstadoMonitoreo({ signal } = {}) {
  try {
    return adaptarEstadoMonitoreo(await solicitarApi('/monitoreo/estado', { signal }));
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(`No se pudo consultar el lector biométrico. ${error.message}`, { cause: error });
  }
}

/* ------------------------------------------------------------------ *
 * Administración de cuentas (solo rol sistemas, sección admin)
 *
 * GET  /admin/cuentas → [CuentaApi]
 * GET  /admin/candidatos?busqueda=&limite= → [CandidatoApi] (2+ caracteres)
 * POST /admin/cuentas {rol, usuario_turnos_id, password}
 *   | {rol, username, nombre, password} → 201 {cuenta}
 * POST /admin/cuentas/{id}/desactivar | /reactivar → CuentaApi
 * POST /admin/cuentas/{id}/clave {password} → {cuenta}
 *
 * CuentaApi = {id, username, rol, activo, debe_cambiar,
 *   usuario_turnos_id|null, vinculada, nombre|null, categoria|null,
 *   creada, ultimo_ingreso|null}
 * CandidatoApi = {usuario_turnos_id, login, nombre, categoria,
 *   cuenta_id|null}
 *
 * Los motivos del backend se traducen a español claro. Root escribe la
 * contraseña definitiva: la cuenta entra con ella sin cambio obligatorio, y
 * la contraseña nunca vuelve del servidor ni se guarda en el navegador.
 * ------------------------------------------------------------------ */

/** Roles que puede tener una cuenta devuelta por la API. */
const ROLES_CUENTA = ['sistemas', 'jefa', 'cocinera'];

/** Roles permitidos al crear: nunca se crea otra cuenta de sistemas. */
const ROLES_CUENTA_NUEVA = ['jefa', 'cocinera'];

/** Motivos del backend con el texto que lee la jefatura. */
const MOTIVOS_ADMIN = {
  username_en_uso: 'Ese nombre de usuario ya está en uso.',
  persona_ya_tiene_cuenta: 'Esa persona ya tiene una cuenta.',
  persona_inexistente: 'Esa persona ya no figura en el padrón.',
  login_invalido: 'El nombre de usuario no es válido. Use letras, números, puntos o guiones.',
  rol_no_permitido: 'Solo se pueden crear cuentas de Cocinera o Jefa.',
  no_puede_desactivarse_a_si_misma: 'No puede desactivar su propia cuenta.',
  ultima_cuenta_sistemas: 'No se puede desactivar: es la última cuenta de Sistemas.',
  cuenta_eliminada: 'Esta cuenta fue eliminada de la lista y no se puede reactivar.',
  nombre_del_padron: 'El nombre de esta cuenta se administra desde el padrón.',
  rol_sistemas_protegido: 'El rol de una cuenta de Sistemas no se puede cambiar desde este formulario.',
  password_rechazada: 'La contraseña no cumple las reglas: al menos 8 caracteres y distinta del usuario.',
};

/** Texto claro del motivo, o null si no es un motivo conocido. */
function mensajeDeMotivoAdmin(motivo, detalle) {
  // Una contraseña rechazada trae del servidor la regla exacta que no cumple.
  if (motivo === 'password_rechazada' && typeof detalle === 'string' && detalle) return detalle;
  return typeof motivo === 'string' ? MOTIVOS_ADMIN[motivo] ?? null : null;
}

function adaptarCuenta(dato) {
  if (!Number.isInteger(dato?.id) || dato.id <= 0
    || typeof dato.username !== 'string' || dato.username.length === 0
    || !ROLES_CUENTA.includes(dato.rol)
    || typeof dato.activo !== 'boolean'
    || typeof dato.debe_cambiar !== 'boolean'
    || !(dato.usuario_turnos_id === null || (Number.isInteger(dato.usuario_turnos_id) && dato.usuario_turnos_id > 0))
    || typeof dato.vinculada !== 'boolean'
    || !(dato.nombre === null || typeof dato.nombre === 'string')
    || !(dato.categoria === null || typeof dato.categoria === 'string')
    || typeof dato.creada !== 'string' || dato.creada.length === 0
    || !(dato.ultimo_ingreso === null || typeof dato.ultimo_ingreso === 'string')) {
    throw new Error('La API devolvió una cuenta inválida.');
  }
  return {
    id: dato.id,
    username: dato.username,
    rol: dato.rol,
    activo: dato.activo,
    debeCambiar: dato.debe_cambiar,
    usuarioTurnosId: dato.usuario_turnos_id,
    vinculada: dato.vinculada,
    nombre: dato.nombre,
    categoria: dato.categoria,
    creada: dato.creada,
    ultimoIngreso: dato.ultimo_ingreso,
  };
}

function adaptarCandidato(dato) {
  if (!Number.isInteger(dato?.usuario_turnos_id) || dato.usuario_turnos_id <= 0
    || typeof dato.login !== 'string' || dato.login.length === 0
    || typeof dato.nombre !== 'string' || dato.nombre.length === 0
    || !(typeof dato.categoria === 'string' || dato.categoria === null)
    || !(dato.cuenta_id === null || (Number.isInteger(dato.cuenta_id) && dato.cuenta_id > 0))) {
    throw new Error('La API devolvió un candidato inválido.');
  }
  return {
    usuarioTurnosId: dato.usuario_turnos_id,
    login: dato.login,
    nombre: dato.nombre,
    categoria: dato.categoria,
    cuentaId: dato.cuenta_id,
    tieneCuenta: dato.cuenta_id !== null,
  };
}

function adaptarCuentaRespuesta(dato) {
  if (!dato || typeof dato !== 'object') {
    throw new Error('La API devolvió una cuenta inválida.');
  }
  return { cuenta: adaptarCuenta(dato.cuenta) };
}

/** La contraseña que escribe root: texto no vacío; las reglas las decide el servidor. */
function exigirClave(password) {
  if (typeof password !== 'string' || password.length === 0) {
    throw new Error('Escriba la contraseña de la cuenta.');
  }
}

/** GET /admin/cuentas: todas las cuentas del comedor. */
export async function obtenerCuentas({ signal } = {}) {
  try {
    const cuentas = await solicitarApi('/admin/cuentas', { signal });
    if (!Array.isArray(cuentas)) {
      throw new Error('La API devolvió una lista de cuentas inválida.');
    }
    return cuentas.map(adaptarCuenta);
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(`No se pudieron cargar las cuentas. ${error.message}`);
  }
}

/** GET /admin/candidatos: personas del padrón que coinciden (2+ caracteres). */
export async function buscarCandidatos(busqueda, { limite = 20, signal } = {}) {
  const termino = typeof busqueda === 'string' ? busqueda.trim() : '';
  if (termino.length < 2) {
    throw new Error('Escriba al menos 2 caracteres para buscar en el padrón.');
  }
  if (!Number.isInteger(limite) || limite < 1 || limite > 50) {
    throw new Error('Límite de búsqueda inválido.');
  }
  try {
    const parametros = new URLSearchParams({ busqueda: termino, limite: String(limite) });
    const candidatos = await solicitarApi(`/admin/candidatos?${parametros}`, { signal });
    if (!Array.isArray(candidatos)) {
      throw new Error('La API devolvió una lista de candidatos inválida.');
    }
    return candidatos.map(adaptarCandidato);
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(`No se pudo buscar en el padrón. ${error.message}`);
  }
}

/**
 * POST /admin/cuentas: crea la cuenta con la contraseña que elige root.
 * Desde el padrón: {rol, usuarioTurnosId, password}. Sin vínculo:
 * {rol, username, nombre, password}. La cuenta queda lista para ingresar.
 */
export async function crearCuenta({ rol, usuarioTurnosId = null, username = '', nombre = '', password = '' } = {}, { signal } = {}) {
  if (!ROLES_CUENTA_NUEVA.includes(rol)) {
    throw new Error(MOTIVOS_ADMIN.rol_no_permitido);
  }
  exigirClave(password);
  let cuerpo;
  if (usuarioTurnosId !== null && usuarioTurnosId !== undefined) {
    if (!Number.isInteger(usuarioTurnosId) || usuarioTurnosId <= 0) {
      throw new Error('Elija una persona del padrón.');
    }
    cuerpo = { rol, usuario_turnos_id: usuarioTurnosId, password };
  } else {
    const usuario = typeof username === 'string' ? username.trim().toLowerCase() : '';
    const nombreLimpio = typeof nombre === 'string' ? nombre.trim() : '';
    if (!usuario) throw new Error('Escriba el nombre de usuario.');
    if (!nombreLimpio) throw new Error('Escriba el nombre de la persona.');
    cuerpo = { rol, username: usuario, nombre: nombreLimpio, password };
  }
  try {
    return adaptarCuentaRespuesta(await solicitarApi('/admin/cuentas', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cuerpo),
      signal,
    }));
  } catch (error) {
    if (signal?.aborted) throw error;
    const mensaje = mensajeDeMotivoAdmin(error.datos?.motivo, error.datos?.detail);
    if (mensaje) throw new Error(mensaje);
    throw new Error(`No se pudo crear la cuenta. ${error.message}`);
  }
}

async function cambiarEstadoCuenta(id, ruta, frase, { signal } = {}) {
  if (!Number.isInteger(id) || id <= 0) {
    throw new Error('Cuenta inválida.');
  }
  try {
    return adaptarCuenta(await solicitarApi(ruta, { method: 'POST', signal }));
  } catch (error) {
    if (signal?.aborted) throw error;
    const mensaje = mensajeDeMotivoAdmin(error.datos?.motivo);
    if (mensaje) throw new Error(mensaje);
    throw new Error(`${frase} ${error.message}`);
  }
}

/** POST /admin/cuentas/{id}/desactivar. */
export function desactivarCuenta(id, { signal } = {}) {
  return cambiarEstadoCuenta(id, `/admin/cuentas/${id}/desactivar`, 'No se pudo desactivar la cuenta.', { signal });
}

/** POST /admin/cuentas/{id}/reactivar. */
export function reactivarCuenta(id, { signal } = {}) {
  return cambiarEstadoCuenta(id, `/admin/cuentas/${id}/reactivar`, 'No se pudo reactivar la cuenta.', { signal });
}

/** PATCH /admin/cuentas/{id}: conserva usuario, contraseña e historial. */
export async function editarCuenta(id, cambios, { signal } = {}) {
  if (!Number.isInteger(id) || id <= 0) throw new Error('Cuenta inválida.');
  const cuerpo = {};
  if (cambios?.nombre !== undefined) {
    if (typeof cambios.nombre !== 'string' || !cambios.nombre.trim() || cambios.nombre.trim().length > 100) {
      throw new Error('Escriba un nombre de hasta 100 caracteres.');
    }
    cuerpo.nombre = cambios.nombre.trim();
  }
  if (cambios?.rol !== undefined) {
    if (!['cocinera', 'jefa', 'sistemas'].includes(cambios.rol)) throw new Error('Rol inválido.');
    cuerpo.rol = cambios.rol;
  }
  if (!Object.keys(cuerpo).length) throw new Error('No hay cambios para guardar.');
  try {
    return adaptarCuenta(await solicitarApi(`/admin/cuentas/${id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cuerpo), signal,
    }));
  } catch (error) {
    if (signal?.aborted) throw error;
    const mensaje = mensajeDeMotivoAdmin(error.datos?.motivo, error.datos?.detail);
    throw new Error(mensaje || `No se pudo editar la cuenta. ${error.message}`);
  }
}

/** Baja lógica: desactiva y oculta; conserva la cuenta y su historial. */
export async function eliminarCuenta(id, { signal } = {}) {
  if (!Number.isInteger(id) || id <= 0) throw new Error('Cuenta inválida.');
  try {
    await solicitarApi(`/admin/cuentas/${id}`, { method: 'DELETE', signal });
  } catch (error) {
    if (signal?.aborted) throw error;
    const mensaje = mensajeDeMotivoAdmin(error.datos?.motivo, error.datos?.detail);
    throw new Error(mensaje || `No se pudo eliminar la cuenta. ${error.message}`);
  }
}

/** POST /admin/cuentas/{id}/clave: root fija la contraseña nueva; se cierran sus sesiones. */
export async function cambiarClaveCuenta(id, password, { signal } = {}) {
  if (!Number.isInteger(id) || id <= 0) {
    throw new Error('Cuenta inválida.');
  }
  exigirClave(password);
  try {
    return adaptarCuentaRespuesta(await solicitarApi(`/admin/cuentas/${id}/clave`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
      signal,
    }));
  } catch (error) {
    if (signal?.aborted) throw error;
    const mensaje = mensajeDeMotivoAdmin(error.datos?.motivo, error.datos?.detail);
    if (mensaje) throw new Error(mensaje);
    throw new Error(`No se pudo cambiar la contraseña. ${error.message}`);
  }
}


/* ------------------------------------------------------------------ *
 * Reglas del sistema: horarios de comida (solo sistemas)
 *
 * GET  /reglas/horarios → [HorarioRegla]   (sin query: la versión de cada
 *   comida que rige a la hora del servidor, una fila por comida)
 * GET  /reglas/horarios/historial?comida_id= → [HorarioRegla]
 * POST /reglas/horarios {comida_id, hora_inicio, hora_fin, base_horario_id}
 *   → 201 HorarioRegla. Las cuatro claves son obligatorias y no hay otras:
 *   el horario rige desde el instante en que el servidor lo guarda.
 *
 * HorarioRegla = {horario_id, comida_id, comida|null, hora_inicio "HH:MM:SS",
 *   hora_fin, cruza_medianoche, vigente_desde (datetime sin zona),
 *   vigente_hasta|null, motivo|null, creada_por|null, creada,
 *   estado: vigente|anterior|inactiva}
 *
 * Los horarios ya no se programan ni se borran, y el derecho a comer dejó
 * de ser editable desde la interfaz: acá no queda ninguna llamada de
 * escritura a esas rutas. El backend decide y valida; acá solo se adapta
 * snake_case, se valida la forma y se traducen los motivos.
 *
 * GET /cuentas → [CuentaLecturaApi] (para la jefa; sin cuentas sistemas)
 * CuentaLecturaApi = {id, username, nombre|null, rol, activo,
 *   debe_cambiar, ultimo_ingreso|null}
 * ------------------------------------------------------------------ */

/** Hora de la API: "11:30" o "11:30:00", con rangos válidos. */
function esHoraApi(valor) {
  const partes = typeof valor === 'string' ? /^(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(valor) : null;
  return partes !== null && Number(partes[1]) <= 23 && Number(partes[2]) <= 59
    && (partes[3] === undefined || Number(partes[3]) <= 59);
}

const ESTADOS_HORARIO = ['vigente', 'anterior', 'inactiva'];

/*
 * vigente_desde, vigente_hasta y creada son datetimes del servidor sin zona
 * y con hasta 6 decimales: se validan y se conservan como texto, sin
 * convertirlos a UTC ni a la zona de este equipo.
 */
function adaptarHorario(dato) {
  if (!Number.isInteger(dato?.horario_id) || dato.horario_id <= 0
    || !Number.isInteger(dato.comida_id) || dato.comida_id <= 0
    || !(dato.comida === null || (typeof dato.comida === 'string' && dato.comida.length > 0))
    || !esHoraApi(dato.hora_inicio)
    || !esHoraApi(dato.hora_fin)
    || typeof dato.cruza_medianoche !== 'boolean'
    || !esFechaHora(dato.vigente_desde)
    || !(dato.vigente_hasta === null || esFechaHora(dato.vigente_hasta))
    || !(dato.motivo === null || typeof dato.motivo === 'string')
    || !(dato.creada_por === null || typeof dato.creada_por === 'string')
    || !esFechaHora(dato.creada)
    || !ESTADOS_HORARIO.includes(dato.estado)) {
    throw new Error('La API devolvió un horario inválido.');
  }
  return {
    horarioId: dato.horario_id,
    comidaId: dato.comida_id,
    comida: dato.comida,
    horaInicio: dato.hora_inicio,
    horaFin: dato.hora_fin,
    cruzaMedianoche: dato.cruza_medianoche,
    vigenteDesde: dato.vigente_desde,
    vigenteHasta: dato.vigente_hasta,
    motivo: dato.motivo,
    creadaPor: dato.creada_por,
    creada: dato.creada,
    estado: dato.estado,
  };
}

function adaptarCuentaLectura(dato) {
  if (!Number.isInteger(dato?.id) || dato.id <= 0
    || typeof dato.username !== 'string' || dato.username.length === 0
    || !(dato.nombre === null || typeof dato.nombre === 'string')
    || !ROLES_CUENTA.includes(dato.rol)
    || typeof dato.activo !== 'boolean'
    || typeof dato.debe_cambiar !== 'boolean'
    || !(dato.ultimo_ingreso === null || typeof dato.ultimo_ingreso === 'string')) {
    throw new Error('La API devolvió una cuenta inválida.');
  }
  return {
    id: dato.id,
    username: dato.username,
    nombre: dato.nombre,
    rol: dato.rol,
    activo: dato.activo,
    debeCambiar: dato.debe_cambiar,
    ultimoIngreso: dato.ultimo_ingreso,
  };
}

/** GET /cuentas: cuentas para la vista de solo lectura de la jefa. */
export async function obtenerCuentasLectura({ signal } = {}) {
  try {
    const cuentas = await solicitarApi('/cuentas', { signal });
    if (!Array.isArray(cuentas)) {
      throw new Error('La API devolvió una lista de cuentas inválida.');
    }
    return cuentas.map(adaptarCuentaLectura);
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(`No se pudieron cargar las cuentas. ${error.message}`);
  }
}

/** Motivos del historial con el texto que lee sistemas. */
const MOTIVOS_HISTORIAL = {
  comida_inexistente: 'Esa comida ya no existe. Actualice la lista.',
};

/** GET /reglas/horarios: la versión de cada comida que rige ahora. Sin query. */
export async function obtenerHorariosVigentes({ signal } = {}) {
  try {
    const horarios = await solicitarApi('/reglas/horarios', { signal });
    if (!Array.isArray(horarios)) {
      throw new Error('La API devolvió horarios inválidos.');
    }
    return horarios.map(adaptarHorario);
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(`No se pudieron cargar los horarios. ${error.message}`);
  }
}

/** GET /reglas/horarios/historial: todas las versiones de una comida. */
export async function obtenerHistorialHorario(comidaId, { signal } = {}) {
  if (!Number.isInteger(comidaId) || comidaId <= 0) {
    throw new Error('Comida inválida.');
  }
  try {
    const versiones = await solicitarApi(`/reglas/horarios/historial?comida_id=${comidaId}`, { signal });
    if (!Array.isArray(versiones)) {
      throw new Error('La API devolvió un historial de horarios inválido.');
    }
    return versiones.map(adaptarHorario);
  } catch (error) {
    if (signal?.aborted) throw error;
    const mensaje = MOTIVOS_HISTORIAL[error.datos?.motivo];
    if (mensaje) throw new Error(mensaje);
    throw new Error(`No se pudo cargar el historial del horario. ${error.message}`);
  }
}

/**
 * Fallo de POST /reglas/horarios. `incierto` es true cuando el servidor pudo
 * haber guardado el cambio sin que lo sepamos (red, tiempo agotado, 5xx o una
 * respuesta ilegible): entonces nadie debe afirmar que no se guardó y hay que
 * recargar y comprobar antes de volver a enviar. `recargar` pide releer los
 * horarios antes de otro intento. `motivo` es el del servidor, si lo hubo.
 */
export class ErrorGuardadoHorario extends Error {
  constructor(mensaje, { motivo = null, status = null, incierto = false, recargar = false } = {}) {
    super(mensaje);
    this.name = 'ErrorGuardadoHorario';
    this.motivo = motivo;
    this.status = status;
    this.incierto = incierto;
    this.recargar = recargar;
  }
}

const RECARGAR_Y_COMPROBAR = 'Recargue los horarios y compruebe cómo quedaron antes de volver a guardar.';

/* 4xx con motivo: el servidor rechazó el cambio y no escribió nada. */
const MOTIVOS_GUARDADO = {
  version_desactualizada: {
    texto: 'Este horario cambió desde que lo abrió. Recargue los horarios, revise los valores actuales y vuelva a guardar si todavía corresponde.',
    recargar: true,
  },
  sin_cambios: { texto: 'El horario guardado ya es ese: no hay nada que cambiar.' },
  solapa_con_otra_comida: { texto: 'Esa franja se superpone con la de otra comida. Elija horas que no se crucen.' },
  instante_no_posterior: {
    texto: 'El reloj del sistema no es posterior a la última versión guardada de los horarios, por eso el cambio no se aplicó. Revise la hora del servidor.',
  },
  cambio_en_curso: { texto: 'Hay otro cambio de horarios en curso. Espere unos segundos y vuelva a intentarlo.' },
  versiones_abiertas_multiples: {
    texto: 'Esta comida tiene más de una versión abierta en la base de datos. Hay que corregir esos datos antes de guardar: avise a soporte.',
    recargar: true,
  },
  horario_invalido: { texto: 'El horario no es válido. Revise la hora de inicio y la de fin: no pueden ser iguales.' },
  comida_inexistente: { texto: 'Esa comida ya no existe. Recargue los horarios.', recargar: true },
};

/** Convierte lo que lanzó la petición en un ErrorGuardadoHorario. */
function errorDeGuardado(error) {
  if (!(error instanceof ErrorApi)) {
    /* Sin respuesta del servidor (red, tiempo agotado, cuerpo ilegible): no se sabe. */
    return new ErrorGuardadoHorario(
      `${error.message} No sabemos si el cambio se guardó. ${RECARGAR_Y_COMPROBAR}`,
      { incierto: true, recargar: true },
    );
  }
  const motivo = typeof error.datos?.motivo === 'string' ? error.datos.motivo : null;
  if (error.status >= 500) {
    const causa = motivo === 'cerrojo_ausente'
      ? 'El servidor no pudo completar el cambio: falta preparar el bloqueo de horarios (migraciones sin aplicar).'
      : `El servidor respondió con un error (HTTP ${error.status}).`;
    return new ErrorGuardadoHorario(
      `${causa} No sabemos si el cambio se guardó. ${RECARGAR_Y_COMPROBAR}`,
      { motivo, status: error.status, incierto: true, recargar: true },
    );
  }
  const conocido = MOTIVOS_GUARDADO[motivo];
  if (conocido) {
    return new ErrorGuardadoHorario(conocido.texto, {
      motivo, status: error.status, recargar: conocido.recargar === true,
    });
  }
  if (error.status === 422 && Array.isArray(error.datos?.detail)) {
    return new ErrorGuardadoHorario(
      'El servidor no aceptó los datos enviados. Revise la hora de inicio y la de fin.',
      { motivo, status: 422 },
    );
  }
  const detalle = typeof error.datos?.detail === 'string' && error.datos.detail
    ? error.datos.detail
    : error.message;
  return new ErrorGuardadoHorario(`No se pudo guardar el horario. ${detalle}`, { motivo, status: error.status });
}

/** "11:30" → "11:30:00"; "11:30:15" queda igual; otra forma → null. */
function horaConSegundos(valor) {
  if (!esHoraApi(valor)) return null;
  return valor.length === 5 ? `${valor}:00` : valor;
}

/**
 * POST /reglas/horarios: guarda el horario de una comida con efecto
 * inmediato. `baseHorarioId` es el `horario_id` de la versión abierta que se
 * editó, o null solo si se comprobó que la comida no tiene ninguna; si no se
 * sabe, no se envía. Un envío, sin reintentos: si el resultado es incierto,
 * el error lo dice (`incierto`) y quien llama debe recargar y comprobar.
 */
export async function guardarHorario({
  comidaId,
  horaInicio,
  horaFin,
  baseHorarioId,
} = {}, { signal } = {}) {
  if (!Number.isInteger(comidaId) || comidaId <= 0) {
    throw new ErrorGuardadoHorario('Comida inválida.');
  }
  const inicio = horaConSegundos(horaInicio);
  const fin = horaConSegundos(horaFin);
  if (inicio === null || fin === null) {
    throw new ErrorGuardadoHorario('Escriba la hora de inicio y la de fin.');
  }
  if (baseHorarioId !== null && (!Number.isInteger(baseHorarioId) || baseHorarioId <= 0)) {
    throw new ErrorGuardadoHorario('No se sabe qué versión del horario se está editando. Recargue los horarios.');
  }
  let cuerpo;
  try {
    cuerpo = await solicitarApi('/reglas/horarios', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        comida_id: comidaId,
        hora_inicio: inicio,
        hora_fin: fin,
        base_horario_id: baseHorarioId,
      }),
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw errorDeGuardado(error);
  }
  try {
    return adaptarHorario(cuerpo);
  } catch {
    throw new ErrorGuardadoHorario(
      `El servidor respondió, pero la respuesta no se pudo interpretar. No sabemos si el cambio se guardó. ${RECARGAR_Y_COMPROBAR}`,
      { incierto: true, recargar: true },
    );
  }
}
