/*
 * B1 — registro manual independiente en Supervisión y actualización de
 * cocina desde la API. Todo con respuestas sintéticas del contrato B1:
 * fetch, temporizador y documento falsos; nada sale a una API real.
 */
import test, { afterEach, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import {
  autorizarMarcacionManual,
  claveDeEvento,
  marcacionIncierta,
  marcarAsistencia,
  obtenerUltimasMarcaciones,
} from '../src/api.js';
import {
  LIMITE_MARCACIONES_COCINA,
  MS_CICLO_COCINA,
  detectarNueva,
  programarCicloCocina,
} from '../src/cocinaEnVivo.js';
import { escucharSesion } from '../src/sesion.js';
import { puedeMarcarManual, puedeVerSeccion } from '../src/permisos.js';
import Supervision from '../src/components/secciones/Supervision.jsx';
import RegistroManual, {
  avisoDeFalloRegistro,
  avisoDeRegistroManual,
  crearRegistroManual,
  filtrarPadron,
} from '../src/components/secciones/RegistroManual.jsx';
import { etiquetaDeOrigen, eventoDeFila, filasConPropia } from '../src/components/secciones/PantallaEnVivo.jsx';

const fetchOriginal = globalThis.fetch;
const json = (datos, status = 200) => new Response(JSON.stringify(datos), { status });
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

/** fetch falso que anota cada petición y responde con `responder`. */
function grabar(responder) {
  const peticiones = [];
  globalThis.fetch = async (url, opciones = {}) => {
    const destino = new URL(url);
    const peticion = {
      ruta: destino.pathname,
      busqueda: destino.search,
      metodo: opciones.method ?? 'GET',
      cuerpo: opciones.body === undefined ? undefined : JSON.parse(opciones.body),
    };
    peticiones.push(peticion);
    return responder(peticion);
  };
  return peticiones;
}

/** Fila de GET /pantalla/ultimas-marcaciones tal como la manda la API (B1). */
const filaApi = (origen, id, cambios = {}) => ({
  id,
  fecha_hora: '2026-10-10T12:30:00',
  usuario_id: 3,
  nombre: 'Persona 3',
  categoria: 'Médico',
  comida_id: 2,
  comida: 'Almuerzo',
  resultado: 'aceptada',
  motivo: null,
  valido: true,
  dispositivo: origen === 'asistencia_manual' ? 'registro-manual' : 'simulador-navegador',
  origen,
  clave_evento: `${origen}:${id}`,
  ...cambios,
});

/** Fila ya adaptada (lo que usa la UI). */
const fila = (origen, id, cambios = {}) => ({
  id,
  origen,
  clave: claveDeEvento(origen, id),
  valido: true,
  titulo: 'Marcación válida',
  hora: '12:30:00',
  comida: 'Almuerzo',
  persona: { id: 3, nombre: 'Persona 3', categoria: 'Médico' },
  ...cambios,
});

const ANA = { id: 99, nombre: 'Ana Gomez', categoria: 'Bioquímica', legajo: 'B-99' };
const LUIS = { id: 7, nombre: 'Luis Perez', categoria: 'Planta', legajo: 'P-7' };

// -------------------------------------------------------------
// 1. Contrato de la lista y de la respuesta del POST
// -------------------------------------------------------------

test('la lista expone origen y clave; dos filas con el mismo id y distinto origen son eventos distintos', async () => {
  const peticiones = grabar(() => json([
    filaApi('asistencia_manual', 5, { dispositivo: 'lector-raro' }),
    filaApi('lectura_biometrica', 5, { dispositivo: 'registro-manual' }),
  ]));
  const lista = await obtenerUltimasMarcaciones({ limite: LIMITE_MARCACIONES_COCINA });
  assert.equal(peticiones[0].busqueda, '?limite=100');
  assert.deepEqual(lista.map(({ id, origen, clave }) => ({ id, origen, clave })), [
    { id: 5, origen: 'asistencia_manual', clave: 'asistencia_manual:5' },
    { id: 5, origen: 'lectura_biometrica', clave: 'lectura_biometrica:5' },
  ]);
  // El método no sale del texto del dispositivo.
  assert.equal(etiquetaDeOrigen(lista[0].origen), 'Registro manual');
  assert.equal(etiquetaDeOrigen(lista[1].origen), 'Lectura biométrica');

  for (const invalida of [
    { ...filaApi('lectura_biometrica', 6), origen: undefined },
    { ...filaApi('lectura_biometrica', 6), origen: 'otro' },
    { ...filaApi('lectura_biometrica', 6), clave_evento: 'lectura_biometrica:7' },
    { ...filaApi('lectura_biometrica', 6), clave_evento: 6 },
  ]) {
    grabar(() => json([invalida]));
    await assert.rejects(obtenerUltimasMarcaciones(), /sin origen válido/);
  }
});

test('la respuesta del POST lleva la clave de su fila: lectura si hay lectura, manual si no, null si no dejó fila', async () => {
  const base = { titulo: 't', detalle: 'd', usuario_id: 3, nombre: 'Persona 3', comida: 'Almuerzo', comida_id: 2 };
  const persona = { id: 3, nombre: 'Persona 3', categoria: 'Médico', legajo: 'L-3' };

  grabar(() => json({ ...base, valido: true, lectura_id: 41, asistencia_id: 90 }));
  let evento = await marcarAsistencia(3, { persona, metodo: 'biometrico' });
  assert.equal(evento.claveEvento, 'lectura_biometrica:41', 'una asistencia ligada a lectura es la lectura');
  assert.equal(evento.origen, 'lectura_biometrica');

  grabar(() => json({ ...base, valido: true, lectura_id: null, asistencia_id: 41 }));
  evento = await marcarAsistencia(3, { persona, metodo: 'manual' });
  assert.equal(evento.claveEvento, 'asistencia_manual:41');

  grabar(() => json({ ...base, valido: false, motivo: 'sin_derecho', lectura_id: null, asistencia_id: null }));
  evento = await marcarAsistencia(3, { persona, metodo: 'manual' });
  assert.equal(evento.claveEvento, null, 'un rechazo manual no deja fila en cocina');
  assert.equal(evento.origen, null);
});

test('registro manual: un solo POST con {usuario_id, metodo: manual}, sin momento, dispositivo ni operador', async () => {
  const peticiones = grabar(() => json({
    valido: true, titulo: 'Marcación válida', detalle: 'Ración habilitada', usuario_id: 99,
    nombre: 'Ana Gomez', lectura_id: null, asistencia_id: 12,
  }));
  const resultado = await autorizarMarcacionManual(99, { persona: ANA });
  assert.equal(resultado.valido, true);
  assert.deepEqual(peticiones, [{
    ruta: '/asistencias', busqueda: '', metodo: 'POST', cuerpo: { usuario_id: 99, metodo: 'manual' },
  }]);
  await assert.rejects(autorizarMarcacionManual(0), /Seleccione un comensal/);
  await assert.rejects(autorizarMarcacionManual('99'), /Seleccione un comensal/);
});

test('un fallo sin respuesta del servidor es incierto; un error HTTP no', async () => {
  globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
  const red = await autorizarMarcacionManual(99, { persona: ANA }).catch((e) => e);
  assert.equal(marcacionIncierta(red), true);
  assert.match(red.message, /Verifique el registro/);

  globalThis.fetch = async () => json({ valido: 'si' });
  const ilegible = await autorizarMarcacionManual(99, { persona: ANA }).catch((e) => e);
  assert.equal(marcacionIncierta(ilegible), true);

  globalThis.fetch = async () => json({ detail: 'Datos inválidos' }, 422);
  const http = await autorizarMarcacionManual(99, { persona: ANA }).catch((e) => e);
  assert.equal(marcacionIncierta(http), false);
});

// -------------------------------------------------------------
// 2. Registro manual en Supervisión
// -------------------------------------------------------------

test('permisos: solo jefa y sistemas registran a mano; la cocinera ni ve Supervisión', () => {
  assert.equal(puedeMarcarManual('jefa'), true);
  assert.equal(puedeMarcarManual('sistemas'), true);
  assert.equal(puedeMarcarManual('cocinera'), false);
  assert.equal(puedeVerSeccion('cocinera', 'supervision'), false);

  const props = { cargandoInicial: false, comidasIniciales: { comidas: [], rechazosSinComida: 0 } };
  const sinPermiso = renderToStaticMarkup(h(Supervision, props));
  assert.doesNotMatch(sinPermiso, /Registrar ración manual/);
});

test('registrar ración manual está disponible sin lecturas previas, con datos y aun con error de carga', () => {
  const vacio = renderToStaticMarkup(h(Supervision, {
    cargandoInicial: false,
    comidasIniciales: { comidas: [], rechazosSinComida: 0 },
    marcacionesIniciales: [],
    puedeRegistrarManual: true,
    personal: [ANA],
  }));
  assert.match(vacio, /No hay registros de supervisión para este día/);
  assert.match(vacio, /<span class="boton__texto">Registrar ración manual<\/span>/);

  const conDatos = renderToStaticMarkup(h(Supervision, {
    cargandoInicial: false,
    comidasIniciales: { comidas: [], rechazosSinComida: 0 },
    marcacionesIniciales: [fila('lectura_biometrica', 1)],
    puedeRegistrarManual: true,
  }));
  assert.match(conDatos, /Registrar ración manual/);

  const conError = renderToStaticMarkup(h(Supervision, {
    cargandoInicial: false, errorInicial: 'Sin conexión', puedeRegistrarManual: true,
  }));
  assert.match(conError, /Reintentar supervisión/);
  assert.match(conError, /Registrar ración manual/);
});

test('el panel distingue carga, padrón vacío, error y lista; confirma mostrando la identidad', () => {
  const abrir = (props) => renderToStaticMarkup(h(RegistroManual, { abiertoInicial: true, ...props }));

  assert.match(abrir({ cargandoPadron: true }), /Cargando padrón…/);
  assert.match(abrir({ errorPadron: 'HTTP 500' }), /role="alert"[^>]*>No se puede registrar: el padrón no se cargó\. HTTP 500/);
  assert.match(abrir({ personal: [] }), /El padrón no tiene comensales para elegir/);

  const lista = abrir({ personal: [ANA, LUIS] });
  assert.match(lista, /momento actual del servidor/);
  assert.match(lista, /aunque la tabla esté mostrando otra\s+comida/);
  assert.match(lista, /Ana Gomez — Bioquímica \(B-99\)/);
  assert.doesNotMatch(lista, /Confirmar registro/, 'sin comensal elegido no hay confirmación');

  const elegido = abrir({ personal: [ANA, LUIS], elegidoInicial: 99 });
  assert.match(elegido, /registro-manual__identidad"><strong>Ana Gomez<\/strong><span>Bioquímica · Legajo B-99<\/span>/);
  assert.match(elegido, /<span class="boton__texto">Confirmar registro<\/span>/);
  assert.doesNotMatch(elegido, /autoriza|excepci/i, 'no simula una autorización excepcional');

  assert.deepEqual(filtrarPadron([ANA, LUIS], 'p-7'), [LUIS]);
  assert.deepEqual(filtrarPadron([ANA, LUIS], '  ana '), [ANA]);
  assert.deepEqual(filtrarPadron([ANA, LUIS], ''), [ANA, LUIS]);
});

test('doble clic: un solo POST mientras el primero está en vuelo', async () => {
  let resolver;
  let llamadas = 0;
  let inmediato = false;
  const exito = { valido: true, titulo: 'Marcación válida', detalle: 'ok' };
  const registrar = crearRegistroManual({
    registrar: () => {
      llamadas += 1;
      return inmediato ? Promise.resolve(exito) : new Promise((r) => { resolver = r; });
    },
  });
  const primero = registrar(ANA);
  const segundo = await registrar(ANA);
  assert.equal(segundo, null);
  assert.equal(llamadas, 1);
  resolver(exito);
  await primero;
  inmediato = true;
  await registrar(ANA);
  assert.equal(llamadas, 2, 'terminado el primero, se puede volver a registrar');
  assert.equal(await registrar({ id: 0 }), null, 'sin comensal válido no hay POST');
  assert.equal(llamadas, 2);
});

test('aceptación, rechazo y red: solo valido=true anuncia éxito; nada se reenvía', async () => {
  const correr = async (registrarFn) => {
    const registro = { avisos: [], exitos: 0, refrescos: 0, llamadas: 0 };
    const registrar = crearRegistroManual({
      registrar: async (...args) => { registro.llamadas += 1; return registrarFn(...args); },
      alResultado: (aviso) => registro.avisos.push(aviso),
      alExito: () => { registro.exitos += 1; },
      refrescar: async () => { registro.refrescos += 1; },
    });
    await registrar(ANA);
    return registro;
  };

  const aceptado = await correr(async () => ({ valido: true, titulo: 'Marcación válida', detalle: 'Ración habilitada' }));
  assert.deepEqual(aceptado.avisos, [{ tipo: 'exito', titulo: 'Marcación válida', detalle: 'Ana Gomez: Ración habilitada' }]);
  assert.equal(aceptado.exitos, 1);
  assert.equal(aceptado.refrescos, 1, 'tras registrar se relee del servidor');

  const rechazado = await correr(async () => ({ valido: false, motivo: 'sin_derecho', titulo: 'Sin derecho', detalle: 'No le corresponde.' }));
  assert.equal(rechazado.avisos[0].tipo, 'rechazo');
  assert.match(rechazado.avisos[0].detalle, /No se registró ninguna ración/);
  assert.equal(rechazado.exitos, 0);
  assert.equal(rechazado.refrescos, 1);

  const ambiguo = await correr(async () => ({ valido: 'true', titulo: 'x', detalle: 'y' }));
  assert.equal(ambiguo.avisos[0].tipo, 'rechazo', 'solo el booleano true es éxito');

  const red = await correr(async () => { throw new Error('No se pudo conectar', { cause: new TypeError('x') }); });
  assert.equal(red.llamadas, 1, 'no se reenvía automáticamente');
  assert.equal(red.avisos[0].titulo, 'No se pudo confirmar el registro');
  assert.match(red.avisos[0].detalle, /Revise en la tabla si la ración\s+quedó registrada/);
  assert.equal(red.exitos, 0);

  assert.deepEqual(avisoDeRegistroManual({ valido: true }, ANA).tipo, 'exito');
  assert.equal(avisoDeFalloRegistro(new Error('x', { cause: new TypeError('y') })).tipo, 'error');
});

test('un fallo del refresco posterior no oculta que el POST tuvo éxito', async () => {
  // Extremo a extremo con fetch falso: el POST responde válido y el refresco cae.
  grabar(({ ruta }) => (ruta === '/asistencias'
    ? json({ valido: true, titulo: 'Marcación válida', detalle: 'Ración habilitada', usuario_id: 99, asistencia_id: 3 })
    : json({}, 500)));
  const recibidos = [];
  const registrar = crearRegistroManual({
    alResultado: (aviso) => recibidos.push(aviso),
    refrescar: () => obtenerUltimasMarcaciones({ limite: 100 }),
  });
  const aviso = await registrar(ANA);
  assert.equal(aviso.tipo, 'exito');
  assert.deepEqual(recibidos.map(({ tipo }) => tipo), ['exito']);

  // En pantalla conviven el éxito y el aviso de datos sin actualizar.
  const html = renderToStaticMarkup(h(Supervision, {
    cargandoInicial: false,
    comidasIniciales: { comidas: [], rechazosSinComida: 0 },
    marcacionesIniciales: [fila('lectura_biometrica', 1)],
    avisoAccionInicial: aviso,
    errorRefrescoInicial: 'HTTP 500',
  }));
  assert.match(html, /supervision__aviso-accion--exito/);
  assert.match(html, /No se pudo actualizar/);
  assert.match(html, /Se muestran los datos anteriores\. HTTP 500/);
});

test('la autorización de filas sigue: no_identificado activa, sin_derecho desactivada; filas por clave', () => {
  const html = renderToStaticMarkup(h(Supervision, {
    cargandoInicial: false,
    comidasIniciales: { comidas: [], rechazosSinComida: 0 },
    marcacionesIniciales: [
      fila('lectura_biometrica', 5, { valido: false, motivo: 'no_identificado' }),
      fila('asistencia_manual', 5),
      fila('lectura_biometrica', 6, { valido: false, motivo: 'sin_derecho' }),
    ],
    filaExpandidaInicial: 'lectura_biometrica:5',
    personal: [ANA],
    puedeRegistrarManual: true,
  }));
  // Mismo id 5 en dos orígenes: ambas filas, y solo la lectura se expande.
  assert.equal(html.match(/<td>Registro manual<\/td>/g).length, 1);
  assert.equal(html.match(/supervision__fila-autorizar/g).length, 1);
  assert.match(html, /id="autorizar-lectura_biometrica:5"/);
  assert.match(html, /<button[^>]*data-tooltip="Requiere excepción de jefatura \(pendiente\)"[^>]*disabled=""/);
});

test('un 403 al registrar sigue el manejo central de sesión', async () => {
  grabar(() => json({ detail: 'Sin permiso.', motivo: 'metodo_no_autorizado' }, 403));
  const recibidos = [];
  const registrar = crearRegistroManual({ alResultado: (aviso) => recibidos.push(aviso) });
  await registrar(ANA);
  assert.deepEqual(avisos, ['prohibido']);
  assert.equal(recibidos[0].titulo, 'No se registró la ración');
});

// -------------------------------------------------------------
// 3. Cocina: detección de novedades
// -------------------------------------------------------------

test('primera carga fija la referencia; luego solo la novedad más reciente, sin la propia', () => {
  const historicas = [fila('lectura_biometrica', 2), fila('lectura_biometrica', 1)];
  let paso = detectarNueva(null, historicas);
  assert.equal(paso.nueva, null, 'lo histórico no es un toque recién ocurrido');

  // Una marcación externa (manual de la jefa) en consultas consecutivas.
  const conManual = [fila('asistencia_manual', 2), ...historicas];
  paso = detectarNueva(paso.conocidas, conManual);
  assert.equal(paso.nueva.clave, 'asistencia_manual:2', 'mismo id 2 que una lectura, pero otro evento');

  // Varias a la vez: se presenta la más reciente y la lista las conserva.
  const varias = [fila('lectura_biometrica', 4), fila('lectura_biometrica', 3), ...conManual];
  paso = detectarNueva(paso.conocidas, varias);
  assert.equal(paso.nueva.clave, 'lectura_biometrica:4');
  assert.equal(paso.conocidas.size, varias.length);

  // La marcación que envió esta pantalla no se anuncia dos veces.
  const conPropia = [fila('lectura_biometrica', 5), ...varias];
  paso = detectarNueva(paso.conocidas, conPropia, new Set(['lectura_biometrica:5']));
  assert.equal(paso.nueva, null);

  // Sin cambios: nada nuevo.
  assert.equal(detectarNueva(paso.conocidas, conPropia).nueva, null);
});

test('deduplicación: la copia local cae cuando llega su fila; otra con el mismo id no la reemplaza', () => {
  const evento = {
    id: 9, claveEvento: 'lectura_biometrica:5', origen: 'lectura_biometrica', valido: true,
    titulo: 'Marcación válida', hora: '12:30:00', tiempo: 'Almuerzo', comida_id: 2,
    persona: { id: 3, nombre: 'Persona 3', categoria: 'Médico' },
  };
  assert.equal(filasConPropia(null, evento)[0].clave, 'local-9', 'mientras no llega, se ve la local');
  const conManual = filasConPropia([fila('asistencia_manual', 5)], evento);
  assert.deepEqual(conManual.map(({ clave }) => clave), ['local-9', 'asistencia_manual:5']);
  const conLectura = filasConPropia([fila('lectura_biometrica', 5), fila('asistencia_manual', 5)], evento);
  assert.deepEqual(conLectura.map(({ clave }) => clave), ['lectura_biometrica:5', 'asistencia_manual:5']);
  assert.deepEqual(filasConPropia([fila('lectura_biometrica', 1)], null).length, 1);

  const manual = eventoDeFila(fila('asistencia_manual', 5));
  assert.equal(manual.id, 'asistencia_manual:5');
  assert.equal(manual.titulo, 'Registro manual');
  assert.match(manual.detalle, /a mano/);
  assert.doesNotMatch(manual.detalle, /lector/i);
});

// -------------------------------------------------------------
// 4. Cocina: ciclo de 3 s
// -------------------------------------------------------------

function temporizadorFalso() {
  const pendientes = new Map();
  let siguiente = 1;
  return {
    pendientes,
    setTimeout(fn, ms) {
      const id = siguiente++;
      pendientes.set(id, { fn, ms });
      return id;
    },
    clearTimeout(id) {
      pendientes.delete(id);
    },
    disparar() {
      const [[id, { fn }]] = pendientes;
      pendientes.delete(id);
      fn();
    },
  };
}

function documentoFalso() {
  const oyentes = new Set();
  return {
    visibilityState: 'visible',
    oyentes,
    addEventListener: (tipo, fn) => { if (tipo === 'visibilitychange') oyentes.add(fn); },
    removeEventListener: (tipo, fn) => { if (tipo === 'visibilitychange') oyentes.delete(fn); },
    cambiar(estado) {
      this.visibilityState = estado;
      oyentes.forEach((fn) => fn());
    },
  };
}

const vaciar = async () => {
  for (let i = 0; i < 5; i += 1) await new Promise((r) => setImmediate(r));
};

function armarCiclo({ detectar = () => true } = {}) {
  const llamadas = [];
  const estados = [];
  const resultados = [];
  let enVuelo = 0;
  let maximo = 0;
  const temporizador = temporizadorFalso();
  const documento = documentoFalso();
  const control = programarCicloCocina({
    consultarMarcaciones: ({ signal }) => new Promise((resolver, rechazar) => {
      enVuelo += 1;
      maximo = Math.max(maximo, enVuelo);
      const fin = (fn) => (valor) => { enVuelo -= 1; fn(valor); };
      llamadas.push({ signal, resolver: fin(resolver), rechazar: fin(rechazar) });
    }),
    refrescarEstado: ({ origen }) => { estados.push(origen); },
    alActualizar: (resultado) => resultados.push(resultado),
    puedeDetectar: detectar,
    temporizador,
    documento,
  });
  return { control, llamadas, estados, resultados, temporizador, documento, maximo: () => maximo };
}

test('ciclo: el siguiente sale 3 s después de terminar, sin solapes ni temporizadores duplicados', async () => {
  const c = armarCiclo();
  await vaciar();
  assert.equal(c.llamadas.length, 1);
  assert.deepEqual(c.estados, ['inicial'], 'el estado del comedor viaja en el mismo ciclo');
  assert.equal(c.temporizador.pendientes.size, 0, 'nada programado con el ciclo en vuelo');

  // solicitar() durante el vuelo no abre otra petición: repite al terminar.
  c.control.solicitar();
  c.control.solicitar();
  assert.equal(c.llamadas.length, 1);
  c.llamadas[0].resolver([fila('lectura_biometrica', 1)]);
  await vaciar();
  assert.equal(c.llamadas.length, 2, 'una sola repetición');
  assert.equal(c.temporizador.pendientes.size, 0);
  assert.equal(c.resultados[0].nueva, null, 'la primera carga solo fija la referencia');

  c.llamadas[1].resolver([fila('asistencia_manual', 1), fila('lectura_biometrica', 1)]);
  await vaciar();
  assert.equal(c.resultados[1].nueva.clave, 'asistencia_manual:1', 'marcación externa en consultas consecutivas');
  assert.equal(c.temporizador.pendientes.size, 1);
  assert.equal([...c.temporizador.pendientes.values()][0].ms, MS_CICLO_COCINA);
  assert.equal(MS_CICLO_COCINA, 3000);

  c.temporizador.disparar();
  await vaciar();
  assert.equal(c.llamadas.length, 3);
  assert.deepEqual(c.estados, ['inicial', 'solicitado', 'ciclo']);
  assert.equal(c.maximo(), 1, 'nunca dos consultas a la vez');
  c.control.cancelar();
});

test('ciclo: un error conserva la lista, avisa y no reproduce alertas al reconectar', async () => {
  const c = armarCiclo();
  c.llamadas[0].resolver([fila('lectura_biometrica', 1)]);
  await vaciar();
  c.temporizador.disparar();
  c.llamadas[1].rechazar(new Error('No se pudieron cargar las últimas marcaciones. HTTP 500'));
  await vaciar();
  assert.deepEqual(c.resultados[1], { error: 'No se pudieron cargar las últimas marcaciones. HTTP 500' });
  assert.equal(c.resultados[1].filas, undefined, 'sin filas: la pantalla conserva las anteriores');

  // Mientras estuvo caído llegaron dos: se actualiza sin anunciarlas.
  c.temporizador.disparar();
  c.llamadas[2].resolver([fila('lectura_biometrica', 3), fila('lectura_biometrica', 2), fila('lectura_biometrica', 1)]);
  await vaciar();
  assert.equal(c.resultados[2].nueva, null);
  assert.equal(c.resultados[2].filas.length, 3);
  c.control.cancelar();
});

test('ciclo: pausa con la pestaña oculta, revalida al volver sin cola y cancela al desmontar', async () => {
  const c = armarCiclo();
  c.llamadas[0].resolver([fila('lectura_biometrica', 1)]);
  await vaciar();
  assert.equal(c.temporizador.pendientes.size, 1);

  c.documento.cambiar('hidden');
  assert.equal(c.temporizador.pendientes.size, 0, 'oculta: nada programado');
  c.documento.cambiar('visible');
  assert.equal(c.llamadas.length, 2);
  await vaciar();
  assert.equal(c.estados.at(-1), 'regreso');

  // Volver otra vez con el ciclo en vuelo descarta el anterior.
  c.documento.cambiar('hidden');
  c.documento.cambiar('visible');
  assert.equal(c.llamadas.length, 3);
  assert.equal(c.llamadas[1].signal.aborted, true);
  c.llamadas[1].resolver([fila('lectura_biometrica', 9)]);
  await vaciar();
  assert.equal(c.resultados.length, 1, 'el ciclo descartado no actualiza');

  c.llamadas[2].resolver([fila('lectura_biometrica', 2), fila('lectura_biometrica', 1)]);
  await vaciar();
  assert.equal(c.resultados[1].nueva, null, 'lo ocurrido con la pestaña oculta no se anuncia');

  c.control.cancelar();
  assert.equal(c.temporizador.pendientes.size, 0);
  assert.equal(c.documento.oyentes.size, 0);
  c.control.solicitar();
  assert.equal(c.llamadas.length, 3, 'cancelado no consulta más');
});

test('ciclo: durante una marcación local no se anuncia nada; después, la externa sí y la propia no', async () => {
  let leyendo = false;
  const c = armarCiclo({ detectar: () => !leyendo });
  c.llamadas[0].resolver([fila('lectura_biometrica', 1)]);
  await vaciar();

  leyendo = true;
  c.temporizador.disparar();
  c.llamadas[1].resolver([fila('lectura_biometrica', 2), fila('lectura_biometrica', 1)]);
  await vaciar();
  assert.equal(c.resultados[1].nueva, null);
  assert.equal(c.resultados[1].filas.length, 2, 'la lista sí se actualiza');

  leyendo = false;
  c.control.registrarPropia('lectura_biometrica:2');
  c.temporizador.disparar();
  c.llamadas[2].resolver([fila('asistencia_manual', 7), fila('lectura_biometrica', 2), fila('lectura_biometrica', 1)]);
  await vaciar();
  assert.equal(c.resultados[2].nueva.clave, 'asistencia_manual:7');

  // Un cambio de reloj reinicia la referencia: lo que llegue no se anuncia.
  c.control.reiniciarReferencia();
  c.temporizador.disparar();
  c.llamadas[3].resolver([fila('lectura_biometrica', 50)]);
  await vaciar();
  assert.equal(c.resultados[3].nueva, null);
  c.control.cancelar();
});
