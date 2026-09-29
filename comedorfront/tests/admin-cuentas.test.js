/*
 * R1 Administración de cuentas (solo sistemas).
 * Permisos del menú y adaptadores /admin/* con fetch controlado.
 */
import test, { afterEach } from 'node:test';
import assert from 'node:assert/strict';
import {
  buscarCandidatos,
  crearCuenta,
  desactivarCuenta,
  obtenerCuentas,
  reactivarCuenta,
  reiniciarClaveCuenta,
} from '../src/api.js';
import { buscarSeccion, seccionesDeRol } from '../src/navegacion.js';
import { puedeVerSeccion, seccionesPermitidas } from '../src/permisos.js';
import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { Panel } from '../src/App.jsx';
import { ProveedorSesion } from '../src/hooks/useSesion.js';
import Administracion, {
  copiarTexto,
  crearBuscadorCandidatos,
  DialogoClave,
  DialogoConfirmacion,
  DialogoNuevaCuenta,
  esCuentaPropia,
  estadoDeCuenta,
  ejecutarAccionCuenta,
  filtrarCuentas,
  finalizarCreacionCuenta,
  formatoUltimoIngreso,
  normalizarNombreUsuario,
  ordenarCuentas,
} from '../src/components/secciones/Administracion.jsx';

const fetchOriginal = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = fetchOriginal;
});

const json = (datos, status = 200) => new Response(JSON.stringify(datos), { status });

const cuentaApi = (cambios = {}) => ({
  id: 7,
  username: 'maria.cocina',
  rol: 'cocinera',
  activo: true,
  debe_cambiar: false,
  usuario_turnos_id: 31,
  vinculada: true,
  nombre: 'María Cocina',
  categoria: 'Cocina',
  creada: '2026-09-20T08:00:00',
  ultimo_ingreso: '2026-09-28T07:55:00',
  ...cambios,
});

// -------------------------------------------------------------
// 1. Solo sistemas ve 'admin'
// -------------------------------------------------------------
test("solo sistemas ve 'admin': jefa y cocinera no la ven ni la montan", () => {
  assert.deepEqual(seccionesPermitidas('sistemas'), ['supervision', 'dashboard', 'historial', 'reportes', 'reglas', 'admin']);
  assert.deepEqual(seccionesPermitidas('jefa'), ['supervision', 'dashboard', 'historial', 'reportes', 'cuentas']);
  assert.deepEqual(seccionesPermitidas('cocinera'), ['vivo']);
  assert.equal(puedeVerSeccion('sistemas', 'admin'), true);
  assert.equal(puedeVerSeccion('jefa', 'admin'), false);
  assert.equal(puedeVerSeccion('cocinera', 'admin'), false);

  const menuSistemas = seccionesDeRol('sistemas').map(({ id }) => id);
  assert.deepEqual(menuSistemas, ['supervision', 'dashboard', 'historial', 'reportes', 'reglas', 'admin']);
  assert.ok(!seccionesDeRol('jefa').some(({ id }) => id === 'admin'));
  assert.ok(!seccionesDeRol('cocinera').some(({ id }) => id === 'admin'));

  const admin = buscarSeccion('admin');
  assert.equal(admin.etiqueta, 'Administración');
  assert.equal(admin.titulo, 'Administración de cuentas');
  assert.equal(typeof admin.Icono, 'function');
});

// -------------------------------------------------------------
// 2. obtenerCuentas
// -------------------------------------------------------------
test('obtenerCuentas adapta snake_case y rechaza formas inválidas', async () => {
  globalThis.fetch = async (url) => {
    assert.equal(new URL(url).pathname, '/admin/cuentas');
    return json([cuentaApi(), cuentaApi({ id: 8, username: 'jefa.nutri', rol: 'jefa', activo: false, debe_cambiar: true, usuario_turnos_id: null, vinculada: false, nombre: null, categoria: null, ultimo_ingreso: null })]);
  };
  const cuentas = await obtenerCuentas();
  assert.equal(cuentas.length, 2);
  assert.deepEqual(cuentas[0], {
    id: 7,
    username: 'maria.cocina',
    rol: 'cocinera',
    activo: true,
    debeCambiar: false,
    usuarioTurnosId: 31,
    vinculada: true,
    nombre: 'María Cocina',
    categoria: 'Cocina',
    creada: '2026-09-20T08:00:00',
    ultimoIngreso: '2026-09-28T07:55:00',
  });
  assert.equal(cuentas[1].debeCambiar, true);
  assert.equal(cuentas[1].usuarioTurnosId, null);

  globalThis.fetch = async () => json({ total: 1 });
  await assert.rejects(obtenerCuentas(), /lista de cuentas inválida/);
  globalThis.fetch = async () => json([cuentaApi({ id: null })]);
  await assert.rejects(obtenerCuentas(), /cuenta inválida/);
  globalThis.fetch = async () => json([cuentaApi({ rol: 'superadmin' })]);
  await assert.rejects(obtenerCuentas(), /cuenta inválida/);
});

// -------------------------------------------------------------
// 3. buscarCandidatos
// -------------------------------------------------------------
test('buscarCandidatos exige 2+ caracteres, pagina con limite y valida la forma', async () => {
  const rutas = [];
  globalThis.fetch = async (url) => {
    rutas.push(url);
    return json([
      { usuario_turnos_id: 31, login: 'maria.cocina', nombre: 'María Cocina', categoria: 'Cocina', cuenta_id: null },
      { usuario_turnos_id: 32, login: 'mario.ayuda', nombre: 'Mario Ayuda', categoria: 'Ayudante', cuenta_id: 7 },
    ]);
  };
  const candidatos = await buscarCandidatos('mar');
  const pedida = new URL(rutas[0]);
  assert.equal(pedida.pathname, '/admin/candidatos');
  assert.equal(pedida.searchParams.get('busqueda'), 'mar');
  assert.equal(pedida.searchParams.get('limite'), '20');
  assert.deepEqual(candidatos[0], {
    usuarioTurnosId: 31, login: 'maria.cocina', nombre: 'María Cocina', categoria: 'Cocina', cuentaId: null, tieneCuenta: false,
  });
  assert.equal(candidatos[1].tieneCuenta, true);

  await assert.rejects(buscarCandidatos('a'), /al menos 2 caracteres/);
  await assert.rejects(buscarCandidatos('  '), /al menos 2 caracteres/);
  assert.equal(rutas.length, 1);

  globalThis.fetch = async () => json({});
  await assert.rejects(buscarCandidatos('mar'), /lista de candidatos inválida/);
  globalThis.fetch = async () => json([{ usuario_turnos_id: 0, login: '', nombre: '', categoria: 'x', cuenta_id: null }]);
  await assert.rejects(buscarCandidatos('mar'), /candidato inválido/);
});

// -------------------------------------------------------------
// 4. crearCuenta
// -------------------------------------------------------------
test('crearCuenta desde el padrón envía {rol, usuario_turnos_id} y devuelve la clave', async () => {
  let cuerpo;
  globalThis.fetch = async (url, opciones) => {
    assert.equal(new URL(url).pathname, '/admin/cuentas');
    assert.equal(opciones.method, 'POST');
    cuerpo = JSON.parse(opciones.body);
    return json({ cuenta: cuentaApi({ id: 9, username: 'ana.ayuda' }), clave_temporal: 'Tmp-9x2k' }, 201);
  };
  const resultado = await crearCuenta({ rol: 'cocinera', usuarioTurnosId: 44 });
  assert.deepEqual(cuerpo, { rol: 'cocinera', usuario_turnos_id: 44 });
  assert.equal(resultado.cuenta.id, 9);
  assert.equal(resultado.claveTemporal, 'Tmp-9x2k');
});

test('crearCuenta sin vínculo envía {rol, username, nombre} normalizados', async () => {
  let cuerpo;
  globalThis.fetch = async (url, opciones) => {
    cuerpo = JSON.parse(opciones.body);
    return json({ cuenta: cuentaApi({ id: 10, username: 'nueva.persona', vinculada: false, usuario_turnos_id: null }), clave_temporal: 'Tmp-ab12' }, 201);
  };
  const resultado = await crearCuenta({ rol: 'jefa', username: '  Nueva.Persona ', nombre: '  Nueva Persona ' });
  assert.deepEqual(cuerpo, { rol: 'jefa', username: 'nueva.persona', nombre: 'Nueva Persona' });
  assert.equal(resultado.claveTemporal, 'Tmp-ab12');

  await assert.rejects(crearCuenta({ rol: 'jefa', username: '  ', nombre: 'X' }), /nombre de usuario/);
  await assert.rejects(crearCuenta({ rol: 'jefa', username: 'x', nombre: '  ' }), /nombre de la persona/);
  await assert.rejects(crearCuenta({ rol: 'sistemas', username: 'x', nombre: 'X' }), /Cocinera o Jefa/);
});

test('crearCuenta traduce cada motivo a español claro', async () => {
  const casos = [
    ['username_en_uso', /ya está en uso/],
    ['persona_ya_tiene_cuenta', /ya tiene una cuenta/],
    ['persona_inexistente', /ya no figura en el padrón/],
    ['login_invalido', /no es válido/],
    ['rol_no_permitido', /Cocinera o Jefa/],
  ];
  for (const [motivo, esperado] of casos) {
    globalThis.fetch = async () => json({ detail: 'x', motivo }, motivo === 'persona_inexistente' ? 404 : 409);
    await assert.rejects(crearCuenta({ rol: 'cocinera', usuarioTurnosId: 44 }), esperado, motivo);
  }
  globalThis.fetch = async () => json({ cuenta: cuentaApi(), clave_temporal: '' }, 201);
  await assert.rejects(crearCuenta({ rol: 'cocinera', usuarioTurnosId: 44 }), /clave temporal inválida/);
});

// -------------------------------------------------------------
// 5. desactivar / reactivar / reiniciar
// -------------------------------------------------------------
test('desactivarCuenta y reactivarCuenta publican en su ruta y traducen motivos', async () => {
  const rutas = [];
  globalThis.fetch = async (url, opciones) => {
    rutas.push([new URL(url).pathname, opciones.method]);
    return json(cuentaApi({ activo: false }));
  };
  const desactivada = await desactivarCuenta(7);
  assert.equal(desactivada.activo, false);
  assert.deepEqual(rutas[0], ['/admin/cuentas/7/desactivar', 'POST']);

  globalThis.fetch = async (url, opciones) => {
    rutas.push([new URL(url).pathname, opciones.method]);
    return json(cuentaApi({ activo: true }));
  };
  const reactivada = await reactivarCuenta(7);
  assert.equal(reactivada.activo, true);
  assert.deepEqual(rutas[1], ['/admin/cuentas/7/reactivar', 'POST']);

  globalThis.fetch = async () => json({ detail: 'x', motivo: 'no_puede_desactivarse_a_si_misma' }, 409);
  await assert.rejects(desactivarCuenta(7), /propia cuenta/);
  globalThis.fetch = async () => json({ detail: 'x', motivo: 'ultima_cuenta_sistemas' }, 409);
  await assert.rejects(desactivarCuenta(7), /última cuenta de Sistemas/);
  globalThis.fetch = async () => json(cuentaApi({ activo: 'si' }));
  await assert.rejects(reactivarCuenta(7), /cuenta inválida/);
  await assert.rejects(desactivarCuenta(0), /Cuenta inválida/);
});

test('reiniciarClaveCuenta devuelve cuenta y clave temporal', async () => {
  globalThis.fetch = async (url, opciones) => {
    assert.equal(new URL(url).pathname, '/admin/cuentas/7/reiniciar-clave');
    assert.equal(opciones.method, 'POST');
    return json({ cuenta: cuentaApi({ debe_cambiar: true }), clave_temporal: 'Tmp-r7q1' });
  };
  const resultado = await reiniciarClaveCuenta(7);
  assert.equal(resultado.cuenta.debeCambiar, true);
  assert.equal(resultado.claveTemporal, 'Tmp-r7q1');

  globalThis.fetch = async () => json({ cuenta: cuentaApi() });
  await assert.rejects(reiniciarClaveCuenta(7), /clave temporal inválida/);
});

// -------------------------------------------------------------
// 6. Orden, filtro, vínculo, estado y cuenta propia
// -------------------------------------------------------------
const cuenta = (cambios = {}) => ({
  id: 7,
  username: 'maria.cocina',
  rol: 'cocinera',
  activo: true,
  debeCambiar: false,
  usuarioTurnosId: 31,
  vinculada: true,
  nombre: 'María Cocina',
  categoria: 'Cocina',
  creada: '2026-09-20T08:00:00',
  ultimoIngreso: '2026-09-28T07:55:00',
  ...cambios,
});

test('la tabla ordena activas primero, por rol (sistemas, jefa, cocinera) y usuario', () => {
  const lista = [
    cuenta({ id: 1, username: 'zeta.cocina', rol: 'cocinera', activo: true }),
    cuenta({ id: 2, username: 'ana.jefa', rol: 'jefa', activo: true }),
    cuenta({ id: 3, username: 'root', rol: 'sistemas', activo: true }),
    cuenta({ id: 4, username: 'ana.cocina', rol: 'cocinera', activo: true }),
    cuenta({ id: 5, username: 'vieja.jefa', rol: 'jefa', activo: false }),
  ];
  assert.deepEqual(
    ordenarCuentas(lista).map(({ username }) => username),
    ['root', 'ana.jefa', 'ana.cocina', 'zeta.cocina', 'vieja.jefa'],
  );
});

test('el filtro local busca por usuario o nombre; normaliza y detecta la propia', () => {
  const lista = [
    cuenta({ username: 'maria.cocina', nombre: 'María Cocina' }),
    cuenta({ id: 8, username: 'jefa.nutri', nombre: 'Nadia Tarifa' }),
  ];
  assert.deepEqual(filtrarCuentas(lista, 'maria').map(({ id }) => id), [7]);
  assert.deepEqual(filtrarCuentas(lista, 'tarifa').map(({ id }) => id), [8]);
  assert.deepEqual(filtrarCuentas(lista, '  ').map(({ id }) => id), [7, 8]);
  assert.deepEqual(filtrarCuentas(lista, 'nadie'), []);
  assert.equal(normalizarNombreUsuario('  Maria.Cocina '), 'maria.cocina');
  assert.equal(esCuentaPropia(lista[0], 'maria.cocina'), true);
  assert.equal(esCuentaPropia(lista[0], ' Maria.Cocina '), true);
  assert.equal(esCuentaPropia(lista[0], 'otra.cuenta'), false);
  assert.equal(esCuentaPropia(lista[0], null), false);
  assert.deepEqual(estadoDeCuenta(cuenta()), { texto: 'Activa', tono: 'exito' });
  assert.deepEqual(estadoDeCuenta(cuenta({ activo: false })), { texto: 'Inactiva', tono: 'neutro' });
  assert.deepEqual(estadoDeCuenta(cuenta({ debeCambiar: true })), { texto: 'Clave temporal', tono: 'aviso' });
  assert.equal(formatoUltimoIngreso(null), 'Nunca');
  assert.match(formatoUltimoIngreso('2026-09-28T07:55:00'), /2026/);
});

// -------------------------------------------------------------
// 7. Render: carga, vacío, error y tabla
// -------------------------------------------------------------
test('carga, vacío y error son estados distintos', () => {
  const htmlCarga = renderToStaticMarkup(h(Administracion, { cargandoInicial: true }));
  assert.match(htmlCarga, /Cargando cuentas…/);
  assert.doesNotMatch(htmlCarga, /No hay cuentas/);

  const htmlVacio = renderToStaticMarkup(
    h(Administracion, { cargandoInicial: false, cuentasIniciales: [] }),
  );
  assert.match(htmlVacio, /No hay cuentas registradas/);
  assert.doesNotMatch(htmlVacio, /Cargando cuentas/);

  const htmlError = renderToStaticMarkup(
    h(Administracion, { cargandoInicial: false, errorInicial: 'Se cayó la red' }),
  );
  assert.match(htmlError, /Se cayó la red/);
  assert.match(htmlError, /Reintentar cuentas/);
});

test('la tabla muestra Usuario, Nombre, Rol, Vínculo, Estado, Último ingreso y Acciones', () => {
  const html = renderToStaticMarkup(
    h(Administracion, {
      cargandoInicial: false,
      cuentasIniciales: [
        cuenta(),
        cuenta({ id: 8, username: 'suelta.libre', nombre: null, rol: 'jefa', activo: false, debeCambiar: true, vinculada: false, usuarioTurnosId: null, ultimoIngreso: null }),
      ],
    }),
  );
  for (const columna of ['Usuario', 'Nombre', 'Rol', 'Vínculo', 'Estado', 'Último ingreso', 'Acciones']) {
    assert.match(html, new RegExp(columna));
  }
  assert.match(html, /maria\.cocina/);
  assert.match(html, />Padrón</);
  assert.match(html, />Sin vínculo</);
  assert.match(html, />Activa</);
  assert.match(html, />Inactiva</);
  assert.match(html, /Nunca/);
  assert.match(html, /Reiniciar clave/);
  assert.match(html, /Desactivar/);
  assert.match(html, /Reactivar/);
  assert.match(html, /Nueva cuenta/);
});

test('la búsqueda local filtra filas y el orden se respeta en el render', () => {
  const filas = [
    cuenta({ id: 1, username: 'zeta.cocina', nombre: 'Zeta' }),
    cuenta({ id: 2, username: 'ana.jefa', nombre: 'Ana', rol: 'jefa' }),
  ];
  const htmlFiltro = renderToStaticMarkup(
    h(Administracion, { cargandoInicial: false, cuentasIniciales: filas, busquedaInicial: 'zeta' }),
  );
  assert.match(htmlFiltro, /zeta\.cocina/);
  assert.doesNotMatch(htmlFiltro, /ana\.jefa/);

  const htmlSinFiltro = renderToStaticMarkup(
    h(Administracion, { cargandoInicial: false, cuentasIniciales: filas }),
  );
  assert.ok(htmlSinFiltro.indexOf('ana.jefa') < htmlSinFiltro.indexOf('zeta.cocina'));
});

// -------------------------------------------------------------
// 8. La propia cuenta no ofrece Desactivar
// -------------------------------------------------------------
test('en la fila de la propia cuenta no aparece Desactivar', () => {
  const html = renderToStaticMarkup(
    h(Administracion, {
      cargandoInicial: false,
      usuarioActual: 'maria.cocina',
      cuentasIniciales: [
        cuenta(),
        cuenta({ id: 8, username: 'otra.cocina', nombre: 'Otra' }),
      ],
    }),
  );
  assert.match(html, /Su cuenta/);
  assert.equal(html.match(/>Desactivar</g)?.length ?? 0, 1);
  assert.equal(html.match(/>Reiniciar clave</g)?.length ?? 0, 2);
});

// -------------------------------------------------------------
// 9. Nueva cuenta: pestañas, candidatos y vista previa
// -------------------------------------------------------------
const candidato = (cambios = {}) => ({
  usuarioTurnosId: 31,
  login: 'ana.ayuda',
  nombre: 'Ana Ayuda',
  categoria: 'Ayudante',
  cuentaId: null,
  tieneCuenta: false,
  ...cambios,
});

const dialogoVacio = (props = {}) => h(DialogoNuevaCuenta, { onCrear() {}, onCerrar() {}, ...props });

test('el diálogo trae las dos pestañas y el aviso de sin vínculo', () => {
  const htmlPadron = renderToStaticMarkup(dialogoVacio());
  assert.match(htmlPadron, /Desde el padrón/);
  assert.match(htmlPadron, /Sin vínculo/);
  assert.match(htmlPadron, /Buscar en el padrón/);
  assert.match(htmlPadron, />Crear</);

  const htmlLibre = renderToStaticMarkup(dialogoVacio({ pestanaInicial: 'libre' }));
  assert.match(htmlLibre, /aún no están en el padrón/);
  assert.match(htmlLibre, />Crear</);
});

test('los candidatos con cuenta aparecen desactivados con Ya tiene cuenta', () => {
  const html = renderToStaticMarkup(dialogoVacio({
    busquedaPadronInicial: 'ana',
    candidatosIniciales: [
      candidato(),
      candidato({ usuarioTurnosId: 32, login: 'usada.cuenta', nombre: 'Usada Cuenta', cuentaId: 7, tieneCuenta: true }),
    ],
  }));
  assert.match(html, /Ana Ayuda/);
  assert.match(html, /ana\.ayuda/);
  assert.match(html, /Ya tiene cuenta/);
  assert.match(html, /<button[^>]*disabled[^>]*>[\s\S]*?Elegir/);
});

test('al elegir candidato el usuario queda en solo lectura; sin vínculo anticipa el usuario', () => {
  const htmlElegido = renderToStaticMarkup(dialogoVacio({ candidatoInicial: candidato() }));
  assert.match(htmlElegido, /value="ana\.ayuda"/);
  assert.match(htmlElegido, /readOnly/);
  assert.match(htmlElegido, /Cambiar/);

  const htmlLibre = renderToStaticMarkup(dialogoVacio({
    pestanaInicial: 'libre',
    usuarioLibreInicial: '  Maria.Cocina ',
  }));
  assert.match(htmlLibre, /Va a quedar: maria\.cocina/);
});

// -------------------------------------------------------------
// 10. Confirmación y clave temporal
// -------------------------------------------------------------
test('Desactivar, Reactivar y Reiniciar piden confirmación', () => {
  const htmlSin = renderToStaticMarkup(
    h(Administracion, { cargandoInicial: false, cuentasIniciales: [cuenta()] }),
  );
  assert.doesNotMatch(htmlSin, /Desactivar cuenta/);

  const htmlDesactivar = renderToStaticMarkup(
    h(Administracion, {
      cargandoInicial: false,
      cuentasIniciales: [cuenta()],
      confirmacionInicial: { tipo: 'desactivar', cuenta: cuenta() },
    }),
  );
  assert.match(htmlDesactivar, /Desactivar cuenta/);
  assert.match(htmlDesactivar, /¿Desactivar la cuenta de maria\.cocina\?/);
  assert.match(htmlDesactivar, />Cancelar</);

  const htmlReiniciar = renderToStaticMarkup(
    h(DialogoConfirmacion, {
      confirmacion: { tipo: 'reiniciar', cuenta: cuenta() },
      onConfirmar() {},
      onCancelar() {},
    }),
  );
  assert.match(htmlReiniciar, /Reiniciar clave/);
  assert.match(htmlReiniciar, /se muestra una sola vez/);
});

test('el diálogo muestra la clave con Copiar y el aviso; al cerrarlo desaparece', () => {
  const htmlClave = renderToStaticMarkup(
    h(Administracion, {
      cargandoInicial: false,
      cuentasIniciales: [cuenta()],
      claveInicial: { usuario: 'maria.cocina', valor: 'Tmp-unica-1' },
    }),
  );
  assert.match(htmlClave, /Tmp-unica-1/);
  assert.match(htmlClave, />Copiar</);
  assert.match(htmlClave, /No se volverá a mostrar; entréguela en mano\. Se cambia en el primer ingreso/);

  // Estado tras cerrar: la clave se borró y el diálogo ya no se dibuja.
  const htmlCerrado = renderToStaticMarkup(
    h(Administracion, { cargandoInicial: false, cuentasIniciales: [cuenta()], claveInicial: null }),
  );
  assert.doesNotMatch(htmlCerrado, /Tmp-unica-1/);
  assert.doesNotMatch(htmlCerrado, /Clave temporal de/);
});

test('copiarTexto resuelve false sin portapapeles y true con portapapeles', async () => {
  assert.equal(await copiarTexto('x'), false);
  const escritos = [];
  const descriptorOriginal = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
  Object.defineProperty(globalThis, 'navigator', {
    value: { clipboard: { writeText: async (texto) => { escritos.push(texto); } } },
    configurable: true,
    writable: true,
  });
  try {
    assert.equal(await copiarTexto('Tmp-1'), true);
    assert.deepEqual(escritos, ['Tmp-1']);
  } finally {
    if (descriptorOriginal) Object.defineProperty(globalThis, 'navigator', descriptorOriginal);
    else delete globalThis.navigator;
  }
});

// -------------------------------------------------------------
// 11. La tabla se relee tras cada acción
// -------------------------------------------------------------
test('ejecutarAccionCuenta avisa y relee; el error trae el mensaje del motivo', async () => {
  const avisos = [];
  const procesos = [];
  let releidas = 0;
  const guardarAviso = (aviso) => { if (aviso) avisos.push(aviso); };
  const resultado = await ejecutarAccionCuenta({
    ejecutar: async () => 'R',
    tituloExito: 'Hecho',
    tituloError: 'Falló',
    recargar: async () => { releidas += 1; },
    setAviso: guardarAviso,
    setProcesando: (valor) => procesos.push(valor),
  });
  assert.equal(resultado, 'R');
  assert.equal(releidas, 1);
  assert.deepEqual(procesos, [true, false]);
  assert.equal(avisos[0].tipo, 'exito');

  releidas = 0;
  const fallo = await ejecutarAccionCuenta({
    ejecutar: async () => { throw new Error('No puede desactivar su propia cuenta.'); },
    tituloExito: 'Hecho',
    tituloError: 'No se pudo desactivar',
    recargar: async () => { releidas += 1; },
    setAviso: guardarAviso,
  });
  assert.equal(fallo, undefined);
  assert.equal(releidas, 0);
  assert.equal(avisos[1].tipo, 'error');
  assert.match(avisos[1].detalle, /propia cuenta/);
});

test('tras crear, la clave va al diálogo y la tabla se relee', async () => {
  const avisos = [];
  const claves = [];
  let releidas = 0;
  await finalizarCreacionCuenta({
    resultado: { cuenta: cuenta({ username: 'nueva.cuenta' }), claveTemporal: 'Tmp-nueva' },
    setAviso: (aviso) => avisos.push(aviso),
    setClave: (clave) => claves.push(clave),
    recargar: async () => { releidas += 1; },
  });
  assert.equal(releidas, 1);
  assert.match(avisos[0].titulo, /nueva\.cuenta/);
  assert.deepEqual(claves[0], { usuario: 'nueva.cuenta', valor: 'Tmp-nueva' });
});

// -------------------------------------------------------------
// 12. Debounce con cancelación: lo viejo nunca pisa lo nuevo
// -------------------------------------------------------------
const esperar = (ms) => new Promise((resolver) => setTimeout(resolver, ms));

test('el buscador agrupa teclas rápidas en una sola petición con el último texto', async () => {
  const terminos = [];
  const buscador = crearBuscadorCandidatos({
    retardo: 10,
    buscar: async (termino) => { terminos.push(termino); return [termino]; },
  });
  const resultados = [];
  const receptor = { onResultado: (lista) => resultados.push(lista) };
  buscador.programar('an', receptor);
  buscador.programar('ana', receptor);
  buscador.programar('anab', receptor);
  await esperar(60);
  assert.deepEqual(terminos, ['anab']);
  assert.deepEqual(resultados, [['anab']]);
});

test('al seguir escribiendo se aborta la petición en vuelo y lo viejo no pisa', async () => {
  const senales = [];
  let resolverPrimera;
  const primera = new Promise((resolver) => { resolverPrimera = resolver; });
  const buscar = async (termino, { signal }) => {
    senales.push(signal);
    if (termino === 'ana') {
      await primera;
      return ['vieja'];
    }
    return ['nueva'];
  };
  const buscador = crearBuscadorCandidatos({ retardo: 5, buscar });
  const resultados = [];
  buscador.programar('ana', { onResultado: (lista) => resultados.push(lista) });
  await esperar(30);
  assert.equal(senales.length, 1);
  buscador.programar('anab', { onResultado: (lista) => resultados.push(lista) });
  assert.equal(senales[0].aborted, true);
  resolverPrimera();
  await esperar(40);
  assert.deepEqual(resultados, [['nueva']]);
});

// -------------------------------------------------------------
// 13. La clave nunca va a storage ni a la consola
// -------------------------------------------------------------
test('ninguna clave temporal va a storage ni a la consola', async () => {
  const CLAVE = 'Tmp-secreta-xyz';
  const guardado = [];
  const memoria = () => ({
    getItem: () => null,
    setItem: (_clave, valor) => { guardado.push(String(valor)); },
    removeItem: () => {},
  });
  const localOriginal = globalThis.localStorage;
  const sesionOriginal = globalThis.sessionStorage;
  globalThis.localStorage = memoria();
  globalThis.sessionStorage = memoria();
  const metodos = ['log', 'warn', 'error', 'info', 'debug'];
  const originales = metodos.map((metodo) => console[metodo]);
  const consola = [];
  metodos.forEach((metodo) => {
    console[metodo] = (...argumentos) => { consola.push(argumentos.map(String).join(' ')); };
  });
  try {
    renderToStaticMarkup(
      h(Administracion, {
        cargandoInicial: false,
        cuentasIniciales: [cuenta()],
        claveInicial: { usuario: 'maria.cocina', valor: CLAVE },
      }),
    );
    renderToStaticMarkup(h(DialogoClave, { usuario: 'maria.cocina', valor: CLAVE, onCerrar() {} }));
    renderToStaticMarkup(dialogoVacio({ pestanaInicial: 'libre', usuarioLibreInicial: 'x' }));
    globalThis.fetch = async (url, opciones) => {
      if (new URL(url).pathname === '/admin/cuentas') {
        return json({ cuenta: cuentaApi(), clave_temporal: CLAVE }, 201);
      }
      return json({ cuenta: cuentaApi(), clave_temporal: CLAVE });
    };
    await crearCuenta({ rol: 'cocinera', usuarioTurnosId: 44 });
    await reiniciarClaveCuenta(7);
    assert.ok(guardado.every((valor) => !valor.includes(CLAVE)), 'la clave llegó a storage');
    assert.ok(consola.every((linea) => !linea.includes(CLAVE)), 'la clave llegó a la consola');
  } finally {
    metodos.forEach((metodo, indice) => { console[metodo] = originales[indice]; });
    if (localOriginal === undefined) delete globalThis.localStorage;
    else globalThis.localStorage = localOriginal;
    if (sesionOriginal === undefined) delete globalThis.sessionStorage;
    else globalThis.sessionStorage = sesionOriginal;
  }
});

// -------------------------------------------------------------
// 14. Montaje por rol: sistemas abre admin, jefa cae a supervisión
// -------------------------------------------------------------
test('sistemas monta Administración; jefa con admin guardado cae a Supervisión', () => {
  const localOriginal = globalThis.localStorage;
  globalThis.localStorage = { getItem: () => 'admin', setItem: () => {}, removeItem: () => {} };
  try {
    const htmlSistemas = renderToStaticMarkup(
      h(ProveedorSesion, null, h(Panel, { rol: 'sistemas', usuario: 'root' })),
    );
    assert.match(htmlSistemas, /Cargando cuentas…/);

    const htmlJefa = renderToStaticMarkup(
      h(ProveedorSesion, null, h(Panel, { rol: 'jefa', usuario: 'jefa.nutri' })),
    );
    assert.doesNotMatch(htmlJefa, /Cargando cuentas/);
    assert.match(htmlJefa, /Cargando supervisión…/);
  } finally {
    if (localOriginal === undefined) delete globalThis.localStorage;
    else globalThis.localStorage = localOriginal;
  }
});
