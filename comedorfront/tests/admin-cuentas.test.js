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
  assert.deepEqual(seccionesPermitidas('sistemas'), ['supervision', 'dashboard', 'historial', 'reportes', 'admin']);
  assert.deepEqual(seccionesPermitidas('jefa'), ['supervision', 'dashboard', 'historial', 'reportes']);
  assert.deepEqual(seccionesPermitidas('cocinera'), ['vivo']);
  assert.equal(puedeVerSeccion('sistemas', 'admin'), true);
  assert.equal(puedeVerSeccion('jefa', 'admin'), false);
  assert.equal(puedeVerSeccion('cocinera', 'admin'), false);

  const menuSistemas = seccionesDeRol('sistemas').map(({ id }) => id);
  assert.deepEqual(menuSistemas, ['supervision', 'dashboard', 'historial', 'reportes', 'admin']);
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
