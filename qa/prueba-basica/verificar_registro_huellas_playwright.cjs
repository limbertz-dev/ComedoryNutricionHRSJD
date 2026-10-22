'use strict';
// Consulta real de los vinculos existentes: no captura huellas ni limpia ensayos.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { navegador, credencial, salud, sesion, peticion, esperar } = require('./soporte_playwright.cjs');

async function main() {
  await salud();
  const claves = { jefa: credencial('jefa'), cocinera2: credencial('cocinera2') };
  const browser = await navegador().launch({ headless: !process.argv.includes('--visible') });
  const carpeta = path.join(__dirname, 'evidencias', `huellas-supervision-${new Date().toISOString().replace(/[:.]/g, '-')}`);
  fs.mkdirSync(carpeta, { recursive: true });
  let jefa, cocina;
  try {
    jefa = await sesion(browser, 'jefa', claves.jefa);
    cocina = await sesion(browser, 'cocinera2', claves.cocinera2);
    const consulta = await peticion(jefa.page, '/_qa/enrolamiento/registros?limite=50&desplazamiento=0');
    assert.equal(consulta.status, 200);
    const datos = consulta.datos;
    assert.ok(datos.total > 0, 'Primero debe existir al menos una huella registrada.');
    assert.equal((await peticion(cocina.page, '/_qa/enrolamiento/registros')).status, 403);
    assert.equal(await cocina.page.getByRole('table', { name: 'Huellas registradas', exact: true }).count(), 0);
    assert.ok(!JSON.stringify(datos).includes('SIM-HUELLA-'), 'La consulta no debe exponer la referencia del lector.');
    const tabla = jefa.page.getByRole('table', { name: 'Huellas registradas', exact: true });
    await esperar(async () => await tabla.locator('tbody tr').count() === datos.datos.length,
      'La tabla no coincide con los vinculos guardados.');
    for (const fila of datos.datos) {
      const row = tabla.locator('tbody tr').filter({ hasText: `ID ${fila.comensal.usuario_id}` });
      assert.equal(await row.count(), 1);
      const texto = await row.innerText();
      assert.ok(texto.includes(fila.comensal.nombre || `Comensal ${fila.comensal.usuario_id}`));
      assert.ok(texto.includes(fila.cuenta.usuario || 'Cuenta no disponible'));
      if (fila.comensal.legajo) assert.ok(texto.includes(fila.comensal.legajo));
      assert.equal(await row.locator('time').getAttribute('datetime'), fila.registrada_en);
    }
    for (const [width, height] of [[1920, 1080], [1366, 768]]) {
      await jefa.page.setViewportSize({ width, height });
      await jefa.page.getByRole('heading', { name: 'Huellas registradas', exact: true }).scrollIntoViewIfNeeded();
      await jefa.page.locator('.huellas-registro').screenshot({ path: path.join(carpeta, `${width}x${height}.png`) });
      assert.ok(await jefa.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Hay desborde horizontal global.');
    }
    const filtro = datos.datos[0];
    const input = jefa.page.getByLabel('Buscar comensal o cuenta', { exact: true });
    await input.fill(String(filtro.comensal.usuario_id));
    assert.equal(await input.evaluate(e => document.activeElement === e), true);
    const filtrada = jefa.page.waitForResponse(r => r.url().includes('/_qa/enrolamiento/registros?') && new URL(r.url()).searchParams.get('busqueda') === String(filtro.comensal.usuario_id));
    await input.press('Enter');
    assert.equal((await filtrada).status(), 200);
    await esperar(async () => await tabla.locator('tbody tr').count() === 1, 'La busqueda no acoto el vinculo esperado.');
    assert.ok((await tabla.innerText()).includes(filtro.cuenta.usuario));

    // Error de transporte visible: se conservan las filas anteriores y se puede reintentar.
    await jefa.page.route('**/_qa/enrolamiento/registros?**', route => route.abort('failed'));
    await jefa.page.getByRole('button', { name: 'Actualizar huellas', exact: true }).click();
    await jefa.page.locator('.huellas-registro [role="alert"]').waitFor();
    assert.equal(await tabla.locator('tbody tr').count(), 1);
    await jefa.page.locator('.huellas-registro').screenshot({ path: path.join(carpeta, 'error-con-datos-conservados.png') });
    await jefa.page.unroute('**/_qa/enrolamiento/registros?**');
    await jefa.page.getByRole('button', { name: 'Actualizar huellas', exact: true }).click();
    await esperar(async () => await jefa.page.locator('.huellas-registro [role="alert"]').count() === 0, 'El reintento no recupero la consulta.');
    await input.fill('no-existe-este-comensal-qa');
    await input.press('Enter');
    await jefa.page.getByText('No hay huellas que coincidan con la búsqueda.', { exact: true }).waitFor();
    await jefa.page.locator('.huellas-registro').screenshot({ path: path.join(carpeta, 'busqueda-vacia.png') });
    fs.writeFileSync(path.join(carpeta, 'resultado.json'), JSON.stringify({ aprobado: true, total: datos.total,
      controles: ['jefa consulta vinculos reales', 'cocinera recibe 403', 'identidad y autora originales',
        'fecha con zona explicita', '1920x1080 y 1366x768', 'busqueda por teclado', 'error conserva datos', 'reintento', 'busqueda sin coincidencias'],
      vinculos: datos.datos }, null, 2));
    console.log(`APROBADO: ${datos.total} huellas vinculadas verificadas. Evidencia: ${carpeta}`);
  } catch (error) {
    fs.writeFileSync(path.join(carpeta, 'resultado.json'), JSON.stringify({ aprobado: false, error: error.message }, null, 2));
    throw error;
  } finally {
    await cocina?.cerrar(); await jefa?.cerrar(); await browser.close();
    claves.jefa = null; claves.cocinera2 = null;
  }
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
