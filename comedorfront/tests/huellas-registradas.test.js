import test, { afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import HuellasRegistradas from '../src/components/secciones/HuellasRegistradas.jsx';
import Supervision from '../src/components/secciones/Supervision.jsx';
import { obtenerRegistrosHuellas } from '../src/api.js';

const original = globalThis.fetch;
afterEach(() => { globalThis.fetch = original; });
const fila = {
  registrada_en: '2026-10-20T16:00:00+00:00',
  comensal: { usuario_id: 900101, nombre: 'QA 01 NORMAL', legajo: 'LEG-QA01', categoria: 'Medicos', servicio: 'MEDICINA INTERNA', disponible: true },
  cuenta: { id: 2, usuario: 'cocinera2', nombre: 'Cocinera simulada 2', disponible: true },
};
const pagina = { datos: [fila], total: 1, limite: 50, desplazamiento: 0, modo: 'simulado' };

test('lista el comensal, ID, legajo y cuenta registradora con fecha local explícita', () => {
  const html = renderToStaticMarkup(h(HuellasRegistradas, { inicial: { pagina } }));
  for (const texto of ['Huellas registradas', 'QA 01 NORMAL', '900101', 'LEG-QA01', 'cocinera2', 'Cocinera simulada 2', 'MEDICINA INTERNA', '12:00:00', 'Hora de Bolivia']) assert.ok(html.includes(texto), texto);
  assert.doesNotMatch(html, /Confirmar entrega|Simular captura|SIM-HUELLA/);
  assert.match(html, /aria-label="Huellas registradas"/);
});

test('carga, vacío, error y último resultado conservado son estados distintos', () => {
  assert.match(renderToStaticMarkup(h(HuellasRegistradas)), /Cargando huellas registradas/);
  assert.match(renderToStaticMarkup(h(HuellasRegistradas, { inicial: { pagina: { ...pagina, total: 0, datos: [] } } })), /Todavía no hay huellas registradas/);
  const error = renderToStaticMarkup(h(HuellasRegistradas, { inicial: { pagina, error: 'Sin conexión' } }));
  assert.match(error, /role="alert"/);
  assert.match(error, /Se conserva la última consulta/);
  assert.match(error, /QA 01 NORMAL/);
  const sinFicha = { ...fila, comensal: { ...fila.comensal, nombre: null, disponible: false } };
  assert.match(renderToStaticMarkup(h(HuellasRegistradas, { inicial: { pagina: { ...pagina, datos: [sinFicha] } } })), /Ficha no disponible/);
});

test('Supervisión monta el registro con permiso incluso sin marcaciones de comida', () => {
  const base = { cargandoInicial: false, comidasIniciales: { comidas: [] }, huellasIniciales: { pagina } };
  assert.match(renderToStaticMarkup(h(Supervision, { ...base, puedeConsultarHuellas: true })), /QA 01 NORMAL/);
  assert.doesNotMatch(renderToStaticMarkup(h(Supervision, base)), /Huellas registradas/);
});

test('cliente envía búsqueda y página; rechaza fechas e identidades inválidas', async () => {
  let llamadas = 0;
  globalThis.fetch = async url => {
    llamadas += 1;
    const consulta = new URL(url).searchParams;
    assert.equal(consulta.get('busqueda'), 'LEG-QA01');
    assert.equal(consulta.get('desplazamiento'), '50');
    return { ok: true, json: async () => ({ ...pagina, total: 51, desplazamiento: 50 }) };
  };
  assert.equal((await obtenerRegistrosHuellas({ busqueda: ' LEG-QA01 ', desplazamiento: 50 })).total, 51);
  await assert.rejects(obtenerRegistrosHuellas({ limite: 101 }), /Revisa/);
  assert.equal(llamadas, 1);
  for (const invalida of [{ ...fila, registrada_en: 'ayer' }, { ...fila, cuenta: null }, { ...fila, comensal: { ...fila.comensal, usuario_id: '900101' } }]) {
    globalThis.fetch = async () => ({ ok: true, json: async () => ({ ...pagina, datos: [invalida] }) });
    await assert.rejects(obtenerRegistrosHuellas(), /registro de huellas/);
  }
});
