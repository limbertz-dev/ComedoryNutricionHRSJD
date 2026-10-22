/** Recargas reales y fallo controlado de un módulo: no usa cuentas ni modifica MySQL. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { navegador } = require('./soporte_playwright.cjs');

/** @returns {Promise<void>} */
async function main() {
  const salida = path.join(__dirname, 'evidencias', `recarga-front-${new Date().toISOString().replace(/[:.]/g, '-')}`);
  fs.mkdirSync(salida, { recursive: true });
  const archivos = ['corrida.json', 'huellas_simuladas.json'].map(nombre => path.join(__dirname, nombre));
  const previos = archivos.map(archivo => fs.readFileSync(archivo));
  const browser = await navegador().launch({ headless: !process.argv.includes('--visible') });
  const controles = [];
  try {
    const entrada = await fetch('http://127.0.0.1:5173/src/main.jsx');
    assert.equal(entrada.status, 200);
    const modulo = await entrada.text();
    assert.ok(modulo.includes('/node_modules/.vite-qa/deps/'), 'Dependencias optimizadas dentro de node_modules');
    assert.ok(!modulo.includes('/evidencias/vite/'));
    controles.push('Caché QA aislada en node_modules: las dependencias no se procesan como código de la aplicación');
    const contexto = await browser.newContext({ viewport: { width: 1366, height: 768 }, locale: 'es-BO' });
    const page = await contexto.newPage();
    page.setDefaultTimeout(20000);
    const errores = [];
    page.on('pageerror', error => errores.push(error.name));
    for (let intento = 0; intento < 4; intento++) {
      const respuesta = intento ? await page.reload() : await page.goto('http://127.0.0.1:5173');
      assert.equal(respuesta.status(), 200);
      assert.equal(respuesta.headers()['cache-control'], 'no-store');
      await page.locator('#login-usuario').waitFor();
      await page.locator('#qa-abrir').waitFor();
      assert.equal(await page.locator('#qa-arranque').isVisible(), false);
      assert.equal(await page.locator('#qa-abrir').evaluate(el => getComputedStyle(el).position), 'fixed');
      assert.equal(await page.locator('#root').evaluate(el => el.childElementCount > 0), true);
    }
    assert.deepEqual(errores, []);
    controles.push('Carga inicial y tres recargas reales sin errores JavaScript; login y estilos presentes');
    await page.screenshot({ path: path.join(salida, 'recarga-correcta.png') });
    const ruta = '**/src/main.jsx*';
    let liberarCarga;
    const cargaRetenida = new Promise(resolve => { liberarCarga = resolve; });
    await page.route(ruta, async route => { await cargaRetenida; await route.continue(); });
    await page.reload({ waitUntil: 'commit' });
    await page.getByRole('heading', { name: 'Cargando…', exact: true }).waitFor();
    await page.waitForFunction(() => /qa_recargar=\d{13}/.test(document.querySelector('#qa-recargar').href));
    await page.waitForFunction(() => Boolean(window.getComputedStyle(document.querySelector('#qa-arranque-giro')).animationName === 'qa-arranque-girar'));
    assert.equal(await page.locator('#qa-recargar').isVisible(), false);
    assert.equal(await page.locator('#qa-arranque-detalle').isVisible(), false);
    const centro = await page.locator('#qa-arranque-giro').boundingBox();
    assert.ok(Math.abs(centro.x + centro.width / 2 - 1366 / 2) < 2);
    await page.screenshot({ path: path.join(salida, 'cargando-circulo.png') });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    assert.equal(await page.locator('#qa-arranque-giro').evaluate(el => getComputedStyle(el).animationName), 'none');
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    liberarCarga();
    await page.locator('#login-usuario').waitFor();
    assert.equal(await page.locator('#qa-arranque').isVisible(), false);
    controles.push('Carga lenta: círculo centrado con Cargando, sin reintento prematuro, respeta movimiento reducido');
    await page.unroute(ruta);
    await page.route(ruta, route => route.fulfill({ status: 200, contentType: 'text/javascript', body: 'throw new Error("fallo-controlado-del-modulo");' }));
    await page.reload();
    await page.getByRole('heading', { name: 'No se pudo cargar la aplicación', exact: true }).waitFor();
    assert.equal(await page.locator('#qa-abrir').isVisible(), false);
    assert.equal(await page.locator('#root').evaluate(el => el.childElementCount), 0);
    assert.equal(await page.locator('#qa-recargar').isVisible(), true);
    assert.equal(await page.locator('#qa-arranque-giro').isVisible(), false);
    assert.equal(await page.locator('#qa-arranque').evaluate(el => getComputedStyle(el).fontFamily.includes('Segoe')), true);
    controles.push('Fallo controlado del módulo: aviso legible y recuperación; simulador oculto');
    await page.screenshot({ path: path.join(salida, 'fallo-modulo-controlado.png') });
    await page.unroute(ruta);
    await page.locator('#qa-recargar').click();
    await page.locator('#login-usuario').waitFor();
    await page.locator('#qa-abrir').waitFor();
    assert.equal(await page.locator('#qa-arranque').isVisible(), false);
    controles.push('Volver a cargar recupera la aplicación sin limpiar almacenamiento ni datos');
    await page.locator('#qa-abrir').click();
    await page.frameLocator('#qa-marco').locator('#conexion').filter({ hasText: 'Laboratorio conectado' }).waitFor();
    controles.push('El modal sigue conectado al laboratorio después de recuperar el frontend');
    archivos.forEach((archivo, i) => assert.ok(fs.readFileSync(archivo).equals(previos[i]), 'Conservar diario y vínculos'));
    fs.writeFileSync(path.join(salida, 'resultado.json'), JSON.stringify({ aprobado: true,
      alcance: 'Recargas reales del frontend y fallo JavaScript provocado solo en este navegador. Sin autenticación, entregas ni cambios en MySQL.',
      controles }, null, 2));
    console.log(`APROBADO: ${controles.length} controles. Evidencia: ${salida}`);
    await contexto.close();
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
