/*
 * Lector biométrico (solo sistemas): GET /monitoreo/estado reutilizado.
 * Permisos, adaptador (solo el lector) con fetch controlado, refresco con
 * temporizadores y documento falsos, antigüedad y estados de la vista.
 */
import test, { afterEach, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { adaptarEstadoMonitoreo, obtenerEstadoMonitoreo } from '../src/api.js';
import { buscarSeccion, seccionesDeRol } from '../src/navegacion.js';
import { puedeVerSeccion, seccionesPermitidas } from '../src/permisos.js';
import { borrarTokens, escucharSesion, guardarTokens, leerTokens } from '../src/sesion.js';
import {
  MS_ANTIGUEDAD_MAXIMA,
  MS_REFRESCO_MONITOREO,
  datoVigente,
  estadoDeVista,
  programarRefrescoMonitoreo,
  textoFechaHoraServidor,
} from '../src/monitoreo.js';
import { Panel } from '../src/App.jsx';
import { ProveedorSesion } from '../src/hooks/useSesion.js';
import { VistaLectorBiometrico } from '../src/components/secciones/LectorBiometrico.jsx';

/* sessionStorage mínimo: en Node no existe y la sesión guarda los tokens ahí. */
const almacen = new Map();
globalThis.sessionStorage ??= {
  getItem: (clave) => (almacen.has(clave) ? almacen.get(clave) : null),
  setItem: (clave, valor) => almacen.set(clave, String(valor)),
  removeItem: (clave) => almacen.delete(clave),
};

const fetchOriginal = globalThis.fetch;
const json = (datos, status = 200) => new Response(JSON.stringify(datos), { status });
let avisos;
let dejarDeEscuchar;
beforeEach(() => {
  avisos = [];
  dejarDeEscuchar = escucharSesion((aviso) => avisos.push(aviso.tipo));
});
afterEach(() => {
  globalThis.fetch = fetchOriginal;
  dejarDeEscuchar();
  borrarTokens();
});

/** Respuesta 200 sintética del contrato; `cambios` reemplaza claves de primer nivel. */
const estadoApi = (cambios = {}) => ({
  momento_real: '2026-10-09T14:03:10',
  entorno: 'produccion',
  reloj_negocio: { ahora: '2026-10-09T14:03:10', fecha: '2026-10-09' },
  base: { estado: 'ok', revision_alembic: 'f6a7b8c9d0e1', tablas_propias: 14, vistas_contrato: 3, faltan: [] },
  lector: { estado: 'desconocido', razon: 'sin_telemetria' },
  actividad: {
    fuente: 'lecturas_biometricas',
    disponible: true,
    razon: null,
    aceptadas_dia: 12,
    rechazadas_dia: 2,
    registro_mayor_id: {
      id: 345,
      fecha_hora: '2026-10-09T13:58:00',
      resultado: 'rechazada',
      motivo: 'duplicado',
      created_at: '2026-10-09T13:58:01',
    },
  },
  ...cambios,
});
const actividadApi = (cambios) => ({ ...estadoApi().actividad, ...cambios });
const baseApi = (cambios) => ({ ...estadoApi().base, ...cambios });
const ACTIVIDAD_AUSENTE = actividadApi({
  disponible: false, razon: 'tabla_ausente', aceptadas_dia: null, rechazadas_dia: null, registro_mayor_id: null,
});

// -------------------------------------------------------------
// 1. Permisos y montaje: solo sistemas
// -------------------------------------------------------------
test("solo sistemas ve 'monitoreo' (Lector biométrico) en permisos y menú", () => {
  assert.equal(puedeVerSeccion('sistemas', 'monitoreo'), true);
  assert.equal(puedeVerSeccion('jefa', 'monitoreo'), false);
  assert.equal(puedeVerSeccion('cocinera', 'monitoreo'), false);
  assert.equal(puedeVerSeccion('nutricionista', 'monitoreo'), false);
  assert.ok(seccionesPermitidas('sistemas').includes('monitoreo'));
  assert.ok(seccionesDeRol('sistemas').some(({ id }) => id === 'monitoreo'));
  assert.ok(!seccionesDeRol('jefa').some(({ id }) => id === 'monitoreo'));
  assert.ok(!seccionesDeRol('cocinera').some(({ id }) => id === 'monitoreo'));

  const seccion = buscarSeccion('monitoreo');
  assert.equal(seccion.id, 'monitoreo', 'el id interno se conserva');
  assert.equal(seccion.etiqueta, 'Lector biométrico');
  assert.equal(seccion.titulo, 'Lector biométrico');
  assert.equal(typeof seccion.Icono, 'function');
});

test('sistemas monta el Lector biométrico; jefa y cocinera con monitoreo guardado no', () => {
  const localOriginal = globalThis.localStorage;
  const montar = (rol) => {
    globalThis.localStorage = { getItem: () => 'monitoreo', setItem: () => {}, removeItem: () => {} };
    return renderToStaticMarkup(h(ProveedorSesion, null, h(Panel, { rol, usuario: `${rol}.test` })));
  };
  try {
    const htmlSistemas = montar('sistemas');
    assert.match(htmlSistemas, /Consultando el estado del lector…/);
    assert.match(htmlSistemas, /Actualizar|Actualizando…/);
    assert.match(htmlSistemas, /<h1 class="header__titulo">Lector biométrico<\/h1>/);
    assert.doesNotMatch(htmlSistemas, /Grafana|Catálogo de la base|Actividad del día|Reloj de negocio/);

    const htmlJefa = montar('jefa');
    assert.doesNotMatch(htmlJefa, /estado del lector/);
    assert.match(htmlJefa, /Cargando supervisión…/);

    const htmlCocinera = montar('cocinera');
    assert.doesNotMatch(htmlCocinera, /estado del lector/);
  } finally {
    if (localOriginal === undefined) delete globalThis.localStorage;
    else globalThis.localStorage = localOriginal;
  }
});

// -------------------------------------------------------------
// 2. Adaptador GET /monitoreo/estado: solo el lector
// -------------------------------------------------------------
test('obtenerEstadoMonitoreo pide /monitoreo/estado firmado y devuelve solo el lector', async () => {
  guardarTokens({ access: 'acc-sistemas', refresh: null, usuario: 'root' });
  let pedido;
  globalThis.fetch = async (url, opciones) => {
    pedido = { url: new URL(url), opciones };
    return json(estadoApi());
  };
  const estado = await obtenerEstadoMonitoreo();
  assert.equal(pedido.url.pathname, '/monitoreo/estado');
  assert.equal(pedido.url.search, '');
  assert.equal(pedido.opciones.headers.Authorization, 'Bearer acc-sistemas');
  assert.deepEqual(estado, { lector: { estado: 'desconocido', razon: 'sin_telemetria' } });
  assert.deepEqual(avisos, []);
});

test('el resto del diagnóstico no se valida ni se guarda: un campo ajeno no impide ver el lector', () => {
  const ajenoInvalido = adaptarEstadoMonitoreo(estadoApi({
    base: { estado: 'quién sabe' },
    actividad: null,
    reloj_negocio: 'no es un objeto',
    entorno: 'pruebas',
    momento_real: 'ayer',
  }));
  assert.deepEqual(ajenoInvalido, { lector: { estado: 'desconocido', razon: 'sin_telemetria' } });
  const sinResto = adaptarEstadoMonitoreo({ lector: { estado: 'desconocido', razon: 'sin_telemetria' } });
  assert.deepEqual(Object.keys(sinResto), ['lector']);
});

test('el adaptador rechaza un lector distinto del contrato en vez de mostrarlo', async () => {
  const invalidos = [
    ['cuerpo', []],
    ['cuerpo', null],
    ['cuerpo', 'texto'],
    ['lector', estadoApi({ lector: { estado: 'conectado', razon: 'sin_telemetria' } })],
    ['lector', estadoApi({ lector: { estado: 'desconectado', razon: 'sin_telemetria' } })],
    ['lector', estadoApi({ lector: { estado: 'desconocido', razon: null } })],
    ['lector', estadoApi({ lector: { estado: 'desconocido', razon: 'otra' } })],
    ['lector', estadoApi({ lector: null })],
  ];
  for (const [campo, cuerpo] of invalidos) {
    assert.throws(() => adaptarEstadoMonitoreo(cuerpo), (error) => error.message.includes(`(${campo})`),
      `debía rechazar ${campo}`);
  }
  const sinClave = estadoApi();
  delete sinClave.lector;
  assert.throws(() => adaptarEstadoMonitoreo(sinClave), /estado del lector inválido \(lector\)/);

  globalThis.fetch = async () => json(estadoApi({ lector: { estado: 'conectado', razon: 'sin_telemetria' } }));
  await assert.rejects(obtenerEstadoMonitoreo(), /No se pudo consultar el lector biométrico\. .*inválido/);
});

// -------------------------------------------------------------
// 3. Autorización: el manejo central sigue igual
// -------------------------------------------------------------
test('403 avisa «prohibido» y conserva detail y motivo en la causa', async () => {
  guardarTokens({ access: 'acc-jefa', refresh: null, usuario: 'jefa' });
  globalThis.fetch = async () => json({ detail: 'Rol sin permiso.', motivo: 'rol_insuficiente' }, 403);
  await assert.rejects(obtenerEstadoMonitoreo(), (error) => {
    assert.match(error.message, /No tiene permiso/);
    assert.equal(error.cause.status, 403);
    assert.deepEqual(error.cause.datos, { detail: 'Rol sin permiso.', motivo: 'rol_insuficiente' });
    return true;
  });
  assert.deepEqual(avisos, ['prohibido']);
  assert.equal(leerTokens()?.access, 'acc-jefa', 'un 403 no cierra la sesión');
});

test('401 vacía la sesión y avisa «expirada»; un 500 sin cuerpo no inventa causas', async () => {
  guardarTokens({ access: 'acc', refresh: null, usuario: 'root' });
  globalThis.fetch = async () => json({ detail: 'Sesión inválida.', motivo: 'token_invalido' }, 401);
  await assert.rejects(obtenerEstadoMonitoreo(), (error) => error.cause.status === 401
    && error.cause.datos.motivo === 'token_invalido');
  assert.deepEqual(avisos, ['expirada']);
  assert.equal(leerTokens(), null);

  avisos.length = 0;
  globalThis.fetch = async () => new Response('Internal Server Error', { status: 500 });
  await assert.rejects(obtenerEstadoMonitoreo(), (error) => {
    assert.equal(error.message, 'No se pudo consultar el lector biométrico. La API respondió con error HTTP 500.');
    assert.doesNotMatch(error.message, /base de datos|actividad|MySQL/i);
    return true;
  });
  assert.deepEqual(avisos, []);
});

// -------------------------------------------------------------
// 4. Refresco: sin solapes, cancelación, pestaña oculta
// -------------------------------------------------------------
function temporizadorFalso() {
  const pendientes = new Map();
  let siguiente = 1;
  return {
    pendientes,
    setTimeout(fn, ms) {
      const id = siguiente++;
      pendientes.set(id, { fn, ms });
      return id;
    },
    clearTimeout(id) {
      pendientes.delete(id);
    },
    disparar() {
      const [[id, { fn }]] = pendientes;
      pendientes.delete(id);
      fn();
    },
  };
}

function documentoFalso() {
  const oyentes = new Set();
  return {
    visibilityState: 'visible',
    oyentes,
    addEventListener: (tipo, fn) => { if (tipo === 'visibilitychange') oyentes.add(fn); },
    removeEventListener: (tipo, fn) => { if (tipo === 'visibilitychange') oyentes.delete(fn); },
    cambiar(estado) {
      this.visibilityState = estado;
      oyentes.forEach((fn) => fn());
    },
  };
}

/** consultar controlado: cada llamada queda pendiente hasta resolverla. */
function consultaControlada() {
  const llamadas = [];
  const consultar = ({ signal, origen }) => new Promise((resolver) => {
    llamadas.push({ signal, origen, resolver });
  });
  return { llamadas, consultar };
}

const vaciarMicrotareas = () => new Promise((resolver) => setImmediate(resolver));

test('refresco: consulta inicial, la siguiente 30 s DESPUÉS de terminar y sin solaparse con el botón', async () => {
  const temporizador = temporizadorFalso();
  const documento = documentoFalso();
  const { llamadas, consultar } = consultaControlada();
  const refresco = programarRefrescoMonitoreo({ consultar, documento, temporizador });

  assert.equal(llamadas.length, 1);
  assert.equal(llamadas[0].origen, 'inicial');
  assert.equal(temporizador.pendientes.size, 0, 'nada se programa mientras la consulta sigue en vuelo');

  const unida = refresco.actualizar();
  assert.equal(llamadas.length, 1, 'el botón se une a la consulta en curso');

  llamadas[0].resolver();
  await unida;
  await vaciarMicrotareas();
  assert.equal(temporizador.pendientes.size, 1);
  assert.equal([...temporizador.pendientes.values()][0].ms, MS_REFRESCO_MONITOREO);

  temporizador.disparar();
  assert.equal(llamadas.length, 2);
  assert.equal(llamadas[1].origen, 'automatico');
  refresco.actualizar();
  assert.equal(llamadas.length, 2, 'automático en vuelo: el botón no lanza otra');

  llamadas[1].resolver();
  await vaciarMicrotareas();
  refresco.actualizar();
  assert.equal(llamadas.length, 3);
  assert.equal(llamadas[2].origen, 'manual');
  assert.equal(temporizador.pendientes.size, 0, 'la manual reemplaza la espera programada');
  refresco.cancelar();
});

test('refresco: cancelar aborta la petición, quita el temporizador y el listener', async () => {
  const temporizador = temporizadorFalso();
  const documento = documentoFalso();
  const { llamadas, consultar } = consultaControlada();
  const refresco = programarRefrescoMonitoreo({ consultar, documento, temporizador });
  assert.equal(documento.oyentes.size, 1);

  refresco.cancelar();
  assert.equal(llamadas[0].signal.aborted, true);
  assert.equal(documento.oyentes.size, 0);
  llamadas[0].resolver();
  await vaciarMicrotareas();
  assert.equal(temporizador.pendientes.size, 0, 'una consulta cancelada no reprograma');
  refresco.actualizar();
  assert.equal(llamadas.length, 1, 'después de cancelar no se consulta más');

  const segundo = programarRefrescoMonitoreo({ consultar, documento, temporizador });
  llamadas[1].resolver();
  await vaciarMicrotareas();
  assert.equal(temporizador.pendientes.size, 1);
  segundo.cancelar();
  assert.equal(temporizador.pendientes.size, 0);
});

test('refresco: pausa con la pestaña oculta; al volver marca pendiente y pide una respuesta nueva', async () => {
  const temporizador = temporizadorFalso();
  const documento = documentoFalso();
  const { llamadas, consultar } = consultaControlada();
  let vueltas = 0;
  const refresco = programarRefrescoMonitoreo({ consultar, documento, temporizador, alVolver: () => { vueltas += 1; } });
  llamadas[0].resolver();
  await vaciarMicrotareas();
  assert.equal(temporizador.pendientes.size, 1);

  documento.cambiar('hidden');
  assert.equal(temporizador.pendientes.size, 0, 'oculta: sin consultas programadas');
  assert.equal(llamadas.length, 1);

  documento.cambiar('visible');
  assert.equal(vueltas, 1);
  assert.equal(llamadas.length, 2);
  assert.equal(llamadas[1].origen, 'regreso');

  // Una consulta en vuelo al volver se descarta: solo vale una respuesta nueva.
  documento.cambiar('hidden');
  documento.cambiar('visible');
  assert.equal(llamadas[1].signal.aborted, true);
  assert.equal(llamadas.length, 3);
  llamadas[1].resolver();
  await vaciarMicrotareas();
  assert.equal(temporizador.pendientes.size, 0, 'la descartada no reprograma');

  // Si la respuesta llega con la pestaña oculta, no se programa la siguiente.
  documento.cambiar('hidden');
  llamadas[2].resolver();
  await vaciarMicrotareas();
  assert.equal(temporizador.pendientes.size, 0);
  refresco.cancelar();
});

// -------------------------------------------------------------
// 5. Vigencia: relojes del equipo, nunca el de negocio
// -------------------------------------------------------------
test('vigencia: 90 s desde la recepción; suspensión, saltos y relojes ausentes la retiran', () => {
  const recepcion = { pared: 1_000_000, mono: 5_000 };
  assert.equal(datoVigente(recepcion, { pared: 1_030_000, mono: 35_000 }), true);
  assert.equal(datoVigente(recepcion, { pared: 1_000_000 + MS_ANTIGUEDAD_MAXIMA, mono: 5_000 + MS_ANTIGUEDAD_MAXIMA }), true);
  assert.equal(datoVigente(recepcion, { pared: 1_091_000, mono: 96_000 }), false, 'más de 90 s');
  assert.equal(datoVigente(recepcion, { pared: 1_600_000, mono: 6_000 }), false, 'suspensión: el monotónico no avanzó');
  assert.equal(datoVigente(recepcion, { pared: 990_000, mono: 15_000 }), false, 'el reloj de pared retrocedió');
  assert.equal(datoVigente(recepcion, { pared: 1_010_000, mono: 4_000 }), false, 'monotónico hacia atrás');
  assert.equal(datoVigente(recepcion, { pared: 1_010_000, mono: Number.NaN }), false, 'sin reloj monotónico');
  assert.equal(datoVigente(null, { pared: 1_010_000, mono: 15_000 }), false);
});

test('estado de la vista: error, regreso y antigüedad retiran el verde; el reloj de negocio no cuenta', () => {
  const recepcion = { pared: 1_000_000, mono: 5_000 };
  const reciente = { pared: 1_010_000, mono: 15_000 };
  const viejo = { pared: 1_200_000, mono: 205_000 };
  const diagnostico = adaptarEstadoMonitoreo(estadoApi());
  const base = { diagnostico, recepcion, error: '', pendiente: false };

  assert.equal(estadoDeVista({ ...base, diagnostico: null }, reciente), 'cargando');
  assert.equal(estadoDeVista({ ...base, diagnostico: null, error: 'x' }, reciente), 'sin-diagnostico');
  assert.equal(estadoDeVista(base, reciente), 'vigente');
  assert.equal(estadoDeVista({ ...base, error: 'x' }, reciente), 'fallo-con-datos');
  assert.equal(estadoDeVista({ ...base, pendiente: true }, reciente), 'revalidando');
  assert.equal(estadoDeVista(base, viejo), 'antiguo');

  // Un reloj del servidor años atrás o adelante no cambia la vigencia.
  for (const ahora of ['2020-01-01T00:00:00', '2031-12-31T23:59:59']) {
    const desfasado = adaptarEstadoMonitoreo(estadoApi({
      momento_real: ahora,
      reloj_negocio: { ahora, fecha: ahora.slice(0, 10) },
    }));
    assert.equal(estadoDeVista({ ...base, diagnostico: desfasado }, reciente), 'vigente');
    assert.equal(estadoDeVista({ ...base, diagnostico: desfasado }, viejo), 'antiguo');
  }
});

// -------------------------------------------------------------
// 6. Vista: solo el lector y la actualización, sin fingir conectividad
// -------------------------------------------------------------
const RECEPCION = { pared: new Date(2026, 9, 9, 14, 3, 12).getTime(), mono: 0 };
const vista = ({ cuerpo = estadoApi(), estado = 'vigente', error = '', consultando = false, sinDatos = false } = {}) => (
  renderToStaticMarkup(h(VistaLectorBiometrico, {
    lector: sinDatos ? null : adaptarEstadoMonitoreo(cuerpo).lector,
    recepcion: sinDatos ? null : RECEPCION,
    error,
    consultando,
    estado,
    onActualizar() {},
  })).replace(/<!-- -->/g, '')
);
const regionViva = (html) => /<p class="lector__resumen-estado" role="status">(.*?)<\/p>/.exec(html)?.[1] ?? '';

test('vista vigente: lector desconocido en texto neutro, sin verde ni «desconectado»', () => {
  const html = vista();
  assert.match(html, /Lector de huellas/);
  assert.match(html, /<dd>Desconocido<\/dd>/);
  assert.match(html, /etiqueta--neutro">Sin información de conexión/);
  assert.match(html, /todavía no recibe señales del lector/);
  assert.match(html, /no puede saber si está conectado/);
  assert.match(html, /Que el estado sea desconocido no indica una falla/);
  assert.doesNotMatch(html, /etiqueta--exito/, 'nada verde: no se sabe si el lector funciona');
  assert.doesNotMatch(html, /desconectado|en línea|conectado correctamente|lector conectado|Todo operativo/i);
  assert.doesNotMatch(html, /\b(conectar|enrolar|enrolamiento)\b/i, 'sin botones ficticios');
  assert.match(html, /Actualizar/);
  assert.match(html, /Última consulta recibida en este equipo a las 14:03:12/);
  /* La región viva no lleva horas: un refresco no se vuelve a anunciar. */
  assert.doesNotMatch(regionViva(html), /\d{2}:\d{2}/);
  assert.match(regionViva(html), /Consulta reciente/);
});

test('vista: solo información del lector; nada de API, base, reloj, actividad ni Grafana', () => {
  const html = vista({ cuerpo: estadoApi({ entorno: 'desarrollo' }) });
  for (const retirado of [
    /Grafana/, /Integración pendiente/, /Catálogo de la base/, /Actividad del día/, /Reloj de negocio/,
    /Respondió/, /Revisión de migración/, /Lecturas aceptadas/, /Entorno de/,
    /sin zona horaria/, /Registro con el id más alto/, /Tablas propias/, />API</,
  ]) {
    assert.doesNotMatch(html, retirado, String(retirado));
  }
  assert.doesNotMatch(html, /<a\b|href=/);
  assert.equal((html.match(/<section class="tarjeta lector__tarjeta"/g) || []).length, 1, 'una sola tarjeta');
});

test('vista: carga inicial, estado no disponible y datos anteriores tras fallo se distinguen', () => {
  const carga = vista({ sinDatos: true, estado: 'cargando', consultando: true });
  assert.match(regionViva(carga), /Consultando el estado del lector…/);
  assert.match(carga, /Actualizando…/);
  assert.match(carga, /aria-disabled="true"/);
  assert.match(carga, /aria-busy="true"/);
  assert.doesNotMatch(carga, /etiqueta--exito/);
  assert.doesNotMatch(carga, /Lector de huellas|Desconocido/, 'sin datos no se muestra un estado del lector');

  const sinDatos = vista({ sinDatos: true, estado: 'sin-diagnostico', error: 'No se pudo consultar el lector biométrico. La API respondió con error HTTP 500.' });
  assert.match(sinDatos, /Estado no disponible/);
  assert.match(sinDatos, /role="alert"/);
  assert.match(sinDatos, /No se pudo consultar el estado del lector\./);
  assert.match(sinDatos, /error HTTP 500/);
  assert.doesNotMatch(sinDatos, /etiqueta--exito/);
  assert.doesNotMatch(sinDatos, /Lector de huellas|Desconocido/);

  const anteriores = vista({ estado: 'fallo-con-datos', error: 'No se pudo consultar el lector biométrico. No se pudo conectar con la API.' });
  assert.match(anteriores, /No se pudo actualizar el estado del lector\./);
  assert.match(anteriores, /Se muestran los datos de la última consulta/);
  assert.match(anteriores, /etiqueta--aviso">Dato anterior/);
  assert.match(anteriores, /<dd>Desconocido<\/dd>/, 'los datos anteriores siguen a la vista');
  assert.doesNotMatch(anteriores, /etiqueta--exito/);
});

test('vista: datos antiguos y revalidación se marcan como anteriores, también sin verde', () => {
  for (const [estado, texto] of [['antiguo', /Datos anteriores/], ['revalidando', /Revalidando/]]) {
    const html = vista({ estado });
    assert.match(regionViva(html), texto);
    assert.match(html, /etiqueta--aviso">Dato anterior/, estado);
    assert.doesNotMatch(html, /etiqueta--exito/, `${estado} no debe tener verde`);
  }
  assert.match(regionViva(vista({ estado: 'vigente' })), /Consulta reciente/);
  assert.doesNotMatch(vista({ estado: 'vigente' }), /Dato anterior/);
});

test('textoFechaHoraServidor muestra la hora del servidor sin convertir zona', () => {
  assert.equal(textoFechaHoraServidor('2026-10-09T23:59:59'), '09/10/2026 23:59:59');
  assert.equal(textoFechaHoraServidor('2026-10-09T00:00'), '09/10/2026 00:00');
  assert.equal(textoFechaHoraServidor(null), '—');
});
