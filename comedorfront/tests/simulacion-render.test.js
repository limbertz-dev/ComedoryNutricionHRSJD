/*
 * Render real de los componentes con react-dom/server (JSX y CSS los resuelve
 * tests/soporte/cargador-jsx.js). Prueba que fuera de simulación no queda
 * nada de simulación en el HTML, y que en simulación se ve y usa la hora del
 * servidor.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import Header from '../src/components/layout/Header.jsx';
import SimuladorLector from '../src/components/secciones/SimuladorLector.jsx';
import ControlesReloj from '../src/components/secciones/ControlesReloj.jsx';

const seccion = { titulo: 'Control Biométrico', descripcion: 'Marcaciones en vivo' };
/* Un día que no es hoy: si algo usara la hora de la PC, se notaría. */
const reloj = {
  ahora: new Date(2020, 1, 3, 12, 5, 30),
  real: new Date(2026, 8, 25, 9, 0),
  simulado: true,
  congelado: false,
};
const simulador = (props) => h(SimuladorLector, {
  personal: [{ id: 3, nombre: 'Persona 3', categoria: 'Médico', legajo: 'ITEM-3' }],
  seleccionado: '',
  onSeleccionar() {},
  onMarcar() {},
  onSimularFalla() {},
  leyendo: false,
  error: '',
  ...props,
});
const fechaHeader = (fecha) => new Intl.DateTimeFormat('es-BO', {
  weekday: 'short', day: '2-digit', month: 'short', year: 'numeric',
}).format(fecha);
const escapar = (texto) => texto.replace(/&/g, '&amp;');

test('fuera de simulación el header no muestra la franja y usa la fecha de siempre', () => {
  for (const html of [
    renderToStaticMarkup(h(Header, { seccion, turno: 'Almuerzo' })),
    renderToStaticMarkup(h(Header, { seccion, turno: 'Almuerzo', simulacion: null })),
  ]) {
    assert.doesNotMatch(html, /simulaci/i);
    assert.doesNotMatch(html, /2020/);
    assert.match(html, /Turno Almuerzo/);
  }
});

test('en simulación el header muestra SIMULACIÓN y la fecha del servidor', () => {
  const html = renderToStaticMarkup(h(Header, { seccion, turno: 'Almuerzo', simulacion: reloj }));
  assert.match(html, /header__pastilla--simulacion/);
  assert.match(html, /<strong>Simulación<\/strong>/);
  assert.ok(html.includes(escapar(fechaHeader(reloj.ahora))), 'fecha del servidor en la pastilla');
  assert.match(html, /12:05/);
});

test('fuera de simulación el SimuladorLector no tiene controles de reloj', () => {
  for (const html of [
    renderToStaticMarkup(simulador({})),
    renderToStaticMarkup(simulador({ reloj: null })),
  ]) {
    assert.doesNotMatch(html, /reloj-sim/);
    assert.match(html, /Apoyar huella/);
  }
  assert.equal(renderToStaticMarkup(h(ControlesReloj, { reloj: null, abiertoInicial: true })), '');
});

test('en simulación el SimuladorLector suma el reloj con la hora del servidor', () => {
  const html = renderToStaticMarkup(simulador({ reloj, onCambioReloj() {} }));
  assert.match(html, /reloj-sim__disparador/);
  assert.match(html, /12:05/);
  assert.match(html, /aria-expanded="false"/);
  assert.doesNotMatch(html, /reloj-sim__panel/);
});

test('el panel del reloj ofrece fijar, +15 min, próxima franja y volver a real', () => {
  const html = renderToStaticMarkup(h(ControlesReloj, { reloj, onCambio() {}, abiertoInicial: true }));
  assert.match(html, /role="dialog"/);
  // La hora propuesta para fijar es la del servidor, no la de la PC.
  assert.match(html, /type="datetime-local"[^>]*value="2020-02-03T12:05"/);
  assert.match(html, /type="checkbox"/);
  for (const texto of ['Fijar', '\\+15 min', 'Próxima franja', 'Volver a la hora real']) {
    assert.match(html, new RegExp(`<span class="boton__texto">${texto}</span>`));
  }
  assert.match(html, /Simulado/);
});

test('con el reloj en hora real, «Volver a la hora real» queda deshabilitado', () => {
  const html = renderToStaticMarkup(h(ControlesReloj, {
    reloj: { ...reloj, simulado: false }, onCambio() {}, abiertoInicial: true,
  }));
  assert.match(html, /<button[^>]*disabled=""[^>]*><span class="boton__texto">Volver a la hora real/);
  assert.match(html, /Hora real/);
});
