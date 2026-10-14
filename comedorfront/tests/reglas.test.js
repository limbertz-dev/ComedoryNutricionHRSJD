/*
 * Root simplificado: menú de tres secciones, Reglas del sistema (horario de
 * cada comida con efecto inmediato) y Cuentas (jefa, lectura).
 * Permisos y menú, adaptadores /reglas/horarios con fetch controlado,
 * lógica de la pantalla con respuestas sintéticas y renders con
 * react-dom/server. Sin API real, MySQL ni servidores.
 */
import test, { afterEach, beforeEach, mock } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import * as api from '../src/api.js';
import {
  ErrorGuardadoHorario,
  guardarHorario,
  obtenerCuentasLectura,
  obtenerHistorialHorario,
  obtenerHorariosVigentes,
} from '../src/api.js';
import { SECCIONES, buscarSeccion, leerSeccionGuardada, seccionesDeRol } from '../src/navegacion.js';
import {
  puedeMarcarManual,
  puedeVerSeccion,
  resolverSeccionGuardada,
  seccionesPermitidas,
  usaDatosDelComedor,
} from '../src/permisos.js';
import { borrarTokens, escucharSesion } from '../src/sesion.js';
import {
  cargarComidas,
  cruzaMedianoche,
  ejecutarGuardado,
  estadoInicialReglas,
  formatoHora,
  guardarComida,
  horasConSegundos,
  motivoSinGuardar,
  normalizarHora,
  recargarComidas,
  reductorReglas,
  resolverBase,
  textoMomento,
} from '../src/reglasHorarios.js';
import { Panel } from '../src/App.jsx';
import { ProveedorSesion } from '../src/hooks/useSesion.js';
import ReglasSistema, { TarjetaComida, VistaReglas } from '../src/components/secciones/ReglasSistema.jsx';
import CuentasLectura from '../src/components/secciones/CuentasLectura.jsx';

/* sessionStorage mínimo: en Node no existe y la sesión guarda los tokens ahí. */
const almacen = new Map();
globalThis.sessionStorage ??= {
  getItem: (clave) => (almacen.has(clave) ? almacen.get(clave) : null),
  setItem: (clave, valor) => almacen.set(clave, String(valor)),
  removeItem: (clave) => almacen.delete(clave),
};

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
  borrarTokens();
  mock.timers.reset();
});

const json = (datos, status = 200) => new Response(JSON.stringify(datos), { status });

/** Respuesta sintética de GET /reglas/horarios (contrato HorarioRegla). */
const horarioApi = (cambios = {}) => ({
  horario_id: 5,
  comida_id: 2,
  comida: 'Almuerzo',
  hora_inicio: '11:30:00',
  hora_fin: '15:00:00',
  cruza_medianoche: false,
  vigente_desde: '2026-10-14T08:30:15.123456',
  vigente_hasta: null,
  motivo: null,
  creada_por: 'root',
  creada: '2026-10-14T08:30:15.500000',
  estado: 'vigente',
  ...cambios,
});

/** El mismo horario ya adaptado a camelCase. */
const horario = (cambios = {}) => ({
  horarioId: 5,
  comidaId: 2,
  comida: 'Almuerzo',
  horaInicio: '11:30:00',
  horaFin: '15:00:00',
  cruzaMedianoche: false,
  vigenteDesde: '2026-10-14T08:30:15.123456',
  vigenteHasta: null,
  motivo: null,
  creadaPor: 'root',
  creada: '2026-10-14T08:30:15.500000',
  estado: 'vigente',
  ...cambios,
});

const cuentaApi = (cambios = {}) => ({
  id: 7,
  username: 'maria.cocina',
  nombre: 'María Cocina',
  rol: 'cocinera',
  activo: true,
  debe_cambiar: false,
  ultimo_ingreso: '2026-09-28T07:55:00',
  ...cambios,
});

/** Tarjeta ya resuelta, como la entrega cargarComidas. */
const comida = (cambios = {}) => {
  const h0 = cambios.horario ?? horario();
  return {
    comidaId: h0.comidaId,
    horario: h0,
    listado: h0,
    base: { tipo: 'abierta', horario: h0 },
    ...cambios,
  };
};

const guardaBorrador = { inicio: '12:00', fin: '15:30' };
/* El botón, no la frase «Guardar cambios» de la nota explicativa. */
const BOTON_GUARDAR = /<span class="boton__texto">(?:<span[^>]*><\/span>)?Guardar cambios<\/span>/g;

// -------------------------------------------------------------
// 1. Menú de root: tres secciones; el resto de los roles, intacto
// -------------------------------------------------------------
test('sistemas ve solo Reglas, Administración y Lector biométrico, en ese orden', () => {
  assert.deepEqual(seccionesPermitidas('sistemas'), ['reglas', 'admin', 'monitoreo']);
  assert.deepEqual(seccionesDeRol('sistemas').map(({ id }) => id), ['reglas', 'admin', 'monitoreo']);
  assert.deepEqual(seccionesDeRol('sistemas').map(({ etiqueta }) => etiqueta), [
    'Reglas del sistema', 'Administración', 'Lector biométrico',
  ]);
  for (const id of ['supervision', 'dashboard', 'historial', 'reportes', 'vivo', 'cuentas']) {
    assert.equal(puedeVerSeccion('sistemas', id), false, `sistemas no ve ${id}`);
  }
  assert.equal(puedeMarcarManual('sistemas'), false, 'root no registra a mano desde la interfaz');
  assert.equal(usaDatosDelComedor('sistemas'), false);
});

test('las pantallas quitadas a root siguen existiendo para la jefa; la cocinera no cambia', () => {
  assert.deepEqual(seccionesPermitidas('jefa'), ['supervision', 'dashboard', 'historial', 'reportes', 'cuentas']);
  assert.equal(puedeMarcarManual('jefa'), true);
  assert.deepEqual(seccionesPermitidas('cocinera'), ['vivo']);
  assert.equal(puedeMarcarManual('cocinera'), false);
  for (const id of ['supervision', 'dashboard', 'historial', 'reportes', 'vivo', 'cuentas']) {
    assert.ok(SECCIONES.some((seccion) => seccion.id === id), `la sección ${id} no se elimina`);
  }
  assert.equal(usaDatosDelComedor('jefa'), true);
  assert.equal(usaDatosDelComedor('cocinera'), true);
  assert.equal(usaDatosDelComedor('desconocido'), false);

  const menuJefa = seccionesDeRol('jefa').map(({ id }) => id);
  assert.equal(menuJefa[menuJefa.length - 1], 'cuentas');
  assert.ok(!menuJefa.includes('reglas') && !menuJefa.includes('admin') && !menuJefa.includes('monitoreo'));
});

test('una sección guardada que root ya no puede abrir vuelve a Reglas', () => {
  for (const guardada of ['supervision', 'dashboard', 'historial', 'reportes', 'vivo', 'cuentas', 'basura', null, undefined]) {
    assert.equal(resolverSeccionGuardada('sistemas', guardada), 'reglas', `guardada ${guardada}`);
  }
  assert.equal(resolverSeccionGuardada('sistemas', 'admin'), 'admin');
  assert.equal(resolverSeccionGuardada('sistemas', 'monitoreo'), 'monitoreo');

  const localOriginal = globalThis.localStorage;
  try {
    globalThis.localStorage = { getItem: () => 'supervision', setItem: () => {}, removeItem: () => {} };
    assert.equal(leerSeccionGuardada('sistemas'), 'reglas');
    assert.equal(leerSeccionGuardada('jefa'), 'supervision');
    globalThis.localStorage = { getItem: () => { throw new Error('bloqueado'); }, setItem: () => {}, removeItem: () => {} };
    assert.equal(leerSeccionGuardada('sistemas'), 'reglas');
  } finally {
    if (localOriginal === undefined) delete globalThis.localStorage;
    else globalThis.localStorage = localOriginal;
  }
});

test('etiquetas y títulos: Reglas del sistema y Lector biométrico', () => {
  const reglas = buscarSeccion('reglas');
  assert.equal(reglas.etiqueta, 'Reglas del sistema');
  assert.equal(reglas.titulo, 'Reglas del sistema');
  assert.doesNotMatch(reglas.descripcion, /derecho/i);
  assert.equal(typeof reglas.Icono, 'function');

  const lector = buscarSeccion('monitoreo');
  assert.equal(lector.id, 'monitoreo', 'el id interno no cambia');
  assert.equal(lector.etiqueta, 'Lector biométrico');
  assert.equal(lector.titulo, 'Lector biométrico');
  assert.equal(typeof lector.Icono, 'function');

  const cuentas = buscarSeccion('cuentas');
  assert.equal(cuentas.etiqueta, 'Cuentas');
});

// -------------------------------------------------------------
// 2. obtenerCuentasLectura (vista de la jefa, sin cambios)
// -------------------------------------------------------------
test('obtenerCuentasLectura adapta snake_case y rechaza formas inválidas', async () => {
  globalThis.fetch = async (url) => {
    assert.equal(new URL(url).pathname, '/cuentas');
    return json([cuentaApi(), cuentaApi({ id: 8, username: 'jefa.nutri', nombre: null, rol: 'jefa', ultimo_ingreso: null })]);
  };
  const cuentas = await obtenerCuentasLectura();
  assert.deepEqual(cuentas[0], {
    id: 7,
    username: 'maria.cocina',
    nombre: 'María Cocina',
    rol: 'cocinera',
    activo: true,
    debeCambiar: false,
    ultimoIngreso: '2026-09-28T07:55:00',
  });
  assert.equal(cuentas[1].nombre, null);
  assert.equal(cuentas[1].ultimoIngreso, null);

  globalThis.fetch = async () => json({ total: 1 });
  await assert.rejects(obtenerCuentasLectura(), /lista de cuentas inválida/);
  globalThis.fetch = async () => json([cuentaApi({ rol: 'superadmin' })]);
  await assert.rejects(obtenerCuentasLectura(), /cuenta inválida/);
});

// -------------------------------------------------------------
// 3. GET /reglas/horarios y /historial: contrato HorarioRegla
// -------------------------------------------------------------
test('obtenerHorariosVigentes pide /reglas/horarios sin query y adapta HorarioRegla', async () => {
  const pedidas = [];
  globalThis.fetch = async (url, opciones) => {
    pedidas.push({ url: new URL(url), metodo: opciones.method });
    return json([
      horarioApi(),
      horarioApi({
        horario_id: 6, comida_id: 3, comida: 'Cena', hora_inicio: '19:00:00', hora_fin: '06:00:00',
        cruza_medianoche: true, motivo: 'Dato anterior', creada_por: null, estado: 'anterior',
        vigente_hasta: '2026-10-14T09:00:00.000001',
      }),
      horarioApi({ horario_id: 7, comida_id: 4, comida: null, estado: 'inactiva' }),
    ]);
  };
  const horarios = await obtenerHorariosVigentes();
  assert.equal(pedidas[0].url.pathname, '/reglas/horarios');
  assert.equal(pedidas[0].url.search, '');
  assert.equal(pedidas[0].metodo, undefined, 'es un GET');
  assert.deepEqual(horarios[0], horario());
  assert.equal(horarios[1].cruzaMedianoche, true);
  assert.equal(horarios[1].estado, 'anterior');
  assert.equal(horarios[1].vigenteHasta, '2026-10-14T09:00:00.000001');
  assert.equal(horarios[1].creadaPor, null);
  assert.equal(horarios[2].comida, null, 'comida nula se conserva');
  assert.equal(horarios[2].estado, 'inactiva');
  /* Los datetimes quedan como texto del servidor: sin zona ni conversión. */
  assert.equal(horarios[0].vigenteDesde, '2026-10-14T08:30:15.123456');

  /* La fecha como query ya no existe: aunque se la pasen, no viaja. */
  await obtenerHorariosVigentes({ fecha: '2026-10-01' });
  assert.equal(pedidas[1].url.search, '');
});

test('el adaptador rechaza horarios con forma inválida, zonas y estados desconocidos', async () => {
  globalThis.fetch = async () => json({ total: 2 });
  await assert.rejects(obtenerHorariosVigentes(), /horarios inválidos/);
  const invalidos = [
    { hora_inicio: 'once' },
    { hora_inicio: '25:00:00' },
    { hora_fin: '11:61:00' },
    { vigente_desde: '2026-10-14T08:30:15Z' },
    { vigente_desde: '2026-10-14T08:30:15-04:00' },
    { vigente_desde: '2026-10-14' },
    { vigente_desde: '2026-10-14T08:30:15.1234567' },
    { vigente_hasta: '2026-02-31T08:00:00' },
    { creada: null },
    { estado: 'programada' },
    { cruza_medianoche: 'no' },
    { horario_id: 0 },
    { comida: '' },
    { motivo: 3 },
  ];
  for (const cambio of invalidos) {
    globalThis.fetch = async () => json([horarioApi(cambio)]);
    await assert.rejects(obtenerHorariosVigentes(), /horario inválido/, JSON.stringify(cambio));
  }
});

test('obtenerHistorialHorario pide por comida y traduce comida_inexistente', async () => {
  globalThis.fetch = async (url) => {
    const pedida = new URL(url);
    assert.equal(pedida.pathname, '/reglas/horarios/historial');
    assert.equal(pedida.searchParams.get('comida_id'), '2');
    return json([horarioApi(), horarioApi({ horario_id: 4, estado: 'anterior', vigente_hasta: '2026-10-14T08:30:15.123456' })]);
  };
  const versiones = await obtenerHistorialHorario(2);
  assert.equal(versiones.length, 2);
  assert.equal(versiones[1].estado, 'anterior');

  await assert.rejects(obtenerHistorialHorario(0), /Comida inválida/);
  globalThis.fetch = async () => json({ detail: 'x', motivo: 'comida_inexistente' }, 404);
  await assert.rejects(obtenerHistorialHorario(2), /ya no existe/);
});

// -------------------------------------------------------------
// 4. POST /reglas/horarios: contrato exacto y errores
// -------------------------------------------------------------
test('guardarHorario envía exactamente las cuatro claves y adapta la 201', async () => {
  const pedidos = [];
  globalThis.fetch = async (url, opciones) => {
    pedidos.push({ ruta: new URL(url), metodo: opciones.method, cuerpo: opciones.body, cabeceras: opciones.headers });
    return json(horarioApi({ horario_id: 11, hora_inicio: '12:00:00', hora_fin: '15:30:00' }), 201);
  };
  const creado = await guardarHorario({ comidaId: 2, horaInicio: '12:00', horaFin: '15:30', baseHorarioId: 5 });
  assert.equal(pedidos[0].ruta.pathname, '/reglas/horarios');
  assert.equal(pedidos[0].ruta.search, '');
  assert.equal(pedidos[0].metodo, 'POST');
  assert.equal(pedidos[0].cabeceras['Content-Type'], 'application/json');
  assert.deepEqual(JSON.parse(pedidos[0].cuerpo), {
    comida_id: 2, hora_inicio: '12:00:00', hora_fin: '15:30:00', base_horario_id: 5,
  });
  assert.deepEqual(Object.keys(JSON.parse(pedidos[0].cuerpo)), ['comida_id', 'hora_inicio', 'hora_fin', 'base_horario_id']);
  assert.doesNotMatch(pedidos[0].cuerpo, /vigente_desde|motivo|fecha/);
  assert.equal(creado.horarioId, 11);
  assert.equal(creado.horaInicio, '12:00:00');

  /* null solo cuando se sabe que no hay versión abierta; una hora con segundos viaja igual. */
  await guardarHorario({ comidaId: 2, horaInicio: '12:00:30', horaFin: '15:30:00', baseHorarioId: null });
  assert.deepEqual(JSON.parse(pedidos[1].cuerpo), {
    comida_id: 2, hora_inicio: '12:00:30', hora_fin: '15:30:00', base_horario_id: null,
  });
});

test('guardarHorario valida antes de enviar y nunca manda una base desconocida', async () => {
  let llamadas = 0;
  globalThis.fetch = async () => {
    llamadas += 1;
    return json(horarioApi(), 201);
  };
  const base = { comidaId: 2, horaInicio: '11:30', horaFin: '15:00', baseHorarioId: 5 };
  for (const cambio of [
    { comidaId: 0 },
    { comidaId: '2' },
    { horaInicio: 'tres' },
    { horaFin: '' },
    { horaFin: '24:00' },
    { baseHorarioId: undefined },
    { baseHorarioId: 0 },
    { baseHorarioId: '5' },
    { baseHorarioId: -1 },
  ]) {
    const error = await guardarHorario({ ...base, ...cambio }).catch((e) => e);
    assert.ok(error instanceof ErrorGuardadoHorario, JSON.stringify(cambio));
    assert.equal(error.incierto, false, 'un rechazo local no es incierto');
  }
  assert.equal(llamadas, 0, 'nada de eso sale al servidor');
});

test('los 409, 422 y 404 con motivo se traducen y no son inciertos', async () => {
  const casos = [
    [409, 'version_desactualizada', /cambió desde que lo abrió/, true],
    [409, 'sin_cambios', /no hay nada que cambiar/, false],
    [409, 'solapa_con_otra_comida', /se superpone con la de otra comida/, false],
    [409, 'instante_no_posterior', /no es posterior a la última versión/, false],
    [409, 'cambio_en_curso', /otro cambio de horarios en curso/, false],
    [409, 'versiones_abiertas_multiples', /más de una versión abierta/, true],
    [422, 'horario_invalido', /no es válido/, false],
    [404, 'comida_inexistente', /ya no existe/, true],
  ];
  for (const [status, motivo, esperado, recargar] of casos) {
    let llamadas = 0;
    globalThis.fetch = async () => {
      llamadas += 1;
      return json({ detail: 'texto del servidor', motivo }, status);
    };
    const error = await guardarHorario({ comidaId: 2, horaInicio: '12:00', horaFin: '15:00', baseHorarioId: 5 }).catch((e) => e);
    assert.ok(error instanceof ErrorGuardadoHorario, motivo);
    assert.match(error.message, esperado, motivo);
    assert.equal(error.motivo, motivo);
    assert.equal(error.status, status);
    assert.equal(error.incierto, false, `${motivo} es un rechazo, no un resultado incierto`);
    assert.equal(error.recargar, recargar, `${motivo}: recargar`);
    assert.equal(llamadas, 1, 'sin reintentos automáticos');
  }
});

test('un 422 de validación con detail en lista no rompe el mensaje', async () => {
  globalThis.fetch = async () => json({ detail: [{ loc: ['body', 'hora_inicio'], msg: 'Field required', type: 'missing' }] }, 422);
  const error = await guardarHorario({ comidaId: 2, horaInicio: '12:00', horaFin: '15:00', baseHorarioId: 5 }).catch((e) => e);
  assert.equal(error.status, 422);
  assert.equal(error.incierto, false);
  assert.match(error.message, /no aceptó los datos enviados/);
  assert.doesNotMatch(error.message, /\[object|Field required/);
});

test('5xx, red y respuesta ilegible son resultado incierto: no dicen que no se guardó', async () => {
  let llamadas = 0;
  const intento = () => guardarHorario({ comidaId: 2, horaInicio: '12:00', horaFin: '15:00', baseHorarioId: 5 }).catch((e) => e);
  const verificar = (error, esperado) => {
    assert.ok(error instanceof ErrorGuardadoHorario);
    assert.equal(error.incierto, true);
    assert.equal(error.recargar, true);
    assert.match(error.message, esperado);
    assert.match(error.message, /No sabemos si el cambio se guardó/);
    assert.match(error.message, /Recargue los horarios y compruebe/);
    assert.doesNotMatch(error.message, /no se (guardó|aplicó)\.|no quedó guardado/i);
  };

  globalThis.fetch = async () => { llamadas += 1; return new Response('Internal Server Error', { status: 500 }); };
  verificar(await intento(), /HTTP 500/);
  globalThis.fetch = async () => { llamadas += 1; return json({ detail: 'x', motivo: 'cerrojo_ausente' }, 500); };
  const cerrojo = await intento();
  verificar(cerrojo, /falta preparar el bloqueo de horarios/);
  assert.equal(cerrojo.motivo, 'cerrojo_ausente');
  globalThis.fetch = async () => { llamadas += 1; return json({ detail: 'x' }, 503); };
  verificar(await intento(), /HTTP 503/);
  globalThis.fetch = async () => { llamadas += 1; throw new TypeError('fetch failed'); };
  verificar(await intento(), /No se pudo conectar con la API/);
  globalThis.fetch = async () => { llamadas += 1; return new Response('no es json', { status: 201 }); };
  verificar(await intento(), /respuesta inválida/);
  globalThis.fetch = async () => { llamadas += 1; return json({ horario_id: 1 }, 201); };
  verificar(await intento(), /la respuesta no se pudo interpretar/);
  assert.equal(llamadas, 6, 'un intento por caso: nunca se reintenta solo');
});

test('el tiempo agotado también es incierto', async () => {
  mock.timers.enable({ apis: ['setTimeout'] });
  globalThis.fetch = (_url, opciones) => new Promise((_resolver, rechazar) => {
    opciones.signal.addEventListener('abort', () => rechazar(new DOMException('abortado', 'AbortError')));
  });
  const pendiente = guardarHorario({ comidaId: 2, horaInicio: '12:00', horaFin: '15:00', baseHorarioId: 5 }).catch((e) => e);
  mock.timers.tick(15000);
  const error = await pendiente;
  assert.equal(error.incierto, true);
  assert.match(error.message, /tardó demasiado/);
  assert.match(error.message, /No sabemos si el cambio se guardó/);
});

test('401, 403 y cambio de contraseña conservan el manejo central de la sesión', async () => {
  const pedido = () => guardarHorario({ comidaId: 2, horaInicio: '12:00', horaFin: '15:00', baseHorarioId: 5 }).catch((e) => e);

  globalThis.fetch = async () => json({ detail: 'Sesión inválida.', motivo: 'token_invalido' }, 401);
  let error = await pedido();
  assert.equal(error.status, 401);
  assert.equal(error.incierto, false);
  assert.deepEqual(avisos, ['expirada']);

  avisos.length = 0;
  globalThis.fetch = async () => json({ detail: 'Rol sin permiso.', motivo: 'rol_insuficiente' }, 403);
  error = await pedido();
  assert.equal(error.status, 403);
  assert.deepEqual(avisos, ['prohibido']);

  avisos.length = 0;
  globalThis.fetch = async () => json({ detail: 'Cambie su clave.', motivo: 'cambio_password_pendiente' }, 403);
  error = await pedido();
  assert.deepEqual(avisos, ['cambio_requerido']);
});

// -------------------------------------------------------------
// 5. Lógica de la pantalla: base, guardado, incertidumbre y recarga
// -------------------------------------------------------------
test('normalizarHora, formatoHora y cruce de medianoche', () => {
  assert.equal(normalizarHora('11:30'), '11:30:00');
  assert.equal(normalizarHora('11:30:15'), '11:30:15');
  assert.equal(normalizarHora('24:00'), null);
  assert.equal(normalizarHora(''), null);
  assert.equal(formatoHora('11:30:00'), '11:30');
  assert.equal(formatoHora('11:30:15'), '11:30:15');
  assert.equal(horasConSegundos('11:30:00', '15:00'), false);
  assert.equal(horasConSegundos('11:30:00', '15:00:20'), true);
  assert.equal(cruzaMedianoche('19:00', '06:00'), true);
  assert.equal(cruzaMedianoche('11:30', '15:00'), false);
  assert.equal(cruzaMedianoche('11:30', '11:30'), false);
  assert.equal(cruzaMedianoche('', '06:00'), false);
  assert.equal(textoMomento('2026-10-14T08:30:15.123456'), '14/10/2026 08:30');
  assert.equal(textoMomento('2026-10-14 08:30:15'), '14/10/2026 08:30');
  assert.equal(textoMomento(null), '—');
});

test('la base de una fila vigente no consulta el historial', async () => {
  let consultas = 0;
  const base = await resolverBase(horario(), { historial: async () => { consultas += 1; return []; } });
  assert.deepEqual(base, { tipo: 'abierta', horario: horario() });
  assert.equal(consultas, 0);
});

test('con una fila anterior (reloj atrasado) se busca la versión abierta en el historial', async () => {
  const anterior = horario({ horarioId: 4, estado: 'anterior', vigenteHasta: '2026-10-14T08:30:15.123456' });
  const abierta = horario({ horarioId: 9, vigenteDesde: '2026-10-14T10:00:00' });
  const pedidas = [];
  const historial = async (comidaId) => { pedidas.push(comidaId); return [abierta, anterior]; };

  const base = await resolverBase(anterior, { historial });
  assert.deepEqual(pedidas, [2]);
  assert.deepEqual(base, { tipo: 'abierta', horario: abierta });

  assert.deepEqual(await resolverBase(anterior, { historial: async () => [anterior] }), { tipo: 'ninguna' });
  /* Una fila inactiva nunca cuenta como abierta. */
  const inactiva = horario({ horarioId: 3, estado: 'inactiva' });
  assert.deepEqual(await resolverBase(anterior, { historial: async () => [anterior, inactiva] }), { tipo: 'ninguna' });
  assert.deepEqual(
    await resolverBase(anterior, { historial: async () => [abierta, horario({ horarioId: 10 })] }),
    { tipo: 'multiple' },
  );
});

test('si falla el historial la base queda en error: nunca se convierte en null', async () => {
  const anterior = horario({ horarioId: 4, estado: 'anterior', vigenteHasta: '2026-10-14T08:30:15.123456' });
  const base = await resolverBase(anterior, { historial: async () => { throw new Error('No se pudo conectar con la API.'); } });
  assert.equal(base.tipo, 'error');
  assert.match(base.mensaje, /No se pudo conectar/);

  let envios = 0;
  const resultado = await ejecutarGuardado({
    comida: { ...comida({ horario: anterior }), base },
    borrador: guardaBorrador,
    guardar: async () => { envios += 1; return horario(); },
  });
  assert.equal(resultado.tipo, 'sin-base');
  assert.equal(envios, 0, 'sin base comprobada no se envía nada');
});

test('cargarComidas: una fila por comida, orden del servidor, y lista vacía sin inventar comidas', async () => {
  const filas = [
    horario({ horarioId: 1, comidaId: 1, comida: 'Desayuno', horaInicio: '06:30:00', horaFin: '08:00:00' }),
    horario({ horarioId: 8, comidaId: 2, estado: 'anterior', vigenteHasta: '2026-10-14T09:00:00' }),
  ];
  const consultadas = [];
  const comidas = await cargarComidas({
    listar: async () => filas,
    historial: async (id) => { consultadas.push(id); return [horario({ horarioId: 12, comidaId: id })]; },
  });
  assert.deepEqual(comidas.map(({ comidaId }) => comidaId), [1, 2]);
  assert.deepEqual(consultadas, [2], 'solo la fila que no es la versión abierta consulta el historial');
  assert.equal(comidas[0].base.horario.horarioId, 1);
  assert.equal(comidas[1].base.horario.horarioId, 12);
  assert.equal(comidas[1].horario.horarioId, 12, 'se edita la versión abierta');
  assert.equal(comidas[1].listado.horarioId, 8);

  let llamadas = 0;
  const vacio = await cargarComidas({ listar: async () => [], historial: async () => { llamadas += 1; return []; } });
  assert.deepEqual(vacio, []);
  assert.equal(llamadas, 0);
});

test('ejecutarGuardado manda la base abierta, null solo si se comprobó que no hay, y no envía con base dudosa', async () => {
  const enviados = [];
  const guardar = async (datos) => { enviados.push(datos); return horario({ horarioId: 20 }); };

  await ejecutarGuardado({ comida: comida(), borrador: guardaBorrador, guardar });
  assert.deepEqual(enviados[0], { comidaId: 2, horaInicio: '12:00', horaFin: '15:30', baseHorarioId: 5 });

  await ejecutarGuardado({ comida: { ...comida(), base: { tipo: 'ninguna' } }, borrador: guardaBorrador, guardar });
  assert.equal(enviados[1].baseHorarioId, null);

  for (const tipo of ['error', 'multiple']) {
    const resultado = await ejecutarGuardado({ comida: { ...comida(), base: { tipo } }, borrador: guardaBorrador, guardar });
    assert.equal(resultado.tipo, 'sin-base');
  }
  assert.equal(enviados.length, 2);
});

test('motivoSinGuardar: el orden de los motivos que bloquean el botón', () => {
  const estado = estadoInicialReglas();
  const c = comida();
  assert.equal(motivoSinGuardar(estado, c, guardaBorrador), null);
  assert.equal(motivoSinGuardar(estado, c, { inicio: '11:30', fin: '15:00' }), 'sin-cambios');
  assert.equal(motivoSinGuardar(estado, c, { inicio: '11:30:00', fin: '15:00' }), 'sin-cambios');
  assert.equal(motivoSinGuardar(estado, c, { inicio: '12:00', fin: '12:00' }), 'iguales');
  assert.equal(motivoSinGuardar(estado, c, { inicio: '', fin: '12:00' }), 'incompleto');
  assert.equal(motivoSinGuardar({ ...estado, guardando: 2 }, c, guardaBorrador), 'guardando');
  assert.equal(motivoSinGuardar({ ...estado, guardando: 9 }, c, guardaBorrador), 'otro-envio');
  assert.equal(motivoSinGuardar({ ...estado, actualizando: true }, c, guardaBorrador), 'actualizando');
  assert.equal(motivoSinGuardar({ ...estado, incierto: true }, c, guardaBorrador), 'incierto');
  assert.equal(motivoSinGuardar({ ...estado, bloqueadas: [2] }, c, guardaBorrador), 'recargar');
  assert.equal(motivoSinGuardar(estado, { ...c, base: { tipo: 'error', mensaje: 'x' } }, guardaBorrador), 'sin-base');
  assert.equal(motivoSinGuardar(estado, { ...c, base: { tipo: 'multiple' } }, guardaBorrador), 'multiple');
});

/** Pantalla en miniatura: reductor real, acciones registradas. */
function banco(inicial = {}) {
  let estado = { ...estadoInicialReglas(), fase: 'listo', comidas: [comida()], ...inicial };
  const acciones = [];
  return {
    get estado() { return estado; },
    acciones,
    despachar(accion) {
      acciones.push(accion.tipo);
      estado = reductorReglas(estado, accion);
    },
  };
}

test('un guardado exitoso muestra el resultado y recarga una vez', async () => {
  const pantalla = banco();
  let recargas = 0;
  const resultado = await guardarComida({
    comida: comida(),
    borrador: guardaBorrador,
    despachar: pantalla.despachar,
    recargar: async () => { recargas += 1; },
    candado: { ocupado: false },
    guardar: async () => horario({ horarioId: 21, horaInicio: '12:00:00', horaFin: '15:30:00', vigenteDesde: '2026-10-14T10:15:00.250000' }),
  });
  assert.equal(resultado, 'ok');
  assert.equal(recargas, 1);
  assert.deepEqual(pantalla.acciones, ['GUARDADO_INICIO', 'GUARDADO_OK']);
  const aviso = pantalla.estado.avisos[2];
  assert.equal(aviso.tipo, 'exito');
  assert.match(aviso.titulo, /Almuerzo: horario guardado/);
  assert.match(aviso.detalle, /Ahora rige de 12:00 a 15:30 desde el 14\/10\/2026 10:15\./);
  assert.equal(pantalla.estado.guardando, null);
  assert.deepEqual(pantalla.estado.bloqueadas, [2], 'su base quedó cerrada: pide recargar para seguir');
});

test('un fallo del refresco tras el éxito no oculta el resultado guardado', async () => {
  const pantalla = banco();
  const guardar = async () => horario({ horarioId: 21, horaInicio: '12:00:00', horaFin: '15:30:00' });
  await guardarComida({
    comida: comida(),
    borrador: guardaBorrador,
    despachar: pantalla.despachar,
    recargar: () => recargarComidas({
      despachar: pantalla.despachar,
      cargar: async () => { throw new Error('No se pudieron cargar los horarios. No se pudo conectar con la API.'); },
    }),
    candado: { ocupado: false },
    guardar,
  });
  assert.deepEqual(pantalla.acciones, ['GUARDADO_INICIO', 'GUARDADO_OK', 'CARGA_INICIO', 'CARGA_ERROR']);
  const { estado } = pantalla;
  assert.equal(estado.avisos[2].tipo, 'exito', 'el éxito sigue a la vista');
  assert.match(estado.fallaRefresco, /No se pudo conectar con la API/);
  assert.equal(estado.fase, 'listo', 'las tarjetas siguen visibles');
  assert.equal(estado.comidas.length, 1);
  assert.equal(motivoSinGuardar(estado, estado.comidas[0], guardaBorrador), 'recargar', 'no se guarda sobre una base vieja');

  /* La recarga posterior sí desbloquea y trae lo nuevo. */
  await recargarComidas({
    despachar: pantalla.despachar,
    cargar: async () => [comida({ horario: horario({ horarioId: 21, horaInicio: '12:00:00', horaFin: '15:30:00' }) })],
  });
  assert.equal(pantalla.estado.fallaRefresco, '');
  assert.equal(pantalla.estado.avisos[2].tipo, 'exito');
  assert.deepEqual(pantalla.estado.bloqueadas, []);
});

test('un resultado incierto bloquea todo guardado hasta recargar, sin reintentar ni afirmar que no se guardó', async () => {
  const otra = comida({ horario: horario({ horarioId: 6, comidaId: 3, comida: 'Cena', horaInicio: '19:00:00', horaFin: '06:00:00', cruzaMedianoche: true }) });
  const pantalla = banco({ comidas: [comida(), otra] });
  let envios = 0;
  const resultado = await guardarComida({
    comida: comida(),
    borrador: guardaBorrador,
    despachar: pantalla.despachar,
    recargar: async () => assert.fail('no se recarga solo tras un resultado incierto'),
    candado: { ocupado: false },
    guardar: async () => {
      envios += 1;
      throw new ErrorGuardadoHorario('No se pudo conectar con la API. No sabemos si el cambio se guardó. Recargue los horarios y compruebe cómo quedaron antes de volver a guardar.', { incierto: true, recargar: true });
    },
  });
  assert.equal(resultado, 'incierto');
  assert.equal(envios, 1, 'un solo envío');
  const { estado } = pantalla;
  assert.equal(estado.avisos[2].tipo, 'incierto');
  assert.match(estado.avisos[2].titulo, /resultado incierto/);
  assert.doesNotMatch(`${estado.avisos[2].titulo} ${estado.avisos[2].detalle}`, /no se guardó\.|no quedó guardado/i);
  assert.equal(estado.incierto, true);
  assert.equal(motivoSinGuardar(estado, otra, { inicio: '20:00', fin: '06:00' }), 'incierto', 'tampoco otra comida');

  /* Recargar y comprobar levanta el bloqueo y deja el aviso como recordatorio. */
  await recargarComidas({ despachar: pantalla.despachar, cargar: async () => [comida(), otra] });
  assert.equal(pantalla.estado.incierto, false);
  assert.equal(pantalla.estado.avisos[2].tipo, 'aviso');
  assert.match(pantalla.estado.avisos[2].detalle, /si el cambio quedó guardado/);
});

test('version_desactualizada no cambia la base sola: pide recargar y la tarjeta queda bloqueada', async () => {
  const original = comida();
  const pantalla = banco({ comidas: [original] });
  let envios = 0;
  await guardarComida({
    comida: original,
    borrador: guardaBorrador,
    despachar: pantalla.despachar,
    recargar: async () => assert.fail('no recarga ni reenvía sola'),
    candado: { ocupado: false },
    guardar: async () => {
      envios += 1;
      throw new ErrorGuardadoHorario('Este horario cambió desde que lo abrió. Recargue los horarios…', { motivo: 'version_desactualizada', status: 409, recargar: true });
    },
  });
  assert.equal(envios, 1);
  const { estado } = pantalla;
  assert.equal(estado.avisos[2].tipo, 'error');
  assert.match(estado.avisos[2].titulo, /no se guardó/);
  assert.equal(estado.incierto, false, 'fue un rechazo claro del servidor');
  assert.equal(estado.comidas[0].base.horario.horarioId, 5, 'la base sigue siendo la que se abrió');
  assert.equal(motivoSinGuardar(estado, estado.comidas[0], guardaBorrador), 'recargar');
});

test('un rechazo común (solapa) deja corregir y volver a enviar sin recargar', async () => {
  const pantalla = banco();
  await guardarComida({
    comida: comida(),
    borrador: guardaBorrador,
    despachar: pantalla.despachar,
    recargar: async () => assert.fail('no hace falta recargar'),
    candado: { ocupado: false },
    guardar: async () => { throw new ErrorGuardadoHorario('Esa franja se superpone con la de otra comida.', { motivo: 'solapa_con_otra_comida', status: 409 }); },
  });
  assert.equal(pantalla.estado.avisos[2].tipo, 'error');
  assert.equal(motivoSinGuardar(pantalla.estado, comida(), guardaBorrador), null);
});

test('un envío a la vez: el segundo, mientras el primero sigue, no sale', async () => {
  const pantalla = banco();
  const candado = { ocupado: false };
  let envios = 0;
  let liberar;
  const espera = new Promise((resolver) => { liberar = resolver; });
  const guardar = async () => { envios += 1; await espera; return horario({ horarioId: 21 }); };
  const base = { comida: comida(), borrador: guardaBorrador, despachar: pantalla.despachar, recargar: async () => {}, candado, guardar };

  const primero = guardarComida(base);
  const segundo = await guardarComida(base);
  assert.equal(segundo, 'ocupado');
  assert.equal(envios, 1);
  liberar();
  assert.equal(await primero, 'ok');
  assert.equal(candado.ocupado, false);
  assert.equal(pantalla.acciones.filter((tipo) => tipo === 'GUARDADO_INICIO').length, 1);
});

test('reductor: carga inicial con error, carga vacía y refresco con datos anteriores', () => {
  let estado = estadoInicialReglas();
  assert.equal(estado.fase, 'cargando');
  estado = reductorReglas(estado, { tipo: 'CARGA_ERROR', mensaje: 'No se pudieron cargar los horarios.' });
  assert.equal(estado.fase, 'error');
  assert.equal(estado.comidas, null);
  estado = reductorReglas(estado, { tipo: 'CARGA_INICIO' });
  assert.equal(estado.fase, 'cargando');
  estado = reductorReglas(estado, { tipo: 'CARGA_OK', comidas: [] });
  assert.equal(estado.fase, 'listo');
  assert.deepEqual(estado.comidas, []);

  estado = reductorReglas(estado, { tipo: 'CARGA_OK', comidas: [comida()] });
  estado = reductorReglas(estado, { tipo: 'CARGA_INICIO' });
  assert.equal(estado.fase, 'listo', 'recargar no vacía lo que ya se ve');
  assert.equal(estado.actualizando, true);
  estado = reductorReglas(estado, { tipo: 'CARGA_ERROR', mensaje: 'falló' });
  assert.equal(estado.fase, 'listo');
  assert.equal(estado.comidas.length, 1);
  assert.equal(estado.fallaRefresco, 'falló');
});

test('recargarComidas no lanza y respeta la cancelación', async () => {
  const pantalla = banco({ fase: 'cargando', comidas: null });
  assert.equal(await recargarComidas({ despachar: pantalla.despachar, cargar: async () => [comida()] }), true);
  assert.equal(pantalla.estado.fase, 'listo');

  const controlador = new AbortController();
  const tardia = banco({ fase: 'cargando', comidas: null });
  const pendiente = recargarComidas({
    despachar: tardia.despachar,
    cargar: async () => { controlador.abort(); return [comida()]; },
    signal: controlador.signal,
  });
  assert.equal(await pendiente, false);
  assert.deepEqual(tardia.acciones, ['CARGA_INICIO'], 'una respuesta tardía no se publica');
});

// -------------------------------------------------------------
// 6. Render: tarjetas por comida, estados y ausencia de lo retirado
// -------------------------------------------------------------
const vista = (estado, extra = {}) => renderToStaticMarkup(h(VistaReglas, {
  estado: { ...estadoInicialReglas(), fase: 'listo', ...estado },
  onRecargar() {},
  onGuardar() {},
  onCerrarAviso() {},
  ...extra,
})).replace(/<!-- -->/g, '');

const cena = () => comida({
  horario: horario({ horarioId: 6, comidaId: 3, comida: 'Cena', horaInicio: '19:00:00', horaFin: '06:00:00', cruzaMedianoche: true }),
});

test('cada comida es una tarjeta con nombre, inicio, fin y Guardar cambios', () => {
  const html = vista({ comidas: [comida(), cena()] });
  assert.match(html, /Horario de cada comida/);
  assert.match(html, /<h3[^>]*>Almuerzo<\/h3>/);
  assert.match(html, /<h3[^>]*>Cena<\/h3>/);
  assert.equal((html.match(BOTON_GUARDAR) || []).length, 2);
  assert.equal((html.match(/type="time"/g) || []).length, 4);
  assert.match(html, />Inicio</);
  assert.match(html, />Fin</);
  assert.match(html, /value="11:30"/);
  assert.match(html, /value="15:00"/);
  assert.match(html, /value="19:00"/);
  assert.match(html, /Vigente desde el 14\/10\/2026 08:30 · guardado por root/);
  /* Explica que el cambio rige al guardar. */
  assert.match(html, /se aplica\s+en el momento de guardar/);
  assert.match(html, /no hay fecha de vigencia/);
  /* Las etiquetas están ligadas a sus campos. */
  assert.match(html, /<label[^>]*for="comida-2-inicio"/);
  assert.match(html, /id="comida-2-inicio"/);
});

test('indica cuándo la comida cruza la medianoche, por el dato del servidor y por lo editado', () => {
  const html = vista({ comidas: [comida(), cena()] });
  assert.equal((html.match(/Cruza la medianoche: termina el día siguiente\./g) || []).length, 1, 'solo la cena');

  const editada = renderToStaticMarkup(h(TarjetaComida, {
    comida: comida(),
    estado: { ...estadoInicialReglas(), fase: 'listo', comidas: [comida()] },
    onGuardar() {},
    onCerrarAviso() {},
    borradorInicial: { inicio: '22:00', fin: '02:00' },
  })).replace(/<!-- -->/g, '');
  assert.match(editada, /Cruza la medianoche/);
  assert.match(editada, /Cambios sin guardar/);
  assert.match(editada, /aria-disabled="false"/, 'con cambios válidos el botón puede enviar');
});

test('sin calendario, motivo, borrar, programar, historial ni Derecho a comer', () => {
  const html = vista({ comidas: [comida(), cena()] });
  assert.doesNotMatch(html, /type="date"|<textarea|type="checkbox"/);
  assert.doesNotMatch(html, /Motivo|motivo/);
  assert.doesNotMatch(html, /Eliminar|Programar|Historial|historial/);
  assert.doesNotMatch(html, /Derecho a comer|derecho/i);
  assert.doesNotMatch(html, /role="tab"|role="dialog"/);
});

test('el botón explica por qué no guarda y conserva el foco con aria-disabled', () => {
  const html = vista({ comidas: [comida()] });
  assert.match(html, /aria-disabled="true"/);
  assert.match(html, /Sin cambios por guardar\./);
  assert.match(html, /aria-describedby="comida-2-razon"/);
  assert.doesNotMatch(html, /<button[^>]*\sdisabled/, 'no usa disabled: el foco no se pierde');

  const guardando = vista({ comidas: [comida()], guardando: 2 }, { borradores: { 2: guardaBorrador } });
  assert.match(guardando, /Guardando…/);
  assert.match(guardando, /Guardando…<\/span>/);
  const otro = vista({ comidas: [comida(), cena()], guardando: 2 }, { borradores: { 2: guardaBorrador, 3: { inicio: '20:00', fin: '06:00' } } });
  assert.match(otro, /Espere: se está guardando otra comida\./);
});

test('estados: cargando, error, vacío honesto y lista con comidas se distinguen', () => {
  const cargando = vista({ fase: 'cargando', comidas: null });
  assert.match(cargando, /Cargando horarios…/);
  assert.doesNotMatch(cargando, BOTON_GUARDAR);

  const error = vista({ fase: 'error', comidas: null, error: 'No se pudieron cargar los horarios. La API respondió con error HTTP 500.' });
  assert.match(error, /role="alert"/);
  assert.match(error, /error HTTP 500/);
  assert.match(error, /Reintentar horarios/);
  assert.doesNotMatch(error, BOTON_GUARDAR);

  const vacio = vista({ comidas: [] });
  assert.match(vacio, /El servidor no informó ningún horario de comida/);
  assert.doesNotMatch(vacio, BOTON_GUARDAR);
  assert.doesNotMatch(vacio, /type="time"/);
  assert.doesNotMatch(vacio, /Desayuno|Almuerzo|Merienda|Cena/, 'no se inventa ninguna comida');
});

test('resultado incierto, éxito y fallo de refresco se ven aparte y sin decir "no se guardó"', () => {
  const incierto = vista({
    comidas: [comida()],
    incierto: true,
    avisos: { 2: { tipo: 'incierto', titulo: 'Almuerzo: resultado incierto', detalle: 'No sabemos si el cambio se guardó.' } },
  });
  assert.match(incierto, /Hay un guardado sin comprobar/);
  assert.match(incierto, /Recargar y comprobar/);
  assert.match(incierto, /Almuerzo: resultado incierto/);
  assert.match(incierto, /Recargue los horarios para seguir|Recargue los horarios y compruebe/);
  assert.doesNotMatch(incierto, /no se guardó el cambio|no quedó guardado/i);
  assert.doesNotMatch(incierto, /reglas__aviso--exito/);

  const exito = vista({
    comidas: [comida()],
    bloqueadas: [2],
    fallaRefresco: 'No se pudieron cargar los horarios. No se pudo conectar con la API.',
    avisos: { 2: { tipo: 'exito', titulo: 'Almuerzo: horario guardado', detalle: 'Ahora rige de 12:00 a 15:30 desde el 14/10/2026 10:15.' } },
  });
  assert.match(exito, /reglas__aviso--exito/);
  assert.match(exito, /Almuerzo: horario guardado/);
  assert.match(exito, /No se pudieron actualizar los horarios/);
  assert.match(exito, /Recargue los horarios para seguir editando esta comida/);
});

test('versión más reciente por reloj atrasado, comida sin versión abierta y base dudosa se explican', () => {
  const atrasada = comida({
    horario: horario({ horarioId: 9 }),
    listado: horario({ horarioId: 4, estado: 'anterior' }),
  });
  assert.match(vista({ comidas: [atrasada] }), /La hora del sistema está en una fecha anterior a la última versión/);

  const sinAbierta = { ...comida(), base: { tipo: 'ninguna' } };
  assert.match(vista({ comidas: [sinAbierta] }), /no tiene un horario abierto: al guardar se crea uno nuevo/);

  const dudosa = { ...comida(), base: { tipo: 'error', mensaje: 'No se pudo cargar el historial del horario. HTTP 500.' } };
  const htmlDudosa = vista({ comidas: [dudosa] }, { borradores: { 2: guardaBorrador } });
  assert.match(htmlDudosa, /No se pudo comprobar el historial de esta comida, así que no se puede guardar/);
  assert.match(htmlDudosa, /aria-disabled="true"/);

  const multiple = { ...comida(), base: { tipo: 'multiple' } };
  assert.match(vista({ comidas: [multiple] }), /más de un horario abierto/);
});

test('el contenedor monta con Cargando horarios… y sin efectos en el render estático', () => {
  const html = renderToStaticMarkup(h(ReglasSistema)).replace(/<!-- -->/g, '');
  assert.match(html, /Cargando horarios…/);
  assert.match(html, /Horario de cada comida/);
  assert.doesNotMatch(html, BOTON_GUARDAR);
});

// -------------------------------------------------------------
// 7. Lo retirado no existe: ni exportado ni llamado
// -------------------------------------------------------------
test('api.js ya no expone ninguna llamada de escritura retirada ni la edición del derecho', () => {
  for (const nombre of [
    'programarHorario',
    'eliminarHorarioProgramado',
    'programarReglasDerecho',
    'eliminarReglasDerechoProgramadas',
    'obtenerNovedadesDisponibles',
    'obtenerReglasDerecho',
  ]) {
    assert.equal(api[nombre], undefined, `${nombre} se retiró`);
  }
  assert.equal(typeof api.guardarHorario, 'function');
});

test('ninguna fuente de src llama a endpoints retirados de /reglas', () => {
  const archivos = [];
  const recorrer = (dir) => {
    for (const entrada of readdirSync(dir, { withFileTypes: true })) {
      const ruta = join(dir, entrada.name);
      if (entrada.isDirectory()) recorrer(ruta);
      else if (/\.(js|jsx)$/.test(entrada.name)) archivos.push(ruta);
    }
  };
  recorrer(fileURLToPath(new URL('../src', import.meta.url)));
  assert.ok(archivos.length > 20);

  const apiJs = readFileSync(join(fileURLToPath(new URL('../src', import.meta.url)), 'api.js'), 'utf8');
  /* Todo lo de reglas vive después de su encabezado: ahí solo hay lecturas y un POST. */
  const reglas = apiJs.slice(apiJs.indexOf('Reglas del sistema: horarios de comida'));
  assert.doesNotMatch(reglas, /method:\s*'(DELETE|PUT|PATCH)'/);
  assert.equal((reglas.match(/method:\s*'POST'/g) || []).length, 1, 'un solo POST: guardar el horario');
  assert.doesNotMatch(reglas, /\/reglas\/derecho/);
  assert.doesNotMatch(reglas, /\/reglas\/horarios\/\$\{/, 'no hay rutas /reglas/horarios/{id}');
  assert.doesNotMatch(reglas, /fecha=|vigente_desde:|motivoLimpio/);

  for (const ruta of archivos) {
    const texto = readFileSync(ruta, 'utf8');
    assert.doesNotMatch(texto, /programarHorario|eliminarHorarioProgramado|programarReglasDerecho|eliminarReglasDerechoProgramadas|obtenerNovedadesDisponibles|obtenerReglasDerecho/, ruta);
  }
});

// -------------------------------------------------------------
// 8. Cuentas de la jefa: lectura, sin acciones ni Nueva cuenta
// -------------------------------------------------------------
test('la tabla de lectura trae 5 columnas, busca y dice Nunca sin ingreso', () => {
  const html = renderToStaticMarkup(
    h(CuentasLectura, {
      cargandoInicial: false,
      cuentasIniciales: [
        { id: 7, username: 'maria.cocina', nombre: 'María Cocina', rol: 'cocinera', activo: true, debeCambiar: false, ultimoIngreso: '2026-09-28T07:55:00' },
        { id: 8, username: 'suelta.libre', nombre: null, rol: 'jefa', activo: false, debeCambiar: true, ultimoIngreso: null },
      ],
    }),
  );
  for (const columna of ['Usuario', 'Nombre', 'Rol', 'Estado', 'Último ingreso']) {
    assert.match(html, new RegExp(columna));
  }
  assert.match(html, /maria\.cocina/);
  assert.match(html, /María Cocina/);
  assert.match(html, /Cocinera/);
  assert.match(html, /Activa/);
  assert.match(html, /Nunca/);
  assert.match(html, />Actualizar</);
  assert.doesNotMatch(html, /Acciones/);
  assert.doesNotMatch(html, /Nueva cuenta/);
  assert.doesNotMatch(html, /Vínculo/);
  assert.doesNotMatch(html, /Reiniciar clave/);
  assert.doesNotMatch(html, /Desactivar/);
  assert.doesNotMatch(html, /Reactivar/);

  const htmlFiltro = renderToStaticMarkup(
    h(CuentasLectura, {
      cargandoInicial: false,
      cuentasIniciales: [
        { id: 7, username: 'maria.cocina', nombre: 'María Cocina', rol: 'cocinera', activo: true, debeCambiar: false, ultimoIngreso: null },
        { id: 8, username: 'jefa.nutri', nombre: 'Nadia Tarifa', rol: 'jefa', activo: true, debeCambiar: false, ultimoIngreso: null },
      ],
      busquedaInicial: 'tarifa',
    }),
  );
  assert.match(htmlFiltro, /jefa\.nutri/);
  assert.doesNotMatch(htmlFiltro, /maria\.cocina/);
});

// -------------------------------------------------------------
// 9. Montaje por rol
// -------------------------------------------------------------
test('sistemas monta Reglas sin padrón ni turno; la jefa conserva su panel; lo ajeno cae a Supervisión', () => {
  const localOriginal = globalThis.localStorage;
  const montar = (rol, guardada) => {
    globalThis.localStorage = { getItem: () => guardada, setItem: () => {}, removeItem: () => {} };
    return renderToStaticMarkup(
      h(ProveedorSesion, null, h(Panel, { rol, usuario: `${rol}.test` })),
    ).replace(/<!-- -->/g, '');
  };
  try {
    const htmlReglas = montar('sistemas', 'reglas');
    assert.match(htmlReglas, /Horario de cada comida/);
    assert.match(htmlReglas, /Cargando horarios…/);
    assert.doesNotMatch(htmlReglas, /Cargando padrón|comensales cargados|Consultando estado del comedor/);
    assert.doesNotMatch(htmlReglas, /Turno /, 'sistemas no ve un turno que no usa');
    assert.match(htmlReglas, /<h1 class="header__titulo">Reglas del sistema<\/h1>/);

    for (const guardada of ['supervision', 'dashboard', 'historial', 'reportes', 'vivo', 'cuentas', 'basura']) {
      const html = montar('sistemas', guardada);
      assert.match(html, /Horario de cada comida/, `guardada ${guardada}: vuelve a Reglas`);
      assert.doesNotMatch(html, /Cargando supervisión|Cargando cuentas…/, `guardada ${guardada}`);
    }

    const htmlCuentas = montar('jefa', 'cuentas');
    assert.match(htmlCuentas, /Cargando cuentas…/);
    assert.doesNotMatch(htmlCuentas, /Nueva cuenta/);
    assert.match(htmlCuentas, /Turno /, 'la jefa conserva su encabezado');

    const htmlJefaReglas = montar('jefa', 'reglas');
    assert.doesNotMatch(htmlJefaReglas, /Cargando horarios/);
    assert.match(htmlJefaReglas, /Cargando supervisión…/);

    const htmlCocinera = montar('cocinera', 'reglas');
    assert.doesNotMatch(htmlCocinera, /Cargando horarios/);
    assert.doesNotMatch(htmlCocinera, /Cargando cuentas/);
  } finally {
    if (localOriginal === undefined) delete globalThis.localStorage;
    else globalThis.localStorage = localOriginal;
  }
});
