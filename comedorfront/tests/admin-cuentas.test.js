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
  editarCuenta,
  eliminarCuenta,
  obtenerCuentas,
  reactivarCuenta,
  cambiarClaveCuenta,
} from '../src/api.js';
import { buscarSeccion, seccionesDeRol } from '../src/navegacion.js';
import { puedeVerSeccion, seccionesPermitidas } from '../src/permisos.js';
import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { Panel } from '../src/App.jsx';
import { ProveedorSesion } from '../src/hooks/useSesion.js';
import Administracion, {
  crearBuscadorCandidatos,
  DialogoCambiarClave,
  DialogoEditarCuenta,
  DialogoConfirmacion,
  DialogoNuevaCuenta,
  esCuentaPropia,
  estadoDeCuenta,
  ejecutarAccionCuenta,
  filtrarCuentas,
  finalizarCreacionCuenta,
  formatoUltimoIngreso,
  motivoClaveInvalida,
  normalizarNombreUsuario,
  ordenarCuentas,
} from '../src/components/secciones/Administracion.jsx';

const CLAVE = 'clave-elegida-1';

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
  assert.deepEqual(seccionesPermitidas('sistemas'), ['reglas', 'admin', 'monitoreo']);
  assert.deepEqual(seccionesPermitidas('jefa'), ['supervision', 'dashboard', 'historial', 'reportes', 'cuentas']);
  assert.deepEqual(seccionesPermitidas('cocinera'), ['vivo']);
  assert.equal(puedeVerSeccion('sistemas', 'admin'), true);
  assert.equal(puedeVerSeccion('jefa', 'admin'), false);
  assert.equal(puedeVerSeccion('cocinera', 'admin'), false);

  const menuSistemas = seccionesDeRol('sistemas').map(({ id }) => id);
  assert.deepEqual(menuSistemas, ['reglas', 'admin', 'monitoreo']);
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
test('crearCuenta desde el padrón envía {rol, usuario_turnos_id, password} y devuelve la cuenta', async () => {
  let cuerpo;
  globalThis.fetch = async (url, opciones) => {
    assert.equal(new URL(url).pathname, '/admin/cuentas');
    assert.equal(opciones.method, 'POST');
    cuerpo = JSON.parse(opciones.body);
    return json({ cuenta: cuentaApi({ id: 9, username: 'ana.ayuda' }) }, 201);
  };
  const resultado = await crearCuenta({ rol: 'cocinera', usuarioTurnosId: 44, password: CLAVE });
  assert.deepEqual(cuerpo, { rol: 'cocinera', usuario_turnos_id: 44, password: CLAVE });
  assert.equal(resultado.cuenta.id, 9);
  assert.deepEqual(Object.keys(resultado), ['cuenta']);
});

test('crearCuenta sin vínculo envía {rol, username, nombre, password} normalizados', async () => {
  let cuerpo;
  globalThis.fetch = async (url, opciones) => {
    cuerpo = JSON.parse(opciones.body);
    return json({ cuenta: cuentaApi({ id: 10, username: 'nueva.persona', vinculada: false, usuario_turnos_id: null }) }, 201);
  };
  const resultado = await crearCuenta({ rol: 'jefa', username: '  Nueva.Persona ', nombre: '  Nueva Persona ', password: CLAVE });
  assert.deepEqual(cuerpo, { rol: 'jefa', username: 'nueva.persona', nombre: 'Nueva Persona', password: CLAVE });
  assert.equal(resultado.cuenta.username, 'nueva.persona');

  await assert.rejects(crearCuenta({ rol: 'jefa', username: '  ', nombre: 'X', password: CLAVE }), /nombre de usuario/);
  await assert.rejects(crearCuenta({ rol: 'jefa', username: 'x', nombre: '  ', password: CLAVE }), /nombre de la persona/);
  await assert.rejects(crearCuenta({ rol: 'sistemas', username: 'x', nombre: 'X', password: CLAVE }), /Cocinera o Jefa/);
  await assert.rejects(crearCuenta({ rol: 'jefa', username: 'x', nombre: 'X' }), /Escriba la contraseña/);
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
    await assert.rejects(crearCuenta({ rol: 'cocinera', usuarioTurnosId: 44, password: CLAVE }), esperado, motivo);
  }
  // Una contraseña rechazada muestra la regla exacta que da el servidor.
  globalThis.fetch = async () => json({ detail: 'La contraseña debe tener al menos 8 caracteres.', motivo: 'password_rechazada' }, 422);
  await assert.rejects(crearCuenta({ rol: 'cocinera', usuarioTurnosId: 44, password: 'x' }), /al menos 8 caracteres/);
  globalThis.fetch = async () => json({ cuenta: cuentaApi({ id: null }) }, 201);
  await assert.rejects(crearCuenta({ rol: 'cocinera', usuarioTurnosId: 44, password: CLAVE }), /cuenta inválida/);
});

// -------------------------------------------------------------
// 5. desactivar / reactivar / cambiar clave
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

test('cambiarClaveCuenta envía {password} a /clave y devuelve la cuenta', async () => {
  let cuerpo;
  globalThis.fetch = async (url, opciones) => {
    assert.equal(new URL(url).pathname, '/admin/cuentas/7/clave');
    assert.equal(opciones.method, 'POST');
    cuerpo = JSON.parse(opciones.body);
    return json({ cuenta: cuentaApi() });
  };
  const resultado = await cambiarClaveCuenta(7, 'otra-clave-2');
  assert.deepEqual(cuerpo, { password: 'otra-clave-2' });
  assert.equal(resultado.cuenta.debeCambiar, false);

  await assert.rejects(cambiarClaveCuenta(7, ''), /Escriba la contraseña/);
  await assert.rejects(cambiarClaveCuenta(0, CLAVE), /Cuenta inválida/);
  globalThis.fetch = async () => json({ detail: 'La contraseña no puede ser el nombre de usuario.', motivo: 'password_rechazada' }, 422);
  await assert.rejects(cambiarClaveCuenta(7, 'maria.cocina'), /nombre de usuario/);
});

test('motivoClaveInvalida anticipa las reglas del servidor', () => {
  assert.equal(motivoClaveInvalida('', '', 'x'), 'Escriba la contraseña.');
  assert.match(motivoClaveInvalida('corta', 'corta', 'x'), /al menos 8/);
  assert.match(motivoClaveInvalida('Cocinera4', 'Cocinera4', ' cocinera4 '), /nombre de usuario/);
  assert.match(motivoClaveInvalida(CLAVE, 'otra-cosa', 'x'), /no coinciden/);
  assert.equal(motivoClaveInvalida(CLAVE, CLAVE, 'cocinera4'), '');
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

test('la tabla muestra nombre y conserva Desactivar, Reactivar y Eliminar separados', () => {
  const html = renderToStaticMarkup(
    h(Administracion, {
      cargandoInicial: false,
      cuentasIniciales: [
        cuenta(),
        cuenta({ id: 8, username: 'suelta.libre', nombre: null, rol: 'jefa', activo: false, debeCambiar: true, vinculada: false, usuarioTurnosId: null, ultimoIngreso: null }),
      ],
    }),
  );
  assert.deepEqual([...html.matchAll(/<th scope="col">([^<]+)<\/th>/g)].map(m => m[1]),
    ['Usuario', 'Nombre', 'Rol', 'Estado', 'Último ingreso', 'Acciones']);
  assert.match(html, /maria\.cocina/);
  assert.doesNotMatch(html, />Vínculo<|>Padrón<|>Sin vínculo</);
  assert.match(html, /María Cocina/);
  assert.match(html, />Activa</);
  assert.match(html, />Inactiva</);
  assert.match(html, /Nunca/);
  assert.match(html, /Cambiar clave/);
  assert.doesNotMatch(html, /Reiniciar clave/);
  assert.match(html, /Desactivar/);
  assert.match(html, /Reactivar/);
  assert.equal(html.match(/>Eliminar</g)?.length ?? 0, 2);
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
  assert.equal(html.match(/>Eliminar</g)?.length ?? 0, 1);
  assert.equal(html.match(/>Cambiar clave</g)?.length ?? 0, 2);
});

// -------------------------------------------------------------
// 9. Nueva cuenta: pestañas, candidatos y vista previa
// -------------------------------------------------------------
const dialogoVacio = (props = {}) => h(DialogoNuevaCuenta, { onCrear() {}, onCerrar() {}, ...props });

test('nueva cuenta abre directamente los datos manuales, sin pestanas ni candidatos', () => {
  const html = renderToStaticMarkup(dialogoVacio());
  assert.doesNotMatch(html, /role="tab|nueva-busqueda-padron|nueva-usuario-padron|Candidatos/);
  assert.match(html, /id="nueva-usuario-libre"/);
  assert.match(html, /id="nueva-nombre-libre"/);
  assert.match(html, /id="nueva-rol-libre"/);
  assert.match(html, /<form/);
  assert.match(html, /type="submit"/);
  assert.equal(html.match(/type="password"/g)?.length ?? 0, 2);
  assert.match(html, /sin tener que cambiarla/);
});

test('el alta manual anticipa el usuario normalizado y conserva los dos roles permitidos', () => {
  const html = renderToStaticMarkup(dialogoVacio({ usuarioLibreInicial: '  Maria.Cocina ' }));
  assert.match(html, /Va a quedar: maria\.cocina/);
  assert.match(html, /value="cocinera"/);
  assert.match(html, /value="jefa"/);
  assert.doesNotMatch(html, /value="sistemas"/);
  assert.doesNotMatch(html, /readOnly/);
});

// -------------------------------------------------------------
// 10. Confirmación y cambio de clave
// -------------------------------------------------------------
test('Desactivar y Reactivar piden confirmación', () => {
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

  const htmlReactivar = renderToStaticMarkup(
    h(DialogoConfirmacion, {
      confirmacion: { tipo: 'reactivar', cuenta: cuenta() },
      onConfirmar() {},
      onCancelar() {},
    }),
  );
  assert.match(htmlReactivar, /Reactivar cuenta/);
});

test('Eliminar advierte que oculta y desactiva conservando los registros', () => {
  const html = renderToStaticMarkup(h(DialogoConfirmacion, {
    confirmacion: { tipo: 'eliminar', cuenta: cuenta() },
    onConfirmar() {}, onCancelar() {},
  }));
  assert.match(html, /Eliminar cuenta/);
  assert.match(html, /Quedará desactivada/);
  assert.match(html, /Sus datos y registros se conservarán/);
  assert.match(html, />Cancelar</);
});

test('Editar abre los datos actuales y protege usuario y rol Sistemas', () => {
  const html = renderToStaticMarkup(h(DialogoEditarCuenta, {
    cuenta: cuenta({ vinculada: false }), onGuardada() {}, onCerrar() {},
  }));
  assert.match(html, /Editar cuenta/);
  assert.match(html, /value="María Cocina"/);
  assert.match(html, /id="editar-usuario"[^>]*readOnly/);
  assert.match(html, /<option value="cocinera" selected=""/);
  assert.match(html, /type="submit"[^>]*disabled/);
  assert.doesNotMatch(html, /type="password"/);
  const sistemas = renderToStaticMarkup(h(DialogoEditarCuenta, {
    cuenta: cuenta({ rol: 'sistemas', vinculada: false }), onGuardada() {}, onCerrar() {},
  }));
  assert.match(sistemas, /id="editar-rol"[^>]*disabled/);
});

test('editarCuenta envía PATCH de nombre y rol sin cambiar usuario ni contraseña', async () => {
  globalThis.fetch = async (url, opciones) => {
    assert.equal(new URL(url).pathname, '/admin/cuentas/7');
    assert.equal(opciones.method, 'PATCH');
    assert.deepEqual(JSON.parse(opciones.body), { nombre: 'Sandra Lima', rol: 'jefa' });
    return json(cuentaApi({ nombre: 'Sandra Lima', rol: 'jefa' }));
  };
  const respuesta = await editarCuenta(7, { nombre: ' Sandra Lima ', rol: 'jefa', username: 'no-se-envia' });
  assert.equal(respuesta.nombre, 'Sandra Lima');
  assert.equal(respuesta.rol, 'jefa');
  for (const cambios of [{}, { nombre: '   ' }, { rol: 'administrador' }]) {
    await assert.rejects(editarCuenta(7, cambios));
  }
  globalThis.fetch = async () => json({ motivo: 'rol_sistemas_protegido' }, 409);
  await assert.rejects(editarCuenta(7, { rol: 'jefa' }), /Sistemas/);
});

test('eliminarCuenta usa DELETE sin cuerpo, acepta 204 y propaga errores', async () => {
  globalThis.fetch = async (url, opciones) => {
    assert.equal(new URL(url).pathname, '/admin/cuentas/7');
    assert.equal(opciones.method, 'DELETE');
    assert.equal(opciones.body, undefined);
    return new Response(null, { status: 204 });
  };
  assert.equal(await eliminarCuenta(7), undefined);
  await assert.rejects(eliminarCuenta(0), /Cuenta inválida/);
  globalThis.fetch = async () => json({ motivo: 'ultima_cuenta_sistemas' }, 409);
  await assert.rejects(eliminarCuenta(7), /última cuenta de Sistemas/);
  globalThis.fetch = async () => json({ detail: 'fallo' }, 500);
  await assert.rejects(eliminarCuenta(7), /No se pudo eliminar/);
});

test('Cambiar clave abre un diálogo con dos campos de contraseña y aviso de sesiones', () => {
  const html = renderToStaticMarkup(
    h(Administracion, {
      cargandoInicial: false,
      cuentasIniciales: [cuenta()],
      cambioClaveInicial: cuenta(),
    }),
  );
  assert.match(html, /Cambiar clave de maria\.cocina/);
  assert.equal(html.match(/type="password"/g)?.length ?? 0, 2);
  assert.match(html, /se cerrará/);
  assert.match(html, />Guardar contraseña</);
  assert.doesNotMatch(html, /Clave temporal de/);
});

test('el diálogo de cambio no envía nada hasta pulsar Guardar', async () => {
  // Abrirlo o escribir no llama al servidor: solo «Guardar contraseña» envía.
  const enviados = [];
  const cambiar = async (id, clave) => { enviados.push([id, clave]); return { cuenta: cuenta() }; };
  const html = renderToStaticMarkup(h(DialogoCambiarClave, {
    cuenta: cuenta(), onCambiada() {}, onCerrar() {}, cambiar, claveInicial: CLAVE,
  }));
  assert.match(html, new RegExp(`value="${CLAVE}"`));
  assert.deepEqual(enviados, []);
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

test('tras crear, avisa que ya puede ingresar y la tabla se relee', async () => {
  const avisos = [];
  let releidas = 0;
  await finalizarCreacionCuenta({
    resultado: { cuenta: cuenta({ username: 'nueva.cuenta' }) },
    setAviso: (aviso) => avisos.push(aviso),
    recargar: async () => { releidas += 1; },
  });
  assert.equal(releidas, 1);
  assert.match(avisos[0].titulo, /nueva\.cuenta/);
  assert.match(avisos[0].detalle, /contraseña que eligió/);
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
test('la contraseña nunca va a storage ni a la consola', async () => {
  const SECRETA = 'Secreta-elegida-xyz';
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
    renderToStaticMarkup(dialogoVacio({ usuarioLibreInicial: 'x', claveInicial: SECRETA }));
    renderToStaticMarkup(h(DialogoCambiarClave, { cuenta: cuenta(), onCambiada() {}, onCerrar() {}, claveInicial: SECRETA }));
    globalThis.fetch = async () => json({ cuenta: cuentaApi() }, 201);
    await crearCuenta({ rol: 'cocinera', usuarioTurnosId: 44, password: SECRETA });
    await cambiarClaveCuenta(7, SECRETA);
    assert.ok(guardado.every((valor) => !valor.includes(SECRETA)), 'la contraseña llegó a storage');
    assert.ok(consola.every((linea) => !linea.includes(SECRETA)), 'la contraseña llegó a la consola');
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
