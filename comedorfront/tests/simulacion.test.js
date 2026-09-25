import test, { afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { API_BASE_URL, API_BASE_URL_POR_OMISION, resolverApiBaseUrl } from '../src/config.js';
import { avanzarReloj, fechaHoraDelServidor, fijarReloj, obtenerReloj, obtenerSalud,
  saltarAProximaFranja, valorFechaHoraLocal, volverARelojReal } from '../src/api.js';
import { claveDelDia, consultarSimulacion, estadoDelReloj } from '../src/simulacion.js';
import { puedeOperarReloj } from '../src/permisos.js';

const fetchOriginal = globalThis.fetch;
afterEach(() => { globalThis.fetch = fetchOriginal; });
const json = (datos, status = 200) => new Response(JSON.stringify(datos), { status });

/* EstadoReloj tal como lo serializa FastAPI: hora local sin zona. */
const estadoReloj = (cambios = {}) => ({
  ahora: '2026-08-10T12:05:30.123456', real: '2026-09-25T09:00:00.5', simulado: true,
  congelado: false, ...cambios,
});
const salud = (entorno, reloj = { ahora: '2026-08-10T12:05:30', real: '2026-09-25T09:00:00', simulado: true }) =>
  ({ estado: 'ok', base_de_datos: 'conectada', entorno, reloj, faltan: [] });

/** fetch falso que anota cada petición y responde con `responder`. */
function grabar(responder) {
  const peticiones = [];
  globalThis.fetch = async (url, opciones = {}) => {
    const destino = new URL(url);
    const peticion = {
      origen: destino.origin,
      ruta: destino.pathname,
      metodo: opciones.method ?? 'GET',
      cuerpo: opciones.body === undefined ? undefined : JSON.parse(opciones.body),
    };
    peticiones.push(peticion);
    return responder(peticion);
  };
  return peticiones;
}

// --- URL base configurable ---

test('API_BASE_URL: sin VITE_API_URL queda la de siempre; con ella, la configurada', () => {
  assert.equal(API_BASE_URL_POR_OMISION, 'http://127.0.0.1:8000');
  // En node no hay import.meta.env: rige el valor por omisión.
  assert.equal(API_BASE_URL, 'http://127.0.0.1:8000');
  assert.equal(resolverApiBaseUrl(undefined), 'http://127.0.0.1:8000');
  assert.equal(resolverApiBaseUrl({}), 'http://127.0.0.1:8000');
  assert.equal(resolverApiBaseUrl({ VITE_API_URL: '   ' }), 'http://127.0.0.1:8000');
  assert.equal(resolverApiBaseUrl({ VITE_API_URL: 'http://127.0.0.1:8001' }), 'http://127.0.0.1:8001');
  assert.equal(resolverApiBaseUrl({ VITE_API_URL: ' http://sim.local:9000/ ' }), 'http://sim.local:9000');
});

test('las peticiones salen hacia API_BASE_URL', async () => {
  const peticiones = grabar(() => json(salud('desarrollo')));
  await obtenerSalud();
  assert.equal(peticiones[0].origen, 'http://127.0.0.1:8000');
  assert.equal(peticiones[0].ruta, '/salud');
});

// --- /salud: ¿hay simulación? ---

test('/salud fuera de simulación: sin reloj, aunque la API lo informe', async () => {
  for (const entorno of ['produccion', 'desarrollo']) {
    grabar(() => json(salud(entorno)));
    assert.deepEqual(await obtenerSalud(), { entorno, simulacion: false, reloj: null });
  }
  // Una API anterior al modo simulación no informa el entorno.
  grabar(() => json({ estado: 'ok' }));
  assert.deepEqual(await obtenerSalud(), { entorno: null, simulacion: false, reloj: null });
});

test('/salud en simulación trae la hora del servidor como hora de pared', async () => {
  grabar(() => json(salud('simulacion')));
  const { simulacion, reloj } = await obtenerSalud();
  assert.equal(simulacion, true);
  assert.equal(reloj.simulado, true);
  assert.equal(reloj.congelado, null);
  assert.deepEqual(
    [reloj.ahora.getFullYear(), reloj.ahora.getMonth(), reloj.ahora.getDate(),
      reloj.ahora.getHours(), reloj.ahora.getMinutes(), reloj.ahora.getSeconds()],
    [2026, 7, 10, 12, 5, 30],
  );
});

test('/salud con 503 (base incompleta) igual informa el entorno; sin cuerpo, falla', async () => {
  grabar(() => json({ ...salud('simulacion'), estado: 'incompleta', faltan: ['x'] }, 503));
  assert.equal((await obtenerSalud()).simulacion, true);
  grabar(() => new Response('caído', { status: 503 }));
  await assert.rejects(obtenerSalud(), /estado de la API.*HTTP 503/);
  grabar(() => json(salud('simulacion', { ahora: 'ayer', simulado: true })));
  await assert.rejects(obtenerSalud(), /reloj inválido/);
});

test('fuera de simulación nunca se consulta /simulacion/*, ni siquiera con rol de jefatura', async () => {
  const peticiones = grabar(() => json(salud('produccion')));
  assert.deepEqual(await consultarSimulacion({ operaReloj: true }), { simulacion: false, reloj: null });
  assert.deepEqual(peticiones.map(({ ruta }) => ruta), ['/salud']);
});

test('en simulación, jefatura lee /simulacion/reloj; los demás, solo /salud', async () => {
  let peticiones = grabar(({ ruta }) => json(ruta === '/salud' ? salud('simulacion') : estadoReloj({ congelado: true })));
  const jefa = await consultarSimulacion({ operaReloj: true });
  assert.deepEqual(peticiones.map(({ ruta }) => ruta), ['/salud', '/simulacion/reloj']);
  assert.equal(jefa.reloj.congelado, true);

  peticiones = grabar(({ ruta }) => json(ruta === '/salud' ? salud('simulacion') : estadoReloj()));
  const cocinera = await consultarSimulacion({ operaReloj: false });
  assert.deepEqual(peticiones.map(({ ruta }) => ruta), ['/salud']);
  assert.equal(cocinera.simulacion, true);

  // Vueltas siguientes de jefatura: directo al reloj.
  peticiones = grabar(() => json(estadoReloj()));
  await consultarSimulacion({ operaReloj: true, yaEnSimulacion: true });
  assert.deepEqual(peticiones.map(({ ruta }) => ruta), ['/simulacion/reloj']);

  // Si el reloj falla, queda la hora de /salud.
  grabar(({ ruta }) => (ruta === '/salud' ? json(salud('simulacion')) : json({}, 500)));
  const respaldo = await consultarSimulacion({ operaReloj: true });
  assert.equal(respaldo.simulacion, true);
  assert.equal(respaldo.reloj.ahora.getHours(), 12);
});

// --- Las 5 rutas de /simulacion/reloj ---

test('GET /simulacion/reloj', async () => {
  const peticiones = grabar(() => json(estadoReloj()));
  const reloj = await obtenerReloj();
  assert.deepEqual(peticiones, [{ origen: 'http://127.0.0.1:8000', ruta: '/simulacion/reloj', metodo: 'GET', cuerpo: undefined }]);
  assert.equal(reloj.simulado, true);
  assert.equal(reloj.congelado, false);
  assert.equal(valorFechaHoraLocal(reloj.ahora), '2026-08-10T12:05');
  assert.equal(valorFechaHoraLocal(reloj.real), '2026-09-25T09:00');

  grabar(() => json(estadoReloj({ congelado: undefined })));
  await assert.rejects(obtenerReloj(), /consultar el reloj.*reloj inválido/);
  grabar(() => json({ detail: 'Not Found' }, 404));
  await assert.rejects(obtenerReloj(), /HTTP 404/);
});

test('PUT /simulacion/reloj {momento, congelar}', async () => {
  const peticiones = grabar(() => json(estadoReloj({ ahora: '2026-08-10T07:30:00', congelado: true })));
  const reloj = await fijarReloj({ momento: '2026-08-10T07:30', congelar: true });
  assert.deepEqual(peticiones.map(({ ruta, metodo, cuerpo }) => ({ ruta, metodo, cuerpo })), [
    { ruta: '/simulacion/reloj', metodo: 'PUT', cuerpo: { momento: '2026-08-10T07:30:00', congelar: true } },
  ]);
  assert.equal(reloj.congelado, true);
  assert.equal(valorFechaHoraLocal(reloj.ahora), '2026-08-10T07:30');

  await fijarReloj({ momento: '2026-08-10T07:30' });
  assert.deepEqual(peticiones[1].cuerpo, { momento: '2026-08-10T07:30:00', congelar: false });

  for (const momento of [undefined, '', '10/08/2026 07:30', '2026-08-10']) {
    await assert.rejects(fijarReloj({ momento }), /Indique la fecha y la hora/);
  }
  assert.equal(peticiones.length, 2);
  grabar(() => json({ detail: [] }, 422));
  await assert.rejects(fijarReloj({ momento: '2026-08-10T07:30' }), /fijar el reloj.*HTTP 422/);
});

test('POST /simulacion/reloj/avanzar {minutos|horas|dias}', async () => {
  const peticiones = grabar(() => json(estadoReloj({ ahora: '2026-08-10T12:20:30' })));
  const reloj = await avanzarReloj({ minutos: 15 });
  assert.deepEqual(peticiones[0], {
    origen: 'http://127.0.0.1:8000', ruta: '/simulacion/reloj/avanzar', metodo: 'POST', cuerpo: { minutos: 15 },
  });
  assert.equal(reloj.ahora.getMinutes(), 20);

  await avanzarReloj({ dias: 1, horas: 2 });
  assert.deepEqual(peticiones[1].cuerpo, { dias: 1, horas: 2 });

  await assert.rejects(avanzarReloj(), /cuánto avanzar/);
  await assert.rejects(avanzarReloj({ minutos: 0 }), /cuánto avanzar/);
  await assert.rejects(avanzarReloj({ minutos: -15 }), /cuánto avanzar/);
  await assert.rejects(avanzarReloj({ horas: 1.5 }), /cuánto avanzar/);
  assert.equal(peticiones.length, 2);
});

test('POST /simulacion/reloj/proxima-franja salta al inicio de la comida', async () => {
  const peticiones = grabar(() => json({
    comida_id: 2, comida: 'Almuerzo', inicio: '2026-08-10T12:00:00',
    reloj: estadoReloj({ ahora: '2026-08-10T12:00:00' }),
  }));
  const resultado = await saltarAProximaFranja();
  assert.deepEqual(peticiones.map(({ ruta, metodo, cuerpo }) => ({ ruta, metodo, cuerpo })), [
    { ruta: '/simulacion/reloj/proxima-franja', metodo: 'POST', cuerpo: undefined },
  ]);
  assert.equal(resultado.tipo, 'ok');
  assert.equal(resultado.comidaId, 2);
  assert.equal(resultado.comida, 'Almuerzo');
  assert.equal(valorFechaHoraLocal(resultado.inicio), '2026-08-10T12:00');
  assert.equal(valorFechaHoraLocal(resultado.reloj.ahora), '2026-08-10T12:00');

  grabar(() => json({ comida_id: 2, comida: 'Almuerzo', inicio: '2026-08-10T12:00:00' }));
  await assert.rejects(saltarAProximaFranja(), /próxima franja.*reloj inválido/);
  grabar(() => json({ comida: 'Almuerzo' }));
  await assert.rejects(saltarAProximaFranja(), /franja inválida/);
});

test('proxima-franja con 409 es un mensaje, no un error', async () => {
  grabar(() => json({ detail: 'No hay ninguna franja de comida vigente hoy ni mañana.' }, 409));
  assert.deepEqual(await saltarAProximaFranja(), {
    tipo: 'sin_franja', detalle: 'No hay ninguna franja de comida vigente hoy ni mañana.',
  });
  // Sin cuerpo legible, igual es un mensaje.
  grabar(() => new Response('', { status: 409 }));
  assert.equal((await saltarAProximaFranja()).tipo, 'sin_franja');
  // Cualquier otro error sí se informa como tal.
  grabar(() => json({}, 500));
  await assert.rejects(saltarAProximaFranja(), /próxima franja.*HTTP 500/);
});

test('DELETE /simulacion/reloj vuelve a la hora real', async () => {
  const peticiones = grabar(() => json(estadoReloj({ ahora: '2026-09-25T09:00:01', simulado: false })));
  const reloj = await volverARelojReal();
  assert.deepEqual(peticiones.map(({ ruta, metodo }) => ({ ruta, metodo })), [
    { ruta: '/simulacion/reloj', metodo: 'DELETE' },
  ]);
  assert.equal(reloj.simulado, false);
  assert.equal(estadoDelReloj(reloj), 'Hora real');
});

// --- Derivados y permisos ---

test('fechas del servidor: hora de pared, sin conversión de zona', () => {
  const momento = fechaHoraDelServidor('2026-08-10T23:59:59.999999');
  assert.deepEqual([momento.getDate(), momento.getHours(), momento.getMinutes()], [10, 23, 59]);
  assert.equal(valorFechaHoraLocal(fechaHoraDelServidor('2026-08-10 07:05')), '2026-08-10T07:05');
  assert.equal(fechaHoraDelServidor('2026-08-10'), null);
  assert.equal(fechaHoraDelServidor(null), null);
});

test('clave del día y estado del reloj', () => {
  assert.equal(claveDelDia(null), 'real');
  assert.equal(claveDelDia({ ahora: new Date(2026, 7, 10, 23, 59) }), '2026-08-10');
  assert.equal(estadoDelReloj({ simulado: true, congelado: true }), 'Congelado');
  assert.equal(estadoDelReloj({ simulado: true, congelado: false }), 'Simulado');
  assert.equal(estadoDelReloj({ simulado: true, congelado: null }), 'Simulado');
  assert.equal(estadoDelReloj({ simulado: false, congelado: false }), 'Hora real');
});

test('solo jefatura mueve el reloj, igual que en el backend', () => {
  assert.equal(puedeOperarReloj('jefa'), true);
  assert.equal(puedeOperarReloj('Sistemas'), true);
  assert.equal(puedeOperarReloj('cocinera'), false);
  assert.equal(puedeOperarReloj('otro'), false);
  assert.equal(puedeOperarReloj(undefined), false);
});
