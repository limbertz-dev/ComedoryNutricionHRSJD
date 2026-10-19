/*
 * Intervenciones de cocina: la cocinera identifica una huella no reconocida y
 * confirma la entrega; la jefa solo consulta.
 *
 * Contrato: comedorback/app/api/asistencias.py, app/api/intervenciones.py y
 * app/esquemas/pantalla.py (feat/jefa-intervenciones-back, bfcacb3). Todo con
 * fetch controlado: ni API real ni base de datos.
 */
import test, { afterEach, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import {
  esClaveIdempotencia,
  identificarLectura,
  nuevaClaveIdempotencia,
  obtenerIntervencionesCocina,
  obtenerLecturasPorIdentificar,
  obtenerUltimasMarcaciones,
} from '../src/api.js';
import {
  avisoDeIdentificacion,
  crearIdentificador,
  horaCortaServidor,
  revisionesCambiadas,
} from '../src/identificacion.js';
import { programarCicloCocina } from '../src/cocinaEnVivo.js';
import {
  puedeConsultarIntervenciones,
  puedeIdentificarLecturas,
  puedeMarcarManual,
} from '../src/permisos.js';
import { escucharSesion } from '../src/sesion.js';
import IdentificarLectura from '../src/components/secciones/IdentificarLectura.jsx';
import IntervencionesCocina from '../src/components/secciones/IntervencionesCocina.jsx';
import PantallaEnVivo, { eventoDeFila } from '../src/components/secciones/PantallaEnVivo.jsx';
import { Panel } from '../src/App.jsx';
import { ProveedorSesion } from '../src/hooks/useSesion.js';

const fetchOriginal = globalThis.fetch;
let avisos;
let dejarDeEscuchar;
beforeEach(() => {
  avisos = [];
  dejarDeEscuchar = escucharSesion((aviso) => avisos.push(aviso.tipo));
});
afterEach(() => {
  globalThis.fetch = fetchOriginal;
  dejarDeEscuchar();
});

const json = (datos, status = 200) => new Response(JSON.stringify(datos), {
  status, headers: { 'Content-Type': 'application/json' },
});

/** Graba cada petición y responde con `responder({ ruta, consulta, opciones })`. */
function grabar(responder) {
  const peticiones = [];
  globalThis.fetch = async (url, opciones = {}) => {
    const destino = new URL(url);
    const peticion = { ruta: destino.pathname, consulta: destino.searchParams, opciones };
    peticiones.push(peticion);
    return responder(peticion);
  };
  return peticiones;
}

const CLAVE = '3f2b8c1e-9a4d-4c7b-8e2f-1a2b3c4d5e6f';

const respuestaRegistrada = (cambios = {}) => ({
  valido: true,
  resultado: 'registrada',
  motivo: null,
  titulo: 'Entrega registrada',
  detalle: 'Identificada manualmente por cocina. La lectura original no se modificó.',
  reintento: false,
  lectura_id: 7,
  asistencia_id: 31,
  intervencion_id: 55,
  usuario_id: 99,
  nombre: 'Ana Gomez',
  comida: 'Cena',
  comida_id: 4,
  fecha_comida: '2026-09-27',
  servicio_id: 4,
  raciones_restantes: 12,
  causa: 'identificacion_manual_por_no_identificado',
  momento: '2026-09-28T00:30:00',
  ...cambios,
});

const ANA = { id: 99, nombre: 'Ana Gomez', categoria: 'Médico', legajo: 'M-99' };

/* ------------------------------------------------------------------ permisos */

test('solo la cocinera identifica; solo la jefa consulta; sistemas queda fuera de las dos', () => {
  assert.equal(puedeIdentificarLecturas('cocinera'), true);
  assert.equal(puedeIdentificarLecturas('jefa'), false);
  assert.equal(puedeIdentificarLecturas('sistemas'), false);
  assert.equal(puedeConsultarIntervenciones('jefa'), true);
  assert.equal(puedeConsultarIntervenciones('cocinera'), false);
  assert.equal(puedeConsultarIntervenciones('sistemas'), false);
  assert.equal(puedeIdentificarLecturas('desconocido'), false);
  assert.equal(puedeConsultarIntervenciones(undefined), false);
  /* El registro manual de jefatura no cambia. */
  assert.equal(puedeMarcarManual('jefa'), true);
  assert.equal(puedeMarcarManual('cocinera'), false);
});

/* ------------------------------------------------------- clave de idempotencia */

test('la clave de idempotencia es un UUID v4 y se genera sin randomUUID', () => {
  const claves = new Set(Array.from({ length: 50 }, () => nuevaClaveIdempotencia()));
  assert.equal(claves.size, 50);
  for (const clave of claves) assert.ok(esClaveIdempotencia(clave), clave);

  /* Un navegador sin contexto seguro tiene getRandomValues, no randomUUID. */
  const cripto = { getRandomValues: (bytes) => bytes.fill(0xff) };
  const clave = nuevaClaveIdempotencia(cripto);
  assert.equal(clave, 'ffffffff-ffff-4fff-bfff-ffffffffffff');
  assert.ok(esClaveIdempotencia(clave));
  assert.equal(esClaveIdempotencia('no-es-uuid'), false);
  assert.equal(esClaveIdempotencia('3F2B8C1E-9A4D-4C7B-8E2F-1A2B3C4D5E6F'), false, 'el servidor la normaliza a minúsculas');
});

/* ------------------------------------------------------ POST de identificación */

test('identificar envía solo {usuario_id} con Idempotency-Key, sin nota, motivo ni momento', async () => {
  const peticiones = grabar(() => json(respuestaRegistrada()));
  const resultado = await identificarLectura(7, 99, { clave: CLAVE });

  assert.equal(peticiones.length, 1);
  const [peticion] = peticiones;
  assert.equal(peticion.ruta, '/asistencias/lecturas/7/identificar');
  assert.equal(peticion.opciones.method, 'POST');
  assert.equal(peticion.opciones.headers['Idempotency-Key'], CLAVE);
  assert.deepEqual(JSON.parse(peticion.opciones.body), { usuario_id: 99 });

  assert.equal(resultado.estado, 'registrada');
  assert.equal(resultado.asistenciaId, 31);
  assert.equal(resultado.nombre, 'Ana Gomez');
  assert.equal(resultado.comida, 'Cena');
  assert.equal(resultado.fechaComida, '2026-09-27');
  assert.equal(resultado.reintento, false);
});

test('un 200 con valido=false es un intento rechazado, nunca una entrega', async () => {
  grabar(() => json(respuestaRegistrada({
    valido: false, resultado: 'rechazada', motivo: 'duplicado', asistencia_id: null,
    titulo: 'Intento rechazado', detalle: 'No se registró entrega: ya recibió su cena de hoy.',
  })));
  const resultado = await identificarLectura(7, 99, { clave: CLAVE });
  assert.equal(resultado.estado, 'rechazada');
  assert.equal(resultado.motivo, 'duplicado');
  const aviso = avisoDeIdentificacion(resultado, ANA);
  assert.equal(aviso.tipo, 'rechazo');
  assert.doesNotMatch(aviso.titulo, /registrada/i);
  assert.match(aviso.titulo, /no se registró entrega/);
  assert.equal(aviso.repetir, false);
});

test('los conflictos sobre la lectura vuelven como conflicto; ya resuelta dice si fue esta cuenta y nunca quién', async () => {
  grabar(() => json({
    detail: 'La lectura ya fue resuelta.', motivo: 'lectura_ya_resuelta',
    resultado: 'rechazada', lectura_id: 7, intervencion_id: 56, resuelta_por_mi: false, reintento: false,
  }, 409));
  const ajena = await identificarLectura(7, 99, { clave: CLAVE });
  assert.equal(ajena.estado, 'conflicto');
  assert.equal(ajena.motivo, 'lectura_ya_resuelta');
  assert.equal(ajena.resueltaPorMi, false);
  const avisoAjena = avisoDeIdentificacion(ajena);
  assert.equal(avisoAjena.titulo, 'Ya fue resuelta');
  assert.equal(avisoAjena.cerrar, true);

  grabar(() => json({ detail: 'x', motivo: 'lectura_ya_resuelta', resuelta_por_mi: true }, 409));
  const propia = await identificarLectura(7, 99, { clave: CLAVE });
  assert.equal(avisoDeIdentificacion(propia).titulo, 'Ya la registró usted');

  grabar(() => json({ detail: 'La lectura no pertenece al servicio en curso.', motivo: 'servicio_distinto' }, 409));
  const fuera = await identificarLectura(7, 99, { clave: CLAVE });
  assert.equal(fuera.estado, 'conflicto');
  assert.equal(avisoDeIdentificacion(fuera).cerrar, true);

  /* Ningún 409 pasa por el manejo central de sesión. */
  assert.deepEqual(avisos, []);
});

test('503 resultado_incierto, otro 5xx, la red o una respuesta ilegible son inciertos: repetir con la misma clave', async () => {
  grabar(() => json({ detail: 'No se pudo confirmar el resultado. Repita la solicitud con la misma clave.', motivo: 'resultado_incierto' }, 503));
  const incierto = await identificarLectura(7, 99, { clave: CLAVE });
  assert.equal(incierto.estado, 'incierto');
  const aviso = avisoDeIdentificacion(incierto);
  assert.equal(aviso.repetir, true);
  assert.doesNotMatch(aviso.titulo + aviso.detalle, /no hubo entrega|no se registró/i, 'nunca afirma que no hubo entrega');

  grabar(() => json({ detail: 'boom' }, 500));
  assert.equal((await identificarLectura(7, 99, { clave: CLAVE })).estado, 'incierto');

  globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
  assert.equal((await identificarLectura(7, 99, { clave: CLAVE })).estado, 'incierto');

  grabar(() => json({ valido: true, resultado: 'registrada', lectura_id: 8 }));
  assert.equal((await identificarLectura(7, 99, { clave: CLAVE })).estado, 'incierto', 'otra lectura o cuerpo incompleto');

  grabar(() => json({ detail: 'Hay otra intervención en curso.', motivo: 'intervencion_en_curso' }, 409));
  const enCurso = await identificarLectura(7, 99, { clave: CLAVE });
  assert.equal(enCurso.estado, 'en_curso');
  assert.equal(avisoDeIdentificacion(enCurso).repetir, true);
});

test('un 403 sigue el manejo central y no se toma como incierto', async () => {
  grabar(() => json({ detail: 'El rol no puede identificar lecturas.', motivo: 'rol_no_autorizado' }, 403));
  const resultado = await identificarLectura(7, 99, { clave: CLAVE });
  assert.equal(resultado.estado, 'error');
  assert.deepEqual(avisos, ['prohibido']);
});

test('sin lectura, persona o clave válidas no se envía nada', async () => {
  const peticiones = grabar(() => json(respuestaRegistrada()));
  await assert.rejects(identificarLectura(0, 99, { clave: CLAVE }), /Lectura inválida/);
  await assert.rejects(identificarLectura(7, null, { clave: CLAVE }), /Seleccione/);
  await assert.rejects(identificarLectura(7, 99, { clave: 'repetida' }), /Clave de idempotencia/);
  assert.equal(peticiones.length, 0);
});

/* ------------------------------------------------- intento e idempotencia */

const LECTURA_9 = { id: 9, clave: 'lectura_biometrica:9', hora: '23:58:00', comida: 'Cena' };
const LUIS = { id: 15, nombre: 'Luis Perez', categoria: 'Planta', legajo: 'P-15' };

/** Identificador con POST grabado: `respuestas` se consumen en orden. */
function identificadorGrabado(respuestas) {
  const llamadas = [];
  let n = 0;
  let i = 0;
  const identificador = crearIdentificador({
    identificar: async (lecturaId, usuarioId, { clave }) => {
      llamadas.push({ lecturaId, usuarioId, clave });
      const respuesta = respuestas[n++];
      if (respuesta instanceof Error) throw respuesta;
      return respuesta;
    },
    nuevaClave: () => `clave-${++i}`,
  });
  return { identificador, llamadas };
}

test('un resultado incierto se verifica con la MISMA clave y la misma persona; la entrega cierra el intento', async () => {
  const { identificador, llamadas } = identificadorGrabado([
    { estado: 'incierto' }, { estado: 'registrada', reintento: true }, { estado: 'registrada' },
  ]);
  assert.equal((await identificador.confirmar(LECTURA_9, ANA)).estado, 'incierto');
  const pendiente = identificador.pendiente(9);
  assert.equal(pendiente.usuarioId, 99);
  assert.equal(pendiente.clave, 'clave-1');
  assert.equal(pendiente.estado, 'incierto');

  assert.equal((await identificador.verificar(9)).reintento, true);
  assert.deepEqual(llamadas[1], { lecturaId: 9, usuarioId: 99, clave: 'clave-1' });
  assert.equal(identificador.pendiente(9), null, 'la entrega confirmada cierra el intento');

  /* Un intento nuevo sobre otra lectura lleva otra clave. */
  await identificador.confirmar({ ...LECTURA_9, id: 8 }, ANA);
  assert.equal(llamadas[2].clave, 'clave-2');
});

test('durante la incertidumbre no se puede cambiar de persona; tras un resultado definitivo, sí y con otra clave', async () => {
  const { identificador, llamadas } = identificadorGrabado([
    { estado: 'en_curso' }, { estado: 'rechazada' }, { estado: 'rechazada' },
  ]);
  await identificador.confirmar(LECTURA_9, ANA);
  /* Otra persona sobre la misma huella: bloqueado, sin petición. */
  assert.deepEqual(await identificador.confirmar(LECTURA_9, LUIS), { estado: 'bloqueado' });
  assert.equal(llamadas.length, 1);
  assert.equal(identificador.pendiente(9).usuarioId, 99, 'la decisión pendiente no se sustituye');
  assert.equal(avisoDeIdentificacion({ estado: 'bloqueado' }).repetir, true);

  /* Verificar resuelve (rechazo definitivo): recién ahí se puede elegir a otra. */
  await identificador.verificar(9);
  assert.equal(llamadas[1].clave, 'clave-1');
  assert.equal(identificador.pendiente(9), null);
  await identificador.confirmar(LECTURA_9, LUIS);
  assert.deepEqual(llamadas[2], { lecturaId: 9, usuarioId: 15, clave: 'clave-2' });
});

test('un error inesperado después de iniciar el envío es incierto: conserva el intento y no dice que no hubo entrega', async () => {
  const { identificador, llamadas } = identificadorGrabado([new Error('se cortó la respuesta'), undefined]);
  const resultado = await identificador.confirmar(LECTURA_9, ANA);
  assert.equal(resultado.estado, 'incierto');
  assert.equal(identificador.pendiente(9).clave, 'clave-1');
  const aviso = avisoDeIdentificacion(resultado, ANA);
  assert.equal(aviso.repetir, true);
  assert.doesNotMatch(aviso.titulo + aviso.detalle, /no se registró|no hubo entrega/i);

  /* Una respuesta sin estado tampoco se toma como definitiva. */
  assert.equal((await identificador.verificar(9)).estado, 'incierto');
  assert.equal(llamadas[1].clave, 'clave-1');
  assert.ok(identificador.pendiente(9));
  /* Un estado desconocido tampoco afirma nada. */
  assert.doesNotMatch(avisoDeIdentificacion({ estado: 'otra-cosa' }).titulo, /no se registró/i);
});

test('sin huella o persona válidas no se abre intento ni se envía nada', async () => {
  const { identificador, llamadas } = identificadorGrabado([]);
  assert.equal((await identificador.confirmar(LECTURA_9, { id: null })).estado, 'invalido');
  assert.equal((await identificador.confirmar({ id: 0 }, ANA)).estado, 'invalido');
  assert.equal(await identificador.verificar(9), null, 'nada que verificar');
  assert.equal(llamadas.length, 0);
  assert.deepEqual(identificador.pendientes(), []);
});

test('un segundo clic mientras el POST está en vuelo no envía nada', async () => {
  let liberar;
  let llamadas = 0;
  const identificador = crearIdentificador({
    identificar: () => { llamadas += 1; return new Promise((resolver) => { liberar = resolver; }); },
  });
  const primero = identificador.confirmar(LECTURA_9, ANA);
  assert.equal(identificador.enVuelo(), true);
  assert.equal(await identificador.confirmar(LECTURA_9, ANA), null);
  assert.equal(await identificador.verificar(9), null);
  liberar({ estado: 'registrada' });
  assert.equal((await primero).estado, 'registrada');
  assert.equal(llamadas, 1);
});

test('el identificador no ofrece forma de descartar un intento sin resolver', () => {
  const identificador = crearIdentificador({ identificar: async () => ({ estado: 'incierto' }) });
  assert.equal('olvidar' in identificador, false);
  assert.deepEqual(Object.keys(identificador).sort(), ['confirmar', 'enVuelo', 'pendiente', 'pendientes', 'verificar']);
});

/* --------------------------- panel de cocina con un intento sin resolver */

const panel = (props) => renderToStaticMarkup(h(IdentificarLectura, {
  pendientes: pendientesFixture([lecturaUi(9), lecturaUi(12, '00:20:00')]),
  personal: [ANA, LUIS],
  ...props,
}));

test('1. incierto → cerrar → reabrir: se recupera la misma decisión y se verifica con la misma clave y usuario', async () => {
  const { identificador, llamadas } = identificadorGrabado([{ estado: 'incierto' }, { estado: 'registrada', reintento: true }]);
  await identificador.confirmar(LECTURA_9, ANA);

  /* Cerrado: el intento sigue listado para verificar. */
  const cerrado = panel({ identificador, abierta: null });
  assert.match(cerrado, /Por verificar/);
  assert.match(cerrado, /Ana Gomez/);
  assert.match(cerrado, /<span class="boton__texto">Verificar<\/span>/);

  /* Reabierto: la persona del intento, sin selector, y «Verificar entrega». */
  const reabierto = panel({ identificador, abierta: 9 });
  assert.match(reabierto, /<strong>Ana Gomez<\/strong>/);
  assert.match(reabierto, /<span class="boton__texto">Verificar entrega<\/span>/);
  assert.doesNotMatch(reabierto, /Confirmar entrega/);

  await identificador.verificar(9);
  assert.deepEqual(llamadas.map(({ usuarioId, clave }) => ({ usuarioId, clave })), [
    { usuarioId: 99, clave: 'clave-1' },
    { usuarioId: 99, clave: 'clave-1' },
  ]);
});

test('2. la persona deja de aparecer en el padrón: el intento se puede verificar igual', async () => {
  const { identificador, llamadas } = identificadorGrabado([{ estado: 'en_curso' }, { estado: 'registrada', reintento: true }]);
  await identificador.confirmar(LECTURA_9, ANA);

  /* Padrón sin Ana (o con una búsqueda que la deja fuera). */
  for (const props of [{ personal: [LUIS] }, { personal: [] }, { personal: [ANA], busquedaInicial: 'zzz' }]) {
    const html = panel({ identificador, abierta: 9, ...props });
    assert.match(html, /<strong>Ana Gomez<\/strong>/);
    assert.match(html, /Médico · Legajo M-99/);
    assert.doesNotMatch(html, /<button[^>]*disabled=""[^>]*><span class="boton__icono">[\s\S]*?Verificar entrega/);
  }
  /* Ni el padrón vacío ni su error esconden el intento. */
  const conError = panel({ identificador, abierta: 9, personal: [], errorPadron: 'HTTP 500' });
  assert.match(conError, /Verificar entrega/);
  assert.doesNotMatch(conError, /el padrón no se cargó/);

  await identificador.verificar(9);
  assert.equal(llamadas[1].usuarioId, 99);
});

test('3. la huella sale de los pendientes: el intento incierto no se pierde ni se da por entregado', async () => {
  const { identificador } = identificadorGrabado([{ estado: 'incierto' }]);
  await identificador.confirmar(LECTURA_9, ANA);
  const sinHuellas = pendientesFixture([]);

  const cerrado = panel({ identificador, pendientes: sinHuellas, abierta: null });
  assert.match(cerrado, /Por verificar/);
  assert.match(cerrado, /Huella · 23:58:00 · Cena/);
  assert.doesNotMatch(cerrado, /No hay huellas sin reconocer pendientes/);

  const abierto = panel({ identificador, pendientes: sinHuellas, abierta: 9 });
  assert.match(abierto, /Eso no confirma la entrega: pudo terminar el\s+servicio/);
  assert.doesNotMatch(abierto, /la resolvió alguien/);
  assert.match(abierto, /Verificar entrega/);
  assert.doesNotMatch(abierto, /<button[^>]*disabled=""[^>]*><span class="boton__icono">[\s\S]*?Verificar entrega/);
  assert.ok(identificador.pendiente(9), 'el intento sigue vivo');
});

test('4. durante la incertidumbre el panel no deja elegir a otra persona', async () => {
  const { identificador } = identificadorGrabado([{ estado: 'incierto' }]);
  await identificador.confirmar(LECTURA_9, ANA);
  const html = panel({ identificador, abierta: 9, elegidoInicial: '15' });
  assert.doesNotMatch(html, /<select|<input/, 'sin buscador ni selector');
  assert.doesNotMatch(html, /Luis Perez/);
  assert.match(html, /No se puede elegir a otra hasta verificarla/);
  /* La lista marca esa huella como por verificar, no como identificable. */
  assert.equal(html.match(/<span class="boton__texto">Identificar<\/span>/g).length, 1, 'solo la otra huella');
});

/* ------------------------------------------- lecturas por identificar (nocturno) */

const lecturaApi = (id, fechaHora, cambios = {}) => ({
  id,
  fecha_hora: fechaHora,
  usuario_id: null,
  nombre: 'Huella no reconocida',
  categoria: 'Sin identificar',
  comida_id: 4,
  comida: 'Cena',
  resultado: 'rechazada',
  motivo: 'no_identificado',
  valido: false,
  dispositivo: 'lector-pb',
  origen: 'lectura_biometrica',
  clave_evento: `lectura_biometrica:${id}`,
  comida_origen: 'reconstruida_por_horario',
  decision_original: { resultado: 'rechazada', motivo: 'no_identificado', fecha_hora: fechaHora, dispositivo: 'lector-pb' },
  estado_final: 'sin_racion',
  resultado_final: null,
  puede_identificar: true,
  motivo_no_identificable: null,
  identificable_hasta: '2026-09-28T01:00:00',
  intervencion: { revision: 0, actualizado_en: null, resuelta: false, resuelta_por_mi: false },
  ...cambios,
});

test('lecturas-por-identificar sigue el servicio que cruza la medianoche, sin fecha ni tope de 100', async () => {
  const peticiones = grabar(() => json({
    servicio: {
      comida_id: 4, comida: 'Cena', fecha_comida: '2026-09-27',
      inicio: '2026-09-27T19:00:00', fin: '2026-09-28T01:00:00',
    },
    total: 2,
    truncado: false,
    lecturas: [lecturaApi(12, '2026-09-28T00:20:00'), lecturaApi(9, '2026-09-27T23:58:00')],
  }));
  const pendientes = await obtenerLecturasPorIdentificar();

  assert.equal(peticiones[0].ruta, '/pantalla/lecturas-por-identificar');
  assert.equal([...peticiones[0].consulta.keys()].length, 0, 'no manda fecha ni límite');
  assert.equal(pendientes.servicio.fechaComida, '2026-09-27');
  assert.equal(pendientes.lecturas.length, 2);
  /* La de las 23:58 de «ayer» sigue en la lista a las 00:30. */
  assert.equal(pendientes.lecturas[1].clave, 'lectura_biometrica:9');
  assert.equal(pendientes.lecturas[1].fechaHora, '2026-09-27T23:58:00');
  assert.equal(pendientes.lecturas[1].puedeIdentificar, true);
  assert.equal(horaCortaServidor(pendientes.servicio.fin), '01:00');
});

test('lecturas-por-identificar rechaza filas que no se pueden identificar o una lista sin servicio', async () => {
  grabar(() => json({ servicio: null, total: 0, truncado: false, lecturas: [] }));
  assert.equal((await obtenerLecturasPorIdentificar()).servicio, null);

  grabar(() => json({ servicio: null, total: 1, truncado: false, lecturas: [lecturaApi(9, '2026-09-27T23:58:00')] }));
  await assert.rejects(obtenerLecturasPorIdentificar(), /inválidas/);

  grabar(() => json({
    servicio: { comida_id: 4, comida: 'Cena', fecha_comida: '2026-09-27', inicio: 'a', fin: 'b' },
    total: 1, truncado: false,
    lecturas: [lecturaApi(9, '2026-09-27T23:58:00', { puede_identificar: false })],
  }));
  await assert.rejects(obtenerLecturasPorIdentificar(), /no se puede identificar/);
});

test('ultimas-marcaciones separa la decisión original del resultado final y trae la revisión', async () => {
  grabar(() => json([
    lecturaApi(9, '2026-09-27T23:58:00', {
      estado_final: 'racion_servida',
      comida_origen: 'persistida_en_asistencia',
      resultado_final: {
        via: 'identificacion_manual', asistencia_id: 31,
        comensal: { usuario_id: 99, nombre: 'Ana Gomez' },
        comida: 'Cena', fecha_comida: '2026-09-27', momento: '2026-09-28T00:30:00',
      },
      puede_identificar: false,
      motivo_no_identificable: 'lectura_ya_resuelta',
      intervencion: {
        revision: 2, actualizado_en: '2026-09-28T00:30:00', resuelta: true, resuelta_por_mi: false,
        registrada_por: { cuenta_id: 4, usuario: 'maria.cocina', nombre: 'María Cocina' }, intentos_rechazados: 1,
      },
    }),
  ]));
  const [fila] = await obtenerUltimasMarcaciones({ fecha: '2026-09-27' });
  assert.equal(fila.valido, false, 'valido sigue siendo la decisión del lector');
  assert.equal(fila.decisionOriginal.motivo, 'no_identificado');
  assert.equal(fila.estadoFinal, 'racion_servida');
  assert.equal(fila.resultadoFinal.via, 'identificacion_manual');
  assert.equal(fila.resultadoFinal.comensal.nombre, 'Ana Gomez');
  assert.equal(fila.intervencion.revision, 2);
  assert.equal(fila.intervencion.registradaPor.nombre, 'María Cocina');
  assert.equal(fila.intervencion.intentosRechazados, 1);

  /* Un resultado final que contradice su estado es una respuesta inválida. */
  grabar(() => json([lecturaApi(9, '2026-09-27T23:58:00', { estado_final: 'racion_servida' })]));
  await assert.rejects(obtenerUltimasMarcaciones(), /no coincide con su estado/);
});

test('revisionesCambiadas detecta la fila que otra cocinera resolvió aunque su clave ya existiera', () => {
  const primera = [
    { clave: 'lectura_biometrica:9', intervencion: { revision: 0 } },
    { clave: 'lectura_biometrica:8', intervencion: null },
  ];
  let paso = revisionesCambiadas(null, primera);
  assert.deepEqual(paso.cambiadas, [], 'la primera consulta solo fija la referencia');
  paso = revisionesCambiadas(paso.revisiones, [
    { clave: 'lectura_biometrica:9', intervencion: { revision: 1 } },
    { clave: 'lectura_biometrica:8', intervencion: null },
  ]);
  assert.deepEqual(paso.cambiadas, ['lectura_biometrica:9']);
  paso = revisionesCambiadas(paso.revisiones, [{ clave: 'lectura_biometrica:9', intervencion: { revision: 1 } }]);
  assert.deepEqual(paso.cambiadas, []);
});

/* ------------------------------------------------------ ciclo de cocina */

function temporizadorFalso() {
  const pendientes = new Map();
  let siguiente = 1;
  return {
    setTimeout(fn) { const id = siguiente++; pendientes.set(id, fn); return id; },
    clearTimeout(id) { pendientes.delete(id); },
    disparar() { const fns = [...pendientes.values()]; pendientes.clear(); fns.forEach((fn) => fn()); },
  };
}
const documentoFalso = () => ({ visibilityState: 'visible', addEventListener() {}, removeEventListener() {} });
const vaciar = async () => {
  for (let i = 0; i < 5; i += 1) await new Promise((r) => setImmediate(r));
};

test('el ciclo de cocina consulta las huellas por identificar y un fallo suyo no tapa la lista', async () => {
  const listas = [];
  const pendientes = [];
  let falla = false;
  const temporizador = temporizadorFalso();
  const control = programarCicloCocina({
    consultarMarcaciones: async () => [{ clave: 'lectura_biometrica:1' }],
    consultarPendientes: async () => {
      if (falla) throw new Error('HTTP 500');
      return { servicio: null, total: 0, truncado: false, lecturas: [] };
    },
    alActualizar: (r) => listas.push(r),
    alActualizarPendientes: (r) => pendientes.push(r),
    temporizador,
    documento: documentoFalso(),
  });
  await vaciar();
  assert.equal(pendientes[0].error, '');
  assert.equal(pendientes[0].resultado.total, 0);

  falla = true;
  temporizador.disparar();
  await vaciar();
  assert.match(pendientes[1].error, /HTTP 500/);
  assert.equal(listas[1].filas.length, 1, 'la lista de marcaciones sigue llegando');
  control.cancelar();
});

test('sin consultarPendientes (jefa, sistemas) el ciclo no pide huellas por identificar', async () => {
  const pendientes = [];
  const control = programarCicloCocina({
    consultarMarcaciones: async () => [],
    alActualizarPendientes: (r) => pendientes.push(r),
    temporizador: temporizadorFalso(),
    documento: documentoFalso(),
  });
  await vaciar();
  assert.deepEqual(pendientes, []);
  control.cancelar();
});

/* ------------------------------------------------------ pantalla de cocina */

const pendientesFixture = (lecturas) => ({
  servicio: { comidaId: 4, comida: 'Cena', fechaComida: '2026-09-27', inicio: '2026-09-27T19:00:00', fin: '2026-09-28T01:00:00' },
  total: lecturas.length,
  truncado: false,
  lecturas,
});
const lecturaUi = (id, hora = '23:58:00') => ({
  id, clave: `lectura_biometrica:${id}`, origen: 'lectura_biometrica', valido: false, motivo: 'no_identificado',
  hora, comida: 'Cena', dispositivo: 'lector-pb', puedeIdentificar: true,
  identificableHasta: '2026-09-28T01:00:00', persona: { id: null, nombre: 'Huella no reconocida' },
});

test('cocina ve sus huellas por identificar y la persona se elige sin nota ni motivo', () => {
  const html = renderToStaticMarkup(h(IdentificarLectura, {
    pendientes: pendientesFixture([lecturaUi(9), lecturaUi(12, '00:20:00')]),
    personal: [ANA],
    abierta: 9,
    elegidoInicial: '99',
  }));
  assert.match(html, /Huellas por identificar/);
  assert.match(html, /Cena · se pueden identificar hasta las 01:00/);
  assert.match(html, /23:58:00/);
  assert.match(html, /00:20:00/);
  /* La abierta muestra la identidad a confirmar y el botón de entrega. */
  assert.match(html, /<strong>Ana Gomez<\/strong>/);
  assert.match(html, /<span class="boton__texto">Confirmar entrega<\/span>/);
  /* Un solo campo de texto (la búsqueda) y el selector: nada de nota ni motivo. */
  assert.equal(html.match(/<input/g).length, 1);
  assert.equal(html.match(/<select/g).length, 1);
  assert.doesNotMatch(html, /<textarea|[Nn]ota|[Mm]otivo/);
  /* La otra lectura ofrece abrirse. */
  assert.equal(html.match(/<span class="boton__texto">Identificar<\/span>/g).length, 1);
});

test('una huella que salió de la lista ya no se puede confirmar', () => {
  const html = renderToStaticMarkup(h(IdentificarLectura, {
    pendientes: pendientesFixture([]),
    personal: [ANA],
    abierta: 9,
    elegidoInicial: '99',
  }));
  assert.match(html, /ya no está pendiente: la resolvió alguien o terminó el servicio/);
  assert.match(html, /<button[^>]*disabled=""[^>]*><span class="boton__icono">[\s\S]*?Confirmar entrega/);
});

test('cocina distingue cargando, vacío, sin servicio y error', () => {
  assert.match(renderToStaticMarkup(h(IdentificarLectura, {})), /Consultando huellas por identificar/);
  const vacio = renderToStaticMarkup(h(IdentificarLectura, { pendientes: { servicio: null, total: 0, truncado: false, lecturas: [] } }));
  assert.match(vacio, /No hay un servicio en curso/);
  assert.match(vacio, /No hay huellas sin reconocer pendientes/);
  const error = renderToStaticMarkup(h(IdentificarLectura, { error: 'No se pudieron cargar las huellas por identificar.' }));
  assert.match(error, /role="alert"/);
});

test('Control Biométrico muestra el panel solo a quien puede identificar', () => {
  const props = { pantalla: null, turno: 'Cena' };
  assert.match(renderToStaticMarkup(h(PantallaEnVivo, { ...props, puedeIdentificar: true })), /Huellas por identificar/);
  assert.doesNotMatch(renderToStaticMarkup(h(PantallaEnVivo, props)), /Huellas por identificar/);
});

test('una huella identificada por cocina se muestra como entrega, sin decir que el lector la reconoció', () => {
  const evento = eventoDeFila({
    clave: 'lectura_biometrica:9', origen: 'lectura_biometrica', valido: false, hora: '23:58:00',
    titulo: 'Huella no reconocida', persona: { id: null, nombre: 'Huella no reconocida' },
    resultadoFinal: { via: 'identificacion_manual', comensal: { usuarioId: 99, nombre: 'Ana Gomez' } },
  });
  assert.equal(evento.valido, true);
  assert.equal(evento.titulo, 'Entrega registrada por cocina');
  assert.equal(evento.persona.id, 99);
  assert.match(evento.detalle, /no reconoció la huella/);
});

test('el panel de la cocinera monta las huellas por identificar; jefa y sistemas no pueden operarla', () => {
  const localOriginal = globalThis.localStorage;
  const montar = (rol, guardada = null) => {
    globalThis.localStorage = { getItem: () => guardada, setItem: () => {}, removeItem: () => {} };
    return renderToStaticMarkup(h(ProveedorSesion, null, h(Panel, { rol, usuario: `${rol}.test` })));
  };
  try {
    const cocina = montar('cocinera');
    assert.match(cocina, /Huellas por identificar/);
    assert.match(cocina, /Consultando huellas por identificar…/);
    assert.doesNotMatch(cocina, /Intervenciones de cocina/);

    for (const guardada of [null, 'vivo']) {
      const jefa = montar('jefa', guardada);
      assert.doesNotMatch(jefa, /Huellas por identificar|Confirmar entrega|Identificar a la persona/);
      assert.match(jefa, /Cargando supervisión…/);
    }

    for (const guardada of [null, 'vivo', 'supervision']) {
      const sistemas = montar('sistemas', guardada);
      assert.doesNotMatch(sistemas, /Huellas por identificar|Confirmar entrega|Identificar a la persona|Intervenciones de cocina/);
      assert.match(sistemas, /Reglas del sistema/);
    }
  } finally {
    if (localOriginal === undefined) delete globalThis.localStorage;
    else globalThis.localStorage = localOriginal;
  }
});

test('columna lateral solo contiene Marcaciones del turno y la identificación se integra al área central', () => {
  const html = renderToStaticMarkup(h(PantallaEnVivo, {
    pantalla: null,
    turno: 'Cena',
    puedeIdentificar: true,
  }));
  const lateralMatch = html.match(/<aside class="vivo__lateral">([\s\S]*?)<\/aside>/);
  assert.ok(lateralMatch, 'debe existir la columna lateral');
  const lateralHtml = lateralMatch[1];
  assert.match(lateralHtml, /Marcaciones del turno/);
  assert.doesNotMatch(lateralHtml, /Huellas por identificar|class="identificar/);

  const centralMatch = html.match(/<div class="escenario__principal[^"]*">([\s\S]*?)<\/div>/);
  assert.ok(centralMatch, 'debe existir el área central');
  assert.match(centralMatch[1], /Huellas por identificar/);
});

test('al abrir una lectura pendiente en las marcaciones, el área central despliega el flujo en 3 pasos sin preselección', () => {
  const pendiente = {
    id: 101,
    hora: '12:14:22',
    comida: 'Almuerzo',
    dispositivo: 'LECTOR-01',
    hasta: '15:00:00',
    resuelta: false,
    decisionOriginal: { resultado: 'rechazada', motivo: 'no_identificado' },
  };
  const html = renderToStaticMarkup(h(PantallaEnVivo, {
    pantalla: null,
    turno: 'Almuerzo',
    puedeIdentificar: true,
    marcacionesIniciales: [
      {
        id: 101,
        origen: 'lectura_biometrica',
        clave_evento: 'lectura_biometrica:101',
        usuario_id: null,
        nombre: 'Huella no reconocida',
        categoria: 'Sin identificar',
        valido: false,
        resultado: 'rechazada',
        motivo: 'no_identificado',
        dispositivo: 'LECTOR-01',
        fecha_hora: '2026-10-15T12:14:22',
        comida_id: 2,
        comida: 'Almuerzo',
        estado_final: 'sin_racion',
        puede_identificar: true,
        identificable_hasta: '2026-10-15T15:00:00',
      },
    ],
    pendientesIniciales: {
      servicio: { comida_id: 2, comida: 'Almuerzo' },
      total: 1,
      truncado: false,
      lecturas: [pendiente],
    },
    lecturaAbiertaInicial: 101,
    personal: [ANA],
  }));

  assert.match(html, /1\. Lectura seleccionada/);
  assert.match(html, /Huella no reconocida de las <strong>12:14:22<\/strong>/);
  assert.match(html, /El lector no reconoció la huella: la identidad aún se desconoce y esto no demuestra falta de turno/);
  assert.match(html, /2\. Buscar y elegir comensal del padrón/);
  assert.match(html, /Seleccione a la persona…/);
  assert.match(html, /3\. Sin comensal preseleccionado: busque por nombre o legajo y elija a la persona para confirmar la entrega\./);
  assert.match(html, /<button[^>]*disabled=""[^>]*>[\s\S]*?Confirmar entrega/);
  assert.doesNotMatch(html, /<textarea|[Nn]ota|[Mm]otivo/);
});

test('distingue huella no reconocida de falta de turno sin asumir falta de derecho', () => {
  const eventoNoReconocido = eventoDeFila({
    clave: 'lectura_biometrica:101',
    origen: 'lectura_biometrica',
    valido: false,
    hora: '12:14:22',
    titulo: 'Huella no reconocida',
    persona: { id: null, nombre: 'Huella no reconocida' },
    motivo: 'no_identificado',
    puedeIdentificar: true,
  });
  assert.equal(eventoNoReconocido.sinIdentificar, true);
  assert.match(eventoNoReconocido.detalle, /no reconoció la huella — identidad aún no determinada \(no implica falta de turno\)/);
  assert.doesNotMatch(eventoNoReconocido.detalle, /sin derecho|no habilitada para este turno/);

  const eventoSinDerecho = eventoDeFila({
    clave: 'lectura_biometrica:102',
    origen: 'lectura_biometrica',
    valido: false,
    hora: '12:15:00',
    titulo: 'Ana Lucía Mendoza Vargas',
    persona: { id: 50, nombre: 'Ana Lucía Mendoza Vargas' },
    motivo: 'sin_derecho',
    puedeIdentificar: false,
  });
  assert.equal(eventoSinDerecho.sinIdentificar, false);
  assert.equal(eventoSinDerecho.detalle, 'Marcación no habilitada para este turno');
});

test('un intento por verificar mantiene la identidad bloqueada y permite recuperar sin duplicar', () => {
  const identificadorIncierto = {
    pendiente: (id) => (id === 101 ? {
      lecturaId: 101,
      usuarioId: 99,
      persona: ANA,
      clave: CLAVE,
      estado: 'incierto',
      lectura: { id: 101, hora: '12:14:22', comida: 'Almuerzo' },
    } : null),
    pendientes: () => [{
      lecturaId: 101,
      usuarioId: 99,
      persona: ANA,
      clave: CLAVE,
      estado: 'incierto',
      lectura: { id: 101, hora: '12:14:22', comida: 'Almuerzo' },
    }],
    enVuelo: () => false,
    confirmar: async () => {},
    verificar: async () => {},
  };
  const html = renderToStaticMarkup(h(IdentificarLectura, {
    pendientes: pendientesFixture([lecturaUi(101, '12:14:22')]),
    personal: [ANA],
    abierta: 101,
    identificador: identificadorIncierto,
    avisoInicial: {
      tipo: 'aviso',
      titulo: 'No se pudo confirmar si quedó registrada',
      detalle: 'Verifique la entrega: se repite la misma solicitud con la misma persona y, si ya quedó, se recupera sin duplicarla.',
    },
  }));
  assert.match(html, /No se pudo confirmar si quedó registrada/);
  assert.match(html, /Entrega por verificar con esta persona\. No se puede elegir a otra hasta verificarla\./);
  assert.match(html, /Identidad del intento por verificar/);
  assert.match(html, /Ana Gomez/);
  assert.match(html, /Médico · Legajo M-99/);
  assert.match(html, /Verificar entrega/);
  assert.doesNotMatch(html, /<select/);
});

/* ------------------------------------------------------- consulta de jefa */

const intervencionApi = (id, cambios = {}) => ({
  id,
  clave_evento: `intervencion_lectura:${id}`,
  resultado: 'registrada',
  motivo_rechazo: null,
  causa: 'identificacion_manual_por_no_identificado',
  momento: '2026-09-28T00:30:00',
  decision_original: { lectura_id: 9, resultado: 'rechazada', motivo: 'no_identificado', fecha_hora: '2026-09-27T23:58:00', dispositivo: 'lector-pb' },
  cuenta: { id: 4, usuario: 'maria.cocina', nombre: 'María Cocina' },
  comensal: { usuario_id: 99, nombre: 'Ana Gomez', categoria: 'Médico' },
  servicio_usado: { comida_id: 4, comida: 'Cena', fecha_comida: '2026-09-27', origen: 'reconstruido_por_horario' },
  resultado_final: { entrega_registrada: true, asistencia_id: 31 },
  estado_actual_lectura: 'resuelta',
  ...cambios,
});

test('la jefa consulta intervenciones por día y comida, con totales de todo el filtro', async () => {
  const peticiones = grabar(() => json({
    desde: '2026-09-28', hasta: '2026-09-28', total: 2, limite: 50, desplazamiento: 0,
    totales: { registradas: 1, rechazadas: 1 },
    datos: [
      intervencionApi(56),
      intervencionApi(55, {
        resultado: 'rechazada', motivo_rechazo: 'sin_derecho',
        resultado_final: { entrega_registrada: false, asistencia_id: null }, estado_actual_lectura: 'resuelta',
      }),
    ],
  }));
  const pagina = await obtenerIntervencionesCocina({ desde: '2026-09-28', hasta: '2026-09-28', comidaId: 4 });
  const consulta = peticiones[0].consulta;
  assert.equal(peticiones[0].ruta, '/intervenciones-cocina');
  assert.equal(consulta.get('desde'), '2026-09-28');
  assert.equal(consulta.get('comida_id'), '4');
  assert.equal(consulta.get('limite'), '50');
  assert.equal(pagina.totales.registradas, 1);
  assert.equal(pagina.datos[0].cuenta.nombre, 'María Cocina');
  assert.equal(pagina.datos[1].entregaRegistrada, false);
  assert.equal(pagina.datos[1].motivoRechazo, 'sin_derecho');

  grabar(() => json({
    desde: '2026-09-28', hasta: '2026-09-28', total: 1, limite: 50, desplazamiento: 0,
    totales: { registradas: 1, rechazadas: 0 },
    datos: [intervencionApi(56, { resultado_final: { entrega_registrada: false } })],
  }));
  await assert.rejects(obtenerIntervencionesCocina(), /intervención de cocina inválida/);
});

test('la consulta de intervenciones muestra persona, comida, momento, cocinera, decisión original y resultado final, sin aprobar nada', async () => {
  const pagina = {
    desde: '2026-09-28', hasta: '2026-09-28', total: 2, limite: 50, desplazamiento: 0,
    totales: { registradas: 1, rechazadas: 1 },
    datos: [
      {
        id: 56, clave: 'intervencion_lectura:56', resultado: 'registrada', motivoRechazo: null, momento: '2026-09-28T00:30:00',
        decisionOriginal: { lecturaId: 9, resultado: 'rechazada', motivo: 'no_identificado', fechaHora: '2026-09-27T23:58:00', dispositivo: 'lector-pb' },
        cuenta: { id: 4, usuario: 'maria.cocina', nombre: 'María Cocina' },
        comensal: { usuarioId: 99, nombre: 'Ana Gomez', categoria: 'Médico' },
        servicio: { comidaId: 4, comida: 'Cena', fechaComida: '2026-09-27', reconstruido: true },
        entregaRegistrada: true, asistenciaId: 31, lecturaResuelta: true,
      },
      {
        id: 55, clave: 'intervencion_lectura:55', resultado: 'rechazada', motivoRechazo: 'sin_derecho', momento: '2026-09-28T00:28:10',
        decisionOriginal: { lecturaId: 9, resultado: 'rechazada', motivo: 'no_identificado', fechaHora: '2026-09-27T23:58:00', dispositivo: 'lector-pb' },
        cuenta: { id: 4, usuario: 'maria.cocina', nombre: null },
        comensal: { usuarioId: 15, nombre: 'Luis Perez', categoria: 'Planta' },
        servicio: { comidaId: 4, comida: 'Cena', fechaComida: '2026-09-27', reconstruido: true },
        entregaRegistrada: false, asistenciaId: null, lecturaResuelta: true,
      },
    ],
  };
  const html = renderToStaticMarkup(h(IntervencionesCocina, { comida: 'Cena', inicial: { pagina } }));
  for (const columna of ['Momento', 'Persona', 'Comida', 'Cocinera', 'Decisión original', 'Resultado final']) {
    assert.match(html, new RegExp(`<th scope="col">${columna}</th>`));
  }
  assert.match(html, /00:30:00/);
  assert.match(html, /Ana Gomez/);
  assert.match(html, /María Cocina/);
  assert.match(html, />maria\.cocina</, 'sin nombre, la cuenta se muestra por su usuario');
  assert.match(html, /Rechazada · Huella no reconocida/);
  assert.match(html, /Lector 23:58:00 · lector-pb/);
  assert.match(html, /Servicio del 27\/09/, 'la cena de ayer identificada pasada la medianoche');
  assert.match(html, /Entrega registrada/);
  assert.match(html, /Intento rechazado/);
  assert.match(html, /Sin derecho en este turno · la huella se resolvió en otro intento/);
  assert.match(html, /Entregas registradas 1/);
  assert.match(html, /Intentos rechazados 1/);
  /* Solo consulta: los únicos botones son los del filtro. */
  assert.equal(html.match(/<button/g).length, 3);
  assert.doesNotMatch(html, /Autorizar|Aprobar|Confirmar|Anular|Deshacer/);
});

test('la consulta de intervenciones distingue cargando, vacío y error, y pagina con Anterior/Siguiente', async () => {
  const vacia = { desde: '2026-09-28', hasta: '2026-09-28', total: 0, limite: 50, desplazamiento: 0, totales: { registradas: 0, rechazadas: 0 }, datos: [] };
  assert.match(renderToStaticMarkup(h(IntervencionesCocina, { inicial: { pagina: vacia } })), /No hubo intervenciones de cocina en este período/);
  const error = renderToStaticMarkup(h(IntervencionesCocina, { inicial: { error: 'No se pudieron cargar las intervenciones de cocina.' } }));
  assert.match(error, /role="alert"/);

  const fila = (id) => ({
    id, clave: `intervencion_lectura:${id}`, resultado: 'registrada', motivoRechazo: null, momento: '2026-09-28T12:00:00',
    decisionOriginal: { lecturaId: id, resultado: 'rechazada', motivo: 'no_identificado', fechaHora: '2026-09-28T11:59:00', dispositivo: 'l' },
    cuenta: { id: 4, usuario: 'maria.cocina', nombre: 'María Cocina' },
    comensal: { usuarioId: id, nombre: `P${id}`, categoria: null },
    servicio: { comidaId: 2, comida: 'Almuerzo', fechaComida: '2026-09-28', reconstruido: true },
    entregaRegistrada: true, asistenciaId: id, lecturaResuelta: true,
  });
  const larga = { ...vacia, total: 120, totales: { registradas: 120, rechazadas: 0 }, datos: Array.from({ length: 50 }, (_, i) => fila(i + 1)) };
  const html = renderToStaticMarkup(h(IntervencionesCocina, { inicial: { pagina: larga } }));
  assert.match(html, /1–50 de 120/);
  assert.match(html, /<button[^>]*disabled=""[^>]*><span class="boton__texto">Anterior<\/span>/);
  assert.match(html, /<span class="boton__texto">Siguiente<\/span>/);
});
