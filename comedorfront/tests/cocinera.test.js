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
import { guardarSeccionActiva } from '../src/navegacion.js';
import PanelSesionCocinera, {
  CajaSesionCocinera,
  admitePantallaCompleta,
  alternarPantallaCompleta,
} from '../src/components/layout/PanelSesionCocinera.jsx';

const conSesion = (elemento) => h(ProveedorSesion, null, elemento);

test('la cocinera abre en el checklist de comida, a pantalla completa', () => {
  const html = renderToStaticMarkup(conSesion(h(Panel, { rol: 'cocinera' })));

  assert.doesNotMatch(html, /class="sidebar"/);
  assert.doesNotMatch(html, /<header class="header"/);
  assert.match(html, /app--pantalla-completa/);
  assert.match(html, /aria-label="Checklist de comida"/);
  assert.match(html, /Cargando la lista de la comida…/);
  // Control Biométrico ya no es la principal.
  assert.doesNotMatch(html, /Huellas por identificar|Marcaciones del turno/);
  // Sin el aviso de padrón cargado de las secciones de jefatura.
  assert.doesNotMatch(html, /comensales? cargados?/);
  assert.match(html, /aria-label="Menú de sesión"/);
});

test('la cocinera conserva Biométrico o Checklist al volver a cargar el panel', () => {
  const localOriginal = globalThis.localStorage;
  const guardado = new Map();
  globalThis.localStorage = {
    getItem: (clave) => guardado.get(clave) ?? null,
    setItem: (clave, valor) => guardado.set(clave, valor),
  };
  try {
    for (const id of ['vivo', 'checklist']) {
      guardarSeccionActiva(id);
      // Cada montaje reconstruye el estado, como una recarga de la página.
      for (let carga = 0; carga < 2; carga += 1) {
        const html = renderToStaticMarkup(conSesion(h(Panel, { rol: 'cocinera' })));
        if (id === 'vivo') {
          assert.match(html, /Huellas por identificar/);
          assert.doesNotMatch(html, /aria-label="Checklist de comida"/);
        } else {
          assert.match(html, /aria-label="Checklist de comida"/);
          assert.doesNotMatch(html, /Huellas por identificar/);
        }
      }
    }
  } finally {
    if (localOriginal === undefined) delete globalThis.localStorage;
    else globalThis.localStorage = localOriginal;
  }
});

test('el panel flotante cambia entre checklist y Control Biométrico', () => {
  const props = {
    cajaRef: { current: null }, abierto: true, onAlternar() {}, usuario: 'maria.cocina',
    rol: 'cocinera', onCerrarSesion() {},
  };
  const enChecklist = renderToStaticMarkup(h(CajaSesionCocinera, {
    ...props, seccionActiva: 'checklist', onCambiarSeccion() {},
  }));
  assert.match(enChecklist, /Ir a Control Biométrico/);
  assert.doesNotMatch(enChecklist, /Ir al Checklist de comida/);

  const enVivo = renderToStaticMarkup(h(CajaSesionCocinera, {
    ...props, seccionActiva: 'vivo', onCambiarSeccion() {},
  }));
  assert.match(enVivo, /Ir al Checklist de comida/);

  // Sin callback no se ofrece el cambio.
  const sinCambio = renderToStaticMarkup(h(CajaSesionCocinera, props));
  assert.doesNotMatch(sinCambio, /Ir a Control Biométrico|Ir al Checklist/);
});

test('con rol cocinera en Control Biométrico, la pantalla del lector ocupa toda la ventana', () => {
  const html = renderToStaticMarkup(conSesion(h(Panel, { rol: 'cocinera', seccionInicial: 'vivo' })));

  // Sin sidebar ni header, con el modificador de pantalla completa
  assert.doesNotMatch(html, /class="sidebar"/);
  assert.doesNotMatch(html, /<header class="header"/);
  assert.match(html, /app--pantalla-completa/);

  // Mismo contenido: panel del lector, ficha del día, huellas por identificar y marcaciones del turno
  assert.match(html, /Control de raciones · Comedor planta baja/);
  // Sin rótulo ni punto animado que aparente un lector conectado.
  assert.doesNotMatch(html, /Lector biométrico|escenario__pulso/);
  assert.match(html, /vivo__dia/);
  assert.match(html, /Huellas por identificar/);
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
  assert.doesNotMatch(html, /Huellas por identificar/);
});

test('el panel flotante contiene usuario, rol y Cerrar sesión', () => {
  const html = renderToStaticMarkup(
    h(CajaSesionCocinera, {
      cajaRef: { current: null },
      abierto: true,
      onAlternar() {},
      usuario: 'maria.cocina',
      rol: 'cocinera',
      onCerrarSesion() {},
    })
  );

  assert.match(html, /maria\.cocina/);
  assert.match(html, /Cocinera/);
  assert.match(html, /<span class="boton__texto">Cerrar sesión<\/span>/);
});

test('el panel abre cerrado y se abre con abiertoInicial', () => {
  const htmlCerrado = renderToStaticMarkup(
    conSesion(h(PanelSesionCocinera))
  );
  assert.match(htmlCerrado, /aria-label="Menú de sesión"/);
  assert.match(htmlCerrado, /aria-expanded="false"/);
  assert.doesNotMatch(htmlCerrado, /Cerrar sesión/);

  const htmlAbierto = renderToStaticMarkup(
    conSesion(h(PanelSesionCocinera, { abiertoInicial: true }))
  );
  assert.match(htmlAbierto, /aria-expanded="true"/);
  assert.match(htmlAbierto, /Cerrar sesión/);
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
