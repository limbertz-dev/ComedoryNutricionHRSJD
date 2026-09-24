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
  desconocida: 'Huella no reconocida',
};

function horaDeMarcacion(fechaHora) {
  const momento = new Date(fechaHora);
  return Number.isNaN(momento.getTime()) ? '--:--:--' : horaLegible(momento);
}

/**
 * GET /pantalla/ultimas-marcaciones: el hilo real del lector, ya persistido.
 *
 * Incluye los rechazos, porque son justo lo que hay que ver frente al lector.
 * Sin `fecha` devuelve el día de hoy. La respuesta se adapta a la misma forma
 * que ya usa la tarjeta de marcaciones (`persona`, `hora`, `valido`, `titulo`),
 * para que la lista del servidor y la marcación recién enviada se pinten con
 * el mismo componente.
 */
export async function obtenerUltimasMarcaciones({ fecha, comidaId, limite = 20, signal } = {}) {
  try {
    const parametros = new URLSearchParams({ limite: String(limite) });
    if (fecha !== undefined && fecha !== null) parametros.set('fecha', formatearFechaEstado(fecha));
    if (comidaId !== undefined && comidaId !== null) parametros.set('comida_id', String(comidaId));
    const marcaciones = await solicitarApi(`/pantalla/ultimas-marcaciones?${parametros}`, { signal });
    if (!Array.isArray(marcaciones)) {
      throw new Error('La API devolvió una lista de marcaciones inválida.');
    }
    return marcaciones.map((dato) => {
      if (!Number.isInteger(dato?.id)) {
        throw new Error('La API devolvió una marcación sin identificador.');
      }
      const valido = typeof dato.valido === 'boolean' ? dato.valido : dato.resultado === 'aceptada';
      return {
        id: dato.id,
        usuarioId: dato.usuario_id ?? null,
        valido,
        titulo: valido ? 'Marcación válida'
          : MOTIVOS_LEGIBLES[dato.motivo] ?? (dato.motivo || 'Marcación rechazada'),
        hora: horaDeMarcacion(dato.fecha_hora),
        // Sin comida: el lector no llegó a resolver ningún turno para esa hora
        // (fuera de horario) o la lectura es de una huella no reconocida.
        comidaId: dato.comida_id ?? null,
        comida: dato.comida ?? null,
        persona: {
          id: dato.usuario_id ?? null,
          nombre: dato.nombre || 'Desconocido',
          categoria: dato.categoria || 'Sin clasificar',
        },
      };
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(`No se pudieron cargar las últimas marcaciones. ${error.message}`);
  }
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

/** Error HTTP con el código y el cuerpo JSON de la respuesta, si lo trae. */
export class ErrorApi extends Error {
  constructor(mensaje, status, datos) {
    super(mensaje);
    this.name = 'ErrorApi';
    this.status = status;
    this.datos = datos;
  }
}

/*
 * Toda petición lleva el token de la sesión. Un 401 vacía la sesión y
 * devuelve al Login con «Sesión expirada»; un 403 le avisa al panel para que
 * pinte «Sin permiso» en lugar de la sección; un 428 pide el cambio de
 * contraseña temporal. `manejoPropio` apaga esos avisos en /auth/login y
 * /auth/cambio-password, donde esos códigos hablan de la credencial tecleada
 * y los resuelve el propio formulario.
 */
async function solicitarApi(ruta, { signal, manejoPropio = false, ...opciones } = {}) {
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
      if (!manejoPropio) avisarPorStatus(respuesta.status);
      throw new ErrorApi(mensajeDeStatus(respuesta.status), respuesta.status, datos);
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

function avisarPorStatus(status) {
  if (status === 401) {
    borrarTokens();
    avisarSesion({ tipo: 'expirada' });
  } else if (status === 403) {
    avisarSesion({ tipo: 'prohibido' });
  } else if (status === 428) {
    avisarSesion({ tipo: 'cambio_requerido' });
  }
}

/*
 * --- Autenticación (contrato congelado) ---
 * POST /auth/login → 200 {access, refresh, rol, debe_cambiar}
 *                  | 401 {detalle} | 423 {detalle, reintento_en} | 428 {temporal: true}
 * POST /auth/cambio-password
 * GET  /auth/yo
 *
 * El contrato no fija los nombres del cuerpo de las peticiones: viven solo
 * aquí para ajustarlos en un único lugar al verificar contra el backend.
 */
const cuerpoLogin = (usuario, contrasena) => ({ usuario, contrasena });
const cuerpoCambio = ({ usuario, actual, nueva, conToken }) => ({
  ...(conToken ? {} : { usuario }),
  contrasena_actual: actual,
  contrasena_nueva: nueva,
});

/**
 * POST /auth/login. Devuelve lo que el Login tiene que mostrar:
 * `{ tipo: 'ok', rol, debeCambiar }` (los tokens ya quedan guardados),
 * `{ tipo: 'credencial', detalle }`, `{ tipo: 'bloqueada', detalle, reintentoEn }`
 * o `{ tipo: 'cambio' }`. Los errores de red o de servidor se lanzan.
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
      return { tipo: 'credencial', detalle: error.datos?.detalle || 'Usuario o contraseña incorrectos.' };
    }
    if (error.status === 423) {
      return {
        tipo: 'bloqueada',
        detalle: error.datos?.detalle || 'La cuenta está bloqueada temporalmente.',
        reintentoEn: momentoDeReintento(error.datos?.reintento_en),
      };
    }
    if (error.status === 428 && error.datos?.temporal === true) return { tipo: 'cambio' };
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
 * `reintento_en` como Date. El contrato no fija el formato: se aceptan
 * segundos restantes (número o texto numérico) y fecha ISO. null si no se
 * puede interpretar; el Login muestra entonces solo el `detalle`.
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
 * POST /auth/cambio-password y, si el servidor lo acepta, un login nuevo con
 * la contraseña recién puesta: así la sesión queda con tokens emitidos para
 * ella, sin depender de qué devuelva el cambio. Devuelve el resultado de
 * `iniciarSesion`.
 */
export async function cambiarContrasena({ usuario, actual, nueva, signal }) {
  const conToken = Boolean(leerTokens()?.access);
  try {
    await solicitarApi('/auth/cambio-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cuerpoCambio({ usuario, actual, nueva, conToken })),
      manejoPropio: true,
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(error.datos?.detalle || `No se pudo cambiar la contraseña. ${error.message}`);
  }
  return iniciarSesion(usuario, nueva, { signal });
}

/** GET /auth/yo: el rol de la sesión guardada, al abrir la app. */
export async function obtenerUsuarioActual({ signal } = {}) {
  const yo = await solicitarApi('/auth/yo', { signal });
  if (typeof yo?.rol !== 'string' || !yo.rol) {
    throw new Error('La API devolvió un usuario sin rol.');
  }
  return { rol: yo.rol };
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
 * POST /asistencias: el servidor resuelve todas las reglas de la marcación.
 * `personaId` siempre corresponde a users.id (usuario_id en la API), salvo
 * con `metodo: 'biometrico'`: ahí puede ser `null`, que es como el simulador
 * imita una huella que el lector no llegó a reconocer contra nadie del
 * padrón (a diferencia de "sin derecho", que sí identifica a la persona).
 *
 * `metodo` distingue quién originó la marcación y el backend lo usa: con
 * 'biometrico' guarda además la lectura del lector en su bitácora, con
 * 'manual' solo la asistencia. El simulador del lector manda 'biometrico'
 * justamente para recorrer el mismo camino que recorrerá el hardware; el
 * registro a mano de una ración se queda en 'manual', que es el valor por
 * omisión aquí.
 */
export async function marcarAsistencia(personaId, { persona, metodo = 'manual', signal } = {}) {
  try {
    const fallaBiometrica = personaId === null && metodo === 'biometrico';
    if (!fallaBiometrica && (!Number.isInteger(personaId) || personaId <= 0)) {
      throw new Error('Seleccione un comensal del padrón.');
    }
    const ficha = fallaBiometrica
      ? null
      : persona?.id === personaId
        ? persona
        : adaptarPersona(await solicitarApi(`/personal/${personaId}`, { signal }));
    const respuesta = await solicitarApi('/asistencias', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ usuario_id: personaId, metodo }),
      signal,
    });
    if (typeof respuesta?.valido !== 'boolean' || typeof respuesta.titulo !== 'string'
      || typeof respuesta.detalle !== 'string'
      || (respuesta.usuario_id != null && respuesta.usuario_id !== personaId)) {
      throw new Error('La API devolvió una marcación inválida.');
    }
    return {
      ...respuesta,
      id: (secuenciaEvento += 1),
      // La respuesta actual no trae hora: esta es la hora de recepción local.
      hora: horaLegible(new Date()),
      persona: ficha
        ? { ...ficha, nombre: respuesta.nombre || ficha.nombre }
        : { id: null, nombre: 'Huella no reconocida', categoria: 'Sin identificar', legajo: '—' },
      tiempo: respuesta.comida,
      motivo: respuesta.valido ? MOTIVOS.OK
        : respuesta.motivo === 'duplicado' ? MOTIVOS.YA_MARCO : respuesta.motivo,
    };
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(`No se pudo confirmar la marcación. ${error.message} Verifique el registro antes de volver a enviarla.`);
  }
}

/** Nombre conservado para compatibilidad; ahora exige una persona explícita. */
export async function simularMarcacion({ personal, personaId, signal }) {
  const persona = personal.find(({ id }) => id === personaId);
  if (!persona) {
    throw new Error('Seleccione un comensal del padrón antes de registrar.');
  }
  return marcarAsistencia(personaId, { persona, signal });
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
    || typeof grupo.equivalente !== 'number' || Number.isNaN(grupo.equivalente) || grupo.equivalente < 0) {
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
    throw new Error(`No se pudo cargar el historial. ${error.message}`);
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

/** El endpoint diario no filtra por usuario: busca la ficha entre sus páginas. */
export async function obtenerDiaPersonal(usuarioId, { fecha, signal } = {}) {
  let desplazamiento = 0;
  let pagina;
  do {
    pagina = await obtenerHistorialDiarioPersonal({ fecha, limite: 200, desplazamiento, signal });
    const persona = pagina.datos.find(({ id }) => id === usuarioId);
    if (persona) return persona;
    desplazamiento += pagina.datos.length;
  } while (desplazamiento < pagina.total);
  return null;
}
