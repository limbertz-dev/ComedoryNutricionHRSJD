/*
 * R2 Reglas del sistema (solo sistemas) y Cuentas (jefa, lectura).
 * Permisos y menú, adaptadores /reglas/* y /cuentas con fetch controlado,
 * fecha mínima del servidor y renders con react-dom/server.
 */
import test, { afterEach } from 'node:test';
import assert from 'node:assert/strict';
import {
  eliminarHorarioProgramado,
  eliminarReglasDerechoProgramadas,
  obtenerCuentasLectura,
  obtenerHistorialHorario,
  obtenerHorariosVigentes,
  obtenerNovedadesDisponibles,
  obtenerReglasDerecho,
  programarHorario,
  programarReglasDerecho,
} from '../src/api.js';
import { buscarSeccion, seccionesDeRol } from '../src/navegacion.js';
import { puedeVerSeccion, seccionesPermitidas } from '../src/permisos.js';
import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { Panel } from '../src/App.jsx';
import { ProveedorSesion } from '../src/hooks/useSesion.js';
import ReglasSistema, {
  DialogoHistorialHorario,
  DialogoNuevaVersion,
  DialogoProgramarHorario,
  PestanaDerecho,
  PestanaHorarios,
  estadoHorario,
  fechaLocal,
  formatoDiaMes,
  formatoFecha,
  formatoHora,
  minimoVigencia,
  ordenarVersionesDerecho,
  resumenDiferencias,
} from '../src/components/secciones/ReglasSistema.jsx';
import CuentasLectura from '../src/components/secciones/CuentasLectura.jsx';

const fetchOriginal = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = fetchOriginal;
});

const json = (datos, status = 200) => new Response(JSON.stringify(datos), { status });
const sinContenido = () => new Response(null, { status: 204 });

const versionApi = (cambios = {}) => ({
  id: 3,
  vigente_desde: '2026-10-01',
  duracion_minima_horas: 12,
  novedades_que_anulan: ['vacacion'],
  excluir_enfermeria: false,
  motivo: 'Motivo de prueba valido',
  creada_por: 'root',
  creada: '2026-09-20T08:00:00',
  estado: 'vigente',
  ...cambios,
});

const version = (cambios = {}) => ({
  id: 3,
  vigenteDesde: '2026-10-01',
  duracionMinimaHoras: 12,
  novedadesQueAnulan: ['vacacion'],
  excluirEnfermeria: false,
  motivo: 'Motivo de prueba valido',
  creadaPor: 'root',
  creada: '2026-09-20T08:00:00',
  estado: 'vigente',
  ...cambios,
});

const horarioApi = (cambios = {}) => ({
  horario_id: 5,
  comida_id: 2,
  comida: 'Almuerzo',
  hora_inicio: '11:30',
  hora_fin: '15:00',
  cruza_medianoche: false,
  vigente_desde: '2026-09-01',
  vigente_hasta: null,
  motivo: 'Horario habitual',
  creada_por: 'root',
  ...cambios,
});

const horario = (cambios = {}) => ({
  horarioId: 5,
  comidaId: 2,
  comida: 'Almuerzo',
  horaInicio: '11:30',
  horaFin: '15:00',
  cruzaMedianoche: false,
  vigenteDesde: '2026-09-01',
  vigenteHasta: null,
  motivo: 'Horario habitual',
  creadaPor: 'root',
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

// -------------------------------------------------------------
// 1. Permisos y menú: reglas solo sistemas, cuentas solo jefa
// -------------------------------------------------------------
test('reglas es solo de sistemas y cuentas solo de la jefa', () => {
  assert.deepEqual(seccionesPermitidas('sistemas'), ['supervision', 'dashboard', 'historial', 'reportes', 'reglas', 'admin', 'monitoreo']);
  assert.deepEqual(seccionesPermitidas('jefa'), ['supervision', 'dashboard', 'historial', 'reportes', 'cuentas']);
  assert.equal(puedeVerSeccion('sistemas', 'reglas'), true);
  assert.equal(puedeVerSeccion('sistemas', 'cuentas'), false);
  assert.equal(puedeVerSeccion('jefa', 'cuentas'), true);
  assert.equal(puedeVerSeccion('jefa', 'reglas'), false);
  assert.equal(puedeVerSeccion('cocinera', 'reglas'), false);
  assert.equal(puedeVerSeccion('cocinera', 'cuentas'), false);

  const menuSistemas = seccionesDeRol('sistemas').map(({ id }) => id);
  assert.ok(menuSistemas.indexOf('reglas') < menuSistemas.indexOf('admin'));
  assert.ok(!menuSistemas.includes('cuentas'));
  const menuJefa = seccionesDeRol('jefa').map(({ id }) => id);
  assert.equal(menuJefa[menuJefa.length - 1], 'cuentas');
  assert.ok(!menuJefa.includes('reglas'));
  assert.ok(!seccionesDeRol('cocinera').some(({ id }) => id === 'reglas' || id === 'cuentas'));

  const reglas = buscarSeccion('reglas');
  assert.equal(reglas.etiqueta, 'Reglas del sistema');
  assert.equal(reglas.titulo, 'Reglas del sistema');
  assert.equal(typeof reglas.Icono, 'function');
  const cuentas = buscarSeccion('cuentas');
  assert.equal(cuentas.etiqueta, 'Cuentas');
  assert.equal(typeof cuentas.Icono, 'function');
});

// -------------------------------------------------------------
// 2. obtenerCuentasLectura
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
// 3. obtenerReglasDerecho y obtenerNovedadesDisponibles
// -------------------------------------------------------------
test('obtenerReglasDerecho adapta vigente y versiones; rechaza formas inválidas', async () => {
  globalThis.fetch = async (url) => {
    assert.equal(new URL(url).pathname, '/reglas/derecho');
    return json({
      vigente: versionApi(),
      versiones: [versionApi(), versionApi({ id: 4, estado: 'programada', vigente_desde: '2026-11-01' })],
    });
  };
  const reglas = await obtenerReglasDerecho();
  assert.equal(reglas.vigente.estado, 'vigente');
  assert.equal(reglas.vigente.duracionMinimaHoras, 12);
  assert.deepEqual(reglas.vigente.novedadesQueAnulan, ['vacacion']);
  assert.deepEqual(reglas.versiones.map(({ id }) => id), [3, 4]);

  globalThis.fetch = async () => json({ vigente: versionApi() });
  await assert.rejects(obtenerReglasDerecho(), /reglas de derecho inválidas/);
  globalThis.fetch = async () => json({ vigente: versionApi({ estado: 'futura' }), versiones: [] });
  await assert.rejects(obtenerReglasDerecho(), /versión de derecho inválida/);
  globalThis.fetch = async () => json({ vigente: versionApi(), versiones: [versionApi({ duracion_minima_horas: 99 })] });
  await assert.rejects(obtenerReglasDerecho(), /versión de derecho inválida/);
});

test('obtenerNovedadesDisponibles devuelve strings y rechaza formas inválidas', async () => {
  globalThis.fetch = async (url) => {
    assert.equal(new URL(url).pathname, '/reglas/derecho/novedades');
    return json(['vacacion', 'licencia']);
  };
  assert.deepEqual(await obtenerNovedadesDisponibles(), ['vacacion', 'licencia']);

  globalThis.fetch = async () => json(['vacacion', 7]);
  await assert.rejects(obtenerNovedadesDisponibles(), /novedades inválidas/);
  globalThis.fetch = async () => json('vacacion');
  await assert.rejects(obtenerNovedadesDisponibles(), /novedades inválidas/);
});

// -------------------------------------------------------------
// 4. programarReglasDerecho: contrato exacto, guía y motivos
// -------------------------------------------------------------
test('programarReglasDerecho envía exactamente el contrato y adapta la 201', async () => {
  let cuerpo;
  let metodo;
  globalThis.fetch = async (url, opciones) => {
    assert.equal(new URL(url).pathname, '/reglas/derecho');
    metodo = opciones.method;
    cuerpo = JSON.parse(opciones.body);
    return json(versionApi({ id: 9, estado: 'programada' }), 201);
  };
  const creada = await programarReglasDerecho({
    vigenteDesde: '2026-10-01',
    duracionMinimaHoras: 8,
    novedadesQueAnulan: ['licencia'],
    excluirEnfermeria: true,
    motivo: '  Cambio de turno minimo  ',
  });
  assert.equal(metodo, 'POST');
  assert.deepEqual(cuerpo, {
    vigente_desde: '2026-10-01',
    duracion_minima_horas: 8,
    novedades_que_anulan: ['licencia'],
    excluir_enfermeria: true,
    motivo: 'Cambio de turno minimo',
  });
  assert.equal(creada.id, 9);
  assert.equal(creada.estado, 'programada');
});

test('programarReglasDerecho guía en el front y traduce los motivos', async () => {
  let llamadas = 0;
  globalThis.fetch = async () => {
    llamadas += 1;
    return json(versionApi(), 201);
  };
  const base = { vigenteDesde: '2026-10-01', duracionMinimaHoras: 8, motivo: 'Motivo suficientemente largo' };
  await assert.rejects(programarReglasDerecho({ ...base, duracionMinimaHoras: 0 }), /1 a 48 horas/);
  await assert.rejects(programarReglasDerecho({ ...base, duracionMinimaHoras: 49 }), /1 a 48 horas/);
  await assert.rejects(programarReglasDerecho({ ...base, motivo: 'corto' }), /10 caracteres/);
  await assert.rejects(programarReglasDerecho({ ...base, vigenteDesde: '01/10/2026' }), /qué fecha rige/);
  assert.equal(llamadas, 0);

  const casos = [
    ['vigencia_en_el_pasado', /ya pasó/],
    ['version_en_esa_fecha', /programado para esa fecha/],
    ['motivo_obligatorio', /motivo del cambio/],
  ];
  for (const [motivo, esperado] of casos) {
    globalThis.fetch = async () => json({ detail: 'x', motivo }, 422);
    await assert.rejects(programarReglasDerecho(base), esperado, motivo);
  }
});

test('eliminarReglasDerechoProgramadas usa DELETE y traduce sus motivos', async () => {
  const rutas = [];
  globalThis.fetch = async (url, opciones) => {
    rutas.push([new URL(url).pathname, opciones.method]);
    return sinContenido();
  };
  assert.equal(await eliminarReglasDerechoProgramadas(9), null);
  assert.deepEqual(rutas[0], ['/reglas/derecho/9', 'DELETE']);

  await assert.rejects(eliminarReglasDerechoProgramadas(0), /Versión inválida/);

  globalThis.fetch = async () => json({ detail: 'x', motivo: 'version_ya_vigente' }, 409);
  await assert.rejects(eliminarReglasDerechoProgramadas(9), /ya está vigente/);
  globalThis.fetch = async () => json({ detail: 'x', motivo: 'version_inexistente' }, 404);
  await assert.rejects(eliminarReglasDerechoProgramadas(9), /ya no existe/);
});

// -------------------------------------------------------------
// 5. obtenerHorariosVigentes y obtenerHistorialHorario
// -------------------------------------------------------------
test('obtenerHorariosVigentes adapta y acepta fecha opcional', async () => {
  const pedidas = [];
  globalThis.fetch = async (url) => {
    pedidas.push(new URL(url));
    return json([
      horarioApi(),
      horarioApi({ horario_id: 6, comida_id: 3, comida: 'Cena', hora_inicio: '19:00:00', hora_fin: '06:00:00', cruza_medianoche: true, motivo: null, creada_por: null }),
    ]);
  };
  const horarios = await obtenerHorariosVigentes();
  assert.equal(pedidas[0].pathname, '/reglas/horarios');
  assert.equal(pedidas[0].search, '');
  assert.deepEqual(horarios[0], horario());
  assert.equal(horarios[1].cruzaMedianoche, true);
  assert.equal(horarios[1].motivo, null);

  await obtenerHorariosVigentes({ fecha: '2026-10-01' });
  assert.equal(pedidas[1].searchParams.get('fecha'), '2026-10-01');

  await assert.rejects(obtenerHorariosVigentes({ fecha: 'ayer' }), /Fecha inválida/);
  assert.equal(pedidas.length, 2);

  globalThis.fetch = async () => json({ total: 2 });
  await assert.rejects(obtenerHorariosVigentes(), /horarios inválidos/);
  globalThis.fetch = async () => json([horarioApi({ hora_inicio: 'once' })]);
  await assert.rejects(obtenerHorariosVigentes(), /horario inválido/);
});

test('obtenerHistorialHorario pide por comida y traduce comida_inexistente', async () => {
  globalThis.fetch = async (url) => {
    const pedida = new URL(url);
    assert.equal(pedida.pathname, '/reglas/horarios/historial');
    assert.equal(pedida.searchParams.get('comida_id'), '2');
    return json([horarioApi()]);
  };
  const versiones = await obtenerHistorialHorario(2);
  assert.equal(versiones.length, 1);
  assert.equal(versiones[0].horarioId, 5);

  await assert.rejects(obtenerHistorialHorario(0), /Comida inválida/);
  globalThis.fetch = async () => json({ detail: 'x', motivo: 'comida_inexistente' }, 404);
  await assert.rejects(obtenerHistorialHorario(2), /ya no existe/);
});

// -------------------------------------------------------------
// 6. programarHorario: contrato exacto, guía y motivos
// -------------------------------------------------------------
test('programarHorario envía exactamente el contrato y adapta la 201', async () => {
  let cuerpo;
  let metodo;
  globalThis.fetch = async (url, opciones) => {
    assert.equal(new URL(url).pathname, '/reglas/horarios');
    metodo = opciones.method;
    cuerpo = JSON.parse(opciones.body);
    return json(horarioApi({ horario_id: 11, vigente_desde: '2026-10-01' }), 201);
  };
  const creado = await programarHorario({
    comidaId: 2,
    horaInicio: '11:30',
    horaFin: '15:00',
    vigenteDesde: '2026-10-01',
    motivo: '  Ajuste de cocina  ',
  });
  assert.equal(metodo, 'POST');
  assert.deepEqual(cuerpo, {
    comida_id: 2,
    hora_inicio: '11:30',
    hora_fin: '15:00',
    vigente_desde: '2026-10-01',
    motivo: 'Ajuste de cocina',
  });
  assert.equal(creado.horarioId, 11);
});

test('programarHorario guía en el front y traduce los motivos', async () => {
  let llamadas = 0;
  globalThis.fetch = async () => {
    llamadas += 1;
    return json(horarioApi(), 201);
  };
  const base = { comidaId: 2, horaInicio: '11:30', horaFin: '15:00', vigenteDesde: '2026-10-01', motivo: 'Ajuste de cocina' };
  await assert.rejects(programarHorario({ ...base, horaFin: 'tres' }), /hora de inicio y la de fin/);
  await assert.rejects(programarHorario({ ...base, vigenteDesde: 'mañana' }), /qué fecha rige/);
  await assert.rejects(programarHorario({ ...base, motivo: '   ' }), /motivo del cambio/);
  await assert.rejects(programarHorario({ ...base, comidaId: 0 }), /Comida inválida/);
  assert.equal(llamadas, 0);

  const casos = [
    ['vigencia_en_el_pasado', /ya pasó/],
    ['horario_invalido', /no es válido/],
    ['solapa_con_otra_comida', /se cruza con otra comida/],
    ['version_en_esa_fecha', /programado para esa fecha/],
    ['comida_inexistente', /ya no existe/],
    ['motivo_obligatorio', /motivo del cambio/],
  ];
  for (const [motivo, esperado] of casos) {
    globalThis.fetch = async () => json({ detail: 'x', motivo }, 422);
    await assert.rejects(programarHorario(base), esperado, motivo);
  }
});

test('eliminarHorarioProgramado usa DELETE y traduce sus motivos', async () => {
  const rutas = [];
  globalThis.fetch = async (url, opciones) => {
    rutas.push([new URL(url).pathname, opciones.method]);
    return sinContenido();
  };
  assert.equal(await eliminarHorarioProgramado(11), null);
  assert.deepEqual(rutas[0], ['/reglas/horarios/11', 'DELETE']);

  await assert.rejects(eliminarHorarioProgramado(-2), /Horario inválido/);

  globalThis.fetch = async () => json({ detail: 'x', motivo: 'version_ya_vigente' }, 409);
  await assert.rejects(eliminarHorarioProgramado(11), /ya está vigente/);
  globalThis.fetch = async () => json({ detail: 'x', motivo: 'version_inexistente' }, 404);
  await assert.rejects(eliminarHorarioProgramado(11), /ya no existe/);
});

// -------------------------------------------------------------
// 7. Fecha mínima: hoy del servidor en simulación, local fuera
// -------------------------------------------------------------
test('el mínimo es el hoy del servidor en simulación y el local fuera', () => {
  assert.equal(minimoVigencia('2026-08-10'), '2026-08-10');
  assert.equal(minimoVigencia(undefined), fechaLocal());
  assert.equal(minimoVigencia('ayer'), fechaLocal());
  const dos = (n) => String(n).padStart(2, '0');
  const ahora = new Date();
  assert.equal(fechaLocal(ahora), `${ahora.getFullYear()}-${dos(ahora.getMonth() + 1)}-${dos(ahora.getDate())}`);
  assert.equal(formatoFecha('2026-09-30'), '30/09/2026');
  assert.equal(formatoDiaMes('2026-10-01'), '01/10');
  assert.equal(formatoHora('11:30:00'), '11:30');
  assert.equal(formatoHora('11:30'), '11:30');
});

test('los diálogos limitan vigente desde al hoy del servidor', () => {
  const htmlHorario = renderToStaticMarkup(
    h(DialogoProgramarHorario, {
      horario: horario(),
      hoyMinimo: '2026-09-29',
      onProgramado() {},
      onCerrar() {},
    }),
  );
  assert.match(htmlHorario, /min="2026-09-29"/);

  const htmlVersion = renderToStaticMarkup(
    h(DialogoNuevaVersion, {
      vigente: version(),
      novedadesDisponibles: ['vacacion'],
      hoyMinimo: '2026-09-29',
      onProgramada() {},
      onCerrar() {},
    }),
  );
  assert.match(htmlVersion, /min="2026-09-29"/);
});

// -------------------------------------------------------------
// 8. Render: aviso fijo, pestañas y tabla de horarios
// -------------------------------------------------------------
test('la sección trae el aviso fijo y las dos pestañas', () => {
  const html = renderToStaticMarkup(h(ReglasSistema, { hoy: '2026-09-29' }));
  assert.match(html, /Los cambios se aplican desde la fecha elegida y nunca modifican días pasados/);
  assert.match(html, /Horarios de comida/);
  assert.match(html, /Derecho a comer/);
  assert.match(html, /Cargando horarios…/);

  const htmlDerecho = renderToStaticMarkup(h(ReglasSistema, { hoy: '2026-09-29', pestanaInicial: 'derecho' }));
  assert.match(htmlDerecho, /Los cambios se aplican desde la fecha elegida y nunca modifican días pasados/);
  assert.match(htmlDerecho, /Cargando derecho a comer…/);
});

test('la tabla muestra Comida, Horario, Vigente desde, Motivo y Acciones', () => {
  const html = renderToStaticMarkup(
    h(PestanaHorarios, {
      hoyMinimo: '2026-09-29',
      cargandoInicial: false,
      horariosIniciales: [
        horario(),
        horario({ horarioId: 6, comidaId: 3, comida: 'Cena', horaInicio: '19:00', horaFin: '06:00', cruzaMedianoche: true, motivo: null }),
      ],
    }),
  );
  for (const columna of ['Comida', 'Horario', 'Vigente desde', 'Motivo', 'Acciones']) {
    assert.match(html, new RegExp(columna));
  }
  assert.match(html, /Almuerzo/);
  assert.match(html, /11:30–15:00/);
  assert.match(html, /cruza medianoche/);
  assert.match(html, /01\/09\/2026/);
  assert.match(html, /Programar cambio/);
  assert.match(html, /Historial/);
});

test('programar cambio anticipa Desde el DD/MM, comida y horas nuevas', () => {
  const html = renderToStaticMarkup(
    h(DialogoProgramarHorario, {
      horario: horario(),
      hoyMinimo: '2026-09-29',
      valoresIniciales: { horaInicio: '11:30', horaFin: '15:00', vigenteDesde: '2026-10-01' },
      onProgramado() {},
      onCerrar() {},
    }),
  );
  assert.ok(html.includes('Desde el 01/10, Almuerzo pasará a 11:30–15:00.'));
  assert.match(html, /Hora de inicio/);
  assert.match(html, /Hora de fin/);
  assert.match(html, /Vigente desde/);
  assert.match(html, /Motivo/);
});

// -------------------------------------------------------------
// 9. Eliminar solo en programadas y con confirmación
// -------------------------------------------------------------
const historialMezclado = () => ([
  horario({ horarioId: 7, vigenteDesde: '2026-10-05', vigenteHasta: null }),
  horario({ horarioId: 5, vigenteDesde: '2026-09-01', vigenteHasta: null }),
  horario({ horarioId: 4, vigenteDesde: '2026-08-01', vigenteHasta: '2026-08-31' }),
]);

test('el estado del horario sale de sus fechas contra el hoy', () => {
  const [programada, vigente, anterior] = historialMezclado();
  assert.equal(estadoHorario(programada, '2026-09-29'), 'programada');
  assert.equal(estadoHorario(vigente, '2026-09-29'), 'vigente');
  assert.equal(estadoHorario(anterior, '2026-09-29'), 'anterior');
  assert.equal(estadoHorario(vigente, '2026-09-01'), 'vigente');
});

test('el historial solo ofrece Eliminar en la programada y la confirma', () => {
  const props = {
    horario: horario(),
    hoy: '2026-09-29',
    onEliminado() {},
    onCerrar() {},
    versionesIniciales: historialMezclado(),
    cargandoInicial: false,
  };
  const html = renderToStaticMarkup(h(DialogoHistorialHorario, props));
  assert.match(html, /Historial de Almuerzo/);
  assert.match(html, /Programada/);
  assert.match(html, /Vigente/);
  assert.match(html, /Anterior/);
  assert.equal((html.match(/>Eliminar</g) || []).length, 1);

  const htmlConfirma = renderToStaticMarkup(
    h(DialogoHistorialHorario, { ...props, confirmacionInicial: historialMezclado()[0] }),
  );
  assert.match(htmlConfirma, /Eliminar horario programado/);
  assert.match(htmlConfirma, /¿Eliminar el cambio de Almuerzo que regiría desde el 05\/10\/2026\?/);
  assert.match(htmlConfirma, />Cancelar</);
});

test('las versiones de derecho se ordenan programadas, vigente y anteriores', () => {
  const desorden = [
    version({ id: 1, estado: 'anterior', vigenteDesde: '2026-07-01' }),
    version({ id: 3, estado: 'vigente', vigenteDesde: '2026-09-01' }),
    version({ id: 5, estado: 'programada', vigenteDesde: '2026-11-01' }),
    version({ id: 2, estado: 'anterior', vigenteDesde: '2026-08-01' }),
    version({ id: 4, estado: 'programada', vigenteDesde: '2026-10-01' }),
  ];
  assert.deepEqual(ordenarVersionesDerecho(desorden).map(({ id }) => id), [4, 5, 3, 2, 1]);
});

test('la tarjeta vigente y la lista solo eliminan la programada, con confirmación', () => {
  const props = {
    hoyMinimo: '2026-09-29',
    cargandoInicial: false,
    derechoInicial: {
      vigente: version(),
      versiones: [
        version({ id: 5, estado: 'programada', vigenteDesde: '2026-11-01' }),
        version(),
        version({ id: 1, estado: 'anterior', vigenteDesde: '2026-07-01' }),
      ],
    },
    novedadesIniciales: ['vacacion', 'licencia'],
  };
  const html = renderToStaticMarkup(h(PestanaDerecho, props));
  assert.match(html, /Versión vigente/);
  assert.match(html, /Turno mínimo/);
  assert.match(html, /12 h/);
  assert.match(html, /vacacion/);
  assert.match(html, /Enfermería excluida/);
  assert.match(html, /01\/10\/2026/);
  assert.match(html, /root/);
  assert.match(html, /Motivo de prueba valido/);
  assert.match(html, /Programar nueva versión/);
  const iProgramada = html.indexOf('01/11/2026');
  const iVigente = html.lastIndexOf('01/10/2026');
  const iAnterior = html.indexOf('01/07/2026');
  assert.ok(iProgramada !== -1 && iVigente !== -1 && iAnterior !== -1);
  assert.ok(iProgramada < iVigente && iVigente < iAnterior);
  assert.equal((html.match(/>Eliminar</g) || []).length, 1);

  const htmlConfirma = renderToStaticMarkup(
    h(PestanaDerecho, {
      ...props,
      confirmacionInicial: version({ id: 5, estado: 'programada', vigenteDesde: '2026-11-01' }),
    }),
  );
  assert.match(htmlConfirma, /Eliminar versión programada/);
  assert.match(htmlConfirma, /¿Eliminar la versión que regiría desde el 01\/11\/2026\?/);
  assert.match(htmlConfirma, />Cancelar</);
});

// -------------------------------------------------------------
// 10. Resumen de diferencias antes de confirmar
// -------------------------------------------------------------
test('el resumen lista cada cambio contra la vigente', () => {
  const vigente = version();
  assert.deepEqual(resumenDiferencias(vigente, {
    duracionMinimaHoras: 12,
    novedadesQueAnulan: ['vacacion'],
    excluirEnfermeria: false,
  }), ['Sin cambios respecto a la versión vigente.']);
  assert.deepEqual(resumenDiferencias(vigente, {
    duracionMinimaHoras: 8,
    novedadesQueAnulan: ['licencia'],
    excluirEnfermeria: true,
  }), [
    'Turno mínimo: de 12 h a 8 h.',
    'Novedades que anulan: se agrega «licencia».',
    'Novedades que anulan: se quita «vacacion».',
    'Enfermería: ahora queda excluida.',
  ]);
});

test('el formulario muestra el resumen de cambios antes de Programar versión', () => {
  const html = renderToStaticMarkup(
    h(DialogoNuevaVersion, {
      vigente: version(),
      novedadesDisponibles: ['vacacion', 'licencia'],
      hoyMinimo: '2026-09-29',
      valoresIniciales: { duracionMinimaHoras: 8, novedadesQueAnulan: ['licencia'], excluirEnfermeria: true },
      onProgramada() {},
      onCerrar() {},
    }),
  );
  assert.match(html, /Programar nueva versión/);
  assert.match(html, /Turno mínimo \(horas\)/);
  assert.match(html, /Novedades que anulan el derecho/);
  assert.match(html, /Excluir a enfermería/);
  assert.match(html, /Motivo \(10 caracteres o más\)/);
  assert.match(html, /Resumen de cambios/);
  assert.match(html, /Turno mínimo: de 12 h a 8 h\./);
  assert.match(html, /se agrega «licencia»/);
  assert.match(html, /se quita «vacacion»/);
  assert.match(html, /ahora queda excluida/);
  assert.match(html, />Programar versión</);
});

// -------------------------------------------------------------
// 11. Cuentas de la jefa: lectura, sin acciones ni Nueva cuenta
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
// 12. Montaje por rol: sistemas abre reglas, jefa abre cuentas
// -------------------------------------------------------------
test('sistemas monta Reglas; jefa monta Cuentas; lo ajeno cae a Supervisión', () => {
  const localOriginal = globalThis.localStorage;
  const montar = (rol, guardada) => {
    globalThis.localStorage = { getItem: () => guardada, setItem: () => {}, removeItem: () => {} };
    return renderToStaticMarkup(
      h(ProveedorSesion, null, h(Panel, { rol, usuario: `${rol}.test` })),
    );
  };
  try {
    const htmlReglas = montar('sistemas', 'reglas');
    assert.match(htmlReglas, /Los cambios se aplican desde la fecha elegida/);
    assert.match(htmlReglas, /Cargando horarios…/);

    const htmlCuentas = montar('jefa', 'cuentas');
    assert.match(htmlCuentas, /Cargando cuentas…/);
    assert.doesNotMatch(htmlCuentas, /Nueva cuenta/);

    const htmlJefaReglas = montar('jefa', 'reglas');
    assert.doesNotMatch(htmlJefaReglas, /Cargando horarios/);
    assert.match(htmlJefaReglas, /Cargando supervisión…/);

    const htmlSistemasCuentas = montar('sistemas', 'cuentas');
    assert.doesNotMatch(htmlSistemasCuentas, /Cargando cuentas/);
    assert.match(htmlSistemasCuentas, /Cargando supervisión…/);

    const htmlCocinera = montar('cocinera', 'reglas');
    assert.doesNotMatch(htmlCocinera, /Cargando horarios/);
    assert.doesNotMatch(htmlCocinera, /Cargando cuentas/);
  } finally {
    if (localOriginal === undefined) delete globalThis.localStorage;
    else globalThis.localStorage = localOriginal;
  }
});
