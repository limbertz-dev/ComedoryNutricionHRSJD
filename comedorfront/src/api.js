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
        motivo: dato.motivo ?? null,
        dispositivo: dato.dispositivo ?? null,
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
 *
 * Fuera de simulación el servidor rechaza 'biometrico' desde el navegador
 * con 403 `biometrico_solo_lector`: ese rechazo no es «Sin permiso» de la
 * sección, así que vuelve como ErrorApi con el `detail` del servidor
 * (ver `esRechazoBiometricoSoloLector`) y nunca se reintenta como manual.
 */
export async function marcarAsistencia(personaId, { persona, metodo = 'manual', ahora = new Date(), signal } = {}) {
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
      motivosLocales: metodo === 'biometrico' ? [MOTIVO_BIOMETRICO_SOLO_LECTOR] : [],
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
      // La respuesta actual no trae hora: esta es la hora de recepción local,
      // o la del reloj del servidor cuando App la conoce (simulación).
      hora: horaLegible(ahora),
      persona: ficha
        ? { ...ficha, nombre: respuesta.nombre || ficha.nombre }
        : { id: null, nombre: 'Huella no reconocida', categoria: 'Sin identificar', legajo: '—' },
      tiempo: respuesta.comida,
      motivo: respuesta.valido ? MOTIVOS.OK
        : respuesta.motivo === 'duplicado' ? MOTIVOS.YA_MARCO : respuesta.motivo,
    };
  } catch (error) {
    if (signal?.aborted) throw error;
    if (metodo === 'biometrico' && esRechazoBiometricoSoloLector(error)) {
      throw new ErrorApi(
        detalleDe(error.datos, 'La marcación biométrica requiere un lector autorizado fuera de simulación.'),
        403,
        error.datos,
      );
    }
    throw new Error(`No se pudo confirmar la marcación. ${error.message} Verifique el registro antes de volver a enviarla.`);
  }
}

/** Motivo del 403 de POST /asistencias con 'biometrico' fuera de simulación. */
export const MOTIVO_BIOMETRICO_SOLO_LECTOR = 'biometrico_solo_lector';

/** true si `error` es el rechazo de una marcación biométrica fuera de simulación. */
export function esRechazoBiometricoSoloLector(error) {
  return error instanceof ErrorApi && error.status === 403
    && error.datos?.motivo === MOTIVO_BIOMETRICO_SOLO_LECTOR;
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

/**
 * Autoriza una ración manual para una lectura no identificada en Supervisión.
 * Envía { usuario_id, metodo: 'manual' } sin parámetro momento.
 */
export async function autorizarMarcacionManual(usuarioId, { signal } = {}) {
  if (!Number.isInteger(usuarioId) || usuarioId <= 0) {
    throw new Error('Seleccione un comensal del padrón.');
  }
  return marcarAsistencia(usuarioId, { metodo: 'manual', signal });
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

/*
 * --- Simulación (contrato real comedorback/app/api/simulacion.py) ---
 * GET  /salud → {entorno, reloj: {ahora, real, simulado}, ...}; sin token.
 *               Responde 503 con el mismo cuerpo si la base está incompleta.
 * Solo con ENTORNO=simulacion y rol de jefatura (en otro entorno, 404):
 * GET    /simulacion/reloj                → EstadoReloj
 * PUT    /simulacion/reloj {momento, congelar} → EstadoReloj
 * POST   /simulacion/reloj/avanzar {dias?, horas?, minutos?} → EstadoReloj
 * POST   /simulacion/reloj/proxima-franja → {comida_id, comida, inicio, reloj}
 *                                          | 409 si no hay franja hoy ni mañana
 * DELETE /simulacion/reloj                → EstadoReloj (vuelve a la hora real)
 * EstadoReloj = {ahora, real, simulado, congelado}
 *
 * Las horas del servidor son locales y sin zona. Se leen como hora de pared
 * (año, mes, día, hora…) y nunca se convierten de zona: lo que se muestra es
 * exactamente la hora que ve el servidor.
 */
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

function adaptarReloj(dato, { conCongelado = true } = {}) {
  const ahora = fechaHoraDelServidor(dato?.ahora);
  const real = fechaHoraDelServidor(dato?.real);
  if (!ahora || !real || typeof dato.simulado !== 'boolean'
    || (conCongelado && typeof dato.congelado !== 'boolean')) {
    throw new Error('La API devolvió un reloj inválido.');
  }
  return {
    ahora,
    real,
    simulado: dato.simulado,
    // /salud no informa si el reloj está congelado: null es "no se sabe".
    congelado: typeof dato.congelado === 'boolean' ? dato.congelado : null,
  };
}

/**
 * GET /salud: en qué entorno corre la API y qué hora ve. `simulacion` es
 * true solo con entorno 'simulacion'; en cualquier otro caso (o si la API
 * todavía no informa el entorno) no hay nada de simulación que mostrar.
 * `reloj` es null fuera de simulación.
 */
export async function obtenerSalud({ signal } = {}) {
  const { entorno, simulacion, reloj } = await leerSalud({ signal });
  return { entorno, simulacion, reloj };
}

/**
 * GET /salud como confirmación del entorno. Igual que `obtenerSalud`, más
 * `confirmaSimulacion`: true solo si la API respondió 200 con entorno
 * 'simulacion' y un reloj válido. Un 503 deja ver el reloj, pero no confirma
 * nada; un error o una respuesta inválida se lanzan.
 */
export async function confirmarEntornoSalud({ signal } = {}) {
  const { entorno, simulacion, reloj, degradada } = await leerSalud({ signal });
  return { entorno, simulacion, reloj, confirmaSimulacion: simulacion && !degradada };
}

async function leerSalud({ signal }) {
  let datos;
  let degradada = false;
  try {
    datos = await solicitarApi('/salud', { signal, manejoPropio: true });
  } catch (error) {
    if (signal?.aborted) throw error;
    // Con 503 la API responde igual, solo avisa que a la base le falta algo.
    if (error.status !== 503 || !error.datos) {
      throw new Error(`No se pudo consultar el estado de la API. ${error.message}`);
    }
    datos = error.datos;
    degradada = true;
  }
  const entorno = typeof datos?.entorno === 'string' ? datos.entorno : null;
  const simulacion = entorno === 'simulacion';
  return {
    entorno,
    simulacion,
    reloj: simulacion ? adaptarReloj(datos.reloj, { conCongelado: false }) : null,
    degradada,
  };
}

/*
 * --- Monitoreo (contrato R3-1-20261009) ---
 * GET /monitoreo/estado → diagnóstico; solo sistemas, sin caché.
 * {momento_real, entorno, reloj_negocio: {ahora, fecha, simulado, congelado},
 *  base: {estado, revision_alembic, tablas_propias, vistas_contrato, faltan},
 *  lector: {estado: 'desconocido', razon: 'sin_telemetria'},
 *  actividad: {fuente, disponible, razon, aceptadas_dia, rechazadas_dia,
 *              registro_mayor_id: null | {id, fecha_hora, resultado, motivo, created_at}}}
 * Un error (sin cuerpo garantizado) no dice qué componente falló.
 */
const ENTORNOS = ['produccion', 'desarrollo', 'simulacion'];
const RAZONES_ACTIVIDAD = ['tabla_ausente', 'error_consulta'];
const RESULTADOS_LECTURA = ['aceptada', 'rechazada'];
const MOTIVOS_LECTURA = ['duplicado', 'sin_derecho', 'fuera_horario', 'no_identificado'];
/* Hora local sin zona: una «Z» o un desfase no están confirmados y se rechazan. */
const FECHA_HORA_SIN_ZONA = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d{1,6})?)?$/;
const FECHA_DIA = /^(\d{4})-(\d{2})-(\d{2})$/;
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

function esFecha(valor) {
  const partes = typeof valor === 'string' ? FECHA_DIA.exec(valor) : null;
  return partes !== null && esDiaValido(Number(partes[1]), Number(partes[2]), Number(partes[3]));
}

function esFechaHora(valor) {
  const partes = typeof valor === 'string' ? FECHA_HORA_SIN_ZONA.exec(valor) : null;
  if (!partes) return false;
  const [anio, mes, dia, hora, minuto, segundo = 0] = partes.slice(1)
    .map((parte) => (parte === undefined ? undefined : Number(parte)));
  return esDiaValido(anio, mes, dia) && hora <= 23 && minuto <= 59 && segundo <= 59;
}

function diagnosticoInvalido(campo) {
  return new Error(`La API devolvió un diagnóstico inválido (${campo}).`);
}

function adaptarRegistroMayorId(dato) {
  if (dato === null) return null;
  if (!dato || typeof dato !== 'object') throw diagnosticoInvalido('registro_mayor_id');
  if (!Number.isInteger(dato.id) || dato.id <= 0) throw diagnosticoInvalido('registro_mayor_id.id');
  if (!esFechaHora(dato.fecha_hora)) throw diagnosticoInvalido('registro_mayor_id.fecha_hora');
  if (!RESULTADOS_LECTURA.includes(dato.resultado)) throw diagnosticoInvalido('registro_mayor_id.resultado');
  if (dato.motivo !== null && !MOTIVOS_LECTURA.includes(dato.motivo)) {
    throw diagnosticoInvalido('registro_mayor_id.motivo');
  }
  if (!esFechaHora(dato.created_at)) throw diagnosticoInvalido('registro_mayor_id.created_at');
  return {
    id: dato.id,
    fechaHora: dato.fecha_hora,
    resultado: dato.resultado,
    motivo: dato.motivo,
    createdAt: dato.created_at,
  };
}

/*
 * disponible=true: razon null y contadores enteros (0 es un día sin
 * lecturas). disponible=false: razon conocida y todo en null, nunca 0.
 */
function adaptarActividad(dato) {
  if (!dato || typeof dato !== 'object') throw diagnosticoInvalido('actividad');
  if (dato.fuente !== 'lecturas_biometricas') throw diagnosticoInvalido('actividad.fuente');
  if (typeof dato.disponible !== 'boolean') throw diagnosticoInvalido('actividad.disponible');
  if (dato.disponible) {
    if (dato.razon !== null) throw diagnosticoInvalido('actividad.razon');
    if (!esEnteroNoNegativo(dato.aceptadas_dia) || !esEnteroNoNegativo(dato.rechazadas_dia)) {
      throw diagnosticoInvalido('actividad.contadores');
    }
  } else {
    if (!RAZONES_ACTIVIDAD.includes(dato.razon)) throw diagnosticoInvalido('actividad.razon');
    if (dato.aceptadas_dia !== null || dato.rechazadas_dia !== null || dato.registro_mayor_id !== null) {
      throw diagnosticoInvalido('actividad sin datos');
    }
  }
  return {
    fuente: dato.fuente,
    disponible: dato.disponible,
    razon: dato.razon,
    aceptadasDia: dato.aceptadas_dia,
    rechazadasDia: dato.rechazadas_dia,
    registroMayorId: adaptarRegistroMayorId(dato.registro_mayor_id),
  };
}

/* Presencia en el catálogo: «ok» con elementos faltantes sería contradictorio. */
function adaptarBase(dato) {
  if (!dato || typeof dato !== 'object') throw diagnosticoInvalido('base');
  if (dato.estado !== 'ok' && dato.estado !== 'incompleta') throw diagnosticoInvalido('base.estado');
  if (dato.revision_alembic !== null
    && (typeof dato.revision_alembic !== 'string' || dato.revision_alembic === '')) {
    throw diagnosticoInvalido('base.revision_alembic');
  }
  if (!esEnteroNoNegativo(dato.tablas_propias) || !esEnteroNoNegativo(dato.vistas_contrato)) {
    throw diagnosticoInvalido('base.conteos');
  }
  if (!Array.isArray(dato.faltan)
    || !dato.faltan.every((nombre) => typeof nombre === 'string' && nombre !== '')) {
    throw diagnosticoInvalido('base.faltan');
  }
  if (dato.estado === 'ok' && dato.faltan.length > 0) throw diagnosticoInvalido('base.estado');
  return {
    estado: dato.estado,
    revisionAlembic: dato.revision_alembic,
    tablasPropias: dato.tablas_propias,
    vistasContrato: dato.vistas_contrato,
    faltan: [...dato.faltan],
  };
}

function adaptarRelojNegocio(dato) {
  if (!dato || typeof dato !== 'object') throw diagnosticoInvalido('reloj_negocio');
  if (!esFechaHora(dato.ahora)) throw diagnosticoInvalido('reloj_negocio.ahora');
  // La fecha deriva del mismo `ahora`: si no coinciden, el diagnóstico no es coherente.
  if (!esFecha(dato.fecha) || dato.ahora.slice(0, 10) !== dato.fecha) {
    throw diagnosticoInvalido('reloj_negocio.fecha');
  }
  if (typeof dato.simulado !== 'boolean' || typeof dato.congelado !== 'boolean') {
    throw diagnosticoInvalido('reloj_negocio');
  }
  return { ahora: dato.ahora, fecha: dato.fecha, simulado: dato.simulado, congelado: dato.congelado };
}

/**
 * Valida el cuerpo de GET /monitoreo/estado y lo pasa a camelCase. Las
 * horas quedan como texto del servidor (sin zona): no se convierten ni se
 * comparan entre sí. Ningún null se vuelve cero ni ningún texto, número.
 */
export function adaptarEstadoMonitoreo(dato) {
  if (!dato || typeof dato !== 'object' || Array.isArray(dato)) throw diagnosticoInvalido('cuerpo');
  if (!esFechaHora(dato.momento_real)) throw diagnosticoInvalido('momento_real');
  if (!ENTORNOS.includes(dato.entorno)) throw diagnosticoInvalido('entorno');
  if (dato.lector?.estado !== 'desconocido' || dato.lector?.razon !== 'sin_telemetria') {
    throw diagnosticoInvalido('lector');
  }
  return {
    momentoReal: dato.momento_real,
    entorno: dato.entorno,
    relojNegocio: adaptarRelojNegocio(dato.reloj_negocio),
    base: adaptarBase(dato.base),
    lector: { estado: dato.lector.estado, razon: dato.lector.razon },
    actividad: adaptarActividad(dato.actividad),
  };
}

/**
 * GET /monitoreo/estado: diagnóstico técnico para sistemas. Pasa por
 * `solicitarApi` sin `manejoPropio`, así 401/403/428 siguen el manejo
 * central de la sesión. El error conserva su causa (con `status`).
 */
export async function obtenerEstadoMonitoreo({ signal } = {}) {
  try {
    return adaptarEstadoMonitoreo(await solicitarApi('/monitoreo/estado', { signal }));
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(`No se pudo obtener el diagnóstico del sistema. ${error.message}`, { cause: error });
  }
}

async function operarReloj(ruta, opciones, accion) {
  try {
    return adaptarReloj(await solicitarApi(ruta, opciones));
  } catch (error) {
    if (opciones.signal?.aborted) throw error;
    throw new Error(`No se pudo ${accion}. ${error.message}`);
  }
}

const cuerpoJson = (datos) => ({
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(datos),
});

/** GET /simulacion/reloj: la hora que ve el sistema, con `congelado`. */
export function obtenerReloj({ signal } = {}) {
  return operarReloj('/simulacion/reloj', { signal }, 'consultar el reloj');
}

/**
 * PUT /simulacion/reloj. `momento` es el valor de un datetime-local
 * ("2026-08-10T12:05"): hora local del servidor, sin zona.
 */
export async function fijarReloj({ momento, congelar = false, signal } = {}) {
  if (typeof momento !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(momento)) {
    throw new Error('Indique la fecha y la hora a fijar.');
  }
  return operarReloj('/simulacion/reloj', {
    method: 'PUT', ...cuerpoJson({ momento: `${momento}:00`, congelar: congelar === true }), signal,
  }, 'fijar el reloj');
}

/** POST /simulacion/reloj/avanzar: al menos uno de días, horas o minutos. */
export async function avanzarReloj({ dias = 0, horas = 0, minutos = 0, signal } = {}) {
  const cuanto = { dias, horas, minutos };
  if (Object.values(cuanto).some((valor) => !Number.isInteger(valor) || valor < 0)
    || Object.values(cuanto).every((valor) => valor === 0)) {
    throw new Error('Indique cuánto avanzar el reloj.');
  }
  const cuerpo = Object.fromEntries(Object.entries(cuanto).filter(([, valor]) => valor > 0));
  return operarReloj('/simulacion/reloj/avanzar', { method: 'POST', ...cuerpoJson(cuerpo), signal },
    'avanzar el reloj');
}

/**
 * POST /simulacion/reloj/proxima-franja. El 409 no es una falla: es la
 * respuesta a "no hay ninguna franja hoy ni mañana", y se devuelve como
 * `{ tipo: 'sin_franja', detalle }` para que la pantalla lo muestre como
 * mensaje. Lo demás llega como `{ tipo: 'ok', comidaId, comida, inicio, reloj }`.
 */
export async function saltarAProximaFranja({ signal } = {}) {
  let datos;
  try {
    datos = await solicitarApi('/simulacion/reloj/proxima-franja', { method: 'POST', signal });
  } catch (error) {
    if (signal?.aborted) throw error;
    if (error.status === 409) {
      return { tipo: 'sin_franja', detalle: detalleDe(error.datos, 'No hay ninguna franja de comida hoy ni mañana.') };
    }
    throw new Error(`No se pudo saltar a la próxima franja. ${error.message}`);
  }
  const inicio = fechaHoraDelServidor(datos?.inicio);
  if (!Number.isInteger(datos?.comida_id) || typeof datos.comida !== 'string' || !inicio) {
    throw new Error('No se pudo saltar a la próxima franja. La API devolvió una franja inválida.');
  }
  let reloj;
  try {
    reloj = adaptarReloj(datos.reloj);
  } catch (error) {
    throw new Error(`No se pudo saltar a la próxima franja. ${error.message}`);
  }
  return { tipo: 'ok', comidaId: datos.comida_id, comida: datos.comida, inicio, reloj };
}

/* ------------------------------------------------------------------ *
 * Administración de cuentas (solo rol sistemas, sección admin)
 *
 * GET  /admin/cuentas → [CuentaApi]
 * GET  /admin/candidatos?busqueda=&limite= → [CandidatoApi] (2+ caracteres)
 * POST /admin/cuentas {rol, usuario_turnos_id} | {rol, username, nombre}
 *   → 201 {cuenta, clave_temporal}
 * POST /admin/cuentas/{id}/desactivar | /reactivar → CuentaApi
 * POST /admin/cuentas/{id}/reiniciar-clave → {cuenta, clave_temporal}
 *
 * CuentaApi = {id, username, rol, activo, debe_cambiar,
 *   usuario_turnos_id|null, vinculada, nombre|null, categoria|null,
 *   creada, ultimo_ingreso|null}
 * CandidatoApi = {usuario_turnos_id, login, nombre, categoria,
 *   cuenta_id|null}
 *
 * Los motivos del backend se traducen a español claro para la jefatura;
 * la clave temporal se entrega tal cual y solo vive en memoria mientras
 * su diálogo está abierto (nunca se guarda ni se registra).
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
};

/** Texto claro del motivo, o null si no es un motivo conocido. */
function mensajeDeMotivoAdmin(motivo) {
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

function adaptarCuentaConClave(dato) {
  if (!dato || typeof dato !== 'object'
    || typeof dato.clave_temporal !== 'string' || dato.clave_temporal.length === 0) {
    throw new Error('La API devolvió una clave temporal inválida.');
  }
  return { cuenta: adaptarCuenta(dato.cuenta), claveTemporal: dato.clave_temporal };
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
 * POST /admin/cuentas: crea la cuenta y devuelve su clave temporal.
 * Desde el padrón: {rol, usuarioTurnosId}. Sin vínculo: {rol, username, nombre}.
 */
export async function crearCuenta({ rol, usuarioTurnosId = null, username = '', nombre = '' } = {}, { signal } = {}) {
  if (!ROLES_CUENTA_NUEVA.includes(rol)) {
    throw new Error(MOTIVOS_ADMIN.rol_no_permitido);
  }
  let cuerpo;
  if (usuarioTurnosId !== null && usuarioTurnosId !== undefined) {
    if (!Number.isInteger(usuarioTurnosId) || usuarioTurnosId <= 0) {
      throw new Error('Elija una persona del padrón.');
    }
    cuerpo = { rol, usuario_turnos_id: usuarioTurnosId };
  } else {
    const usuario = typeof username === 'string' ? username.trim().toLowerCase() : '';
    const nombreLimpio = typeof nombre === 'string' ? nombre.trim() : '';
    if (!usuario) throw new Error('Escriba el nombre de usuario.');
    if (!nombreLimpio) throw new Error('Escriba el nombre de la persona.');
    cuerpo = { rol, username: usuario, nombre: nombreLimpio };
  }
  try {
    return adaptarCuentaConClave(await solicitarApi('/admin/cuentas', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cuerpo),
      signal,
    }));
  } catch (error) {
    if (signal?.aborted) throw error;
    const mensaje = mensajeDeMotivoAdmin(error.datos?.motivo);
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

/** POST /admin/cuentas/{id}/reiniciar-clave: nueva clave temporal de un solo uso. */
export async function reiniciarClaveCuenta(id, { signal } = {}) {
  if (!Number.isInteger(id) || id <= 0) {
    throw new Error('Cuenta inválida.');
  }
  try {
    return adaptarCuentaConClave(await solicitarApi(`/admin/cuentas/${id}/reiniciar-clave`, {
      method: 'POST',
      signal,
    }));
  } catch (error) {
    if (signal?.aborted) throw error;
    const mensaje = mensajeDeMotivoAdmin(error.datos?.motivo);
    if (mensaje) throw new Error(mensaje);
    throw new Error(`No se pudo reiniciar la clave. ${error.message}`);
  }
}

/** DELETE /simulacion/reloj: el sistema vuelve a la hora real. */
export function volverARelojReal({ signal } = {}) {
  return operarReloj('/simulacion/reloj', { method: 'DELETE', signal }, 'volver a la hora real');
}

/* ------------------------------------------------------------------ *
 * Reglas del sistema (R2): horarios de comida y derecho a comer
 *
 * GET  /cuentas → [CuentaLecturaApi] (para la jefa; sin cuentas sistemas)
 * GET  /reglas/derecho → {vigente, versiones}
 * GET  /reglas/derecho/novedades → [str]
 * POST /reglas/derecho {vigente_desde, duracion_minima_horas,
 *   novedades_que_anulan, excluir_enfermeria, motivo} → 201 VersionApi
 * DELETE /reglas/derecho/{id} → 204 (solo programadas)
 * GET  /reglas/horarios?fecha= → [HorarioApi]
 * GET  /reglas/horarios/historial?comida_id= → [HorarioApi]
 * POST /reglas/horarios {comida_id, hora_inicio, hora_fin,
 *   vigente_desde, motivo} → 201
 * DELETE /reglas/horarios/{horario_id} → 204 (solo programados)
 *
 * VersionApi = {id, vigente_desde, duracion_minima_horas,
 *   novedades_que_anulan, excluir_enfermeria, motivo, creada_por|null,
 *   creada, estado: programada|vigente|anterior}
 * HorarioApi = {horario_id, comida_id, comida, hora_inicio, hora_fin,
 *   cruza_medianoche, vigente_desde, vigente_hasta|null, motivo|null,
 *   creada_por|null}
 * CuentaLecturaApi = {id, username, nombre|null, rol, activo,
 *   debe_cambiar, ultimo_ingreso|null}
 *
 * El backend decide y valida; acá solo se adapta snake_case, se valida
 * la forma y se traducen los motivos a español claro. Cada cambio es una
 * versión nueva con "vigente desde" de hoy o futura, nunca hacia atrás.
 * ------------------------------------------------------------------ */

/** Motivos del backend con el texto que lee jefatura y sistemas. */
const MOTIVOS_REGLAS = {
  vigencia_en_el_pasado: 'La fecha elegida ya pasó. Elija hoy o un día futuro.',
  horario_invalido: 'El horario no es válido. Revise la hora de inicio y la de fin.',
  solapa_con_otra_comida: 'Ese horario se cruza con otra comida. Elija horas que no se solapen.',
  version_en_esa_fecha: 'Ya hay un cambio programado para esa fecha.',
  comida_inexistente: 'Esa comida ya no existe. Actualice la lista.',
  version_inexistente: 'Esa versión ya no existe. Actualice la lista.',
  version_ya_vigente: 'Esa versión ya está vigente y no se puede eliminar.',
  motivo_obligatorio: 'Escriba el motivo del cambio.',
};

/** Texto claro del motivo, o null si no es un motivo conocido. */
function mensajeDeMotivoReglas(motivo) {
  return typeof motivo === 'string' ? MOTIVOS_REGLAS[motivo] ?? null : null;
}

/** Hora de la API: "11:30" o "11:30:00". */
const HORA_API = /^\d{2}:\d{2}(:\d{2})?$/;

const ESTADOS_VERSION = ['programada', 'vigente', 'anterior'];

function adaptarVersionDerecho(dato) {
  if (!Number.isInteger(dato?.id) || dato.id <= 0
    || typeof dato.vigente_desde !== 'string' || !FECHA_API.test(dato.vigente_desde)
    || !Number.isInteger(dato.duracion_minima_horas) || dato.duracion_minima_horas < 1
    || dato.duracion_minima_horas > 48
    || !Array.isArray(dato.novedades_que_anulan)
    || dato.novedades_que_anulan.some((novedad) => typeof novedad !== 'string' || novedad.length === 0)
    || typeof dato.excluir_enfermeria !== 'boolean'
    || typeof dato.motivo !== 'string' || dato.motivo.length === 0
    || !(dato.creada_por === null || typeof dato.creada_por === 'string')
    || typeof dato.creada !== 'string' || dato.creada.length === 0
    || !ESTADOS_VERSION.includes(dato.estado)) {
    throw new Error('La API devolvió una versión de derecho inválida.');
  }
  return {
    id: dato.id,
    vigenteDesde: dato.vigente_desde,
    duracionMinimaHoras: dato.duracion_minima_horas,
    novedadesQueAnulan: [...dato.novedades_que_anulan],
    excluirEnfermeria: dato.excluir_enfermeria,
    motivo: dato.motivo,
    creadaPor: dato.creada_por,
    creada: dato.creada,
    estado: dato.estado,
  };
}

function adaptarHorario(dato) {
  if (!Number.isInteger(dato?.horario_id) || dato.horario_id <= 0
    || !Number.isInteger(dato.comida_id) || dato.comida_id <= 0
    || typeof dato.comida !== 'string' || dato.comida.length === 0
    || typeof dato.hora_inicio !== 'string' || !HORA_API.test(dato.hora_inicio)
    || typeof dato.hora_fin !== 'string' || !HORA_API.test(dato.hora_fin)
    || typeof dato.cruza_medianoche !== 'boolean'
    || typeof dato.vigente_desde !== 'string' || !FECHA_API.test(dato.vigente_desde)
    || !(dato.vigente_hasta === null
      || (typeof dato.vigente_hasta === 'string' && FECHA_API.test(dato.vigente_hasta)))
    || !(dato.motivo === null || typeof dato.motivo === 'string')
    || !(dato.creada_por === null || typeof dato.creada_por === 'string')) {
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

/** GET /reglas/derecho: versión vigente y todas las versiones. */
export async function obtenerReglasDerecho({ signal } = {}) {
  try {
    const dato = await solicitarApi('/reglas/derecho', { signal });
    if (!dato || typeof dato !== 'object' || !Array.isArray(dato.versiones)) {
      throw new Error('La API devolvió reglas de derecho inválidas.');
    }
    return {
      vigente: adaptarVersionDerecho(dato.vigente),
      versiones: dato.versiones.map(adaptarVersionDerecho),
    };
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(`No se pudieron cargar las reglas de derecho. ${error.message}`);
  }
}

/** GET /reglas/derecho/novedades: novedades que se pueden marcar. */
export async function obtenerNovedadesDisponibles({ signal } = {}) {
  try {
    const novedades = await solicitarApi('/reglas/derecho/novedades', { signal });
    if (!Array.isArray(novedades)
      || novedades.some((novedad) => typeof novedad !== 'string' || novedad.length === 0)) {
      throw new Error('La API devolvió novedades inválidas.');
    }
    return [...novedades];
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(`No se pudieron cargar las novedades. ${error.message}`);
  }
}

/**
 * POST /reglas/derecho: programa una versión nueva. Guía local (rango
 * 1–48 h, motivo de 10+ caracteres); el servidor valida y decide.
 */
export async function programarReglasDerecho({
  vigenteDesde,
  duracionMinimaHoras,
  novedadesQueAnulan = [],
  excluirEnfermeria = false,
  motivo,
} = {}, { signal } = {}) {
  if (typeof vigenteDesde !== 'string' || !FECHA_API.test(vigenteDesde)) {
    throw new Error('Elija desde qué fecha rige la versión.');
  }
  if (!Number.isInteger(duracionMinimaHoras) || duracionMinimaHoras < 1 || duracionMinimaHoras > 48) {
    throw new Error('El turno mínimo es de 1 a 48 horas.');
  }
  if (!Array.isArray(novedadesQueAnulan)
    || novedadesQueAnulan.some((novedad) => typeof novedad !== 'string' || novedad.length === 0)) {
    throw new Error('Las novedades elegidas no son válidas.');
  }
  if (typeof excluirEnfermeria !== 'boolean') {
    throw new Error('La exclusión de enfermería no es válida.');
  }
  const motivoLimpio = typeof motivo === 'string' ? motivo.trim() : '';
  if (motivoLimpio.length < 10) {
    throw new Error('Escriba el motivo del cambio (10 caracteres o más).');
  }
  try {
    return adaptarVersionDerecho(await solicitarApi('/reglas/derecho', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        vigente_desde: vigenteDesde,
        duracion_minima_horas: duracionMinimaHoras,
        novedades_que_anulan: novedadesQueAnulan,
        excluir_enfermeria: excluirEnfermeria,
        motivo: motivoLimpio,
      }),
      signal,
    }));
  } catch (error) {
    if (signal?.aborted) throw error;
    const mensaje = mensajeDeMotivoReglas(error.datos?.motivo);
    if (mensaje) throw new Error(mensaje);
    throw new Error(`No se pudo programar la versión. ${error.message}`);
  }
}

/** DELETE /reglas/derecho/{id}: elimina una versión programada. */
export async function eliminarReglasDerechoProgramadas(id, { signal } = {}) {
  if (!Number.isInteger(id) || id <= 0) {
    throw new Error('Versión inválida.');
  }
  try {
    await solicitarApi(`/reglas/derecho/${id}`, { method: 'DELETE', signal });
    return null;
  } catch (error) {
    if (signal?.aborted) throw error;
    const mensaje = mensajeDeMotivoReglas(error.datos?.motivo);
    if (mensaje) throw new Error(mensaje);
    throw new Error(`No se pudo eliminar la versión. ${error.message}`);
  }
}

/**
 * GET /reglas/horarios: horarios que rigen. Sin `fecha` el servidor usa
 * su hoy; con ella ("YYYY-MM-DD"), los de ese día.
 */
export async function obtenerHorariosVigentes({ fecha, signal } = {}) {
  if (fecha !== undefined && (typeof fecha !== 'string' || !FECHA_API.test(fecha))) {
    throw new Error('Fecha inválida para consultar los horarios.');
  }
  try {
    const horarios = await solicitarApi(
      `/reglas/horarios${fecha === undefined ? '' : `?fecha=${fecha}`}`,
      { signal },
    );
    if (!Array.isArray(horarios)) {
      throw new Error('La API devolvió horarios inválidos.');
    }
    return horarios.map(adaptarHorario);
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(`No se pudieron cargar los horarios. ${error.message}`);
  }
}

/** GET /reglas/horarios/historial: versiones de una comida, con programadas. */
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
    const mensaje = mensajeDeMotivoReglas(error.datos?.motivo);
    if (mensaje) throw new Error(mensaje);
    throw new Error(`No se pudo cargar el historial del horario. ${error.message}`);
  }
}

/**
 * POST /reglas/horarios: programa un horario nuevo desde una fecha.
 * Guía local (horas, fecha, motivo); el servidor valida y decide.
 */
export async function programarHorario({
  comidaId,
  horaInicio,
  horaFin,
  vigenteDesde,
  motivo,
} = {}, { signal } = {}) {
  if (!Number.isInteger(comidaId) || comidaId <= 0) {
    throw new Error('Comida inválida.');
  }
  if (typeof horaInicio !== 'string' || !HORA_API.test(horaInicio)
    || typeof horaFin !== 'string' || !HORA_API.test(horaFin)) {
    throw new Error('Escriba la hora de inicio y la de fin.');
  }
  if (typeof vigenteDesde !== 'string' || !FECHA_API.test(vigenteDesde)) {
    throw new Error('Elija desde qué fecha rige el horario.');
  }
  const motivoLimpio = typeof motivo === 'string' ? motivo.trim() : '';
  if (!motivoLimpio) {
    throw new Error(MOTIVOS_REGLAS.motivo_obligatorio);
  }
  try {
    return adaptarHorario(await solicitarApi('/reglas/horarios', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        comida_id: comidaId,
        hora_inicio: horaInicio,
        hora_fin: horaFin,
        vigente_desde: vigenteDesde,
        motivo: motivoLimpio,
      }),
      signal,
    }));
  } catch (error) {
    if (signal?.aborted) throw error;
    const mensaje = mensajeDeMotivoReglas(error.datos?.motivo);
    if (mensaje) throw new Error(mensaje);
    throw new Error(`No se pudo programar el horario. ${error.message}`);
  }
}

/** DELETE /reglas/horarios/{horario_id}: elimina un horario programado. */
export async function eliminarHorarioProgramado(horarioId, { signal } = {}) {
  if (!Number.isInteger(horarioId) || horarioId <= 0) {
    throw new Error('Horario inválido.');
  }
  try {
    await solicitarApi(`/reglas/horarios/${horarioId}`, { method: 'DELETE', signal });
    return null;
  } catch (error) {
    if (signal?.aborted) throw error;
    const mensaje = mensajeDeMotivoReglas(error.datos?.motivo);
    if (mensaje) throw new Error(mensaje);
    throw new Error(`No se pudo eliminar el horario. ${error.message}`);
  }
}
