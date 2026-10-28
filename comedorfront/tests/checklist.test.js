/*
 * Checklist de cocina: lógica pura (filtros, conteos, plazo para deshacer),
 * contrato con la API y estados de la pantalla.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import {
  desmarcarEnChecklist, desmarcarPoliciaEnChecklist, marcarEnChecklist, obtenerChecklist,
  registrarPoliciaEnChecklist,
} from '../src/api.js';
import {
  avisoDeMarca,
  contarChecklist,
  filtrarChecklist,
  serviciosDeChecklist,
} from '../src/checklist.js';
import ChecklistCocina from '../src/components/secciones/ChecklistCocina.jsx';
import RegistrarPolicia from '../src/components/secciones/RegistrarPolicia.jsx';

const PERSONAS = [
  { id: 1, nombre: 'Zoila Pérez', servicio: 'LABORATORIO', servida: false },
  { id: 2, nombre: 'Ángel Ruiz', servicio: 'IMAGENOLOGIA', servida: true, metodo: 'checklist' },
  { id: 3, nombre: 'Ana Mamani', servicio: 'LABORATORIO', servida: false },
];

async function conFetch(respuestas, cuerpo) {
  const llamadas = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (url, opciones = {}) => {
    llamadas.push({ url: String(url), metodo: opciones.method ?? 'GET', cuerpo: opciones.body });
    const r = respuestas.shift();
    return {
      ok: r.status < 400, status: r.status, headers: { get: () => null },
      json: async () => r.json,
    };
  };
  try {
    await cuerpo(llamadas);
  } finally {
    globalThis.fetch = original;
  }
}

test('conteo, servicios y filtros del checklist', () => {
  assert.deepEqual(contarChecklist(PERSONAS), { total: 3, entregadas: 1, pendientes: 2 });
  assert.deepEqual(serviciosDeChecklist(PERSONAS), ['IMAGENOLOGIA', 'LABORATORIO']);
  assert.deepEqual(filtrarChecklist(PERSONAS).map((p) => p.id), [1, 3]);
  assert.deepEqual(filtrarChecklist(PERSONAS, { estado: 'entregadas' }).map((p) => p.id), [2]);
  // «Todas» pone primero las pendientes.
  assert.deepEqual(filtrarChecklist(PERSONAS, { estado: 'todas' }).map((p) => p.id), [1, 3, 2]);
  // Búsqueda sin tildes ni mayúsculas.
  assert.deepEqual(filtrarChecklist(PERSONAS, { estado: 'todas', busqueda: 'angel' }).map((p) => p.id), [2]);
  assert.deepEqual(filtrarChecklist(PERSONAS, { estado: 'todas', servicio: 'LABORATORIO' }).map((p) => p.id), [1, 3]);
});

test('avisos de marca según la respuesta del servidor', () => {
  assert.equal(avisoDeMarca({ valido: true }, 'Ana').tipo, 'exito');
  assert.match(avisoDeMarca({ valido: false, motivo: 'duplicado' }, 'Ana').texto, /ya recibió/);
  assert.match(avisoDeMarca({ valido: false, motivo: 'sin_derecho' }, 'Ana').texto, /no tiene derecho/);
});

test('contrato: GET /pantalla/checklist, POST y DELETE /asistencias/checklist', async () => {
  await conFetch([
    { status: 200, json: {
      momento: '2026-10-19T12:30:00', fuera_de_horario: false, comida_id: 2, comida: 'Almuerzo',
      fecha_comida: '2026-10-19',
      personas: [{ usuario_id: 7, nombre: 'Ana', categoria: 'Medicos', servicio: 'LAB', turno: 'T1',
        servida: true, metodo: 'checklist', asistencia_id: 70, fecha_hora: '2026-10-19T12:29:00',
        anulable: true }],
    } },
    { status: 200, json: { valido: true, titulo: 'Ración entregada', detalle: '' } },
    { status: 403, json: { detail: 'Solo puede desmarcar quien marcó la ración.', motivo: 'otra_cuenta' } },
  ], async (llamadas) => {
    const lista = await obtenerChecklist();
    assert.equal(lista.comida, 'Almuerzo');
    assert.equal(lista.personas[0].id, 7);
    assert.equal(lista.personas[0].asistenciaId, 70);
    assert.equal(lista.personas[0].anulable, true);

    const marca = await marcarEnChecklist(7);
    assert.equal(marca.valido, true);
    assert.equal(llamadas[1].metodo, 'POST');
    assert.match(llamadas[1].url, /\/asistencias\/checklist$/);
    assert.deepEqual(JSON.parse(llamadas[1].cuerpo), { usuario_id: 7 });

    await assert.rejects(desmarcarEnChecklist(70), (e) => e.status === 403 && e.datos.motivo === 'otra_cuenta');
    assert.equal(llamadas[2].metodo, 'DELETE');
    assert.match(llamadas[2].url, /\/asistencias\/checklist\/70$/);
  });
});

test('la pantalla muestra la comida, los conteos y la marca de cada persona', () => {
  const html = renderToStaticMarkup(h(ChecklistCocina, { datosIniciales: {
    momento: '2026-10-19T12:30:00', fueraDeHorario: false, comidaId: 2, comida: 'Almuerzo',
    fechaComida: '2026-10-19',
    personas: [
      { id: 1, nombre: 'Zoila Pérez', categoria: 'Medicos', servicio: 'LAB', turno: 'T1', servida: false },
      { id: 2, nombre: 'Ana Mamani', categoria: 'Medicos', servicio: 'IMG', turno: 'T1', servida: true,
        metodo: 'biometrico', fechaHora: '2026-10-19T12:10:00' },
    ],
  } }));
  assert.match(html, /Almuerzo/);
  assert.match(html, /Comida en curso/);
  assert.match(html, /Entregar ración a Zoila Pérez/);
  assert.match(html, /role="checkbox"/);
  // Por defecto se ven las pendientes.
  assert.doesNotMatch(html, /Ana Mamani/);
  // Filtro de servicio con el desplegable propio, no el nativo.
  assert.match(html, /app-select/);
  assert.doesNotMatch(html, /<select/);
});

test('fuera de horario solo se muestra el aviso', () => {
  const html = renderToStaticMarkup(h(ChecklistCocina, { datosIniciales: {
    momento: '2026-10-19T03:00:00', fueraDeHorario: true, personas: [],
  } }));
  assert.match(html, /Fuera de horario/);
  assert.doesNotMatch(html, /role="checkbox"/);
});

test('Deshacer aparece sin temporizador y solo en las marcas propias', () => {
  const html = renderToStaticMarkup(h(ChecklistCocina, { datosIniciales: {
    momento: '2026-10-19T12:30:00', fueraDeHorario: false, comidaId: 2, comida: 'Almuerzo',
    fechaComida: '2026-10-19',
    personas: [
      { id: 1, nombre: 'Propia', servida: true, metodo: 'checklist', fechaHora: '2026-10-19T12:01:00', anulable: true, asistenciaId: 10 },
      { id: 2, nombre: 'Ajena', servida: true, metodo: 'checklist', fechaHora: '2026-10-19T12:02:00', anulable: false, asistenciaId: 11 },
    ],
  }, filtroInicial: 'entregadas' }));
  assert.equal(html.match(/>Deshacer</g)?.length, 1);
  assert.doesNotMatch(html, /Deshacer ·|\d:\d\d<\/span><\/button>/);
});

test('contrato: policías del checklist (lista, registro sin identidad y deshacer)', async () => {
  await conFetch([
    { status: 200, json: {
      momento: '2026-10-19T12:30:00', fuera_de_horario: false, comida_id: 2, comida: 'Almuerzo',
      fecha_comida: '2026-10-19', personas: [],
      policias: [{ racion_id: 5, nombre: 'Policía', fecha_hora: '2026-10-19T12:10:00', origen: 'checklist', anulable: true }],
    } },
    { status: 200, json: { valido: true, nombre: 'Policía', detalle: 'ok', racion_id: 6 } },
    { status: 200, json: { racion_id: 6, nombre: null, anulada_en: '2026-10-19T12:31:00' } },
  ], async (llamadas) => {
    const lista = await obtenerChecklist();
    assert.deepEqual(lista.policias[0], {
      id: 5, nombre: 'Policía', fechaHora: '2026-10-19T12:10:00', origen: 'checklist', anulable: true,
    });
    const r = await registrarPoliciaEnChecklist();
    assert.equal(r.valido, true);
    assert.equal(llamadas[1].metodo, 'POST');
    assert.match(llamadas[1].url, /\/asistencias\/checklist\/policias$/);
    assert.equal(llamadas[1].cuerpo, undefined, 'sin nombre: no hay cuerpo');
    await desmarcarPoliciaEnChecklist(6);
    assert.equal(llamadas[2].metodo, 'DELETE');
    assert.match(llamadas[2].url, /\/asistencias\/checklist\/policias\/6$/);
  });
});

test('Registrar policía: botón con confirmación, sin campo de nombre, y lista de la comida', () => {
  const datos = {
    momento: '2026-10-19T12:30:00', fueraDeHorario: false, comidaId: 2, comida: 'Almuerzo',
    fechaComida: '2026-10-19',
    personas: [{ id: 1, nombre: 'Zoila', servida: false }],
    policias: [
      { id: 5, nombre: 'Policía', fechaHora: '2026-10-19T12:10:00', origen: 'checklist', anulable: true },
      { id: 6, nombre: 'Policía', fechaHora: '2026-10-19T12:12:00', origen: 'huella', anulable: false },
    ],
  };
  const html = renderToStaticMarkup(h(ChecklistCocina, { datosIniciales: datos }));
  assert.match(html, />Registrar policía</);
  assert.doesNotMatch(html, /Nuevo policía|Nombre completo/);
  assert.equal(html.match(/<input/g).length, 1, 'solo el buscador');
  assert.match(html, /Policías registrados/);
  assert.match(html, /Checklist · 12:10/);
  assert.match(html, /Huella · 12:12/);
  // Solo la ración propia del checklist ofrece Deshacer.
  assert.equal(html.match(/>Deshacer</g)?.length, 1);
  // La lista de policías va antes que el personal.
  assert.ok(html.indexOf('Policías registrados') < html.indexOf('Zoila'));
});

test('Registrar policía: la confirmación pregunta antes de registrar', () => {
  const html = renderToStaticMarkup(h(RegistrarPolicia, { abiertoInicial: true }));
  assert.match(html, /role="dialog"/);
  assert.match(html, /¿Desea registrar un policía\?/);
  assert.match(html, />Cancelar</);
  assert.match(html, />Sí, registrar policía</);
});
