import test, { afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import RegistrarHuella from '../src/components/secciones/RegistrarHuella.jsx';
import PantallaEnVivo from '../src/components/secciones/PantallaEnVivo.jsx';
import { capturarHuellaQa, leerHuellaQa, obtenerPersonasEnrolamiento } from '../src/api.js';

const fetchOriginal = globalThis.fetch;
afterEach(() => { globalThis.fetch = fetchOriginal; });
const persona = { id: 900101, nombre: 'QA 01 NORMAL', legajo: 'LEG-QA01', categoria: 'Medicos', servicio: 'MEDICINA INTERNA', huella_registrada: false };
const clave = '12345678-1234-4234-8234-123456789abc';

test('Nuevo solo aparece en cocina con enrolamiento QA habilitado y usa el area central', () => {
  const base = { pantalla: null, turno: 'Almuerzo', puedeIdentificar: true };
  assert.doesNotMatch(renderToStaticMarkup(h(PantallaEnVivo, base)), /Nuevo registro de huella/);
  assert.doesNotMatch(renderToStaticMarkup(h(PantallaEnVivo, { ...base, puedeEnrolar: true, puedeIdentificar: false })), /Nuevo registro de huella/);
  const html = renderToStaticMarkup(h(PantallaEnVivo, { ...base, puedeEnrolar: true, registroHuellaInicial: true }));
  assert.match(html, /aria-label="Nuevo registro de huella"/);
  assert.match(html, /Registrar huella/);
  assert.match(html, /Marcaciones del turno/);
  assert.doesNotMatch(html, /Esperando marcación|role="dialog"/);
});

test('el alta inicia sin persona preseleccionada y no permite capturar hasta elegir', () => {
  const html = renderToStaticMarkup(h(RegistrarHuella, { personasIniciales: [persona] }));
  assert.match(html, /<option value="" selected="">Selecciona a la persona/);
  assert.match(html, /<button[^>]*disabled=""[^>]*>[\s\S]*?Simular captura/);
  assert.match(html, /Captura simulada/);
  const elegido = renderToStaticMarkup(h(RegistrarHuella, { personasIniciales: [persona], elegidoInicial: persona.id }));
  assert.match(elegido, /<strong>QA 01 NORMAL/);
  assert.doesNotMatch(elegido, /disabled=""/);
});

test('el resultado confirma el vinculo sin afirmar una comida ni captura fisica', () => {
  const html = renderToStaticMarkup(h(RegistrarHuella, {
    personasIniciales: [persona], elegidoInicial: persona.id,
    resultadoInicial: { ya_registrada: false },
  }));
  assert.match(html, /Huella registrada|huella de prueba quedó vinculada/);
  assert.match(html, /El alta no registra ninguna comida/);
  assert.match(html, /Leer huella de prueba/);
  assert.match(html, /Volver a marcaciones/);
});

test('el alta desde un caso vuelve al simulador sin ofrecer una entrega anticipada', () => {
  const html = renderToStaticMarkup(h(RegistrarHuella, {
    personasIniciales: [persona], elegidoInicial: persona.id, usuarioRequerido: persona.id,
    volverAlSimulador: true, resultadoInicial: { ya_registrada: false },
  }));
  assert.match(html, /Continuar con el caso/);
  assert.match(html, /Volver al simulador/);
  assert.doesNotMatch(html, /Leer huella de prueba|Volver a leer/);
});

test('el alta muestra categorias y servicios del padron con identidad explicita', () => {
  const html = renderToStaticMarkup(h(RegistrarHuella, { personasIniciales: [persona], elegidoInicial: persona.id }));
  assert.match(html, /Filtrar por categoría/);
  assert.match(html, /Filtrar por servicio/);
  assert.match(html, /Medicos/);
  assert.match(html, /MEDICINA INTERNA/);
  assert.match(html, /Todas las permitidas/);
});

test('la lectura usa solo la referencia enrolada, conserva la clave y acepta el rechazo de duplicado', async () => {
  const referencia = `SIM-HUELLA-${clave}`;
  globalThis.fetch = async (url, opciones) => {
    assert.match(url, /\/_qa\/enrolamiento\/lecturas$/);
    assert.deepEqual(JSON.parse(opciones.body), { referencia });
    assert.equal(opciones.headers['Idempotency-Key'], clave);
    return { ok: true, json: async () => ({ modo: 'simulado', usuario_id: persona.id,
      lectura_id: 7, asistencia_id: null, valido: false, motivo: 'duplicado' }) };
  };
  assert.equal((await leerHuellaQa(referencia, clave)).motivo, 'duplicado');
  await assert.rejects(leerHuellaQa('inexistente', clave), /Primero registra/);
});

test('el cliente exige persona y clave antes de enviar y valida la identidad devuelta', async () => {
  let llamadas = 0;
  globalThis.fetch = async () => { llamadas += 1; throw new Error('No debe enviarse'); };
  await assert.rejects(capturarHuellaQa(0, clave), /Selecciona/);
  await assert.rejects(capturarHuellaQa(persona.id, 'invalida'), /Selecciona/);
  assert.equal(llamadas, 0);
  globalThis.fetch = async (url, opciones) => {
    assert.match(url, /\/_qa\/enrolamiento\/capturas$/);
    assert.deepEqual(JSON.parse(opciones.body), { usuario_id: persona.id });
    assert.equal(opciones.headers['Idempotency-Key'], clave);
    return { ok: true, json: async () => ({ usuario_id: 999, modo: 'simulado', referencia: `SIM-HUELLA-${clave}`, ya_registrada: false }) };
  };
  await assert.rejects(capturarHuellaQa(persona.id, clave), /confirmar el vínculo/);
});

test('el padron de enrolamiento conserva personas registradas y no tolera respuestas ficticias', async () => {
  globalThis.fetch = async () => ({ ok: true, json: async () => [{ ...persona, huella_registrada: true }] });
  assert.equal((await obtenerPersonasEnrolamiento())[0].huella_registrada, true);
  globalThis.fetch = async () => ({ ok: true, json: async () => [{ nombre: 'sin identidad' }] });
  await assert.rejects(obtenerPersonasEnrolamiento(), /padrón/);
});
