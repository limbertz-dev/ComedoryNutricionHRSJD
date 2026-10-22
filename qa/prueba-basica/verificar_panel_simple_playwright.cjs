/** Panel real y estado QA de solo lectura; interacciones de escritura HTTP simuladas. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { navegador, clienteLab, salud } = require('./soporte_playwright.cjs');

/** @returns {Promise<void>} */
async function main() {
  await salud();
  const consultar = await clienteLab();
  const estadoReal = await consultar('/estado');
  const archivos = ['corrida.json', 'huellas_simuladas.json'].map(nombre => path.join(__dirname, nombre));
  const originales = archivos.map(archivo => fs.readFileSync(archivo));
  const salida = path.join(__dirname, 'evidencias', `panel-simple-${new Date().toISOString().replace(/[:.]/g, '-')}`);
  fs.mkdirSync(salida, { recursive: true });
  const browser = await navegador().launch({ headless: !process.argv.includes('--visible') });
  const controles = [];
  try {
    const contexto = await browser.newContext({ viewport: { width: 1366, height: 768 }, locale: 'es-BO' });
    const page = await contexto.newPage();
    page.setDefaultTimeout(12000);
    await page.goto('http://127.0.0.1:5173');
    await page.locator('#qa-abrir').click();
    let panel = page.frameLocator('#qa-marco');
    await panel.locator('#conexion').filter({ hasText: 'Laboratorio conectado' }).waitFor();
    assert.ok(await panel.locator('#fecha').inputValue());
    assert.equal(await panel.locator('#advertencias').isVisible(), estadoReal.advertencias.length > 0);
    for (const [ancho, alto] of [[1366, 768], [1920, 1080]]) {
      await page.setViewportSize({ width: ancho, height: alto });
      assert.equal(await panel.locator('body').evaluate(el => el.scrollWidth > el.clientWidth), false);
      await page.screenshot({ path: path.join(salida, `real-${ancho}x${alto}.png`) });
    }
    controles.push('Estado real consultable: fecha, servicio e inconsistencias visibles sin escrituras');
    await panel.locator('#reconectar').focus();
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => !document.querySelector('#qa-modal').open);
    assert.equal(await page.locator('#qa-abrir').evaluate(el => el === document.activeElement), true);
    controles.push('Escape cierra el modal y devuelve el foco al botón');

    // Desde aquí las respuestas de acciones se interceptan: no reinicia ensayos
    // ni cambia el reloj real del laboratorio ni confirma entregas en MySQL.
    let d = structuredClone(estadoReal);
    d.advertencias = [];
    d.preparado_cuatro_comidas = true;
    for (const datos of Object.values(d.casos)) Object.assign(datos, { lectura_id: null, comprobado: false, estado: 'Sin simular', detalle: '', huella_registrada: true });
    let falloEstado = false;
    const acciones = [];
    await page.route('http://127.0.0.1:8002/estado', route => route.fulfill({ status: falloEstado ? 503 : 200,
      json: falloEstado ? { error: 'MySQL no respondió. El ensayo se conserva.' } : d }));
    await page.route('http://127.0.0.1:8002/**', async route => {
      const solicitud = route.request();
      if (solicitud.method() !== 'POST') return route.fallback();
      const ruta = new URL(solicitud.url()).pathname;
      const cuerpo = solicitud.postDataJSON();
      acciones.push({ ruta, cuerpo });
      if (ruta === '/horario') {
        d.momento = cuerpo.momento;
        d.comida_id = cuerpo.comida_id;
        d.servicio = d.comidas.find(c => c.id === cuerpo.comida_id).nombre;
        d.servicio_elegido_vigente = true;
        d.modo = 'fijo';
        d.ultima_accion = 'Horario aplicado. Las marcaciones existentes se conservan.';
      } else if (ruta === '/simular') {
        Object.assign(d.casos[cuerpo.caso], { lectura_id: cuerpo.caso === 'qa01' ? 1001 : 1003,
          estado: cuerpo.caso === 'qa01' ? 'Registro normal comprobado' : 'Por identificar en cocina',
          comprobado: cuerpo.caso === 'qa01' });
      } else return route.fulfill({ status: 409, json: { error: 'Acción no incluida en esta prueba visual.' } });
      return route.fulfill({ status: 200, json: d });
    });
    await page.locator('#qa-abrir').click();
    await panel.locator('#reconectar').click();
    await panel.locator('#qa01 .estado').filter({ hasText: 'Sin simular' }).waitFor();
    for (const id of [1, 2, 3, 4]) {
      await panel.locator(`[data-comida="${id}"]`).click();
      await panel.locator(`[data-comida="${id}"][aria-pressed="true"]`).waitFor();
      assert.equal(acciones.at(-1).ruta, '/horario');
      assert.equal(acciones.at(-1).cuerpo.comida_id, id);
      assert.equal(acciones.at(-1).cuerpo.modo, 'fijo');
    }
    assert.ok(!acciones.some(a => a.ruta === '/nuevo'));
    controles.push('Cuatro comidas con un clic, hora sugerida y sin limpieza implícita (HTTP simulado)');
    await panel.locator('#qa01 .simular').click();
    await panel.locator('#qa01 .simular').filter({ hasText: 'Volver a leer' }).waitFor();
    let perdida = true;
    const claves = [];
    await page.route('http://127.0.0.1:8001/**', async route => {
      if (route.request().method() !== 'POST') return route.fallback();
      assert.ok(route.request().url().endsWith('/_qa/enrolamiento/lecturas'), 'No confirmar entregas fuera de la relectura simulada');
      claves.push(route.request().headers()['idempotency-key']);
      if (perdida) return route.fulfill({ status: 503, json: { error: 'Resultado incierto simulado' } });
      return route.fulfill({ status: 200, json: { usuario_id: 900101, lectura_id: 1002, asistencia_id: null, valido: false, motivo: 'duplicado' } });
    });
    await page.evaluate(() => sessionStorage.setItem('comedor_sesion', JSON.stringify({ access: 'fixture-no-valida', usuario: 'cocinera2' })));
    await panel.locator('#qa01 .simular').click();
    try { await panel.locator('#qa01 .simular').filter({ hasText: 'Verificar lectura' }).waitFor(); }
    catch (error) {
      console.error(JSON.stringify({ paso: 'primera relectura', peticiones: claves.length,
        aviso: await panel.locator('#aviso').innerText(), boton: await panel.locator('#qa01 .simular').innerText(),
        referenciaDisponible: Boolean(d.casos.qa01.referencia_huella) }));
      throw error;
    }
    const antes = acciones.length;
    await panel.locator('[data-comida="1"]').click();
    assert.equal(acciones.length, antes);
    await panel.locator('#reconectar').click();
    try { await panel.locator('#qa01 .simular').filter({ hasText: 'Verificar lectura' }).waitFor(); }
    catch (error) {
      console.error(JSON.stringify({ paso: 'tras recargar', peticiones: claves.length,
        aviso: await panel.locator('#aviso').innerText(), boton: await panel.locator('#qa01 .simular').innerText(),
        pendiente: await page.evaluate(() => Boolean(sessionStorage.getItem('qa_relectura_pendiente'))) }));
      throw error;
    }
    perdida = false;
    await panel.locator('#qa01 .simular').click();
    await panel.locator('#resultado-repeticion').filter({ hasText: 'Segunda ración rechazada' }).waitFor();
    assert.equal(claves.length, 2);
    assert.equal(claves[0], claves[1]);
    controles.push('Relectura incierta conserva clave al recargar el panel y termina en duplicado (HTTP simulado)');
    await panel.locator('#qa02 .simular').click();
    await panel.locator('#qa02 .estado').filter({ hasText: 'Por identificar en cocina' }).waitFor();
    controles.push('Fallo de huella deja la decisión a cocina; no confirma automáticamente (HTTP simulado)');
    await panel.locator('#nuevo').click();
    await panel.locator('#confirmacion').waitFor();
    assert.equal(await panel.locator('#cancelar-ensayo').evaluate(el => el === document.activeElement), true);
    await panel.locator('#cancelar-ensayo').click();
    assert.ok(!acciones.some(a => a.ruta === '/nuevo'));
    controles.push('Nuevo ensayo requiere confirmación y Cancelar no escribe');
    falloEstado = true;
    await page.locator('#qa-abrir').evaluate(() => window.dispatchEvent(new Event('qa:volver-simulador')));
    await panel.locator('#aviso').filter({ hasText: 'MySQL no respondió' }).waitFor();
    assert.ok(await panel.locator('#fecha').inputValue());
    falloEstado = false;
    await panel.locator('#reconectar').click();
    await panel.locator('#conexion').filter({ hasText: 'Laboratorio conectado' }).waitFor();
    controles.push('Fallo de consulta conserva datos y Reconectar recupera el panel (HTTP simulado)');
    await page.setViewportSize({ width: 1366, height: 768 });
    await page.screenshot({ path: path.join(salida, 'interacciones-simuladas.png') });
    archivos.forEach((archivo, indice) => assert.ok(fs.readFileSync(archivo).equals(originales[indice]), 'El verificador no debe modificar diarios ni huellas'));
    fs.writeFileSync(path.join(salida, 'resultado.json'), JSON.stringify({ aprobado: true,
      alcance: 'Consulta real de QA y comprobación de interfaz; escrituras HTTP interceptadas. No acredita nuevas entregas en MySQL ni lector físico.',
      controles }, null, 2));
    console.log(`APROBADO: ${controles.length} controles. Evidencia: ${salida}`);
    await contexto.close();
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
