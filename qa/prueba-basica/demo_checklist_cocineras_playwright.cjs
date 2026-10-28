/**
 * Demostración con capturas: un almuerzo con más de 30 personas en el checklist.
 *
 *   1. cocinera1 entrega 15 raciones y registra 2 policías («Registrar policía»
 *      con confirmación: los policías no tienen identidad, son un contador).
 *   2. cocinera2 entrega otras 15, registra 1 policía desde Control Biométrico,
 *      deshace una ración de policía hecha por error y no puede deshacer las ajenas.
 *   3. jefa recorre todas sus pestañas y termina en Reportes (con el Excel).
 *
 * Requiere el padrón sin marcas del día del laboratorio:
 *   python -B qa/prueba-basica/simular_dia.py --solo-padron --comensales 34 --aplicar
 * Claves: QA_CLAVE (común) o QA_CLAVE_COCINERA1/COCINERA2/JEFA.
 * QA_CUENTA_<CUENTA> permite usar otra cuenta del mismo rol.
 *
 *   node qa/prueba-basica/demo_checklist_cocineras_playwright.cjs [--visible]
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { navegador, credencial, clienteLab, peticion } = require('./soporte_playwright.cjs');

const APP = 'http://127.0.0.1:5173';
const FECHA = '2026-10-23';
const SIMULADO = (id) => id >= 960001 && id <= 960999;
const carpeta = path.join(__dirname, 'evidencias', `demo-checklist-${new Date().toISOString().replace(/[:.]/g, '-')}`);
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

async function entrar(browser, cuenta) {
  const contexto = await browser.newContext({ viewport: { width: 1366, height: 768 }, locale: 'es-BO', acceptDownloads: true });
  const page = await contexto.newPage();
  page.setDefaultTimeout(20_000);
  await page.goto(APP);
  // En la grabación no se ve el botón del laboratorio QA.
  await page.addStyleTag({ content: '#qa-abrir { display: none !important; }' }).catch(() => {});
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

/** «Registrar policía» → diálogo de confirmación → «Sí, registrar policía». */
async function registrarPolicia(page, capturarDialogo = null) {
  await page.getByRole('button', { name: 'Registrar policía', exact: true }).click();
  const dialogo = page.getByRole('dialog', { name: 'Registrar policía' });
  await dialogo.waitFor();
  if (capturarDialogo) await captura(page, capturarDialogo);
  await dialogo.getByRole('button', { name: 'Sí, registrar policía' }).click();
  await dialogo.waitFor({ state: 'detached' });
}

async function policiasEnComida(page) {
  return (await peticion(page, '/pantalla/checklist')).datos.policias;
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
  // --visible va más lento para poder seguirlo con la vista.
  const browser = await navegador().launch({ headless: !visible, slowMo: visible ? 250 : 0 });
  const lab = await clienteLab();
  await lab('/horario', { momento: `${FECHA}T12:05:00`, modo: 'continuo', comida_id: 2 });
  anotar(`Almuerzo del ${FECHA} (reloj del laboratorio desde las 12:05, en marcha).`);
  const resumen = {};
  let s;
  try {
    // 1. cocinera1
    anotar('\n1) cocinera1 entrega 15 raciones y registra 2 policías');
    s = await entrar(browser, 'cocinera1');
    await s.page.locator('.checklist__fila').first().waitFor();
    resumen.con_derecho = (await peticion(s.page, '/pantalla/checklist')).datos.personas.length;
    anotar(`  Con derecho al almuerzo: ${resumen.con_derecho} personas`);
    await captura(s.page, 'cocinera1-checklist-al-abrir');
    resumen.cocinera1 = await entregarPersonas(s.page, 8);
    await captura(s.page, 'cocinera1-a-mitad-con-aviso');
    resumen.cocinera1.push(...await entregarPersonas(s.page, 7));
    await registrarPolicia(s.page, 'cocinera1-confirmar-registrar-policia');
    await aviso(s.page).filter({ hasText: 'Ración de policía registrada' }).waitFor();
    await registrarPolicia(s.page);
    await s.page.evaluate(() => document.querySelector('.checklist')?.scrollIntoView());
    await captura(s.page, 'cocinera1-15-entregadas-y-2-policias');
    await s.page.getByRole('tab', { name: /^Entregadas/ }).click();
    await captura(s.page, 'cocinera1-filtro-entregadas', { completa: true });
    await s.cerrar();

    // 2. cocinera2
    anotar('\n2) cocinera2 entrega 15 raciones, registra 1 policía desde Control Biométrico y prueba Deshacer');
    s = await entrar(browser, 'cocinera2');
    await s.page.locator('.checklist__fila').first().waitFor();
    await captura(s.page, 'cocinera2-checklist-al-abrir');
    resumen.cocinera2 = await entregarPersonas(s.page, 15);
    await captura(s.page, 'cocinera2-15-entregadas');
    // Control Biométrico: el mismo botón, en la barra superior.
    await cambiarPantalla(s.page, 'Ir a Control Biométrico');
    await s.page.getByText('Marcaciones del turno', { exact: true }).first().waitFor();
    await registrarPolicia(s.page, 'cocinera2-biometrico-confirmar-policia');
    await s.page.getByText('Ración de policía registrada', { exact: true }).waitFor();
    await captura(s.page, 'cocinera2-biometrico-policia-registrado', { espera: 1500 });
    await cambiarPantalla(s.page, 'Ir al Checklist de comida');
    await s.page.locator('.checklist__fila').first().waitFor();
    // Un policía registrado por error: Deshacer lo quita (solo los propios).
    await registrarPolicia(s.page);
    await aviso(s.page).filter({ hasText: 'Ración de policía registrada' }).waitFor();
    const antes = (await policiasEnComida(s.page)).length;
    await s.page.getByRole('region', { name: /^Policías en/ }).getByRole('button', { name: 'Deshacer' }).last().click();
    await aviso(s.page).filter({ hasText: 'Se deshizo una ración de policía' }).waitFor();
    assert.equal((await policiasEnComida(s.page)).length, antes - 1);
    await captura(s.page, 'cocinera2-deshacer-policia-por-error');
    // Las de la cocinera1 no se pueden deshacer desde otra cuenta.
    const ajenas = (await policiasEnComida(s.page)).filter((p) => !p.anulable).length;
    assert.ok(ajenas >= 2, 'las dos de la cocinera1 no son anulables para la cocinera2');
    const final = (await peticion(s.page, '/pantalla/checklist')).datos;
    resumen.entregadas = final.personas.filter((p) => p.servida).length;
    resumen.pendientes = final.personas.length - resumen.entregadas;
    resumen.policias = final.policias.length;
    anotar(`  Al cerrar: ${resumen.entregadas} entregadas, ${resumen.pendientes} pendientes, ${resumen.policias} policías`);
    await s.cerrar();

    // 3. Jefa: todas sus pestañas
    anotar('\n3) jefa revisa todas sus pestañas');
    await lab('/horario', { momento: `${FECHA}T15:00:00`, modo: 'fijo', comida_id: 2 });
    s = await entrar(browser, 'jefa');
    await seccion(s.page, 'Supervisión');
    await s.page.getByRole('tab', { name: /Almuerzo/ }).first().click();
    await s.page.waitForLoadState('networkidle');
    await captura(s.page, 'jefa-supervision-almuerzo');
    await captura(s.page, 'jefa-supervision-completa', { completa: true });
    for (const [etiqueta, nombre] of [['Resumen', 'resumen'], ['Historial de comidas', 'historial'], ['Cuentas', 'cuentas']]) {
      await seccion(s.page, etiqueta);
      // El gráfico del Resumen se anima: se espera a que termine.
      await captura(s.page, `jefa-${nombre}`, { completa: true, espera: 2000 });
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
    anotar(`  Supervisión, almuerzo: ${almuerzo.servidas} del personal + ${almuerzo.policias} policías = ${almuerzo.servidas + almuerzo.policias} raciones`);
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
