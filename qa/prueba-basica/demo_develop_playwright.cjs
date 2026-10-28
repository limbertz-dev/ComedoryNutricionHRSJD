/**
 * Demostración de develop con el reloj REAL (sin laboratorio QA), contra una
 * base de demostración: la comida en curso es la de verdad y el Historial abre
 * en el día de hoy.
 *
 *   1. cocinera1 entrega 15 raciones y registra 2 policías (con confirmación).
 *   2. cocinera2 entrega otras 15, registra 1 policía desde Control Biométrico y
 *      deshace una ración de policía hecha por error.
 *   3. jefa: Supervisión, Resumen, Historial (diario de hoy, búsqueda y mensual),
 *      Cuentas y Reportes con el Excel.
 *
 * Requiere develop corriendo (API en DEMO_API, front en DEMO_APP) sobre una base
 * con padrón de hoy, y una comida en curso a la hora real.
 *
 *   DEMO_CLAVE=... node qa/prueba-basica/demo_develop_playwright.cjs [--visible]
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { navegador } = require('./soporte_playwright.cjs');

const APP = process.env.DEMO_APP || 'http://127.0.0.1:5174';
const API = process.env.DEMO_API || 'http://127.0.0.1:8010';
const CLAVE = process.env.DEMO_CLAVE;
const SIMULADO = (id) => id >= 960001 && id <= 960999;
assert.ok(CLAVE, 'Falta DEMO_CLAVE.');
const carpeta = path.join(__dirname, 'evidencias', `demo-develop-${new Date().toISOString().replace(/[:.]/g, '-')}`);
fs.mkdirSync(carpeta, { recursive: true });
const registro = [];
let n = 0;

function anotar(texto) {
  registro.push(texto);
  console.log(texto);
}

async function captura(page, nombre, { completa = false, espera = 400 } = {}) {
  n += 1;
  const archivo = `${String(n).padStart(2, '0')}-${nombre}.png`;
  await page.waitForTimeout(espera);
  await page.screenshot({ path: path.join(carpeta, archivo), fullPage: completa });
  anotar(`  📷 ${archivo}`);
}

async function peticion(page, ruta) {
  return page.evaluate(async ({ api, ruta }) => {
    const access = JSON.parse(sessionStorage.getItem('comedor_sesion'))?.access;
    const res = await fetch(api + ruta, { headers: { Authorization: `Bearer ${access}` } });
    return res.json();
  }, { api: API, ruta });
}

async function entrar(browser, cuenta) {
  const contexto = await browser.newContext({ viewport: { width: 1366, height: 768 }, locale: 'es-BO', acceptDownloads: true });
  const page = await contexto.newPage();
  page.setDefaultTimeout(20_000);
  await page.goto(APP);
  await page.locator('#login-usuario').fill(cuenta);
  await page.locator('#login-contrasena').fill(CLAVE);
  await page.locator('button[type="submit"]').click();
  return { page, cerrar: () => contexto.close() };
}

const aviso = (page) => page.locator('.checklist__aviso[role="status"]');

async function entregarPersonas(page, cantidad) {
  const datos = await peticion(page, '/pantalla/checklist');
  const pendientes = datos.personas.filter((p) => SIMULADO(p.usuario_id) && !p.servida).slice(0, cantidad);
  assert.equal(pendientes.length, cantidad, 'no hay suficientes pendientes');
  for (const persona of pendientes) {
    await page.getByLabel('Buscar por nombre', { exact: true }).fill(persona.nombre);
    await page.getByRole('checkbox', { name: `Entregar ración a ${persona.nombre}`, exact: true }).click();
    await aviso(page).filter({ hasText: `Ración entregada a ${persona.nombre}` }).waitFor();
  }
  return pendientes.map((p) => p.nombre);
}

async function registrarPolicia(page, capturarDialogo = null) {
  await page.getByRole('button', { name: 'Registrar policía', exact: true }).click();
  const dialogo = page.getByRole('dialog', { name: 'Registrar policía' });
  await dialogo.waitFor();
  if (capturarDialogo) await captura(page, capturarDialogo);
  await dialogo.getByRole('button', { name: 'Sí, registrar policía' }).click();
  await dialogo.waitFor({ state: 'detached' });
}

async function cambiarPantalla(page, destino) {
  await page.getByRole('button', { name: 'Menú de sesión', exact: true }).click();
  await page.getByRole('button', { name: destino, exact: true }).click();
}

async function seccion(page, etiqueta) {
  await page.locator('.sidebar__item', { hasText: etiqueta }).click();
  await page.waitForLoadState('networkidle');
}

(async () => {
  const visible = process.argv.includes('--visible');
  const browser = await navegador().launch({ headless: !visible, slowMo: visible ? 250 : 0 });
  const resumen = {};
  let s;
  try {
    // 1. cocinera1
    anotar('1) cocinera1 entrega 15 raciones y registra 2 policías');
    s = await entrar(browser, 'cocinera1');
    await s.page.locator('.checklist__fila').first().waitFor();
    const lista = await peticion(s.page, '/pantalla/checklist');
    assert.equal(lista.fuera_de_horario, false, 'no hay comida en curso a esta hora');
    resumen.comida = `${lista.comida} del ${lista.fecha_comida}`;
    resumen.con_derecho = lista.personas.length;
    anotar(`  ${resumen.comida} (hora real) · con derecho: ${resumen.con_derecho} personas`);
    await captura(s.page, 'cocinera1-checklist-al-abrir');
    resumen.cocinera1 = await entregarPersonas(s.page, 8);
    await captura(s.page, 'cocinera1-a-mitad-con-aviso');
    resumen.cocinera1.push(...await entregarPersonas(s.page, 7));
    await registrarPolicia(s.page, 'cocinera1-confirmar-registrar-policia');
    await aviso(s.page).filter({ hasText: 'Ración de policía registrada' }).waitFor();
    await registrarPolicia(s.page);
    await s.page.evaluate(() => document.querySelector('.checklist')?.scrollIntoView());
    await captura(s.page, 'cocinera1-15-entregadas-y-2-policias');
    await s.cerrar();

    // 2. cocinera2
    anotar('\n2) cocinera2 entrega 15 raciones, registra 1 policía desde Control Biométrico y prueba Deshacer');
    s = await entrar(browser, 'cocinera2');
    await s.page.locator('.checklist__fila').first().waitFor();
    resumen.cocinera2 = await entregarPersonas(s.page, 15);
    await captura(s.page, 'cocinera2-15-entregadas');
    await cambiarPantalla(s.page, 'Ir a Control Biométrico');
    await s.page.getByText('Marcaciones del turno', { exact: true }).first().waitFor();
    await registrarPolicia(s.page, 'cocinera2-biometrico-confirmar-policia');
    await s.page.getByText('Ración de policía registrada', { exact: true }).waitFor();
    await captura(s.page, 'cocinera2-biometrico-policia-registrado', { espera: 1500 });
    await cambiarPantalla(s.page, 'Ir al Checklist de comida');
    await s.page.locator('.checklist__fila').first().waitFor();
    await registrarPolicia(s.page);
    await aviso(s.page).filter({ hasText: 'Ración de policía registrada' }).waitFor();
    const antes = (await peticion(s.page, '/pantalla/checklist')).policias.length;
    await s.page.getByRole('region', { name: /^Policías en/ }).getByRole('button', { name: 'Deshacer' }).last().click();
    await aviso(s.page).filter({ hasText: 'Se deshizo una ración de policía' }).waitFor();
    assert.equal((await peticion(s.page, '/pantalla/checklist')).policias.length, antes - 1);
    await captura(s.page, 'cocinera2-deshacer-policia-por-error');
    const final = await peticion(s.page, '/pantalla/checklist');
    resumen.entregadas = final.personas.filter((p) => p.servida).length;
    resumen.pendientes = final.personas.length - resumen.entregadas;
    resumen.policias = final.policias.length;
    anotar(`  Entregadas ${resumen.entregadas}, pendientes ${resumen.pendientes}, policías ${resumen.policias}`);
    await s.cerrar();

    // 3. Jefa
    anotar('\n3) jefa revisa todas sus pestañas');
    s = await entrar(browser, 'jefa');
    await seccion(s.page, 'Supervisión');
    await s.page.getByRole('tab', { name: /Almuerzo|Desayuno|Té|Cena/ }).filter({ hasText: lista.comida }).first().click();
    await s.page.waitForLoadState('networkidle');
    await captura(s.page, 'jefa-supervision');
    await captura(s.page, 'jefa-supervision-completa', { completa: true });

    await seccion(s.page, 'Resumen');
    await captura(s.page, 'jefa-resumen', { completa: true, espera: 2000 });

    await seccion(s.page, 'Historial de comidas');
    await s.page.getByText(/\d+ usuarios · \d+ recibidas/).first().waitFor();
    const cabecera = await s.page.getByText(/\d+ usuarios · \d+ recibidas/).first().textContent();
    resumen.historial_hoy = cabecera.trim();
    anotar(`  Historial de hoy: ${resumen.historial_hoy}`);
    assert.doesNotMatch(cabecera, /^0 usuarios/, 'el Historial de hoy no puede estar vacío');
    await captura(s.page, 'jefa-historial-diario-hoy', { completa: true });
    const buscado = resumen.cocinera1[0];
    await s.page.getByPlaceholder('Buscar nombre').fill(buscado);
    await s.page.waitForTimeout(800);
    await captura(s.page, 'jefa-historial-busqueda-una-persona');
    await s.page.getByPlaceholder('Buscar nombre').fill('');
    await s.page.getByRole('button', { name: 'Mensual', exact: true }).click();
    await s.page.waitForLoadState('networkidle');
    await captura(s.page, 'jefa-historial-mensual', { completa: true, espera: 1000 });

    await seccion(s.page, 'Cuentas');
    await captura(s.page, 'jefa-cuentas', { completa: true });

    await seccion(s.page, 'Reportes');
    await s.page.getByRole('button', { name: 'Excel' }).waitFor();
    await captura(s.page, 'jefa-reportes', { completa: true });
    const [descarga] = await Promise.all([
      s.page.waitForEvent('download'),
      s.page.getByRole('button', { name: 'Excel' }).click(),
    ]);
    const excel = path.join(carpeta, descarga.suggestedFilename());
    await descarga.saveAs(excel);
    anotar(`  📄 ${path.basename(excel)}`);
    const dia = await peticion(s.page, `/pantalla/comidas-del-dia?fecha=${lista.fecha_comida}`);
    const comida = dia.comidas.find((c) => c.comida === lista.comida);
    anotar(`  Supervisión, ${lista.comida}: ${comida.servidas} del personal + ${comida.policias} policías = ${comida.servidas + comida.policias} raciones`);
    await s.cerrar();
  } finally {
    await browser.close();
    fs.writeFileSync(path.join(carpeta, 'resumen.json'), JSON.stringify(resumen, null, 2));
    fs.writeFileSync(path.join(carpeta, 'registro.txt'), registro.join('\n'));
    console.log(`\nEvidencias: ${carpeta}`);
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
