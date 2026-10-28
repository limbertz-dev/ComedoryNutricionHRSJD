/**
 * Demostración con capturas: un almuerzo con más de 30 personas en el checklist.
 *
 *   1. jefa da de alta los policías por número (Supervisión → Policías del comedor).
 *   2. cocinera1 entrega 15 raciones y 2 de policía.
 *   3. cocinera2 entrega otras 15 y 1 de policía; deshace una de policía (vuelve a
 *      pendiente) y la vuelve a entregar.
 *   4. jefa recorre todas sus pestañas y termina en Reportes (con el Excel).
 *
 * Requiere el padrón sin marcas del día del laboratorio:
 *   python -B qa/prueba-basica/simular_dia.py --solo-padron --comensales 34 --aplicar
 * Claves: QA_CLAVE (común) o QA_CLAVE_COCINERA1/COCINERA2/JEFA.
 *
 *   node qa/prueba-basica/demo_checklist_cocineras_playwright.cjs [--visible]
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { navegador, credencial, clienteLab, peticion } = require('./soporte_playwright.cjs');

const APP = 'http://127.0.0.1:5173';
const FECHA = '2026-10-23';
const POLICIAS = 4;
const SIMULADO = (id) => id >= 960001 && id <= 960999;
const carpeta = path.join(__dirname, 'evidencias', `demo-checklist-${new Date().toISOString().replace(/[:.]/g, '-')}`);
fs.mkdirSync(carpeta, { recursive: true });
const registro = [];
let n = 0;

function anotar(texto) {
  registro.push(texto);
  console.log(texto);
}

async function captura(page, nombre, opciones = {}) {
  n += 1;
  const archivo = `${String(n).padStart(2, '0')}-${nombre}.png`;
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(carpeta, archivo), fullPage: opciones.completa ?? false });
  anotar(`  📷 ${archivo}`);
}

async function entrar(browser, cuenta) {
  const contexto = await browser.newContext({ viewport: { width: 1366, height: 768 }, locale: 'es-BO', acceptDownloads: true });
  const page = await contexto.newPage();
  page.setDefaultTimeout(20_000);
  await page.goto(APP);
  // QA_CUENTA_<CUENTA> permite ensayar con otra cuenta del mismo rol.
  await page.locator('#login-usuario').fill(process.env[`QA_CUENTA_${cuenta.toUpperCase()}`] || cuenta);
  await page.locator('#login-contrasena').fill(credencial(cuenta));
  await page.locator('button[type="submit"]').click();
  return { page, cerrar: () => contexto.close() };
}

const aviso = (page) => page.locator('.checklist__aviso[role="status"]');

async function entregarPersonas(page, cantidad) {
  const datos = (await peticion(page, '/pantalla/checklist')).datos;
  const pendientes = datos.personas.filter((p) => SIMULADO(p.usuario_id) && !p.servida).slice(0, cantidad);
  assert.equal(pendientes.length, cantidad, 'no hay suficientes pendientes');
  for (const persona of pendientes) {
    await page.getByLabel('Buscar por nombre', { exact: true }).fill(persona.nombre);
    await page.getByRole('checkbox', { name: `Entregar ración a ${persona.nombre}`, exact: true }).click();
    await aviso(page).filter({ hasText: `Ración entregada a ${persona.nombre}` }).waitFor();
  }
  return pendientes.map((p) => p.nombre);
}

async function entregarPolicia(page, nombre) {
  await page.getByRole('checkbox', { name: `Entregar ración a ${nombre}`, exact: true }).click();
  await aviso(page).filter({ hasText: `Ración entregada a ${nombre}` }).waitFor();
}

async function seccion(page, etiqueta) {
  await page.locator('.sidebar__item', { hasText: etiqueta }).click();
  await page.waitForLoadState('networkidle');
}

(async () => {
  const browser = await navegador().launch({ headless: !process.argv.includes('--visible') });
  const lab = await clienteLab();
  await lab('/horario', { momento: `${FECHA}T12:05:00`, modo: 'continuo', comida_id: 2 });
  anotar(`Almuerzo del ${FECHA} (reloj del laboratorio desde las 12:05, en marcha).`);
  const resumen = {};
  try {
    // 1. Jefa: policías por número
    anotar('\n1) jefa da de alta los policías');
    let s = await entrar(browser, 'jefa');
    await seccion(s.page, 'Supervisión');
    await s.page.getByRole('region', { name: 'Policías del comedor' }).waitFor();
    const panel = s.page.getByRole('region', { name: 'Policías del comedor' });
    await panel.scrollIntoViewIfNeeded();
    const existentes = (await peticion(s.page, '/policias')).datos.filter((p) => p.activo).length;
    for (let i = existentes; i < POLICIAS; i++) {
      await panel.getByRole('button', { name: 'Agregar policía' }).click();
      await panel.getByRole('cell', { name: `Policía ${i + 1}`, exact: true }).waitFor();
    }
    await panel.scrollIntoViewIfNeeded();
    await captura(s.page, 'jefa-policias-dados-de-alta');
    resumen.policias = (await peticion(s.page, '/policias')).datos.filter((p) => p.activo).map((p) => p.nombre);
    anotar(`  Policías activos: ${resumen.policias.join(', ')}`);
    await s.cerrar();

    // 2. cocinera1
    anotar('\n2) cocinera1 entrega 15 raciones y 2 de policía');
    s = await entrar(browser, 'cocinera1');
    await s.page.locator('.checklist__fila').first().waitFor();
    const inicial = (await peticion(s.page, '/pantalla/checklist')).datos;
    resumen.con_derecho = inicial.personas.length;
    anotar(`  Con derecho al almuerzo: ${resumen.con_derecho} personas`);
    await captura(s.page, 'cocinera1-checklist-al-abrir');
    resumen.cocinera1 = await entregarPersonas(s.page, 8);
    await captura(s.page, 'cocinera1-a-mitad-con-aviso');
    resumen.cocinera1.push(...await entregarPersonas(s.page, 7));
    await entregarPolicia(s.page, 'Policía 1');
    await entregarPolicia(s.page, 'Policía 2');
    await s.page.evaluate(() => document.querySelector('.checklist')?.scrollIntoView());
    await captura(s.page, 'cocinera1-15-entregadas-y-2-policias');
    await s.page.getByRole('tab', { name: /^Entregadas/ }).click();
    await captura(s.page, 'cocinera1-filtro-entregadas', { completa: true });
    await s.cerrar();

    // 3. cocinera2
    anotar('\n3) cocinera2 entrega 15 raciones, 1 de policía y prueba Deshacer');
    s = await entrar(browser, 'cocinera2');
    await s.page.locator('.checklist__fila').first().waitFor();
    await captura(s.page, 'cocinera2-checklist-al-abrir');
    resumen.cocinera2 = await entregarPersonas(s.page, 15);
    await entregarPolicia(s.page, 'Policía 3');
    await captura(s.page, 'cocinera2-15-entregadas-y-policia-3');
    const fila3 = s.page.locator('.checklist__fila--policia', { hasText: 'Policía 3' });
    await fila3.getByRole('button', { name: 'Deshacer' }).click();
    await aviso(s.page).filter({ hasText: 'Se deshizo la entrega a Policía 3' }).waitFor();
    await s.page.getByRole('checkbox', { name: 'Entregar ración a Policía 3', exact: true }).waitFor();
    await captura(s.page, 'cocinera2-deshacer-policia-3-vuelve-a-pendiente');
    await entregarPolicia(s.page, 'Policía 3');
    // La cocinera2 no puede deshacer lo de la cocinera1.
    const fila1 = s.page.locator('.checklist__fila--policia', { hasText: 'Policía 1' });
    assert.equal(await fila1.getByRole('button', { name: 'Deshacer' }).count(), 0);
    await captura(s.page, 'cocinera2-final');
    const final = (await peticion(s.page, '/pantalla/checklist')).datos;
    resumen.entregadas = final.personas.filter((p) => p.servida).length;
    resumen.pendientes = final.personas.length - resumen.entregadas;
    resumen.policias_servidos = final.policias.filter((p) => p.servida).map((p) => p.nombre);
    anotar(`  Al cerrar: ${resumen.entregadas} entregadas, ${resumen.pendientes} pendientes, policías ${resumen.policias_servidos.join(', ')}`);
    await s.cerrar();

    // 4. Jefa: todas sus pestañas
    anotar('\n4) jefa revisa todas sus pestañas');
    await lab('/horario', { momento: `${FECHA}T15:00:00`, modo: 'fijo', comida_id: 2 });
    s = await entrar(browser, 'jefa');
    await seccion(s.page, 'Supervisión');
    await s.page.getByRole('region', { name: 'Policías del comedor' }).waitFor();
    await s.page.getByRole('tab', { name: /Almuerzo/ }).first().click();
    await s.page.waitForLoadState('networkidle');
    await captura(s.page, 'jefa-supervision-almuerzo');
    await captura(s.page, 'jefa-supervision-completa', { completa: true });
    for (const [etiqueta, nombre] of [['Resumen', 'resumen'], ['Historial de comidas', 'historial'], ['Cuentas', 'cuentas']]) {
      await seccion(s.page, etiqueta);
      await captura(s.page, `jefa-${nombre}`, { completa: true });
    }
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
    const dia = (await peticion(s.page, `/pantalla/comidas-del-dia?fecha=${FECHA}`)).datos;
    const almuerzo = dia.comidas.find((c) => c.comida === 'Almuerzo');
    resumen.supervision_almuerzo = { servidas: almuerzo.servidas, policias: almuerzo.policias };
    anotar(`  Supervisión, almuerzo: ${almuerzo.servidas} raciones del personal y ${almuerzo.policias} de policía`);
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
