/** UI real con HTTP simulado: no modifica cuentas ni usa contraseñas reales. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { navegador } = require('./soporte_playwright.cjs');
const APP = 'http://127.0.0.1:5173';

async function main() {
  const carpeta = path.join(__dirname, 'evidencias', `baja-cuentas-${new Date().toISOString().replace(/[:.]/g, '-')}`);
  fs.mkdirSync(carpeta, { recursive: true });
  const browser = await navegador().launch({ headless: !process.argv.includes('--visible') });
  const controles = [];
  try {
    const page = await browser.newPage({ viewport: { width: 1366, height: 768 }, reducedMotion: 'reduce' });
    const errores = [];
    page.on('pageerror', error => errores.push(error.message));
    const fila = (id, username, nombre, rol = 'cocinera') => ({ id, username, nombre, rol,
      activo: true, debe_cambiar: false, usuario_turnos_id: null, vinculada: false,
      categoria: null, creada: '2026-10-21T12:00:00', ultimo_ingreso: null, eliminada: false });
    const cuentas = [fila(1, 'root', 'Operador', 'sistemas'), fila(2, 'prueba', 'Nombre de prueba'),
      fila(3, 'conservar', 'Cuenta conservada')];
    let eliminarFalla = false;
    let editarFalla = false;
    let ediciones = 0;
    let refrescoFalla = false;
    let borrados = 0;
    await page.addInitScript(() => sessionStorage.setItem('comedor_sesion', JSON.stringify({
      access: 'fixture-sin-validez', refresh: null, usuario: 'root',
    })));
    await page.route('http://127.0.0.1:8001/**', async route => {
      const req = route.request();
      const url = new URL(req.url());
      let status = 200;
      let data = [];
      if (url.pathname === '/auth/yo') data = { id: 1, username: 'root', rol: 'sistemas', debe_cambiar: false };
      else if (url.pathname === '/admin/cuentas') {
        status = refrescoFalla ? 500 : 200;
        data = cuentas.filter(c => !c.eliminada);
      } else if (/^\/admin\/cuentas\/\d+/.test(url.pathname)) {
        const id = Number(url.pathname.split('/')[3]);
        const cuenta = cuentas.find(c => c.id === id);
        if (req.method() === 'DELETE') {
          if (eliminarFalla) { status = 500; data = { detail: 'Fallo simulado' }; }
          else { cuenta.eliminada = true; cuenta.activo = false; borrados++; status = 204; }
        } else if (req.method() === 'PATCH') {
          if (editarFalla) { status = 500; data = { detail: 'Fallo simulado' }; }
          else {
            const cambios = req.postDataJSON();
            assert.ok(!('username' in cambios) && !('password' in cambios));
            Object.assign(cuenta, cambios);
            ediciones++;
            data = cuenta;
          }
        } else {
          cuenta.activo = url.pathname.endsWith('/reactivar');
          data = cuenta;
        }
      }
      await route.fulfill(status === 204 ? { status } : { status, contentType: 'application/json', body: JSON.stringify(data) });
    });
    await page.goto(APP);
    const abrir = async () => {
      await page.getByRole('button', { name: /Administraci/ }).click();
      await page.getByRole('table', { name: 'Cuentas del comedor' }).waitFor();
    };
    await abrir();
    const tabla = page.getByRole('table', { name: 'Cuentas del comedor' });
    assert.deepEqual(await tabla.getByRole('columnheader').allTextContents(),
      ['Usuario', 'Nombre', 'Rol', 'Estado', 'Último ingreso', 'Acciones']);
    const propia = tabla.getByRole('row').filter({ hasText: 'root' });
    assert.equal(await propia.getByRole('button', { name: /Eliminar|Desactivar/ }).count(), 0);
    controles.push('Nombre visible y cuenta propia protegida');
    const objetivo = tabla.getByRole('row').filter({ has: page.getByRole('cell', { name: 'prueba', exact: true }) });
    await propia.getByRole('button', { name: 'Editar', exact: true }).click();
    assert.equal(await page.getByLabel('Rol', { exact: true }).isDisabled(), true);
    await page.getByRole('dialog').getByRole('button', { name: 'Cancelar', exact: true }).click();
    await objetivo.getByRole('button', { name: 'Editar', exact: true }).click();
    assert.equal(await page.getByLabel('Usuario', { exact: true }).getAttribute('readonly'), '');
    assert.equal(await page.getByLabel('Nombre', { exact: true }).inputValue(), 'Nombre de prueba');
    await page.getByLabel('Nombre', { exact: true }).fill('Cambio cancelado');
    await page.getByRole('dialog').getByRole('button', { name: 'Cancelar', exact: true }).click();
    assert.equal(ediciones, 0);
    await objetivo.getByRole('button', { name: 'Editar', exact: true }).click();
    await page.getByLabel('Nombre', { exact: true }).fill('Sandra Lima');
    await page.getByLabel('Rol', { exact: true }).selectOption('jefa');
    await page.screenshot({ path: path.join(carpeta, 'editar-1366.png'), animations: 'disabled' });
    editarFalla = true;
    await page.getByRole('button', { name: 'Guardar cambios', exact: true }).click();
    await page.getByRole('dialog').getByRole('alert').waitFor();
    assert.equal(await page.getByLabel('Nombre', { exact: true }).inputValue(), 'Sandra Lima');
    editarFalla = false;
    await page.getByRole('button', { name: 'Guardar cambios', exact: true }).click();
    await page.getByRole('dialog').waitFor({ state: 'detached' });
    assert.equal(ediciones, 1);
    assert.ok((await objetivo.textContent()).includes('Sandra Lima'));
    assert.equal(cuentas[1].rol, 'jefa');
    controles.push('Editar conserva usuario, protege Sistemas y guarda nombre y rol; cancelar y error conservan los datos');
    const confirmar = nombre => page.getByRole('dialog').getByRole('button', { name: nombre, exact: true }).click();
    await objetivo.getByRole('button', { name: 'Desactivar', exact: true }).click();
    await confirmar('Desactivar');
    await objetivo.getByRole('button', { name: 'Reactivar', exact: true }).waitFor();
    assert.equal(await objetivo.count(), 1);
    await objetivo.getByRole('button', { name: 'Reactivar', exact: true }).click();
    await confirmar('Reactivar');
    await objetivo.getByRole('button', { name: 'Desactivar', exact: true }).waitFor();
    controles.push('Desactivar mantiene la fila y Reactivar restaura el acceso');
    await objetivo.getByRole('button', { name: 'Eliminar', exact: true }).click();
    await confirmar('Cancelar');
    assert.equal(borrados, 0);
    await page.screenshot({ path: path.join(carpeta, 'cuentas-1366.png'), animations: 'disabled' });
    await page.setViewportSize({ width: 1920, height: 1080 });
    await objetivo.getByRole('button', { name: 'Eliminar', exact: true }).click();
    await page.screenshot({ path: path.join(carpeta, 'confirmacion-1920.png'), animations: 'disabled' });
    await confirmar('Eliminar');
    await objetivo.waitFor({ state: 'detached' });
    assert.equal(cuentas.length, 3);
    assert.equal(cuentas[1].eliminada, true);
    assert.equal(cuentas[1].activo, false);
    await page.reload();
    await abrir();
    assert.equal(await objetivo.count(), 0);
    controles.push('Cancelar no elimina; confirmar oculta y no reaparece al recargar');
    const conservada = tabla.getByRole('row').filter({ hasText: 'Cuenta conservada' });
    eliminarFalla = true;
    await conservada.getByRole('button', { name: 'Eliminar', exact: true }).click();
    await confirmar('Eliminar');
    await page.getByRole('alert').filter({ hasText: 'No se pudo eliminar' }).waitFor();
    assert.equal(await conservada.count(), 1);
    controles.push('Un error al eliminar conserva la fila');
    eliminarFalla = false;
    refrescoFalla = true;
    await conservada.getByRole('button', { name: 'Eliminar', exact: true }).click();
    await confirmar('Eliminar');
    await conservada.waitFor({ state: 'detached' });
    controles.push('Una baja confirmada permanece oculta aunque falle el refresco');
    assert.deepEqual(errores, []);
    fs.writeFileSync(path.join(carpeta, 'resultado.json'), JSON.stringify({
      aprobado: true, metodologia: 'Navegador sobre frontend real con HTTP simulado; sin escritura real', controles,
    }, null, 2));
    console.log(JSON.stringify({ aprobado: true, controles, evidencia: carpeta }, null, 2));
  } finally { await browser.close(); }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
