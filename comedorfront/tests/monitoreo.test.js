/*
 * R3-1 Salud del sistema (solo sistemas), contrato R3-1-20261009.
 * Permisos, adaptador GET /monitoreo/estado con fetch controlado, refresco
 * con temporizadores y documento falsos, vigencia y estados de la vista.
 */
import test, { afterEach, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { adaptarEstadoMonitoreo, obtenerEstadoMonitoreo, obtenerSalud } from '../src/api.js';
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
import { VistaSaludSistema } from '../src/components/secciones/SaludSistema.jsx';

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
  reloj_negocio: { ahora: '2026-10-09T14:03:10', fecha: '2026-10-09', simulado: false, congelado: false },
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
test("solo sistemas ve 'monitoreo' en permisos y menú", () => {
  assert.equal(puedeVerSeccion('sistemas', 'monitoreo'), true);
  assert.equal(puedeVerSeccion('jefa', 'monitoreo'), false);
  assert.equal(puedeVerSeccion('cocinera', 'monitoreo'), false);
  assert.equal(puedeVerSeccion('nutricionista', 'monitoreo'), false);
  assert.ok(seccionesPermitidas('sistemas').includes('monitoreo'));
  assert.ok(seccionesDeRol('sistemas').some(({ id }) => id === 'monitoreo'));
  assert.ok(!seccionesDeRol('jefa').some(({ id }) => id === 'monitoreo'));
  assert.ok(!seccionesDeRol('cocinera').some(({ id }) => id === 'monitoreo'));

  const seccion = buscarSeccion('monitoreo');
  assert.equal(seccion.titulo, 'Salud del sistema');
  assert.equal(typeof seccion.Icono, 'function');
});

test('sistemas monta Salud del sistema; jefa y cocinera con monitoreo guardado no', () => {
  const localOriginal = globalThis.localStorage;
  const montar = (rol) => {
    globalThis.localStorage = { getItem: () => 'monitoreo', setItem: () => {}, removeItem: () => {} };
    return renderToStaticMarkup(h(ProveedorSesion, null, h(Panel, { rol, usuario: `${rol}.test` })));
  };
  try {
    const htmlSistemas = montar('sistemas');
    assert.match(htmlSistemas, /Consultando el diagnóstico del sistema…/);
    assert.match(htmlSistemas, /Actualizar diagnóstico|Actualizando diagnóstico…/);

    const htmlJefa = montar('jefa');
    assert.doesNotMatch(htmlJefa, /diagnóstico/);
    assert.match(htmlJefa, /Cargando supervisión…/);

    const htmlCocinera = montar('cocinera');
    assert.doesNotMatch(htmlCocinera, /diagnóstico/);
  } finally {
    if (localOriginal === undefined) delete globalThis.localStorage;
    else globalThis.localStorage = localOriginal;
  }
});

// -------------------------------------------------------------
// 2. Adaptador GET /monitoreo/estado
// -------------------------------------------------------------
test('obtenerEstadoMonitoreo pide /monitoreo/estado firmado y adapta el caso normal', async () => {
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
  assert.deepEqual(estado, {
    momentoReal: '2026-10-09T14:03:10',
    entorno: 'produccion',
    relojNegocio: { ahora: '2026-10-09T14:03:10', fecha: '2026-10-09', simulado: false, congelado: false },
    base: { estado: 'ok', revisionAlembic: 'f6a7b8c9d0e1', tablasPropias: 14, vistasContrato: 3, faltan: [] },
    lector: { estado: 'desconocido', razon: 'sin_telemetria' },
    actividad: {
      fuente: 'lecturas_biometricas',
      disponible: true,
      razon: null,
      aceptadasDia: 12,
      rechazadasDia: 2,
      registroMayorId: {
        id: 345,
        fechaHora: '2026-10-09T13:58:00',
        resultado: 'rechazada',
        motivo: 'duplicado',
        createdAt: '2026-10-09T13:58:01',
      },
    },
  });
  assert.deepEqual(avisos, []);
});

test('adaptador: nulos válidos, tabla vacía, esquema incompleto y actividad no disponible', () => {
  const vacia = adaptarEstadoMonitoreo(estadoApi({
    base: baseApi({ revision_alembic: null }),
    actividad: actividadApi({ aceptadas_dia: 0, rechazadas_dia: 0, registro_mayor_id: null }),
  }));
  assert.equal(vacia.base.revisionAlembic, null);
  assert.equal(vacia.actividad.aceptadasDia, 0);
  assert.equal(vacia.actividad.registroMayorId, null);

  const incompleta = adaptarEstadoMonitoreo(estadoApi({
    base: baseApi({ estado: 'incompleta', faltan: ['lecturas_biometricas', 'vw_personal'] }),
    actividad: ACTIVIDAD_AUSENTE,
  }));
  assert.equal(incompleta.base.estado, 'incompleta');
  assert.deepEqual(incompleta.base.faltan, ['lecturas_biometricas', 'vw_personal']);
  assert.equal(incompleta.actividad.disponible, false);
  assert.equal(incompleta.actividad.razon, 'tabla_ausente');
  assert.equal(incompleta.actividad.aceptadasDia, null, 'null nunca se vuelve cero');
  assert.equal(incompleta.actividad.rechazadasDia, null);

  const fallida = adaptarEstadoMonitoreo(estadoApi({ actividad: { ...ACTIVIDAD_AUSENTE, razon: 'error_consulta' } }));
  assert.equal(fallida.actividad.razon, 'error_consulta');
  assert.equal(fallida.actividad.aceptadasDia, null);

  const aceptada = adaptarEstadoMonitoreo(estadoApi({
    actividad: actividadApi({ registro_mayor_id: { ...estadoApi().actividad.registro_mayor_id, resultado: 'aceptada', motivo: null } }),
  }));
  assert.equal(aceptada.actividad.registroMayorId.motivo, null);
});

test('adaptador rechaza cuerpos inválidos o incoherentes sin convertir tipos', async () => {
  const invalidos = [
    ['cuerpo', []],
    ['cuerpo', null],
    ['momento_real', estadoApi({ momento_real: '2026-10-09T14:03:10Z' })],
    ['momento_real', estadoApi({ momento_real: '2026-10-09T14:03:10-04:00' })],
    ['entorno', estadoApi({ entorno: 'pruebas' })],
    ['reloj_negocio.fecha', estadoApi({ reloj_negocio: { ...estadoApi().reloj_negocio, fecha: '2026-10-08' } })],
    ['reloj_negocio', estadoApi({ reloj_negocio: { ...estadoApi().reloj_negocio, congelado: 'no' } })],
    ['base.conteos', estadoApi({ base: baseApi({ tablas_propias: '14' }) })],
    ['base.conteos', estadoApi({ base: baseApi({ vistas_contrato: -1 }) })],
    ['base.estado', estadoApi({ base: baseApi({ faltan: ['x'] }) })],
    ['base.faltan', estadoApi({ base: baseApi({ estado: 'incompleta', faltan: [3] }) })],
    ['lector', estadoApi({ lector: { estado: 'conectado', razon: 'sin_telemetria' } })],
    ['lector', estadoApi({ lector: { estado: 'desconocido', razon: null } })],
    ['actividad.fuente', estadoApi({ actividad: actividadApi({ fuente: 'otra' }) })],
    ['actividad.contadores', estadoApi({ actividad: actividadApi({ aceptadas_dia: '12' }) })],
    ['actividad.contadores', estadoApi({ actividad: actividadApi({ rechazadas_dia: null }) })],
    ['actividad.contadores', estadoApi({ actividad: actividadApi({ aceptadas_dia: 1.5 }) })],
    ['actividad.razon', estadoApi({ actividad: actividadApi({ razon: 'tabla_ausente' }) })],
    ['actividad.razon', estadoApi({ actividad: { ...ACTIVIDAD_AUSENTE, razon: null } })],
    ['actividad sin datos', estadoApi({ actividad: { ...ACTIVIDAD_AUSENTE, aceptadas_dia: 0, rechazadas_dia: 0 } })],
    ['registro_mayor_id.id', estadoApi({ actividad: actividadApi({ registro_mayor_id: { ...estadoApi().actividad.registro_mayor_id, id: 0 } }) })],
    ['registro_mayor_id.id', estadoApi({ actividad: actividadApi({ registro_mayor_id: { ...estadoApi().actividad.registro_mayor_id, id: '345' } }) })],
    ['registro_mayor_id.motivo', estadoApi({ actividad: actividadApi({ registro_mayor_id: { ...estadoApi().actividad.registro_mayor_id, motivo: 'otro' } }) })],
    ['registro_mayor_id.created_at', estadoApi({ actividad: actividadApi({ registro_mayor_id: { ...estadoApi().actividad.registro_mayor_id, created_at: null } }) })],
  ];
  for (const [campo, cuerpo] of invalidos) {
    assert.throws(() => adaptarEstadoMonitoreo(cuerpo), (error) => error.message.includes(`(${campo})`),
      `debía rechazar ${campo}`);
  }
  const sinClave = estadoApi();
  delete sinClave.actividad;
  assert.throws(() => adaptarEstadoMonitoreo(sinClave), /diagnóstico inválido \(actividad\)/);

  globalThis.fetch = async () => json(estadoApi({ entorno: 'pruebas' }));
  await assert.rejects(obtenerEstadoMonitoreo(), /No se pudo obtener el diagnóstico del sistema\. .*inválido/);
});

test('adaptador: fechas imposibles se rechazan, no se normalizan', () => {
  const conAhora = (ahora) => estadoApi({
    reloj_negocio: { ...estadoApi().reloj_negocio, ahora, fecha: ahora.slice(0, 10) },
  });
  const imposibles = [
    ['31 de febrero', '2026-02-31T12:00:00'],
    ['29 de febrero no bisiesto', '2026-02-29T12:00:00'],
    ['29 de febrero de 1900', '1900-02-29T12:00:00'],
    ['31 de abril', '2026-04-31T12:00:00'],
    ['mes 13', '2026-13-01T12:00:00'],
    ['mes 0', '2026-00-10T12:00:00'],
    ['día 0', '2026-10-00T12:00:00'],
    ['hora 24', '2026-10-09T24:00:00'],
    ['minuto 60', '2026-10-09T14:60:00'],
    ['segundo 60', '2026-10-09T14:03:60'],
  ];
  for (const [caso, texto] of imposibles) {
    assert.throws(() => adaptarEstadoMonitoreo(estadoApi({ momento_real: texto })),
      /\(momento_real\)/, `momento_real: ${caso}`);
    assert.throws(() => adaptarEstadoMonitoreo(conAhora(texto)), /\(reloj_negocio\.ahora\)/,
      `reloj_negocio.ahora: ${caso}`);
    const registro = { ...estadoApi().actividad.registro_mayor_id, fecha_hora: texto };
    assert.throws(() => adaptarEstadoMonitoreo(estadoApi({ actividad: actividadApi({ registro_mayor_id: registro }) })),
      /\(registro_mayor_id\.fecha_hora\)/, `fecha_hora: ${caso}`);
  }
  assert.throws(() => adaptarEstadoMonitoreo(estadoApi({
    reloj_negocio: { ...estadoApi().reloj_negocio, ahora: '2026-02-31T12:00:00', fecha: '2026-02-31' },
  })), /\(reloj_negocio\.ahora\)/);

  // Válidas: bisiestos (incluido 2000), extremos del día, microsegundos y los formatos ya aceptados.
  for (const texto of [
    '2028-02-29T12:00:00',
    '2000-02-29T00:00:00',
    '2026-12-31T23:59:59',
    '2026-10-09T14:03:10.123456',
    '2026-10-09T14:03',
    '2026-10-09 14:03:10',
  ]) {
    const estado = adaptarEstadoMonitoreo(conAhora(texto));
    assert.equal(estado.relojNegocio.ahora, texto, 'el texto se conserva sin convertir zona');
    assert.equal(adaptarEstadoMonitoreo(estadoApi({ momento_real: texto })).momentoReal, texto);
  }
  assert.throws(() => adaptarEstadoMonitoreo(estadoApi({ momento_real: '2026-10-09T14:03:10.1234567' })),
    /\(momento_real\)/, 'más de 6 decimales');
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

test('401 vacía la sesión y avisa «expirada»; un 500 sin cuerpo no nombra componente', async () => {
  guardarTokens({ access: 'acc', refresh: null, usuario: 'root' });
  globalThis.fetch = async () => json({ detail: 'Sesión inválida.', motivo: 'token_invalido' }, 401);
  await assert.rejects(obtenerEstadoMonitoreo(), (error) => error.cause.status === 401
    && error.cause.datos.motivo === 'token_invalido');
  assert.deepEqual(avisos, ['expirada']);
  assert.equal(leerTokens(), null);

  avisos.length = 0;
  globalThis.fetch = async () => new Response('Internal Server Error', { status: 500 });
  await assert.rejects(obtenerEstadoMonitoreo(), (error) => {
    assert.equal(error.message, 'No se pudo obtener el diagnóstico del sistema. La API respondió con error HTTP 500.');
    assert.doesNotMatch(error.message, /base|lector|actividad|MySQL/i);
    return true;
  });
  assert.deepEqual(avisos, []);
});

test('obtenerSalud no cambia: sigue sin firmar avisos y acepta el 503 con cuerpo', async () => {
  globalThis.fetch = async (url) => {
    assert.equal(new URL(url).pathname, '/salud');
    return json({ entorno: 'produccion' }, 503);
  };
  assert.deepEqual(await obtenerSalud(), { entorno: 'produccion', simulacion: false, reloj: null });
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

test('estado de la vista: error, regreso y antigüedad retiran el verde; el reloj simulado no cuenta', () => {
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

  // Un reloj de negocio simulado años atrás o adelante no cambia la vigencia.
  for (const ahora of ['2020-01-01T00:00:00', '2031-12-31T23:59:59']) {
    const simulado = adaptarEstadoMonitoreo(estadoApi({
      entorno: 'simulacion',
      momento_real: ahora,
      reloj_negocio: { ahora, fecha: ahora.slice(0, 10), simulado: true, congelado: true },
    }));
    assert.equal(estadoDeVista({ ...base, diagnostico: simulado }, reciente), 'vigente');
    assert.equal(estadoDeVista({ ...base, diagnostico: simulado }, viejo), 'antiguo');
  }
});

// -------------------------------------------------------------
// 6. Vista: estados y textos
// -------------------------------------------------------------
const RECEPCION = { pared: new Date(2026, 9, 9, 14, 3, 12).getTime(), mono: 0 };
const vista = ({ cuerpo = estadoApi(), estado = 'vigente', error = '', consultando = false, sinDatos = false } = {}) => (
  renderToStaticMarkup(h(VistaSaludSistema, {
    diagnostico: sinDatos ? null : adaptarEstadoMonitoreo(cuerpo),
    recepcion: sinDatos ? null : RECEPCION,
    error,
    consultando,
    estado,
    onActualizar() {},
  })).replace(/<!-- -->/g, '')
);
const regionViva = (html) => /<p class="salud__resumen-estado" role="status">(.*?)<\/p>/.exec(html)?.[1] ?? '';

test('vista vigente: diagnóstico actualizado, sin «Todo operativo», lector sin verde y Grafana sin enlace', () => {
  const html = vista();
  assert.match(html, /Diagnóstico actualizado/);
  assert.doesNotMatch(html, /Todo operativo/i);
  assert.match(html, /etiqueta--exito">Respondió/);
  assert.match(html, /Lector biométrico/);
  assert.match(html, /etiqueta--neutro">Sin telemetría de conexión/);
  assert.doesNotMatch(html, /desconectado/i);
  assert.match(html, /Integración pendiente/);
  assert.doesNotMatch(html, /<a\b|href=/);
  assert.match(html, /Actualizar diagnóstico/);
  assert.match(html, /Solo se comprueba su presencia en el catálogo/);
  assert.match(html, /09\/10\/2026 14:03:10 \(sin zona horaria informada\)/);
  assert.match(html, /14:03:12 \(reloj de este equipo\)/);
  // La región viva no lleva horas: un refresco no se vuelve a anunciar.
  assert.doesNotMatch(regionViva(html), /\d{2}:\d{2}/);
});

test('vista: con lecturas nunca afirma conectividad y el mayor id no es el último toque', () => {
  const html = vista();
  assert.match(html, /Registro con el id más alto/);
  assert.match(html, /N\.º 345/);
  assert.match(html, /no es necesariamente la última huella/);
  assert.match(html, /Tener lecturas no prueba que el lector esté conectado/);
  assert.doesNotMatch(html, /lector conectado|conectado correctamente|en línea/i);
  assert.doesNotMatch(html, /última marcación del lector|último toque/i);
});

test('vista: carga inicial, diagnóstico no disponible y datos anteriores tras fallo', () => {
  const carga = vista({ sinDatos: true, estado: 'cargando', consultando: true });
  assert.match(regionViva(carga), /Consultando el diagnóstico del sistema…/);
  assert.match(carga, /Actualizando diagnóstico…/);
  assert.match(carga, /aria-disabled="true"/);
  assert.match(carga, /aria-busy="true"/);
  assert.doesNotMatch(carga, /etiqueta--exito/);
  assert.doesNotMatch(carga, /Lector biométrico/);

  const sinDiagnostico = vista({ sinDatos: true, estado: 'sin-diagnostico', error: 'No se pudo obtener el diagnóstico del sistema. La API respondió con error HTTP 500.' });
  assert.match(sinDiagnostico, /Diagnóstico no disponible/);
  assert.match(sinDiagnostico, /role="alert"/);
  assert.match(sinDiagnostico, /no es posible saber qué componente falló/);
  assert.doesNotMatch(sinDiagnostico, /etiqueta--exito/);
  assert.doesNotMatch(sinDiagnostico, /Catálogo de la base|Lector biométrico|Actividad del día/);
  assert.match(sinDiagnostico, /Integración pendiente/);

  const anteriores = vista({ estado: 'fallo-con-datos', error: 'No se pudo obtener el diagnóstico del sistema. No se pudo conectar con la API.' });
  assert.match(anteriores, /No se pudo actualizar el diagnóstico/);
  assert.match(anteriores, /Se muestran los datos anteriores/);
  assert.match(anteriores, /Respuesta anterior/);
  assert.match(anteriores, /Presentes en el catálogo \(dato anterior\)/);
  assert.doesNotMatch(anteriores, /etiqueta--exito/);
});

test('vista: datos antiguos y revalidación tampoco muestran verde', () => {
  for (const [estado, texto] of [['antiguo', /Datos antiguos/], ['revalidando', /Revalidando/]]) {
    const html = vista({ estado });
    assert.match(regionViva(html), texto);
    assert.doesNotMatch(html, /etiqueta--exito/, `${estado} no debe tener verde`);
  }
});

test('vista: esquema incompleto, actividad vacía y actividad no consultable se distinguen', () => {
  const incompleta = vista({ cuerpo: estadoApi({
    base: baseApi({ estado: 'incompleta', faltan: ['lecturas_biometricas', 'vw_personal'] }),
    actividad: ACTIVIDAD_AUSENTE,
  }) });
  assert.match(incompleta, /Esquema incompleto/);
  assert.match(incompleta, /<code>lecturas_biometricas<\/code>/);
  assert.match(incompleta, /<code>vw_personal<\/code>/);
  assert.match(incompleta, /La tabla de lecturas no existe en la base/);
  assert.match(incompleta, /no están disponibles \(no son cero\)/);
  assert.doesNotMatch(incompleta, /<dd>0<\/dd>/);

  const errorConsulta = vista({ cuerpo: estadoApi({ actividad: { ...ACTIVIDAD_AUSENTE, razon: 'error_consulta' } }) });
  assert.match(errorConsulta, /La consulta de actividad falló/);
  assert.doesNotMatch(errorConsulta, /<dd>0<\/dd>/);

  const vacia = vista({ cuerpo: estadoApi({ actividad: actividadApi({ aceptadas_dia: 0, rechazadas_dia: 0, registro_mayor_id: null }) }) });
  assert.match(vacia, /La tabla de lecturas está vacía/);
  assert.match(vacia, /<dd>0<\/dd>/);
  assert.doesNotMatch(vacia, /No disponible/);

  const sinHoy = vista({ cuerpo: estadoApi({ actividad: actividadApi({ aceptadas_dia: 0, rechazadas_dia: 0 }) }) });
  assert.match(sinHoy, /No hay lecturas en la fecha de negocio 09\/10\/2026/);
});

test('vista: entorno de simulación con reloj real se muestran como hechos separados', () => {
  const html = vista({ cuerpo: estadoApi({ entorno: 'simulacion' }) });
  assert.match(html, /Entorno de simulación/);
  assert.match(html, /Esto no indica si hay o no un lector\s+físico/);
  assert.match(html, /etiqueta--neutro">Reloj real/);
  assert.match(html, /Real, en marcha/);
  assert.doesNotMatch(html, /Reloj simulado/);
  assert.doesNotMatch(html, /no hay (lector|dispositivo)|sin hardware|sin lector físico/i);

  const simulado = vista({ cuerpo: estadoApi({
    entorno: 'produccion',
    reloj_negocio: { ahora: '2026-10-09T07:00:00', fecha: '2026-10-09', simulado: true, congelado: true },
  }) });
  assert.doesNotMatch(simulado, /Entorno de simulación/);
  assert.match(simulado, /Reloj simulado/);
  assert.match(simulado, /Simulado, congelado/);
});

test('textoFechaHoraServidor muestra la hora del servidor sin convertir zona', () => {
  assert.equal(textoFechaHoraServidor('2026-10-09T23:59:59'), '09/10/2026 23:59:59');
  assert.equal(textoFechaHoraServidor('2026-10-09T00:00'), '09/10/2026 00:00');
  assert.equal(textoFechaHoraServidor(null), '—');
});
