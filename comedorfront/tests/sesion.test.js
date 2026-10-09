import test, { afterEach, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { cambiarContrasena, iniciarSesion, momentoDeReintento, obtenerEstadoPantalla,
  obtenerPersonal, obtenerUsuarioActual } from '../src/api.js';
import { SESION_INICIAL, accionDeAviso, accionDeIngreso, borrarTokens, escucharSesion,
  guardarTokens, leerTokens, reductorSesion, textoDeReintento } from '../src/sesion.js';
import { puedeMarcarManual, puedeVerSeccion, resolverSeccionGuardada, seccionInicialDeRol,
  seccionesPermitidas } from '../src/permisos.js';
import { restaurarSesion } from '../src/hooks/useSesion.js';

/* sessionStorage mínimo: en Node no existe y los tokens deben sobrevivir al "F5". */
const almacen = new Map();
globalThis.sessionStorage = {
  getItem: (clave) => (almacen.has(clave) ? almacen.get(clave) : null),
  setItem: (clave, valor) => almacen.set(clave, String(valor)),
  removeItem: (clave) => almacen.delete(clave),
};

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
  borrarTokens();
});

/** Aplica al reductor una lista de acciones desde un estado dado. */
const recorrer = (estado, ...acciones) => acciones.reduce(reductorSesion, estado);
const ACTIVA_JEFA = { fase: 'activa', rol: 'jefa', usuario: 'ntarifa', aviso: null };

// --- Guardia por rol ---

test('guardia por rol: cocinera 1 sección, jefa 5, sistemas 7 con reglas, admin y monitoreo, rol desconocido ninguna', () => {
  assert.deepEqual(seccionesPermitidas('cocinera'), ['vivo']);
  assert.deepEqual(seccionesPermitidas('jefa'), ['supervision', 'dashboard', 'historial', 'reportes', 'cuentas']);
  assert.deepEqual(seccionesPermitidas('sistemas'), ['supervision', 'dashboard', 'historial', 'reportes', 'reglas', 'admin', 'monitoreo']);
  assert.deepEqual(seccionesPermitidas(' Jefa '), seccionesPermitidas('jefa'));
  for (const rol of ['nutricionista', '', null, undefined, 42]) {
    assert.deepEqual(seccionesPermitidas(rol), [], `rol ${rol} debe negarse por defecto`);
    assert.equal(seccionInicialDeRol(rol), null);
  }
  for (const id of ['supervision', 'dashboard', 'historial', 'reportes', 'inexistente']) {
    assert.equal(puedeVerSeccion('cocinera', id), false, `cocinera no ve ${id}`);
  }
  assert.equal(puedeVerSeccion('cocinera', 'vivo'), true);
  assert.equal(puedeVerSeccion('jefa', 'vivo'), false);
  assert.equal(puedeVerSeccion('jefa', 'supervision'), true);
  assert.equal(puedeVerSeccion('jefa', 'reportes'), true);
});

test('el modo manual se oculta a la cocinera y solo a ella', () => {
  assert.equal(puedeMarcarManual('cocinera'), false);
  assert.equal(puedeMarcarManual('jefa'), true);
  assert.equal(puedeMarcarManual('sistemas'), true);
  assert.equal(puedeMarcarManual('desconocido'), false);
});

test('redirect cocinera: la sección que dejó la jefa en la PC compartida la manda a Control Biométrico', () => {
  assert.equal(resolverSeccionGuardada('cocinera', 'reportes'), 'vivo');
  assert.equal(resolverSeccionGuardada('cocinera', 'historial'), 'vivo');
  assert.equal(resolverSeccionGuardada('cocinera', 'supervision'), 'vivo');
  assert.equal(resolverSeccionGuardada('cocinera', null), 'vivo');
  assert.equal(resolverSeccionGuardada('jefa', 'reportes'), 'reportes');
  assert.equal(resolverSeccionGuardada('jefa', 'vivo'), 'supervision');
  assert.equal(resolverSeccionGuardada('sistemas', 'vivo'), 'supervision');
  assert.equal(resolverSeccionGuardada('jefa', 'basura'), 'supervision');
  assert.equal(resolverSeccionGuardada('nutricionista', 'reportes'), null);
});

// --- POST /auth/login según contrato ---

test('login 200 guarda los tokens y firma las peticiones siguientes con Authorization', async () => {
  const peticiones = [];
  globalThis.fetch = async (ruta, opciones) => {
    peticiones.push({ ruta: new URL(ruta).pathname, opciones });
    if (new URL(ruta).pathname === '/auth/login') {
      return json({ access: 'acc-1', refresh: 'ref-1', rol: 'jefa', debe_cambiar: false });
    }
    return json({ id: 1, username: 'ntarifa', rol: 'jefa', debe_cambiar: false });
  };
  const resultado = await iniciarSesion('ntarifa', 'secreta');
  assert.deepEqual(resultado, { tipo: 'ok', rol: 'jefa', debeCambiar: false });
  assert.equal(peticiones[0].opciones.method, 'POST');
  assert.equal(peticiones[0].opciones.headers.Authorization, undefined);
  assert.deepEqual(JSON.parse(peticiones[0].opciones.body), { username: 'ntarifa', password: 'secreta' });
  assert.deepEqual(leerTokens(), { access: 'acc-1', refresh: 'ref-1', usuario: 'ntarifa' });
  assert.deepEqual(accionDeIngreso(resultado, 'ntarifa'), { tipo: 'INGRESO', rol: 'jefa', usuario: 'ntarifa' });

  assert.deepEqual(await obtenerUsuarioActual(), { id: 1, username: 'ntarifa', rol: 'jefa', debeCambiar: false });
  assert.equal(peticiones[1].ruta, '/auth/yo');
  assert.equal(peticiones[1].opciones.headers.Authorization, 'Bearer acc-1');
});

test('login 401 es credencial incorrecta con el detalle del servidor, no «sesión expirada»', async () => {
  guardarTokens({ access: 'viejo', refresh: null, usuario: 'otra' });
  globalThis.fetch = async () => json({ detail: 'Usuario o contraseña incorrectos.', motivo: 'credenciales_invalidas' }, 401);
  const resultado = await iniciarSesion('ntarifa', 'mal');
  assert.deepEqual(resultado, { tipo: 'credencial', detalle: 'Usuario o contraseña incorrectos.' });
  assert.equal(accionDeIngreso(resultado, 'ntarifa'), null);
  assert.deepEqual(avisos, []);
});

test('login 423 es cuenta bloqueada con la hora de reintento', async () => {
  globalThis.fetch = async () => json({ detail: 'Cuenta bloqueada por intentos fallidos. Intente más tarde.',
    motivo: 'cuenta_bloqueada', reintento_en: '2026-09-24T15:30:00Z' }, 423);
  const resultado = await iniciarSesion('ntarifa', 'mal');
  assert.equal(resultado.tipo, 'bloqueada');
  assert.equal(resultado.detalle, 'Cuenta bloqueada por intentos fallidos. Intente más tarde.');
  assert.equal(resultado.reintentoEn.toISOString(), '2026-09-24T15:30:00.000Z');
  assert.equal(leerTokens(), null);
});

test('reintento_en acepta segundos o fecha ISO y el texto cuenta hacia atrás', () => {
  const ahora = new Date('2026-09-24T12:00:00Z');
  assert.equal(momentoDeReintento(300, ahora).toISOString(), '2026-09-24T12:05:00.000Z');
  assert.equal(momentoDeReintento('90', ahora).toISOString(), '2026-09-24T12:01:30.000Z');
  assert.equal(momentoDeReintento('2026-09-24T12:10:00Z', ahora).toISOString(), '2026-09-24T12:10:00.000Z');
  assert.equal(momentoDeReintento(undefined, ahora), null);
  assert.equal(momentoDeReintento('mañana', ahora), null);

  assert.match(textoDeReintento(new Date('2026-09-24T12:05:00Z'), ahora), /en 5 minutos/);
  assert.match(textoDeReintento(new Date('2026-09-24T12:00:30Z'), ahora), /en 30 segundos/);
  assert.equal(textoDeReintento(new Date('2026-09-24T11:59:00Z'), ahora), '');
  assert.equal(textoDeReintento(null, ahora), 'Intente de nuevo más tarde.');
});

test('login con una respuesta 200 sin la forma del contrato no abre sesión', async () => {
  globalThis.fetch = async () => json({ token: 'x', rol: 'jefa' });
  await assert.rejects(iniciarSesion('ntarifa', 'secreta'), /sesión inválida/);
  assert.equal(leerTokens(), null);
});

// --- Flujo 428: cambio obligatorio ---

test('flujo 428: login pide cambio, se cambia la contraseña y el 200 hidrata sin segundo login', async () => {
  const peticiones = [];
  globalThis.fetch = async (ruta, opciones) => {
    const camino = new URL(ruta).pathname;
    const cuerpo = JSON.parse(opciones.body ?? 'null');
    peticiones.push({ camino, cuerpo, auth: opciones.headers.Authorization });
    if (camino === '/auth/login') {
      return json({ detail: 'Debe cambiar la contraseña temporal.', motivo: 'cambio_password_pendiente', temporal: 'temp-1' }, 428);
    }
    if (camino === '/auth/cambio-password') {
      return json({ access: 'acc-nuevo', refresh: 'ref-nuevo', rol: 'cocinera', debe_cambiar: false });
    }
    throw new Error(`ruta inesperada ${camino}`);
  };

  const primero = await iniciarSesion('cocina1', 'Temporal123');
  assert.deepEqual(primero, { tipo: 'cambio' });
  assert.equal(peticiones[0].cuerpo.username, 'cocina1');
  assert.equal(leerTokens().access, 'temp-1', 'el temporal queda guardado para firmar el cambio');
  let estado = recorrer({ ...SESION_INICIAL, fase: 'anonima' }, accionDeIngreso(primero, 'cocina1'));
  assert.equal(estado.fase, 'cambio');
  assert.equal(estado.rol, null, 'sin rol no se monta el panel');
  assert.equal(estado.usuario, 'cocina1');

  const final = await cambiarContrasena({ usuario: 'cocina1', nueva: 'Nueva#2026' });
  assert.deepEqual(final, { tipo: 'ok', rol: 'cocinera', debeCambiar: false });
  estado = recorrer(estado, accionDeIngreso(final, 'cocina1'));
  assert.deepEqual(estado, { fase: 'activa', rol: 'cocinera', usuario: 'cocina1', aviso: null });

  assert.deepEqual(peticiones.map(({ camino }) => camino),
    ['/auth/login', '/auth/cambio-password']);
  assert.deepEqual(peticiones[1].cuerpo, { password_nueva: 'Nueva#2026' });
  assert.equal(peticiones[1].auth, 'Bearer temp-1');
  assert.equal(leerTokens().access, 'acc-nuevo');
  assert.deepEqual(avisos, [], 'el 428 del login lo resuelve el formulario, no el aviso global');
});

test('flujo 428: 200 con debe_cambiar lleva al cambio y el cambio va firmado con ese token', async () => {
  const llamadas = [];
  globalThis.fetch = async (ruta, opciones) => {
    llamadas.push({ camino: new URL(ruta).pathname, auth: opciones.headers.Authorization, cuerpo: JSON.parse(opciones.body) });
    if (new URL(ruta).pathname === '/auth/cambio-password') {
      return json({ access: 'acc-ok', refresh: 'r2', rol: 'jefa', debe_cambiar: false });
    }
    return json({ access: 'acc-temp', refresh: 'r', rol: 'jefa', debe_cambiar: true });
  };
  const resultado = await iniciarSesion('ntarifa', 'Temporal1');
  assert.deepEqual(accionDeIngreso(resultado, 'ntarifa'), { tipo: 'CAMBIO_REQUERIDO', usuario: 'ntarifa' });
  const final = await cambiarContrasena({ usuario: 'ntarifa', nueva: 'Otra#2026' });
  assert.deepEqual(final, { tipo: 'ok', rol: 'jefa', debeCambiar: false });
  assert.deepEqual(llamadas.map(({ camino }) => camino), ['/auth/login', '/auth/cambio-password']);
  assert.equal(llamadas[1].auth, 'Bearer acc-temp');
  assert.deepEqual(llamadas[1].cuerpo, { password_nueva: 'Otra#2026' });
});

test('flujo 428: un 428 desde cualquier sección saca del panel al cambio de contraseña', async () => {
  guardarTokens({ access: 'acc', refresh: null, usuario: 'ntarifa' });
  globalThis.fetch = async () => json({ detail: 'Debe cambiar su contraseña temporal.', motivo: 'cambio_password_pendiente', temporal: 'temp-2' }, 428);
  await assert.rejects(obtenerEstadoPantalla(), /cambiar su contraseña/);
  assert.deepEqual(avisos, ['cambio_requerido']);
  assert.equal(leerTokens().access, 'temp-2', 'el temporal del 428 queda para firmar el cambio');
  const estado = recorrer(ACTIVA_JEFA, accionDeAviso({ tipo: 'cambio_requerido' }));
  assert.equal(estado.fase, 'cambio');
  assert.equal(estado.usuario, 'ntarifa');
});

test('un cambio de contraseña rechazado muestra el detalle y no entra', async () => {
  globalThis.fetch = async () => json({ detail: 'La contraseña es demasiado corta', motivo: 'password_rechazada' }, 422);
  await assert.rejects(cambiarContrasena({ usuario: 'x', nueva: 'b' }), /demasiado corta/);
  assert.equal(leerTokens(), null);
});

// --- Sesión expirada → Login ---

test('expirado → login: un 401 en cualquier sección borra los tokens y vuelve con «Sesión expirada»', async () => {
  guardarTokens({ access: 'vencido', refresh: 'r', usuario: 'ntarifa' });
  globalThis.fetch = async () => json({ detail: 'Sesión inválida o vencida.', motivo: 'token_invalido' }, 401);
  await assert.rejects(obtenerPersonal(), /sesión expiró/);
  assert.equal(leerTokens(), null);
  assert.equal(sessionStorage.getItem('comedor_sesion'), null);
  assert.deepEqual(avisos, ['expirada']);
  const estado = recorrer(ACTIVA_JEFA, accionDeAviso({ tipo: 'expirada' }));
  assert.deepEqual(estado, { fase: 'anonima', rol: null, usuario: null, aviso: 'expirada' });
});

test('expirado → login: al abrir la app con un token vencido, GET /auth/yo 401 lleva al Login', async () => {
  guardarTokens({ access: 'vencido', refresh: 'r', usuario: 'ntarifa' });
  globalThis.fetch = async () => json({ detail: 'Sesión inválida o vencida.', motivo: 'token_invalido' }, 401);
  const accion = await restaurarSesion();
  assert.deepEqual(accion, { tipo: 'EXPIRADA' });
  assert.equal(recorrer(SESION_INICIAL, accion).aviso, 'expirada');
  assert.equal(leerTokens(), null);
});

test('un 401 rezagado no pisa el Login que ya se está mostrando', () => {
  const anonima = { fase: 'anonima', rol: null, usuario: null, aviso: null };
  assert.equal(recorrer(anonima, { tipo: 'EXPIRADA' }), anonima);
});

test('al abrir la app: sin tokens va al Login sin consultar; con tokens, GET /auth/yo da el rol', async () => {
  let llamadas = 0;
  globalThis.fetch = async (ruta, opciones) => {
    llamadas += 1;
    assert.equal(new URL(ruta).pathname, '/auth/yo');
    assert.equal(opciones.headers.Authorization, 'Bearer acc');
    return json({ id: 7, username: 'cocina1', rol: 'cocinera', debe_cambiar: false });
  };
  assert.deepEqual(await restaurarSesion(), { tipo: 'SIN_SESION' });
  assert.equal(llamadas, 0);

  guardarTokens({ access: 'acc', refresh: 'r', usuario: 'cocina1' });
  assert.deepEqual(await restaurarSesion(), { tipo: 'INGRESO', rol: 'cocinera', usuario: 'cocina1' });

  globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
  assert.deepEqual(await restaurarSesion(), { tipo: 'SIN_CONEXION' });
  assert.equal(leerTokens()?.access, 'acc', 'una caída de red no cierra la sesión');
});

// --- 403 del backend ---

test('un 403 avisa «sin permiso», no devuelve datos y no cierra la sesión', async () => {
  guardarTokens({ access: 'acc', refresh: null, usuario: 'cocina1' });
  globalThis.fetch = async () => json({ detail: 'Sin permiso.', motivo: 'rol_no_autorizado' }, 403);
  await assert.rejects(obtenerPersonal(), /No tiene permiso/);
  assert.deepEqual(avisos, ['prohibido']);
  assert.equal(accionDeAviso({ tipo: 'prohibido' }), null, 'la sesión sigue activa');
  assert.equal(leerTokens()?.access, 'acc');
});

// --- Refresh con reintento ---

test('refresh: un 401 token_expirado renueva y reintenta UNA vez sin avisar', async () => {
  guardarTokens({ access: 'vencido', refresh: 'ref-viejo', usuario: 'ntarifa' });
  const llamadas = [];
  globalThis.fetch = async (ruta, opciones) => {
    const camino = new URL(ruta).pathname;
    llamadas.push({ camino, auth: opciones.headers.Authorization, cuerpo: opciones.body ? JSON.parse(opciones.body) : null });
    if (camino === '/auth/refresh') {
      return json({ access: 'acc-nuevo', refresh: 'ref-viejo', rol: 'jefa', debe_cambiar: false });
    }
    if (llamadas.filter(({ camino: c }) => c === '/personal').length === 1) {
      return json({ detail: 'Sesión inválida o vencida.', motivo: 'token_expirado' }, 401);
    }
    return json({ total: 0, datos: [] });
  };
  assert.deepEqual(await obtenerPersonal(), []);
  assert.deepEqual(llamadas.map(({ camino }) => camino), ['/personal', '/auth/refresh', '/personal']);
  assert.deepEqual(llamadas[1].cuerpo, { refresh: 'ref-viejo' });
  assert.equal(llamadas[2].auth, 'Bearer acc-nuevo');
  assert.equal(leerTokens().access, 'acc-nuevo');
  assert.deepEqual(avisos, [], 'el reintento exitoso no avisa expiración');
});

test('refresh: si renovar falla, la sesión expira sin reintentar la sección', async () => {
  guardarTokens({ access: 'vencido', refresh: 'ref-viejo', usuario: 'ntarifa' });
  const caminos = [];
  globalThis.fetch = async (ruta) => {
    const camino = new URL(ruta).pathname;
    caminos.push(camino);
    if (camino === '/auth/refresh') {
      return json({ detail: 'Sesión inválida o vencida.', motivo: 'token_expirado' }, 401);
    }
    return json({ detail: 'Sesión inválida o vencida.', motivo: 'token_expirado' }, 401);
  };
  await assert.rejects(obtenerPersonal(), /sesión expiró/);
  assert.deepEqual(caminos, ['/personal', '/auth/refresh']);
  assert.equal(leerTokens(), null);
  assert.deepEqual(avisos, ['expirada']);
});

// --- Cambio y bloqueo desde cualquier llamada ---

test('un 403 cambio_password_pendiente desde una sección pide cambio, no «sin permiso»', async () => {
  guardarTokens({ access: 'acc', refresh: null, usuario: 'ntarifa' });
  globalThis.fetch = async () => json({ detail: 'Debe cambiar la contraseña temporal.', motivo: 'cambio_password_pendiente' }, 403);
  await assert.rejects(obtenerEstadoPantalla(), /No tiene permiso/);
  assert.deepEqual(avisos, ['cambio_requerido']);
  assert.equal(leerTokens()?.usuario, 'ntarifa');
  const estado = recorrer(ACTIVA_JEFA, accionDeAviso({ tipo: 'cambio_requerido' }));
  assert.equal(estado.fase, 'cambio');
});

test('login 423 sin reintento_en usa el header Retry-After', async () => {
  const antes = Date.now();
  globalThis.fetch = async () => new Response(JSON.stringify(
    { detail: 'Cuenta bloqueada.', motivo: 'cuenta_bloqueada' },
  ), { status: 423, headers: { 'Retry-After': '300' } });
  const resultado = await iniciarSesion('ntarifa', 'mal');
  assert.equal(resultado.tipo, 'bloqueada');
  assert.ok(resultado.reintentoEn instanceof Date);
  const espera = resultado.reintentoEn.getTime() - antes;
  assert.ok(espera > 290_000 && espera < 310_000, `espera ${espera} ms, debían ser ~300 s`);
});
