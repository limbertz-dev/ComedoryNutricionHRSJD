/*
 * B0 — origen de la marcación biométrica.
 *
 * El simulador del lector solo se habilita con una confirmación vigente de
 * /salud (200, entorno 'simulacion'); el 403 `biometrico_solo_lector` es un
 * error local del simulador, separado del manejo central de la sesión.
 * Temporizador, documento y relojes son falsos: nada sale a una API real.
 */
import test, { afterEach, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { ErrorApi, MOTIVO_BIOMETRICO_SOLO_LECTOR, esRechazoBiometricoSoloLector,
  marcarAsistencia } from '../src/api.js';
import { borrarTokens, escucharSesion, guardarTokens, leerTokens } from '../src/sesion.js';
import { MS_REVALIDAR_SIMULACION, protegerAccionSimulador, vigilarSimulacion } from '../src/simulacion.js';
import { MS_ANTIGUEDAD_MAXIMA } from '../src/monitoreo.js';
import { CajaSesionCocinera } from '../src/components/layout/PanelSesionCocinera.jsx';
import SimuladorLector from '../src/components/secciones/SimuladorLector.jsx';

/* sessionStorage mínimo: en Node no existe y los tokens viven ahí. */
const almacen = new Map();
globalThis.sessionStorage = {
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

const salud = (entorno) => ({
  estado: 'ok', base_de_datos: 'conectada', entorno, faltan: [],
  reloj: { ahora: '2026-08-10T12:05:30', real: '2026-09-25T09:00:00', simulado: true },
});

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

/** Relojes del equipo controlados: pared y monotónico avanzan a mano. */
function relojesFalsos() {
  const ahora = { pared: 1_000_000, mono: 5_000 };
  return {
    medir: () => ({ ...ahora }),
    avanzar(ms, { soloPared = false } = {}) {
      ahora.pared += ms;
      if (!soloPared) ahora.mono += ms;
    },
  };
}

/** consultar controlado: cada vuelta queda pendiente hasta resolverla o fallarla. */
function consultaControlada() {
  const llamadas = [];
  const consultar = ({ signal }) => new Promise((resolver, rechazar) => {
    llamadas.push({ signal, resolver, rechazar });
  });
  return { llamadas, consultar };
}

const vaciar = async (vueltas = 10) => {
  for (let i = 0; i < vueltas; i += 1) await new Promise((r) => setImmediate(r));
};

const RELOJ = { ahora: new Date(2026, 7, 10, 12, 5), real: new Date(), simulado: true, congelado: null };
const confirmada = { simulacion: true, confirmada: true, reloj: RELOJ };

function armar({ consultar } = {}) {
  const temporizador = temporizadorFalso();
  const documento = documentoFalso();
  const relojes = relojesFalsos();
  let cambios = 0;
  const vigilante = vigilarSimulacion({
    consultar, documento, temporizador, medir: relojes.medir, alCambiar: () => { cambios += 1; },
  });
  return { vigilante, temporizador, documento, relojes, cambios: () => cambios };
}

// -------------------------------------------------------------
// 1. Confirmación del entorno
// -------------------------------------------------------------

test('carga: mientras /salud no responde, el simulador no está habilitado', () => {
  const { llamadas, consultar } = consultaControlada();
  const { vigilante } = armar({ consultar });
  assert.equal(llamadas.length, 1);
  assert.equal(vigilante.vigente(), false);
  assert.equal(vigilante.reloj(), null);
  vigilante.cancelar();
});

test('simulación confirmada por /salud habilita; se revalida 30 s después de terminar', async () => {
  const { llamadas, consultar } = consultaControlada();
  const { vigilante, temporizador } = armar({ consultar });
  assert.equal(temporizador.pendientes.size, 0, 'nada se programa con la consulta en vuelo');
  llamadas[0].resolver(confirmada);
  await vaciar();
  assert.equal(vigilante.vigente(), true);
  assert.equal(vigilante.reloj(), RELOJ);
  assert.equal(temporizador.pendientes.size, 1);
  assert.equal([...temporizador.pendientes.values()][0].ms, MS_REVALIDAR_SIMULACION);
  vigilante.cancelar();
});

test('producción y desarrollo: /salud real (fetch falso) nunca habilita', async () => {
  for (const entorno of ['produccion', 'desarrollo']) {
    globalThis.fetch = async () => json(salud(entorno));
    const { vigilante } = armar();
    await vaciar();
    assert.equal(vigilante.vigente(), false, entorno);
    assert.equal(vigilante.reloj(), null);
    vigilante.cancelar();
  }
});

test('/salud: 503, error, respuesta inválida o sin entorno no habilitan', async () => {
  const respuestas = [
    () => json({ ...salud('simulacion'), estado: 'incompleta', faltan: ['x'] }, 503),
    () => new Response('caído', { status: 500 }),
    () => json({ ...salud('simulacion'), reloj: { ahora: 'ayer', simulado: true } }),
    () => new Response('<html>', { status: 200 }),
    () => json({ estado: 'ok' }),
  ];
  for (const responder of respuestas) {
    globalThis.fetch = async () => responder();
    const { vigilante } = armar();
    await vaciar();
    assert.equal(vigilante.vigente(), false);
    vigilante.cancelar();
  }
  // Control: la misma ruta con 200 y entorno simulación sí habilita.
  globalThis.fetch = async () => json(salud('simulacion'));
  const { vigilante } = armar();
  await vaciar();
  assert.equal(vigilante.vigente(), true);
  vigilante.cancelar();
});

test('un fallo después de una confirmación la retira; el reloj queda solo para mostrar', async () => {
  const { llamadas, consultar } = consultaControlada();
  const { vigilante, temporizador } = armar({ consultar });
  llamadas[0].resolver(confirmada);
  await vaciar();
  assert.equal(vigilante.vigente(), true);

  temporizador.disparar();
  llamadas[1].rechazar(new Error('No se pudo consultar el estado de la API.'));
  await vaciar();
  assert.equal(vigilante.vigente(), false);
  assert.equal(vigilante.reloj(), RELOJ);

  // Un entorno distinto tras la confirmación también la retira.
  temporizador.disparar();
  llamadas[2].resolver({ simulacion: false, confirmada: false, reloj: null });
  await vaciar();
  assert.equal(vigilante.vigente(), false);
  vigilante.cancelar();
});

test('antigüedad: una confirmación no habilita más de 90 s ni tras una suspensión', async () => {
  const { llamadas, consultar } = consultaControlada();
  const { vigilante, relojes } = armar({ consultar });
  llamadas[0].resolver(confirmada);
  await vaciar();

  relojes.avanzar(MS_ANTIGUEDAD_MAXIMA);
  assert.equal(MS_ANTIGUEDAD_MAXIMA, 90000);
  assert.equal(vigilante.vigente(), true, 'justo en 90 s todavía vale');
  relojes.avanzar(1);
  assert.equal(vigilante.vigente(), false, 'pasados 90 s, no');
  vigilante.cancelar();

  // Suspensión: la pared salta y el monotónico no; no se puede fechar.
  const otra = consultaControlada();
  const armado = armar({ consultar: otra.consultar });
  otra.llamadas[0].resolver(confirmada);
  await vaciar();
  armado.relojes.avanzar(10_000, { soloPared: true });
  assert.equal(armado.vigilante.vigente(), false);
  armado.vigilante.cancelar();
});

test('regreso a la pestaña: se deshabilita al instante y espera otra confirmación, sin solapes', async () => {
  const { llamadas, consultar } = consultaControlada();
  const { vigilante, documento, temporizador } = armar({ consultar });
  llamadas[0].resolver(confirmada);
  await vaciar();
  assert.equal(vigilante.vigente(), true);

  documento.cambiar('hidden');
  assert.equal(temporizador.pendientes.size, 0, 'oculta: no se consulta');
  documento.cambiar('visible');
  assert.equal(vigilante.vigente(), false, 'al volver no hay permiso hasta confirmar');
  assert.equal(llamadas.length, 2, 'una sola consulta nueva');

  // Volver otra vez con la consulta en vuelo: la anterior se descarta.
  documento.cambiar('hidden');
  documento.cambiar('visible');
  assert.equal(llamadas.length, 3);
  assert.equal(llamadas[1].signal.aborted, true);
  llamadas[1].resolver(confirmada);
  await vaciar();
  assert.equal(vigilante.vigente(), false, 'la respuesta descartada no confirma');

  llamadas[2].resolver(confirmada);
  await vaciar();
  assert.equal(vigilante.vigente(), true);
  vigilante.cancelar();
  assert.equal(documento.oyentes.size, 0);
});

// -------------------------------------------------------------
// 2. Callbacks y montaje
// -------------------------------------------------------------

test('las acciones del simulador no llegan a la API sin confirmación vigente', async () => {
  const { llamadas, consultar } = consultaControlada();
  const { vigilante, relojes } = armar({ consultar });
  const usadas = [];
  const marcar = protegerAccionSimulador(() => vigilante.vigente(), (id) => usadas.push(id));

  marcar(3);
  assert.deepEqual(usadas, [], 'en la carga no se ejecuta');

  llamadas[0].resolver(confirmada);
  await vaciar();
  marcar(3);
  assert.deepEqual(usadas, [3]);

  relojes.avanzar(MS_ANTIGUEDAD_MAXIMA + 1);
  marcar(4);
  assert.deepEqual(usadas, [3], 'vencida, el botón que quedó a la vista no hace nada');

  let bloqueado = true;
  const conBloqueo = protegerAccionSimulador(() => !bloqueado, () => usadas.push('falla'));
  conBloqueo();
  bloqueado = false;
  conBloqueo();
  assert.deepEqual(usadas, [3, 'falla']);
  vigilante.cancelar();
});

test('fuera de simulación el panel de cocinera queda sin selector, Al azar ni Falla biométrica', () => {
  globalThis.document = {
    fullscreenElement: null,
    documentElement: { requestFullscreen: async () => {} },
    exitFullscreen: async () => {},
  };
  try {
    const props = {
      cajaRef: { current: null }, abierto: true, onAlternar() {}, usuario: 'maria.cocina',
      rol: 'cocinera', onCerrarSesion() {},
    };
    const sin = renderToStaticMarkup(h(CajaSesionCocinera, { ...props, simulador: null }));
    assert.doesNotMatch(sin, /panel-sesion__simulador|Modo pruebas|<select|Al azar|Falla biométrica|Apoyar huella/);
    assert.match(sin, /<span class="boton__texto">Pantalla completa<\/span>/);
    assert.match(sin, /<span class="boton__texto">Cerrar sesión<\/span>/);

    const con = renderToStaticMarkup(h(CajaSesionCocinera, {
      ...props,
      simulador: h(SimuladorLector, {
        personal: [], seleccionado: '', onSeleccionar() {}, onMarcar() {}, onSimularFalla() {},
        leyendo: false, error: '',
      }),
    }));
    assert.match(con, /panel-sesion__simulador/);
    assert.match(con, /Falla biométrica/);
  } finally {
    delete globalThis.document;
  }
});

// -------------------------------------------------------------
// 3. 403 biometrico_solo_lector frente a los errores de sesión
// -------------------------------------------------------------

const DETALLE = 'La marcación biométrica requiere un lector autorizado fuera de simulación.';

function responderAsistencias(status, cuerpo) {
  const peticiones = [];
  globalThis.fetch = async (url, opciones = {}) => {
    peticiones.push({ ruta: new URL(url).pathname, metodo: opciones.method ?? 'GET',
      cuerpo: opciones.body ? JSON.parse(opciones.body) : null });
    return json(cuerpo, status);
  };
  return peticiones;
}

test('403 biometrico_solo_lector: detalle del servidor, sin aviso central ni registro manual', async () => {
  guardarTokens({ access: 'acc', refresh: 'r', usuario: 'cocina1' });
  const peticiones = responderAsistencias(403, { detail: DETALLE, motivo: MOTIVO_BIOMETRICO_SOLO_LECTOR });

  await assert.rejects(marcarAsistencia(null, { metodo: 'biometrico' }), (error) => {
    assert.equal(esRechazoBiometricoSoloLector(error), true);
    assert.ok(error instanceof ErrorApi);
    assert.equal(error.message, DETALLE);
    return true;
  });
  assert.deepEqual(avisos, [], 'no es «Sin permiso» ni cierra la sesión');
  assert.equal(leerTokens()?.access, 'acc');
  assert.deepEqual(peticiones, [{ ruta: '/asistencias', metodo: 'POST',
    cuerpo: { usuario_id: null, metodo: 'biometrico' } }], 'una sola petición, nunca como manual');

  // Con persona elegida pasa lo mismo.
  const persona = { id: 3, nombre: 'Persona 3', categoria: 'Médico', legajo: 'ITEM-3' };
  responderAsistencias(403, { detail: DETALLE, motivo: MOTIVO_BIOMETRICO_SOLO_LECTOR });
  await assert.rejects(marcarAsistencia(3, { persona, metodo: 'biometrico' }), esRechazoBiometricoSoloLector);
  assert.deepEqual(avisos, []);
});

test('los demás 401, 403 y 428 de POST /asistencias siguen el manejo central', async () => {
  const casos = [
    { status: 403, cuerpo: { detail: 'Sin permiso.', motivo: 'rol_no_autorizado' }, aviso: 'prohibido' },
    { status: 403, cuerpo: { detail: 'Debe cambiar.', motivo: 'cambio_password_pendiente' }, aviso: 'cambio_requerido' },
    { status: 428, cuerpo: { detail: 'Debe cambiar.', motivo: 'cambio_password_pendiente' }, aviso: 'cambio_requerido' },
    { status: 401, cuerpo: { detail: 'Sesión inválida.', motivo: 'token_invalido' }, aviso: 'expirada' },
  ];
  for (const { status, cuerpo, aviso } of casos) {
    avisos.length = 0;
    guardarTokens({ access: 'acc', refresh: null, usuario: 'cocina1' });
    responderAsistencias(status, cuerpo);
    await assert.rejects(marcarAsistencia(null, { metodo: 'biometrico' }), (error) => {
      assert.equal(esRechazoBiometricoSoloLector(error), false);
      assert.match(error.message, /^No se pudo confirmar la marcación\./);
      return true;
    });
    assert.deepEqual(avisos, [aviso], `${status} ${cuerpo.motivo}`);
  }
});

test('el motivo biometrico_solo_lector solo es local en una marcación biométrica', async () => {
  guardarTokens({ access: 'acc', refresh: null, usuario: 'jefa1' });
  const persona = { id: 3, nombre: 'Persona 3', categoria: 'Médico', legajo: 'ITEM-3' };
  responderAsistencias(403, { detail: DETALLE, motivo: MOTIVO_BIOMETRICO_SOLO_LECTOR });
  await assert.rejects(marcarAsistencia(3, { persona, metodo: 'manual' }), (error) => {
    assert.equal(esRechazoBiometricoSoloLector(error), false);
    assert.match(error.message, /^No se pudo confirmar la marcación\./);
    return true;
  });
  assert.deepEqual(avisos, ['prohibido']);
});
