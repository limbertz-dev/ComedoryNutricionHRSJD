/*
 * Render por rol: la cocinera ocupa toda la ventana sin sidebar ni header, con
 * el botón flotante de sesión; jefa y sistemas siguen con sidebar y header.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { Panel } from '../src/App.jsx';
import { ProveedorSesion } from '../src/hooks/useSesion.js';
import PanelSesionCocinera, {
  CajaSesionCocinera,
  admitePantallaCompleta,
  alternarPantallaCompleta,
} from '../src/components/layout/PanelSesionCocinera.jsx';
import SimuladorLector from '../src/components/secciones/SimuladorLector.jsx';

const personal = [{ id: 3, nombre: 'Persona 3', categoria: 'Médico', legajo: 'ITEM-3' }];
const simulador = (props) => h(SimuladorLector, {
  personal,
  seleccionado: '',
  onSeleccionar() {},
  onMarcar() {},
  onSimularFalla() {},
  leyendo: false,
  error: '',
  reloj: null,
  onCambioReloj() {},
  ...props,
});
const conSesion = (elemento) => h(ProveedorSesion, null, elemento);

test('con rol cocinera no hay sidebar ni header y Control Biométrico ocupa toda la ventana', () => {
  const html = renderToStaticMarkup(conSesion(h(Panel, { rol: 'cocinera' })));

  // Sin sidebar ni header, con el modificador de pantalla completa
  assert.doesNotMatch(html, /class="sidebar"/);
  assert.doesNotMatch(html, /<header class="header"/);
  assert.match(html, /app--pantalla-completa/);

  // Mismo contenido: panel del lector, ficha del día y marcaciones del turno
  assert.match(html, /Control de raciones · Comedor planta baja/);
  // Sin rótulo ni punto animado que aparente un lector conectado.
  assert.doesNotMatch(html, /Lector biométrico|escenario__pulso/);
  assert.match(html, /vivo__dia/);
  assert.match(html, /Marcaciones del turno/);

  // Botón flotante de sesión, pequeño y con nombre accesible
  assert.match(html, /aria-label="Menú de sesión"/);
  assert.match(html, /panel-sesion__flotante/);
});

test('con rol jefa siguen el sidebar y el header, sin pantalla completa ni flotante', () => {
  const html = renderToStaticMarkup(conSesion(h(Panel, { rol: 'jefa' })));

  assert.match(html, /class="sidebar"/);
  assert.match(html, /<header class="header"/);
  assert.match(html, /Supervisión del comedor/);
  assert.doesNotMatch(html, /app--pantalla-completa/);
  assert.doesNotMatch(html, /Menú de sesión/);
});

test('el panel flotante contiene usuario, rol, simulador y Cerrar sesión', () => {
  const html = renderToStaticMarkup(
    h(CajaSesionCocinera, {
      cajaRef: { current: null },
      abierto: true,
      onAlternar() {},
      usuario: 'maria.cocina',
      rol: 'cocinera',
      simulador: simulador(),
      onCerrarSesion() {},
    })
  );

  assert.match(html, /maria\.cocina/);
  assert.match(html, /Cocinera/);
  assert.match(html, /Modo pruebas/);
  assert.match(html, /Apoyar huella/);
  assert.match(html, /Falla biométrica/);
  assert.match(html, /<span class="boton__texto">Cerrar sesión<\/span>/);
});

test('el panel abre cerrado y se abre con abiertoInicial', () => {
  const htmlCerrado = renderToStaticMarkup(
    conSesion(h(PanelSesionCocinera, { simulador: simulador() }))
  );
  assert.match(htmlCerrado, /aria-label="Menú de sesión"/);
  assert.match(htmlCerrado, /aria-expanded="false"/);
  assert.doesNotMatch(htmlCerrado, /Cerrar sesión/);
  assert.doesNotMatch(htmlCerrado, /Apoyar huella/);

  const htmlAbierto = renderToStaticMarkup(
    conSesion(h(PanelSesionCocinera, { simulador: simulador(), abiertoInicial: true }))
  );
  assert.match(htmlAbierto, /aria-expanded="true"/);
  assert.match(htmlAbierto, /Cerrar sesión/);
  assert.match(htmlAbierto, /Modo pruebas/);
  assert.match(htmlAbierto, /Apoyar huella/);
});

test('Pantalla completa se oculta si el navegador no la soporta', async () => {
  assert.equal(typeof globalThis.document, 'undefined');
  assert.equal(admitePantallaCompleta(), false);

  const htmlSinSoporte = renderToStaticMarkup(
    h(CajaSesionCocinera, {
      cajaRef: { current: null },
      abierto: true,
      onAlternar() {},
      usuario: 'maria.cocina',
      rol: 'cocinera',
      simulador: simulador(),
      onCerrarSesion() {},
    })
  );
  assert.doesNotMatch(htmlSinSoporte, /Pantalla completa/);

  // Con Fullscreen API disponible, el botón aparece y alterna
  const llamadas = [];
  globalThis.document = {
    fullscreenElement: null,
    documentElement: { requestFullscreen: async () => { llamadas.push('request'); } },
    exitFullscreen: async () => { llamadas.push('exit'); },
  };
  try {
    assert.equal(admitePantallaCompleta(), true);
    const htmlConSoporte = renderToStaticMarkup(
      h(CajaSesionCocinera, {
        cajaRef: { current: null },
        abierto: true,
        onAlternar() {},
        usuario: 'maria.cocina',
        rol: 'cocinera',
        simulador: simulador(),
        onCerrarSesion() {},
      })
    );
    assert.match(htmlConSoporte, /<span class="boton__texto">Pantalla completa<\/span>/);

    await alternarPantallaCompleta();
    globalThis.document.fullscreenElement = globalThis.document.documentElement;
    await alternarPantallaCompleta();
    assert.deepEqual(llamadas, ['request', 'exit']);
  } finally {
    delete globalThis.document;
  }
});
