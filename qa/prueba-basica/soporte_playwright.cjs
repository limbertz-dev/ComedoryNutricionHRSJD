/** Circuito QA real: sin respuestas interceptadas, claves fijas ni aprobación implícita. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const APP = 'http://127.0.0.1:5173', API = 'http://127.0.0.1:8001', LAB = 'http://127.0.0.1:8002';
const evidencias = path.join(__dirname, 'evidencias');

function navegador() {
  const opciones = [process.env.QA_PLAYWRIGHT, path.resolve(__dirname, '../../comedorfront/node_modules/playwright')].filter(Boolean);
  const cache = path.join(process.env.LOCALAPPDATA || '', 'npm-cache/_npx');
  if (fs.existsSync(cache)) for (const carpeta of fs.readdirSync(cache)) opciones.push(path.join(cache, carpeta, 'node_modules/playwright'));
  for (const ruta of opciones) if (fs.existsSync(path.join(ruta, 'package.json'))) return require(ruta).chromium;
  throw new Error('Falta Playwright. Indica su instalación con QA_PLAYWRIGHT.');
}

function credencial(cuenta) {
  const valor = process.env[`QA_CLAVE_${cuenta.toUpperCase()}`] || process.env.QA_CLAVE;
  if (valor) return valor;
  const entrada = spawnSync(path.resolve(__dirname, '../../comedorback/.venv/Scripts/python.exe'),
    ['-B', '-c', 'import getpass,sys; sys.stdout.write(getpass.getpass(sys.argv[1]))', `[${cuenta}] Contraseña definitiva (oculta): `],
    { stdio: ['inherit', 'pipe', 'inherit'], encoding: 'utf8' });
  assert.equal(entrada.status, 0, 'No se pudo leer la contraseña.');
  assert.ok(entrada.stdout, `Falta la contraseña para ${cuenta}.`);
  return entrada.stdout;
}

async function esperar(condicion, mensaje) {
  const limite = Date.now() + 25_000;
  while (Date.now() < limite) {
    if (await condicion()) return;
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error(mensaje);
}

async function salud() {
  await esperar(async () => {
    try {
      const res = await fetch(`${API}/salud`, { signal: AbortSignal.timeout(2000) });
      if (!res.ok) return false;
      const d = await res.json();
      for (const [campo, valor] of Object.entries({ estado: 'ok', entorno: 'desarrollo', base_datos: 'bd_nutricion_escenario_sim', base_turnos: 'bd_turnos_escenario_demo', revision_alembic: 'b3e5f7a9c1d4' })) assert.equal(d[campo], valor);
      return true;
    } catch (error) { if (error instanceof assert.AssertionError) throw error; return false; }
  }, 'La API QA no respondió con una salud válida en 25 segundos.');
}

async function clienteLab() {
  const res = await fetch(LAB, { signal: AbortSignal.timeout(4000) });
  assert.equal(res.status, 200, 'Enciende el laboratorio QA en el puerto 8002.');
  const token = (await res.text()).match(/name="qa-control"\s+content="([^"]+)"/)?.[1];
  assert.ok(token, 'Falta el control de sesión del laboratorio.');
  return async (ruta, cuerpo) => {
    const respuesta = await fetch(`${LAB}${ruta}`, { method: cuerpo ? 'POST' : 'GET',
      headers: { 'Content-Type': 'application/json', 'X-QA-Control': token },
      ...(cuerpo ? { body: JSON.stringify(cuerpo) } : {}), signal: AbortSignal.timeout(90_000) });
    const datos = await respuesta.json();
    assert.equal(respuesta.status, 200, datos.error || `Falló el laboratorio: ${ruta}`);
    return datos;
  };
}

async function peticion(page, ruta, metodo = 'GET', cuerpo) {
  return page.evaluate(async ({ api, ruta, metodo, cuerpo }) => {
    const access = JSON.parse(sessionStorage.getItem('comedor_sesion'))?.access;
    const res = await fetch(api + ruta, { method: metodo,
      headers: { Authorization: `Bearer ${access}`, 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
      ...(cuerpo ? { body: JSON.stringify(cuerpo) } : {}) });
    return { status: res.status, datos: await res.json() };
  }, { api: API, ruta, metodo, cuerpo });
}

async function irAControlBiometrico(page) {
  await page.getByRole('region', { name: 'Checklist de comida', exact: true }).waitFor();
  await page.getByRole('button', { name: 'Menú de sesión', exact: true }).click();
  await page.getByRole('button', { name: 'Ir a Control Biométrico', exact: true }).click();
  await page.getByText('Marcaciones del turno', { exact: true }).first().waitFor();
}

async function elegirEnLista(page, selector, valor) {
  await page.locator(selector).click();
  await page.locator(`${selector} ~ .app-select-menu [data-value="${valor}"]`).click();
}

async function sesion(browser, cuenta, clave) {
  const contexto = await browser.newContext({ viewport: { width: 1366, height: 768 }, locale: 'es-BO' });
  const page = await contexto.newPage();
  page.setDefaultTimeout(15_000);
  await page.goto(APP);
  await page.locator('#login-usuario').fill(cuenta);
  await page.locator('#login-contrasena').fill(clave);
  const login = page.waitForResponse(res => res.url().endsWith('/auth/login') && res.request().method() === 'POST');
  await page.locator('button[type="submit"]').click();
  assert.equal((await login).status(), 200, `Login falló para ${cuenta}; no se reintenta.`);
  const yo = await peticion(page, '/auth/yo');
  assert.equal(yo.status, 200);
  assert.equal(yo.datos.username, cuenta);
  assert.equal(yo.datos.rol, cuenta === 'jefa' ? 'jefa' : 'cocinera');
  assert.equal(yo.datos.debe_cambiar, false);
  // La cocinera abre en el checklist; estos flujos operan Control Biométrico.
  if (yo.datos.rol === 'cocinera') await irAControlBiometrico(page);
  return { page, usuario: yo.datos, cerrar: () => contexto.close() };
}

async function registrar(page, uid) {
  await page.getByRole('button', { name: 'Nuevo registro de huella', exact: true }).click();
  await elegirEnLista(page, '#huella-persona', String(uid));
  const captura = page.waitForResponse(res => res.url().endsWith('/_qa/enrolamiento/capturas') && res.request().method() === 'POST');
  await page.getByRole('button', { name: 'Simular captura', exact: true }).click();
  const res = await captura;
  assert.equal(res.status(), 200);
  assert.equal((await res.json()).usuario_id, uid);
  await page.getByRole('heading', { name: 'Huella registrada', exact: true }).waitFor();
}

async function leer(page, uid, motivo = null) {
  const lectura = page.waitForResponse(res => res.url().endsWith('/_qa/enrolamiento/lecturas') && res.request().method() === 'POST');
  await page.getByRole('button', { name: /^(Leer huella de prueba|Volver a leer)$/ }).click();
  const res = await lectura;
  assert.equal(res.status(), 200);
  const d = await res.json();
  assert.equal(d.usuario_id, uid);
  assert.equal(d.valido, motivo === null);
  assert.equal(d.motivo, motivo);
  assert.ok(Number.isSafeInteger(d.lectura_id) && d.lectura_id > 0);
  assert.equal(Number.isSafeInteger(d.asistencia_id) && d.asistencia_id > 0, motivo === null);
  await page.getByText(motivo ? 'Huella reconocida · Entrega rechazada' : 'Huella reconocida · Entrega registrada', { exact: true }).waitFor();
  return d;
}

function comprobarIntervencion(filas, lecturaId) {
  const fila = filas.find(f => f.decision_original?.lectura_id === lecturaId);
  assert.ok(fila, `La jefa no ve la intervención de la lectura ${lecturaId}.`);
  assert.equal(fila.cuenta.usuario, 'cocinera2');
  assert.equal(fila.resultado, 'registrada');
  assert.equal(fila.comensal.usuario_id, 900102);
  return fila;
}

function verificarReglasOffline() {
  const raiz = path.resolve(__dirname, '../..');
  const entorno = { ...process.env, PYTEST_DISABLE_PLUGIN_AUTOLOAD: '1', PYTHONDONTWRITEBYTECODE: '1' };
  for (const nombre of Object.keys(entorno)) if (nombre.startsWith('QA_CLAVE')) delete entorno[nombre];
  const resultado = spawnSync(path.join(raiz, 'comedorback/.venv/Scripts/python.exe'), ['-B', '-m', 'pytest',
    'qa/prueba-basica/test_perfiles_lectura.py', 'qa/prueba-basica/test_servicios_diario.py',
    '-k', 'huella_preexistente_no_habilita_categoria_excluida or cocina_no_puede_eludir_exclusion_de_categoria or duracion_del_turno_no_se_elude',
    '-q', '-p', 'no:cacheprovider', '--confcutdir=qa/prueba-basica', '--tb=short'],
  { cwd: raiz, env: entorno, encoding: 'utf8', timeout: 60_000 });
  assert.equal(resultado.status, 0, 'Fallaron las reglas offline de categoría o duración. Ejecuta pytest para ver el detalle.');
  return 'SQLite real: rechazo biométrico y manual; categorías excluidas, turnos de 8/11 h y límite permitido de 12 h.';
}

async function ejecutar({ completo }) {
  const claves = Object.fromEntries(['cocinera1', 'cocinera2', 'cocinera3', 'jefa'].map(c => [c, credencial(c)]));
  await salud();
  assert.equal((await fetch(APP)).status, 200, 'Enciende el frontend con npm.cmd run dev:qa.');
  const lab = await clienteLab();
  fs.mkdirSync(evidencias, { recursive: true });
  const visible = process.argv.includes('--visible') || process.argv.includes('--headed');
  const browser = await navegador().launch({ headless: !visible, slowMo: visible ? 150 : 0 });
  const resultados = [], lecturas = [];
  const aprobar = (caso, evidencia) => { resultados.push({ caso, estado: 'APROBADO', evidencia }); console.log(`PASA: ${caso}`); };
  let abierta, fase = 'Preparación';
  try {
    const reglas = verificarReglasOffline();
    resultados.push({ caso: 'Categorías excluidas y turno insuficiente (sin MySQL)', estado: 'APROBADO OFFLINE', evidencia: reglas });
    await lab('/nuevo', { confirmar: true, momento: '2026-10-19T08:00:00', modo: 'fijo', comida_id: 1 });
    await salud();
    fase = 'Desayuno normal y duplicado';
    abierta = await sesion(browser, 'cocinera1', claves.cocinera1);
    const inicial = await peticion(abierta.page, '/pantalla/estado');
    assert.equal(inicial.datos.comida, 'Desayuno');
    await registrar(abierta.page, 900101);
    const desayuno = await leer(abierta.page, 900101); lecturas.push(desayuno);
    aprobar('Desayuno: entrega reconocida', desayuno.lectura_id);
    const duplicado = await leer(abierta.page, 900101, 'duplicado'); lecturas.push(duplicado);
    aprobar('Segunda ración rechazada', duplicado.lectura_id);
    await abierta.cerrar(); abierta = null;

    fase = 'Descanso: mostrar Desayuno y rechazar entrega real';
    await lab('/horario', { momento: '2026-10-19T10:30:00', modo: 'fijo' });
    abierta = await sesion(browser, 'cocinera1', claves.cocinera1);
    const descanso = await peticion(abierta.page, '/pantalla/estado');
    assert.equal(descanso.datos.fuera_de_horario, true);
    assert.equal(descanso.datos.comida, 'Desayuno');
    await abierta.page.getByText('Último servicio · Cerrado', { exact: true }).waitFor();
    await registrar(abierta.page, 900101);
    const rechazo = await leer(abierta.page, 900101, 'fuera_horario'); lecturas.push(rechazo);
    aprobar('Descanso: último servicio visible y backend rechaza la lectura', rechazo.lectura_id);
    await abierta.cerrar(); abierta = null;

    fase = 'Almuerzo normal';
    await lab('/horario', { momento: '2026-10-19T12:00:00', modo: 'fijo', comida_id: 2 });
    abierta = await sesion(browser, 'cocinera1', claves.cocinera1);
    await registrar(abierta.page, 900101);
    const almuerzo = await leer(abierta.page, 900101); lecturas.push(almuerzo);
    aprobar('Almuerzo: entrega reconocida', almuerzo.lectura_id);
    await abierta.cerrar(); abierta = null;

    fase = 'Huella no reconocida e identificación por cocina';
    abierta = await sesion(browser, 'cocinera2', claves.cocinera2);
    const padron = await peticion(abierta.page, '/_qa/enrolamiento/personas');
    assert.equal(padron.status, 200);
    for (const uid of [900001, 900003]) {
      assert.ok(!padron.datos.some(p => p.id === uid), 'El padrón ofrece una categoría excluida.');
      const alta = await peticion(abierta.page, '/_qa/enrolamiento/capturas', 'POST', { usuario_id: uid });
      assert.equal(alta.status, 403, 'El backend permitió enrolar una categoría excluida.');
    }
    aprobar('Alta: Administrativo y Enfermería excluidos por padrón y API', 'HTTP 403 para ambos perfiles sintéticos');
    await registrar(abierta.page, 900102);
    await abierta.page.getByRole('button', { name: 'Volver a marcaciones', exact: true }).click();
    await lab('/simular', { caso: 'qa02' });
    await abierta.page.locator('ul.identificar__lista').getByRole('button', { name: 'Identificar', exact: true }).click();
    assert.equal(await abierta.page.locator('#identificar-persona').inputValue(), '');
    await abierta.page.locator('#identificar-persona').selectOption('900102');
    const confirmacion = abierta.page.waitForResponse(res => /\/asistencias\/lecturas\/\d+\/identificar$/.test(res.url()) && res.request().method() === 'POST');
    await abierta.page.getByRole('button', { name: 'Confirmar entrega', exact: true }).click();
    const respuesta = await confirmacion;
    assert.equal(respuesta.status(), 200);
    const manual = await respuesta.json();
    assert.equal(manual.valido, true);
    assert.ok(manual.asistencia_id > 0 && manual.lectura_id > 0);
    aprobar('Cocinera2 confirma una entrega manual', manual.lectura_id);
    await abierta.cerrar(); abierta = null;

    if (completo) for (const [hora, comida, cuenta, uid] of [
      ['16:00:00', 3, 'cocinera3', 900103], ['19:00:00', 4, 'cocinera1', 900101],
    ]) {
      fase = `Entrega de comida ${comida}`;
      await lab('/horario', { momento: `2026-10-19T${hora}`, modo: 'fijo', comida_id: comida });
      abierta = await sesion(browser, cuenta, claves[cuenta]);
      await registrar(abierta.page, uid);
      const entrega = await leer(abierta.page, uid); assert.equal(entrega.comida_id, comida); lecturas.push(entrega);
      aprobar(comida === 3 ? 'Té: entrega reconocida' : 'Cena: entrega reconocida', entrega.lectura_id);
      await abierta.cerrar(); abierta = null;
    }

    fase = 'Supervisión: datos y tabla de intervenciones';
    abierta = await sesion(browser, 'jefa', claves.jefa);
    // La tabla abre en la comida en curso: contar filas solo cuando llega «Todas».
    const todas = abierta.page.waitForResponse(res => res.url().includes('/pantalla/ultimas-marcaciones') && !res.url().includes('comida_id='));
    await abierta.page.locator('button.supervision__pestana', { hasText: 'Todas' }).click();
    assert.equal((await todas).status(), 200);
    await abierta.page.locator('table.supervision__tabla tbody tr').filter({ hasText: 'Desayuno' }).first().waitFor();
    const consulta = await peticion(abierta.page, '/intervenciones-cocina?usuario_id=900102&desde=2026-10-19&hasta=2026-10-19');
    assert.equal(consulta.status, 200);
    const filas = consulta.datos.datos ?? consulta.datos.items ?? consulta.datos.intervenciones;
    assert.ok(Array.isArray(filas), 'Contrato de intervenciones inválido.');
    const intervencion = comprobarIntervencion(filas, manual.lectura_id);
    assert.equal(intervencion.resultado_final.asistencia_id, manual.asistencia_id);
    assert.equal(intervencion.resultado_final.entrega_registrada, true);
    assert.equal(intervencion.decision_original.resultado, 'rechazada');
    assert.equal(intervencion.decision_original.motivo, 'no_identificado');
    const fila = abierta.page.getByRole('table', { name: 'Intervenciones de cocina', exact: true }).locator('tbody tr').filter({ hasText: 'QA 02 IDENTIFICACION' });
    await fila.waitFor();
    assert.equal(await fila.count(), 1, 'Falta la fila de QA02 o está duplicada.');
    const celdas = await fila.locator('td').allTextContents();
    assert.match(celdas[2], /Almuerzo/); assert.match(celdas[3], /cocinera2/);
    assert.match(celdas[4], /Rechazada.*Huella no reconocida/); assert.match(celdas[5], /Entrega registrada/);
    aprobar('Jefa: intervención exacta, rechazo original conservado y actor cocinera2', manual.lectura_id);
    const marcaciones = abierta.page.locator('table.supervision__tabla tbody tr');
    for (const entrega of lecturas.filter(f => f.valido)) {
      assert.ok(await marcaciones.filter({ hasText: entrega.nombre }).filter({ hasText: entrega.comida }).count() > 0, `Falta la entrega de ${entrega.comida}.`);
    }
    assert.ok(await marcaciones.filter({ hasText: 'duplicado' }).count() > 0);
    aprobar('Supervisión: entregas por comida y duplicado presentes', lecturas.length);
    await abierta.page.screenshot({ path: path.join(evidencias, 'revision-4comidas-supervision.png'), fullPage: true });
    await abierta.cerrar(); abierta = null;
    console.table(resultados);
  } catch (error) {
    resultados.push({ caso: fase, estado: 'FALLA', evidencia: error instanceof assert.AssertionError ? error.message.split('\n')[0] : error.message.split('\n')[0] });
    throw new Error(`FALLA en ${fase}: ${resultados.at(-1).evidencia}`);
  } finally {
    fs.writeFileSync(path.join(evidencias, 'revision-4comidas-resultados.json'), JSON.stringify({ completo, resultados,
      lecturas: lecturas.map(({ lectura_id, asistencia_id, usuario_id, comida_id, valido, motivo }) => ({ lectura_id, asistencia_id, usuario_id, comida_id, valido, motivo })) }, null, 2));
    if (abierta) await abierta.cerrar();
    await browser.close();
  }
}
module.exports = { ejecutar, comprobarIntervencion, navegador, credencial, clienteLab, salud, sesion, peticion, esperar };
