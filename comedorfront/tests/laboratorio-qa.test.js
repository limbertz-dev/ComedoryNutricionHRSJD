import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const codigo = readFileSync(new URL('../../qa/prueba-basica/laboratorio/modal.js', import.meta.url), 'utf8');

/** @returns {object} Entorno DOM minimo para ejecutar el puente real del modal. */
function entorno(fetch = async () => { throw new Error('sin red'); }) {
  const window = new EventTarget();
  const mensajes = [];
  const origen = { postMessage: (...args) => mensajes.push(args) };
  const elementos = Object.fromEntries(['qa-abrir', 'qa-modal', 'qa-cerrar', 'qa-marco'].map(id => [id, new EventTarget()]));
  for (const el of Object.values(elementos)) el.focus = () => {};
  const modal = elementos['qa-modal'];
  modal.open = true;
  modal.close = () => { modal.open = false; modal.dispatchEvent(new Event('close')); };
  modal.showModal = () => { modal.open = true; };
  const marco = elementos['qa-marco'];
  marco.contentWindow = origen;
  marco.getAttribute = () => 'http://127.0.0.1:8002';
  const document = { querySelector: selector => elementos[selector.slice(1)] };
  const almacen = new Map();
  const sessionStorage = { getItem: k => almacen.get(k) ?? null, setItem: (k, v) => almacen.set(k, v), removeItem: k => almacen.delete(k) };
  vm.runInNewContext(codigo, { window, document, CustomEvent, sessionStorage, fetch, crypto, AbortSignal });
  return { window, modal, origen, mensajes, sessionStorage };
}

/** @param {object} entorno @param {object} datos @returns {void} */
function mensaje(entorno, datos) {
  const evento = new Event('message');
  Object.assign(evento, { origin: 'http://127.0.0.1:8002', source: entorno.origen,
    data: { tipo: 'registrar-huella-caso-qa', caso: 'qa01', usuario_id: 900101 }, ...datos });
  entorno.window.dispatchEvent(evento);
}

test('el modal abre solo el registro del caso esperado y vuelve sin otra ventana', () => {
  const e = entorno();
  const solicitudes = [];
  e.window.addEventListener('qa:registrar-huella', evento => { solicitudes.push(evento.detail); evento.preventDefault(); });
  mensaje(e, {});
  assert.deepEqual(JSON.parse(JSON.stringify(solicitudes)), [{ caso: 'qa01', usuarioId: 900101 }]);
  assert.equal(e.modal.open, false);
  e.window.dispatchEvent(new Event('qa:volver-simulador'));
  assert.equal(e.modal.open, true);
  assert.equal(e.mensajes[0][0].tipo, 'actualizar-laboratorio-qa');
});

test('el puente ignora origen, ventana e identidad de caso incorrectos', () => {
  const e = entorno();
  let solicitudes = 0;
  e.window.addEventListener('qa:registrar-huella', () => { solicitudes += 1; });
  mensaje(e, { origin: 'https://ajeno.example' });
  mensaje(e, { source: {} });
  mensaje(e, { data: { tipo: 'registrar-huella-caso-qa', caso: 'qa01', usuario_id: 900103 } });
  mensaje(e, { data: { tipo: 'registrar-huella-caso-qa' } });
  assert.equal(solicitudes, 0);
  assert.equal(e.mensajes.length, 0);
  assert.equal(e.modal.open, true);
});

test('sin cocina autenticada conserva el modal y pide iniciar sesion', () => {
  const e = entorno();
  mensaje(e, {});
  assert.equal(e.modal.open, true);
  assert.equal(e.mensajes[0][0].tipo, 'registro-huella-no-disponible-qa');
});

const referencia = 'SIM-HUELLA-550e8400-e29b-41d4-a716-446655440000';
const leer = { tipo: 'leer-huella-caso-qa', caso: 'qa01', usuario_id: 900101, referencia };

test('la relectura incierta conserva la misma clave tras reconectar y bloquea otro contacto', async () => {
  const llamadas = [];
  let fallo = true;
  const e = entorno(async (_url, opciones) => {
    llamadas.push(opciones);
    if (fallo) throw new Error('red cortada después del commit');
    return { ok: true, status: 200, json: async () => ({ usuario_id: 900101, lectura_id: 27, valido: false, motivo: 'duplicado' }) };
  });
  e.sessionStorage.setItem('comedor_sesion', JSON.stringify({ access: 'fixture-sin-validez', usuario: 'cocinera2' }));
  mensaje(e, { data: leer });
  await new Promise(resolve => setImmediate(resolve));
  const clave = llamadas[0].headers['Idempotency-Key'];
  assert.equal(e.mensajes.at(-1)[0].incierto, true);
  assert.ok(e.sessionStorage.getItem('qa_relectura_pendiente'));
  mensaje(e, { data: { ...leer, referencia: 'SIM-HUELLA-650e8400-e29b-41d4-a716-446655440000' } });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(llamadas.length, 1);
  fallo = false;
  mensaje(e, { data: leer });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(llamadas.length, 2);
  assert.equal(llamadas[1].headers['Idempotency-Key'], clave);
  assert.equal(e.mensajes.at(-1)[0].duplicado, true);
  assert.equal(e.sessionStorage.getItem('qa_relectura_pendiente'), null);
});

test('doble clic en relectura emite un solo POST y respeta la sesión autenticada', async () => {
  let resolver;
  const llamadas = [];
  const e = entorno((_url, opciones) => { llamadas.push(opciones); return new Promise(resolve => { resolver = resolve; }); });
  e.sessionStorage.setItem('comedor_sesion', JSON.stringify({ access: 'fixture-sin-validez', usuario: 'cocinera2' }));
  mensaje(e, { data: leer });
  mensaje(e, { data: leer });
  assert.equal(llamadas.length, 1);
  assert.equal(llamadas[0].headers.Authorization, 'Bearer fixture-sin-validez');
  resolver({ ok: true, status: 200, json: async () => ({ usuario_id: 900101, lectura_id: 28, valido: false, motivo: 'duplicado' }) });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(e.mensajes.at(-1)[0].duplicado, true);
});

test('no ejecuta relecturas de otra ventana, identidad o sin sesión', async () => {
  let llamadas = 0;
  const e = entorno(async () => { llamadas++; });
  mensaje(e, { data: leer, origin: 'https://ajeno.example' });
  mensaje(e, { data: { ...leer, usuario_id: 900102 } });
  mensaje(e, { data: leer });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(llamadas, 0);
  assert.match(e.mensajes.at(-1)[0].error, /Inicia sesión/);
});

test('la sesión expirada no descarta una lectura que ya tenía resultado incierto', async () => {
  const e = entorno(async () => ({ ok: false, status: 401 }));
  const previo = JSON.stringify({ solicitud: 'misma-solicitud', referencia, usuario: 'cocinera2' });
  e.sessionStorage.setItem('qa_relectura_pendiente', previo);
  e.sessionStorage.setItem('comedor_sesion', JSON.stringify({ access: 'fixture-expirada', usuario: 'cocinera2' }));
  mensaje(e, { data: leer });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(e.mensajes.at(-1)[0].incierto, true);
  assert.match(e.mensajes.at(-1)[0].error, /sesión expiró/);
  assert.equal(e.sessionStorage.getItem('qa_relectura_pendiente'), previo);
});
