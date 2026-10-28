/**
 * Checklist de cocina con volumen real: ~180 personas en el almuerzo.
 *
 * Requiere el padrón sin marcas del día del laboratorio:
 *   python -B qa/prueba-basica/simular_dia.py --solo-padron --comensales 180 --aplicar
 * y deshacerlo al final con --limpiar --aplicar.
 *
 * Mide carga, largo del scroll, búsqueda, ritmo de fila, doble clic, Deshacer,
 * dos cocineras sobre la misma persona, cierre de la comida con la pantalla
 * abierta, Nuevo policía y pantallas chicas. Solo marca personas del padrón
 * simulado (usuario_id 960001–960999), nunca a los comensales QA.
 *
 *   node qa/prueba-basica/verificar_checklist_volumen_playwright.cjs [--visible]
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { navegador, credencial, clienteLab, peticion } = require('./soporte_playwright.cjs');

const APP = 'http://127.0.0.1:5173';
const FECHA = '2026-10-23';
const SIMULADO = (id) => id >= 960001 && id <= 960999;
const carpeta = path.join(__dirname, 'evidencias', `checklist-volumen-${new Date().toISOString().replace(/[:.]/g, '-')}`);
fs.mkdirSync(carpeta, { recursive: true });

const resultados = [];
const hallazgos = [];
const medidas = {};

async function caso(nombre, fn) {
  const inicio = Date.now();
  try {
    await fn();
    resultados.push({ nombre, estado: 'APROBADO', ms: Date.now() - inicio });
    console.log(`✔ ${nombre}`);
  } catch (error) {
    resultados.push({ nombre, estado: 'FALLA', ms: Date.now() - inicio, error: String(error.stack || error) });
    console.log(`✘ ${nombre}\n   ${error.message}`);
  }
}

function hallazgo(texto) {
  hallazgos.push(texto);
  console.log(`  ⚠ ${texto}`);
}

async function entrar(browser, cuenta, viewport = { width: 1366, height: 768 }) {
  const contexto = await browser.newContext({ viewport, locale: 'es-BO' });
  const page = await contexto.newPage();
  page.setDefaultTimeout(15_000);
  const errores = [];
  page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') errores.push(m.text()); });
  page.on('pageerror', (e) => errores.push(String(e)));
  await page.goto(APP);
  await page.locator('#login-usuario').fill(cuenta);
  await page.locator('#login-contrasena').fill(credencial(cuenta));
  const t0 = Date.now();
  await page.locator('button[type="submit"]').click();
  await page.getByRole('region', { name: 'Checklist de comida', exact: true }).waitFor();
  await page.locator('.checklist__lista .checklist__fila').first().waitFor();
  return { page, contexto, errores, msCarga: Date.now() - t0, cerrar: () => contexto.close() };
}

const filas = (page) => page.locator('section.checklist > ul.checklist__lista > li.checklist__fila');
const buscador = (page) => page.getByLabel('Buscar por nombre', { exact: true });
const aviso = (page) => page.locator('.checklist__aviso[role="status"]');

async function lista(page) {
  const r = await peticion(page, '/pantalla/checklist');
  assert.equal(r.status, 200);
  return r.datos;
}

async function enVista(page, locator) {
  const caja = await locator.boundingBox();
  if (!caja) return false;
  const alto = page.viewportSize().height;
  return caja.y + caja.height > 0 && caja.y < alto;
}

async function chip(page, nombre) {
  await page.getByRole('tab', { name: new RegExp(`^${nombre}`) }).click();
}

async function marcarPorBusqueda(page, persona) {
  await buscador(page).fill(persona.nombre);
  const fila = page.getByRole('checkbox', { name: `Entregar ración a ${persona.nombre}`, exact: true });
  await fila.waitFor();
  const resp = page.waitForResponse((r) => r.url().endsWith('/asistencias/checklist') && r.request().method() === 'POST');
  await fila.click();
  const datos = await (await resp).json();
  await aviso(page).filter({ hasText: persona.nombre }).waitFor();
  return datos;
}

(async () => {
  const visible = process.argv.includes('--visible');
  const browser = await navegador().launch({ headless: !visible });
  const lab = await clienteLab();
  await lab('/horario', { momento: `${FECHA}T12:00:00`, modo: 'fijo', comida_id: 2 });

  let c1;
  let c2;
  let pendientesSim = [];
  try {
    await caso('01. Carga del checklist con el almuerzo lleno (PC 1366×768)', async () => {
      c1 = await entrar(browser, process.env.QA_CUENTA_A || 'cocinera1');
      const datos = await lista(c1.page);
      assert.equal(datos.comida, 'Almuerzo');
      pendientesSim = datos.personas.filter((p) => SIMULADO(p.usuario_id) && !p.servida);
      medidas.con_derecho = datos.personas.length;
      medidas.ms_login_a_lista = c1.msCarga;
      assert.ok(pendientesSim.length >= 150, `solo ${pendientesSim.length} pendientes simulados`);
      assert.equal(await filas(c1.page).count(), datos.personas.filter((p) => !p.servida).length);
      const { alto, ventana } = await c1.page.evaluate(() => ({ alto: document.documentElement.scrollHeight, ventana: innerHeight }));
      medidas.pantallas_de_scroll = +(alto / ventana).toFixed(1);
      medidas.alto_fila_px = Math.round((await filas(c1.page).first().boundingBox()).height);
      await c1.page.screenshot({ path: path.join(carpeta, '01-arriba.png') });
      if (c1.msCarga > 3000) hallazgo(`La lista tardó ${c1.msCarga} ms en aparecer tras el login.`);
      if (medidas.pantallas_de_scroll > 8) hallazgo(`Con ${medidas.con_derecho} personas la lista mide ${medidas.pantallas_de_scroll} pantallas de alto.`);
    });

    await caso('02. Buscar 10 personas por nombre y entregar (fila con buscador)', async () => {
      const tiempos = [];
      for (const persona of pendientesSim.splice(0, 10)) {
        const t0 = Date.now();
        const r = await marcarPorBusqueda(c1.page, persona);
        tiempos.push(Date.now() - t0);
        assert.equal(r.valido, true, `${persona.nombre}: ${r.motivo}`);
      }
      medidas.ms_buscar_y_marcar_promedio = Math.round(tiempos.reduce((a, b) => a + b, 0) / tiempos.length);
      // Después de entregar, ¿la búsqueda queda escrita? (la cocinera tiene que borrarla a mano)
      const queda = await buscador(c1.page).inputValue();
      if (queda) hallazgo('Tras entregar, el texto de la búsqueda queda escrito: hay que borrarlo a mano antes de la siguiente persona.');
      await buscador(c1.page).fill('');
      // Búsqueda por apellido parcial y sin tildes
      const apellido = pendientesSim[0].nombre.split(' ')[1].toLowerCase();
      await buscador(c1.page).fill(apellido);
      const n = await filas(c1.page).count();
      assert.ok(n >= 1, 'la búsqueda por apellido parcial no encontró a nadie');
      // Búsqueda por carnet: hoy no existe (solo nombre)
      await buscador(c1.page).fill('SIMD0001');
      if ((await filas(c1.page).count()) === 0) hallazgo('El buscador no encuentra por carnet (CI), solo por nombre.');
      await buscador(c1.page).fill('');
    });

    await caso('03. Entregar al último de la lista con la página bajada: ¿se ve el aviso y el buscador?', async () => {
      await chip(c1.page, 'Pendientes');
      const ultima = filas(c1.page).filter({ hasNotText: /^QA / }).last();
      await ultima.scrollIntoViewIfNeeded();
      const nombre = (await ultima.locator('.checklist__nombre').textContent()).trim();
      const resp = c1.page.waitForResponse((r) => r.url().endsWith('/asistencias/checklist') && r.request().method() === 'POST');
      await ultima.getByRole('checkbox').click();
      assert.equal((await (await resp).json()).valido, true);
      await aviso(c1.page).filter({ hasText: nombre }).waitFor();
      await c1.page.screenshot({ path: path.join(carpeta, '03-abajo-tras-marcar.png') });
      if (!(await enVista(c1.page, aviso(c1.page)))) hallazgo('Al marcar abajo de la lista, el aviso («Ración entregada…» o «ya recibió») queda arriba, fuera de la vista.');
      if (!(await enVista(c1.page, buscador(c1.page)))) hallazgo('Abajo de la lista el buscador no se ve: para buscar a alguien hay que volver a subir.');
      pendientesSim = pendientesSim.filter((p) => p.nombre !== nombre);
      await c1.page.evaluate(() => scrollTo(0, 0));
    });

    await caso('04. Ritmo de fila: 120 entregas seguidas tocando la primera pendiente', async () => {
      await chip(c1.page, 'Pendientes');
      const tiempos = [];
      for (let i = 0; i < 120; i++) {
        const fila = filas(c1.page).filter({ hasNotText: /^QA / }).first();
        const nombre = (await fila.locator('.checklist__nombre').textContent()).trim();
        const t0 = Date.now();
        const resp = c1.page.waitForResponse((r) => r.url().endsWith('/asistencias/checklist') && r.request().method() === 'POST');
        await fila.getByRole('checkbox').click();
        const r = await (await resp).json();
        assert.equal(r.valido, true, `${nombre}: ${r.motivo}`);
        await c1.page.getByRole('checkbox', { name: `Entregar ración a ${nombre}`, exact: true }).waitFor({ state: 'detached' });
        tiempos.push(Date.now() - t0);
      }
      tiempos.sort((a, b) => a - b);
      medidas.ritmo_ms_mediana = tiempos[60];
      medidas.ritmo_ms_p95 = tiempos[114];
      if (medidas.ritmo_ms_p95 > 1500) hallazgo(`Cada entrega tarda hasta ${medidas.ritmo_ms_p95} ms (p95) en reflejarse.`);
      await c1.page.screenshot({ path: path.join(carpeta, '04-tras-120.png') });
    });

    await caso('05. Doble clic por accidente: una sola ración', async () => {
      const fila = filas(c1.page).filter({ hasNotText: /^QA / }).first();
      const nombre = (await fila.locator('.checklist__nombre').textContent()).trim();
      const posts = [];
      const escucha = (r) => { if (r.url().endsWith('/asistencias/checklist') && r.request().method() === 'POST') posts.push(r); };
      c1.page.on('response', escucha);
      await fila.getByRole('checkbox').dblclick();
      await aviso(c1.page).filter({ hasText: nombre }).waitFor();
      await c1.page.waitForTimeout(800);
      c1.page.off('response', escucha);
      const datos = await lista(c1.page);
      const persona = datos.personas.find((p) => p.nombre === nombre);
      assert.equal(persona.servida, true);
      const textoAviso = await aviso(c1.page).textContent();
      medidas.doble_clic_posts = posts.length;
      if (posts.length > 1) hallazgo(`El doble clic envió ${posts.length} marcas (el servidor rechazó la segunda, aviso: «${textoAviso.trim()}»).`);
    });

    await caso('06. Deshacer una entrega propia y volver a entregar', async () => {
      await chip(c1.page, 'Entregadas');
      const fila = filas(c1.page).filter({ has: c1.page.getByRole('button', { name: 'Deshacer' }) }).first();
      const nombre = (await fila.locator('.checklist__nombre').textContent()).trim();
      await fila.getByRole('button', { name: 'Deshacer' }).click();
      await aviso(c1.page).filter({ hasText: `Se deshizo la entrega a ${nombre}` }).waitFor();
      await chip(c1.page, 'Pendientes');
      const persona = { nombre };
      const r = await marcarPorBusqueda(c1.page, persona);
      assert.equal(r.valido, true);
      await buscador(c1.page).fill('');
    });

    await caso('07. Dos cocineras marcan a la misma persona al mismo tiempo', async () => {
      c2 = await entrar(browser, process.env.QA_CUENTA_B || 'cocinera2');
      const datos = await lista(c1.page);
      const persona = datos.personas.find((p) => SIMULADO(p.usuario_id) && !p.servida);
      for (const c of [c1, c2]) await buscador(c.page).fill(persona.nombre);
      const cuerpos = await Promise.all([c1, c2].map(async (c) => {
        const [r] = await Promise.all([
          c.page.waitForResponse((x) => x.url().endsWith('/asistencias/checklist') && x.request().method() === 'POST'),
          c.page.getByRole('checkbox', { name: `Entregar ración a ${persona.nombre}`, exact: true }).click(),
        ]);
        return r.json();
      }));
      const validas = cuerpos.filter((c) => c.valido).length;
      assert.equal(validas, 1, `raciones válidas: ${validas}`);
      assert.ok(cuerpos.some((c) => c.motivo === 'duplicado'));
      // La otra cocinera ve la entrega pero no puede deshacerla.
      const perdedora = cuerpos[0].valido ? c2 : c1;
      await buscador(perdedora.page).fill(persona.nombre);
      await chip(perdedora.page, 'Todas');
      const fila = filas(perdedora.page).filter({ hasText: persona.nombre });
      await fila.locator('.checklist__sello').waitFor();
      assert.equal(await fila.getByRole('button', { name: 'Deshacer' }).count(), 0);
      await chip(perdedora.page, 'Pendientes');
      for (const c of [c1, c2]) await buscador(c.page).fill('');
    });

    await caso('08. Las marcas de otra cocinera llegan solas (refresco de 15 s)', async () => {
      const datos = await lista(c2.page);
      const persona = datos.personas.find((p) => SIMULADO(p.usuario_id) && !p.servida);
      await chip(c1.page, 'Pendientes');
      await buscador(c1.page).fill(persona.nombre);
      await c1.page.getByRole('checkbox', { name: `Entregar ración a ${persona.nombre}`, exact: true }).waitFor();
      const r = await marcarPorBusqueda(c2.page, persona);
      assert.equal(r.valido, true);
      const t0 = Date.now();
      await c1.page.getByRole('checkbox', { name: `Entregar ración a ${persona.nombre}`, exact: true }).waitFor({ state: 'detached', timeout: 20_000 });
      medidas.ms_hasta_ver_marca_ajena = Date.now() - t0;
      await buscador(c1.page).fill('');
      await buscador(c2.page).fill('');
    });

    await caso('09. Nuevo policía por nombre y Deshacer', async () => {
      await c1.page.getByRole('button', { name: 'Nuevo policía' }).click();
      await c1.page.getByPlaceholder('Ej.: Juan Pérez Mamani').fill('Policía Prueba Volumen');
      await c1.page.getByRole('button', { name: 'Entregar ración' }).click();
      await aviso(c1.page).filter({ hasText: 'Policía Prueba Volumen' }).waitFor();
      const seccion = c1.page.getByRole('region', { name: 'Policías en Almuerzo' });
      await seccion.waitFor();
      await c1.page.screenshot({ path: path.join(carpeta, '09-policia.png'), fullPage: false });
      if (!(await enVista(c1.page, seccion))) hallazgo('Los policías se listan al final, debajo de las ~180 personas: tras registrar uno no se ve en pantalla.');
      await seccion.getByRole('button', { name: 'Deshacer' }).click();
      await aviso(c1.page).filter({ hasText: 'Se deshizo la ración del policía' }).waitFor();
    });

    await caso('10. Pantallas chicas: laptop 1280×720, tablet 1024×768 y 800×1280, celular 390×844', async () => {
      for (const [ancho, alto] of [[1280, 720], [1024, 768], [800, 1280], [390, 844]]) {
        await c1.page.setViewportSize({ width: ancho, height: alto });
        await c1.page.waitForTimeout(300);
        const m = await c1.page.evaluate(() => ({
          desborde: document.documentElement.scrollWidth - innerWidth,
          primera: document.querySelector('.checklist__fila')?.getBoundingClientRect().top ?? -1,
        }));
        await c1.page.screenshot({ path: path.join(carpeta, `10-${ancho}x${alto}.png`) });
        medidas[`primera_fila_y_${ancho}x${alto}`] = Math.round(m.primera);
        if (m.desborde > 1) hallazgo(`A ${ancho}×${alto} la página se desborda ${m.desborde}px en horizontal.`);
        if (m.primera > alto) hallazgo(`A ${ancho}×${alto} la primera persona queda debajo del borde: hay que bajar para empezar a marcar.`);
      }
      await c1.page.setViewportSize({ width: 1366, height: 768 });
    });

    await caso('11. La comida cierra con la pantalla abierta (14:30)', async () => {
      const datos = await lista(c1.page);
      const persona = datos.personas.find((p) => SIMULADO(p.usuario_id) && !p.servida);
      await buscador(c1.page).fill(persona.nombre);
      await c1.page.getByRole('checkbox', { name: `Entregar ración a ${persona.nombre}`, exact: true }).waitFor();
      await lab('/horario', { momento: `${FECHA}T14:31:00`, modo: 'fijo', comida_id: 2 });
      const resp = c1.page.waitForResponse((r) => r.url().endsWith('/asistencias/checklist') && r.request().method() === 'POST');
      await c1.page.getByRole('checkbox', { name: `Entregar ración a ${persona.nombre}`, exact: true }).click();
      const r = await (await resp).json();
      assert.equal(r.valido, false);
      assert.equal(r.motivo, 'fuera_horario');
      await c1.page.getByText('Fuera de horario', { exact: true }).waitFor();
      await c1.page.screenshot({ path: path.join(carpeta, '11-cerrada.png') });
      // El Deshacer ya no aplica: la comida cerró.
      const entregadas = (await lista(c1.page));
      assert.equal(entregadas.fuera_de_horario, true);
    });

    await caso('12. Pasa sola al Té (15:30) sin recargar', async () => {
      await lab('/horario', { momento: `${FECHA}T15:40:00`, modo: 'fijo', comida_id: 3 });
      const t0 = Date.now();
      await c1.page.getByRole('heading', { name: 'Té' }).waitFor({ timeout: 20_000 });
      medidas.ms_hasta_ver_te = Date.now() - t0;
      const datos = await lista(c1.page);
      assert.equal(datos.comida, 'Té');
      assert.ok(datos.personas.filter((p) => SIMULADO(p.usuario_id)).every((p) => !p.servida));
      await c1.page.screenshot({ path: path.join(carpeta, '12-te.png') });
    });

    await caso('13. Bordes del horario en hora de Tarija', async () => {
      const casos = [
        ['07:29:59', null], ['07:30:00', 'Desayuno'], ['09:29:59', 'Desayuno'], ['09:30:00', null],
        ['11:29:59', null], ['11:30:00', 'Almuerzo'], ['14:29:59', 'Almuerzo'], ['14:30:00', null],
        ['15:30:00', 'Té'], ['17:29:59', 'Té'], ['17:30:00', 'Cena'], ['19:14:59', 'Cena'], ['19:15:00', null],
      ];
      const fallos = [];
      for (const [hora, esperado] of casos) {
        await lab('/horario', { momento: `${FECHA}T${hora}`, modo: 'fijo' });
        const d = await lista(c1.page);
        const obtenido = d.fuera_de_horario ? null : d.comida;
        if (obtenido !== esperado) fallos.push(`${hora}: ${obtenido} (esperado ${esperado})`);
      }
      assert.deepEqual(fallos, []);
    });

    await caso('14. Consola del navegador sin errores', async () => {
      const todos = [...c1.errores, ...(c2?.errores ?? [])].filter((t) => !/Download the React DevTools/.test(t));
      if (todos.length) fs.writeFileSync(path.join(carpeta, 'consola.txt'), todos.join('\n'));
      assert.equal(todos.length, 0, todos.slice(0, 3).join(' | '));
    });
  } finally {
    await c1?.cerrar();
    await c2?.cerrar();
    await browser.close();
    await lab('/horario', { momento: `${FECHA}T12:00:00`, modo: 'fijo', comida_id: 2 }).catch(() => {});
    const informe = { fecha_lab: FECHA, resultados, medidas, hallazgos };
    fs.writeFileSync(path.join(carpeta, 'resultado.json'), JSON.stringify(informe, null, 2));
    const fallidos = resultados.filter((r) => r.estado !== 'APROBADO').length;
    console.log(`\n${resultados.length - fallidos}/${resultados.length} APROBADO · evidencias: ${carpeta}`);
    console.log('Medidas:', JSON.stringify(medidas));
    process.exitCode = fallidos ? 1 : 0;
  }
})();
