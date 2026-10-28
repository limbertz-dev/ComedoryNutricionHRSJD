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

test('las tarjetas de comida y el resumen suman los policías al total de raciones', () => {
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
  assert.match(html, /Policías<\/dt><dd>2<\/dd><small>Total con policías: 2 raciones/);
});

// --- registro de policías (QA) --------------------------------------------------

import { registrarPoliciaQa, leerPoliciaQa } from '../src/api.js';
import RegistrarHuella from '../src/components/secciones/RegistrarHuella.jsx';
import HuellasRegistradas from '../src/components/secciones/HuellasRegistradas.jsx';

const CLAVE = '11111111-1111-4111-8111-111111111111';

test('el registro ofrece Personal o Policía, salvo en un caso fijo del simulador', () => {
  const html = renderToStaticMarkup(h(RegistrarHuella, { personasIniciales: [] }));
  assert.match(html, /role="radiogroup" aria-label="¿A quién se registra\?"/);
  assert.match(html, /Personal del padrón/);
  assert.match(html, />Policía</);
  const caso = renderToStaticMarkup(h(RegistrarHuella, { personasIniciales: [], usuarioRequerido: 900101 }));
  assert.doesNotMatch(caso, /radiogroup/);
});

test('el alta de un policía exige nombre completo y valida el CI o la placa', async () => {
  await assert.rejects(registrarPoliciaQa({ nombre: '  ' }, CLAVE), /nombre completo/);
  await assert.rejects(registrarPoliciaQa({ nombre: 'Juan Perez', documento: '<x>' }, CLAVE), /CI o la placa/);
  let cuerpo;
  globalThis.fetch = async (_url, opciones) => {
    cuerpo = JSON.parse(opciones.body);
    return json({ modo: 'simulado', vinculo_id: 9, identificador: 'qa-pol-1', nombre: 'Juan Perez', documento: null, ya_registrada: false });
  };
  const dato = await registrarPoliciaQa({ nombre: '  Juan   Perez ', documento: '' }, CLAVE);
  assert.deepEqual(cuerpo, { nombre: 'Juan Perez', documento: null });
  assert.equal(dato.vinculo_id, 9);
});

test('la lectura de prueba del policía va a su propio endpoint', async () => {
  let ruta;
  globalThis.fetch = async (url) => { ruta = new URL(url).pathname; return json({ modo: 'simulado', valido: true, nombre: 'Juan Perez' }); };
  assert.equal((await leerPoliciaQa(9, CLAVE)).valido, true);
  assert.equal(ruta, '/_qa/enrolamiento/policias/9/lecturas');
  await assert.rejects(leerPoliciaQa(0, CLAVE), /Primero registra/);
});

test('Huellas registradas muestra al policía con su CI o placa y la etiqueta Policía', () => {
  const pagina = { total: 1, limite: 50, desplazamiento: 0, modo: 'simulado', datos: [{
    tipo: 'policia', registrada_en: '2026-10-22T21:00:00-04:00', activo: true,
    comensal: { usuario_id: null, nombre: 'Juan Perez', legajo: 'PL-1234', categoria: 'Policías', servicio: null, disponible: true },
    cuenta: { id: 3, usuario: 'cocinera1', nombre: 'Cocinera Uno', disponible: true },
  }] };
  const html = renderToStaticMarkup(h(HuellasRegistradas, { inicial: { pagina } }));
  assert.match(html, /Juan Perez/);
  assert.match(html, /CI o placa PL-1234/);
  assert.match(html, /Fuera del padrón · vía libre/);
  assert.match(html, />Policía</);
});

test('Control Biométrico muestra el nombre del policía', () => {
  const evento = eventoDeFila({ ...policia, persona: { id: null, nombre: 'Juan Perez', categoria: 'Policías' } });
  assert.equal(evento.persona.nombre, 'Juan Perez');
  assert.equal(evento.titulo, 'Policía registrado');
});

// --- cocina identifica a un policía (huella no reconocida) ------------------------

import IdentificarLectura from '../src/components/secciones/IdentificarLectura.jsx';
import { identificarComoPolicia, obtenerPoliciasActivos } from '../src/api.js';

const lecturaPendiente = {
  id: 55, clave: 'lectura_biometrica:55', hora: '12:10:00', comida: 'Almuerzo', dispositivo: 'cocina-01',
  identificableHasta: '2026-10-19T15:00:00',
};

test('al identificar, los policías aparecen en su propio grupo de la lista', () => {
  const html = renderToStaticMarkup(h(IdentificarLectura, {
    pendientes: { servicio: { comida: 'Almuerzo', fin: '2026-10-19T15:00:00' }, total: 1, lecturas: [lecturaPendiente] },
    abierta: 55,
    personal: [{ id: 1, nombre: 'Ana Gomez', categoria: 'Médico', legajo: 'L-1' }],
    policiasIniciales: [{ id: 9, nombre: 'Juan Perez', documento: 'PL-1234' }],
  }));
  assert.match(html, /2\. Buscar y elegir comensal del padrón o policía/);
  assert.match(html, /<optgroup label="Policías"><option value="policia:9">Juan Perez — Policía \(CI o placa PL-1234\)<\/option><\/optgroup>/);
  assert.match(html, /Ana Gomez — Médico/);
});

test('la identificación como policía distingue entrega, conflicto e incierto', async () => {
  globalThis.fetch = async (url, opciones) => {
    assert.equal(new URL(url).pathname, '/asistencias/lecturas/55/identificar-policia');
    assert.deepEqual(JSON.parse(opciones.body), { vinculo_id: 9 });
    return json({ valido: true, lectura_id: 55, racion_id: 3, vinculo_id: 9, nombre: 'Juan Perez',
      comida: 'Almuerzo', fecha_comida: '2026-10-19', reintento: false });
  };
  const ok = await identificarComoPolicia(55, 9, { clave: CLAVE });
  assert.deepEqual(ok, { estado: 'registrada', nombre: 'Juan Perez', comida: 'Almuerzo', reintento: false });

  globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Esa huella ya se identificó y tiene su ración.', motivo: 'lectura_ya_resuelta' }), { status: 409 });
  const conflicto = await identificarComoPolicia(55, 9, { clave: CLAVE });
  assert.equal(conflicto.estado, 'conflicto');
  assert.equal(conflicto.motivo, 'lectura_ya_resuelta');

  globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
  assert.equal((await identificarComoPolicia(55, 9, { clave: CLAVE })).estado, 'incierto');
});

test('la lista de policías de cocina se valida', async () => {
  globalThis.fetch = async () => json([{ id: 9, nombre: 'Juan Perez', documento: null }]);
  assert.deepEqual(await obtenerPoliciasActivos(), [{ id: 9, nombre: 'Juan Perez', documento: null }]);
  globalThis.fetch = async () => json([{ id: 'x', nombre: 'Juan' }]);
  await assert.rejects(obtenerPoliciasActivos(), /policías inválida/);
});

test('la huella identificada como policía se ve como entrega y va al apartado Policías', async () => {
  const fila = {
    ...filaApi, id: 55, origen: 'lectura_biometrica', clave_evento: 'lectura_biometrica:55',
    nombre: 'Huella no reconocida', categoria: 'Sin identificar', resultado: 'rechazada', motivo: 'no_identificado',
    valido: false,
    resultado_final: { via: 'identificacion_policia', asistencia_id: null,
      comensal: { usuario_id: null, nombre: 'Juan Perez' }, comida: 'Almuerzo', fecha_comida: '2026-10-19',
      momento: '2026-10-19T12:12:00' },
  };
  globalThis.fetch = async () => json([fila]);
  const [adaptada] = await obtenerUltimasMarcaciones({ limite: 20 });
  const evento = eventoDeFila(adaptada);
  assert.equal(evento.valido, true);
  assert.equal(evento.titulo, 'Policía registrado por cocina');
  assert.equal(evento.persona.nombre, 'Juan Perez');
  assert.equal(esPolicia(adaptada), true);
});
