import test, { afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { obtenerUltimasMarcaciones } from '../src/api.js';
import { eventoDeFila, etiquetaDeOrigen } from '../src/components/secciones/PantallaEnVivo.jsx';
import Supervision, { esPolicia, RacionesPolicia } from '../src/components/secciones/Supervision.jsx';

const fetchOriginal = globalThis.fetch;
afterEach(() => { globalThis.fetch = fetchOriginal; });
const json = (datos) => new Response(JSON.stringify(datos), { status: 200 });

/** Fila de policía tal como la manda GET /pantalla/ultimas-marcaciones. */
const filaApi = {
  id: 7, origen: 'racion_policia', clave_evento: 'racion_policia:7',
  usuario_id: null, nombre: 'Policía', categoria: 'Policías', comida_id: 4, comida: 'Cena',
  resultado: 'aceptada', motivo: null, valido: true, dispositivo: 'cocina-01',
  fecha_hora: '2026-10-19T19:30:00', estado_final: 'racion_servida', decision_original: null,
  resultado_final: {
    via: 'policia', asistencia_id: null, comensal: { usuario_id: null, nombre: 'Policía' },
    comida: 'Cena', fecha_comida: '2026-10-19', momento: '2026-10-19T19:30:00',
  },
  puede_identificar: false, motivo_no_identificable: 'no_aplica', intervencion: null,
};

test('la API acepta la ración de policía como una marcación válida', async () => {
  globalThis.fetch = async () => json([filaApi]);
  const [fila] = await obtenerUltimasMarcaciones({ limite: 20 });
  assert.equal(fila.origen, 'racion_policia');
  assert.equal(fila.clave, 'racion_policia:7');
  assert.equal(fila.valido, true);
  assert.equal(fila.resultadoFinal.via, 'policia');
  assert.equal(fila.resultadoFinal.asistenciaId, null);
});

test('una ración de personal sin asistencia sigue siendo inválida', async () => {
  globalThis.fetch = async () => json([{
    ...filaApi, origen: 'lectura_biometrica', clave_evento: 'lectura_biometrica:7',
    resultado_final: { ...filaApi.resultado_final, via: 'lector' },
  }]);
  await assert.rejects(obtenerUltimasMarcaciones({ limite: 20 }), /resultado final inválido/);
});

test('en Control Biométrico el policía aparece registrado, con check', async () => {
  globalThis.fetch = async () => json([filaApi]);
  const [fila] = await obtenerUltimasMarcaciones({ limite: 20 });
  const evento = eventoDeFila(fila);
  assert.equal(evento.valido, true);
  assert.equal(evento.sinIdentificar, false);
  assert.equal(evento.titulo, 'Policía registrado');
  assert.deepEqual(evento.persona, { id: null, nombre: 'Policía', categoria: 'Policías', legajo: '—' });
  assert.equal(etiquetaDeOrigen('racion_policia'), 'Policía');
});

const personal = {
  id: 701, origen: 'lectura_biometrica', clave: 'lectura_biometrica:701', usuarioId: 1, valido: true,
  titulo: 'Marcación válida', motivo: null, dispositivo: 'cocina-01', hora: '19:10:00', comidaId: 4,
  comida: 'Cena', persona: { id: 1, nombre: 'Comensal Exito', categoria: 'Médico' },
};
const policia = {
  id: 7, origen: 'racion_policia', clave: 'racion_policia:7', usuarioId: null, valido: true,
  titulo: 'Marcación válida', motivo: null, dispositivo: 'cocina-01', hora: '19:30:00', comidaId: 4,
  comida: 'Cena', persona: { id: null, nombre: 'Policía', categoria: 'Policías' },
};

test('en Supervisión los policías van en su apartado, no en la tabla del personal', () => {
  const html = renderToStaticMarkup(h(Supervision, {
    cargandoInicial: false,
    comidasIniciales: { fecha: '2026-10-19', comidas: [], rechazosSinComida: 0 },
    marcacionesIniciales: [personal, policia],
  }));
  const corte = html.indexOf('aria-label="Raciones de policía"');
  const tablaPersonal = html.slice(0, corte);
  const apartado = html.slice(corte);
  assert.match(tablaPersonal, /Comensal Exito/);
  assert.doesNotMatch(tablaPersonal, /Policía<\/td>/);
  assert.match(tablaPersonal, /1 de 1 marcación/);
  assert.match(apartado, /Policías/);
  assert.match(apartado, /1 ración · vía libre/);
  assert.match(apartado, /19:30:00/);
  assert.match(apartado, /Ración registrada/);
});

test('el apartado de policías vacío lo dice', () => {
  const html = renderToStaticMarkup(h(RacionesPolicia, { filas: [] }));
  assert.match(html, /No hay raciones de policía registradas/);
  assert.equal(esPolicia(policia), true);
  assert.equal(esPolicia(personal), false);
});

test('las tarjetas de comida y el resumen suman los policías aparte del cupo', () => {
  const dia = {
    fecha: '2026-10-19', rechazosSinComida: 0,
    comidas: [{
      comidaId: 4, comida: 'Cena', horaInicio: '17:00', horaFin: '23:59', estado: 'en_curso',
      previstas: 3, servidas: 0, manuales: 0, policias: 2,
      rechazos: { noIdentificado: 0, sinDerecho: 0, duplicado: 0 },
    }],
  };
  const html = renderToStaticMarkup(h(Supervision, {
    cargandoInicial: false, comidasIniciales: dia, marcacionesIniciales: [policia],
  }));
  assert.match(html, /Policías: <\/span>2/);
  assert.match(html, /Aceptadas<\/dt><dd>0<\/dd><small>de 3 previstas/);
  assert.match(html, /Policías<\/dt><dd>2<\/dd><small>Aparte del cupo del personal/);
});
