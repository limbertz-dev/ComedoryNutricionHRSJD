'use strict';

// API y MySQL reales de QA. Solo se altera el transporte en los casos indicados.
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { navegador, credencial, clienteLab, salud, sesion, peticion, esperar } = require('./soporte_playwright.cjs');
const API = 'http://127.0.0.1:8001';
const PAUSA = ms => new Promise(resolve => setTimeout(resolve, ms));
const salida = path.join(__dirname, 'evidencias', `concurrencia-${new Date().toISOString().replace(/[:.]/g, '-')}`);
const resultados = [];

async function enviar(page, ruta, cuerpo, clave = randomUUID(), grupo = null) {
  return page.evaluate(async ({ api, ruta, cuerpo, clave, grupo }) => {
    const access = JSON.parse(sessionStorage.getItem('comedor_sesion')).access;
    const res = await fetch(api + ruta, { method: 'POST', signal: AbortSignal.timeout(25000),
      headers: { Authorization: `Bearer ${access}`, 'Content-Type': 'application/json',
        'Idempotency-Key': clave, ...(grupo ? { 'X-QA-Grupo': grupo } : {}) }, body: JSON.stringify(cuerpo) });
    const texto = await res.text();
    let datos;
    try { datos = JSON.parse(texto); } catch { datos = { error: 'Respuesta no JSON' }; }
    return { status: res.status, datos };
  }, { api: API, ruta, cuerpo, clave, grupo });
}

function lectura(page, referencia, { desconocida = false, clave, grupo } = {}) {
  return enviar(page, '/_qa/concurrencia/lecturas', { referencia, desconocida }, clave, grupo);
}

async function grupo(page, participantes) {
  const id = randomUUID();
  assert.equal((await enviar(page, '/_qa/concurrencia/grupos', { id, participantes })).status, 200);
  return id;
}

function comprobarLectura(res, uid, motivo = null) {
  assert.equal(res.status, 200, `La lectura devolvió HTTP ${res.status}: ${JSON.stringify(res.datos)}`);
  assert.equal(res.datos.usuario_id, uid);
  assert.equal(res.datos.valido, motivo === null);
  assert.equal(res.datos.motivo, motivo);
  assert.ok(Number.isSafeInteger(res.datos.lectura_id) && res.datos.lectura_id > 0);
  assert.equal(Number.isSafeInteger(res.datos.asistencia_id) && res.datos.asistencia_id > 0, motivo === null);
}

async function abrirIdentificacion(page, uid) {
  const identificar = page.locator('.identificar__lista').getByRole('button', { name: 'Identificar', exact: true });
  await identificar.first().click();
  await page.locator('#identificar-persona').selectOption(String(uid));
  assert.equal(await page.getByRole('button', { name: 'Confirmar entrega', exact: true }).isEnabled(), true);
}

async function main() {
  await salud();
  const lab = await clienteLab();
  const claves = Object.fromEntries(['cocinera1', 'cocinera2', 'cocinera3', 'jefa'].map(c => [c, credencial(c)]));
  const browser = await navegador().launch({ headless: !process.argv.includes('--visible') });
  fs.mkdirSync(salida, { recursive: true });
  let sesiones = {};
  let referencias = {};

  async function comenzar(nombre, hora = '12:00:00', comida = 2) {
    for (const s of Object.values(sesiones)) await s.cerrar();
    sesiones = {};
    console.log(`\n${nombre}`);
    await lab('/nuevo', { confirmar: true, momento: `2026-10-19T${hora}`, modo: 'fijo', comida_id: comida });
    await salud();
    // Sesiones aisladas: cookies/storage e identidad independientes.
    for (const cuenta of Object.keys(claves)) sesiones[cuenta] = await sesion(browser, cuenta, claves[cuenta]);
    referencias = {};
    for (const uid of [900101, 900102, 900103]) {
      const res = await enviar(sesiones.cocinera1.page, '/_qa/enrolamiento/capturas', { usuario_id: uid });
      assert.equal(res.status, 200);
      assert.equal(res.datos.usuario_id, uid);
      referencias[uid] = res.datos.referencia;
    }
    return sesiones;
  }

  async function comprobar(nombre, cantidades, grupos = [], entregaManual = null) {
    const res = await peticion(sesiones.cocinera1.page, '/_qa/concurrencia/estado');
    assert.equal(res.status, 200, 'Falló la validación de titularidad/relaciones del diario.');
    const d = res.datos;
    for (const [tabla, n] of Object.entries(cantidades)) assert.equal(d[tabla].length, n, `${nombre}: ${tabla}`);
    for (const asistencia of d.asistencias) {
      const original = d.lecturas.find(l => l.id === asistencia.lectura_id);
      assert.ok(original, 'Asistencia sin lectura propia.');
      if (asistencia.metodo === 'biometrico') assert.equal(original.usuario_id, asistencia.usuario_id);
    }
    if (entregaManual) {
      const entrega = d.asistencias.find(a => a.metodo === 'manual');
      assert.ok(entrega, 'Falta la entrega manual esperada.');
      assert.equal(entrega.usuario_id, entregaManual.uid);
      assert.equal(entrega.registrado_por_cuenta, sesiones[entregaManual.cuenta].usuario.id);
    }
    for (const [id, n] of grupos) assert.equal(d.grupos[id]?.llegadas, n, 'Las transacciones no coincidieron antes del INSERT.');
    const pantalla = await peticion(sesiones.cocinera1.page, '/pantalla/estado');
    assert.equal(pantalla.status, 200);
    assert.equal(pantalla.datos.totales_del_dia.raciones_servidas, cantidades.asistencias, 'Contador distinto de las entregas persistidas.');
    const consulta = await peticion(sesiones.jefa.page, '/intervenciones-cocina');
    assert.equal(consulta.status, 200);
    const filas = consulta.datos.datos;
    assert.ok(Array.isArray(filas));
    for (const i of d.intervenciones) {
      const fila = filas.find(f => f.id === i.id);
      assert.ok(fila, 'Falta una intervención en la consulta autenticada de la jefa.');
      assert.equal(fila.decision_original.lectura_id, i.lectura_id);
      assert.equal(fila.decision_original.resultado, 'rechazada');
      assert.equal(fila.decision_original.motivo, 'no_identificado');
      assert.equal(fila.cuenta.id, i.cuenta_id);
      const cuenta = Object.entries(sesiones).find(([, s]) => s.usuario.id === i.cuenta_id)?.[0];
      assert.ok(cuenta, 'La intervención pertenece a una cuenta ajena a las sesiones de prueba.');
      assert.equal(fila.cuenta.usuario, cuenta);
      assert.equal(fila.comensal.usuario_id, i.usuario_id);
      assert.equal(fila.resultado, i.resultado);
      if (i.resultado === 'registrada') assert.equal(fila.resultado_final.asistencia_id, i.asistencia_id);
      const original = d.lecturas.find(l => l.id === i.lectura_id);
      assert.equal(original.usuario_id, null);
      assert.equal(original.resultado, 'rechazada');
    }
    await sesiones.jefa.page.reload();
    await sesiones.jefa.page.locator('button.supervision__pestana').filter({ hasText: 'Todas' }).click();
    if (d.intervenciones.length) {
      const tabla = sesiones.jefa.page.getByRole('table', { name: 'Intervenciones de cocina', exact: true });
      await esperar(async () => await tabla.locator('tbody tr').count() === d.intervenciones.length,
        'La tabla de la jefa no coincide con las intervenciones persistidas.');
      const contenido = await tabla.innerText();
      for (const i of d.intervenciones) {
        const fila = filas.find(f => f.id === i.id);
        assert.ok(contenido.includes(fila.cuenta.nombre ?? fila.cuenta.usuario), 'La jefa no ve la cuenta responsable.');
      }
      await tabla.screenshot({ path: path.join(salida, `${String(resultados.length + 1).padStart(2, '0')}-intervenciones.png`) });
    }
    const indice = String(resultados.length + 1).padStart(2, '0');
    await sesiones.jefa.page.screenshot({ path: path.join(salida, `${indice}-jefa.png`), fullPage: true });
    resultados.push({ caso: nombre, estado: 'APROBADO', ...d });
    guardar();
    console.log(`PASA: ${nombre} (${d.lecturas.length} lecturas, ${d.asistencias.length} entregas, ${d.intervenciones.length} intervenciones).`);
    return d;
  }

  function guardar(error) {
    fs.writeFileSync(path.join(salida, 'resultado.json'), JSON.stringify({
      alcance: 'MySQL QA real; huellas simuladas. Barreras SQL solo en adaptador QA. Sin lector físico.',
      finalizado: !error && resultados.length === 8, resultados, ...(error ? { error } : {})
    }, null, 2));
  }

  try {
    let s = await comenzar('01. Reenvío del mismo contacto: seis solicitudes con la misma clave');
    const claveContacto = randomUUID();
    const repetidas = await Promise.all(Array.from({ length: 6 }, () => lectura(s.cocinera1.page, referencias[900101], { clave: claveContacto })));
    repetidas.forEach(r => comprobarLectura(r, 900101));
    assert.equal(new Set(repetidas.map(r => r.datos.lectura_id)).size, 1);
    assert.equal(new Set(repetidas.map(r => r.datos.asistencia_id)).size, 1);
    const conflicto = await lectura(s.cocinera1.page, referencias[900102], { clave: claveContacto });
    assert.equal(conflicto.status, 409, 'Una clave no puede cambiar de identidad.');
    await comprobar('Reenvío idéntico y reutilización de clave con otra persona', { lecturas: 1, asistencias: 1, intervenciones: 0 });

    s = await comenzar('02. Misma persona: seis transacciones coincidentes desde tres sesiones');
    const g1 = await grupo(s.cocinera1.page, 6);
    const cocinas = [s.cocinera1.page, s.cocinera2.page, s.cocinera3.page];
    const choques = await Promise.all(Array.from({ length: 6 }, (_, i) => lectura(cocinas[i % 3], referencias[900101], { grupo: g1 })));
    assert.equal(choques.filter(r => r.status === 200 && r.datos.valido).length, 1);
    choques.forEach(r => comprobarLectura(r, 900101, r.datos.valido ? null : 'duplicado'));
    await comprobar('Misma persona en lectores simultáneos: una entrega y cinco rechazos', { lecturas: 6, asistencias: 1, intervenciones: 0 }, [[g1, 6]]);

    s = await comenzar('03. Tres personas coincidentes; respuestas entregadas fuera de orden');
    const g2 = await grupo(s.cocinera1.page, 3);
    const orden = [];
    await s.cocinera1.page.route('**/_qa/concurrencia/lecturas', async route => {
      const respuesta = await route.fetch();
      if (route.request().postDataJSON().referencia === referencias[900101]) await PAUSA(700);
      await route.fulfill({ response: respuesta });
    });
    const distintas = await Promise.all([900101, 900102, 900103].map(async uid => {
      const res = await lectura(s.cocinera1.page, referencias[uid], { grupo: g2 });
      comprobarLectura(res, uid);
      orden.push(uid);
      return res;
    }));
    assert.equal(orden.at(-1), 900101);
    assert.equal(new Set(distintas.map(r => r.datos.asistencia_id)).size, 3);
    await s.cocinera1.page.unroute('**/_qa/concurrencia/lecturas');
    const d3 = await comprobar('Personas diferentes sin mezcla de identidades; respuestas fuera de orden', { lecturas: 3, asistencias: 3, intervenciones: 0 }, [[g2, 3]]);
    for (const r of distintas) assert.equal(d3.asistencias.find(a => a.id === r.datos.asistencia_id).usuario_id, r.datos.usuario_id);

    s = await comenzar('04. Límite del desayuno según la ventana efectiva de la base', '08:00:00', 1);
    const pendientes4 = await peticion(s.cocinera1.page, '/pantalla/lecturas-por-identificar');
    assert.equal(pendientes4.status, 200);
    const ventana4 = pendientes4.datos.servicio;
    assert.equal(ventana4?.comida_id, 1);
    assert.match(ventana4.fin, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/);
    const antes4 = new Date(Date.parse(`${ventana4.fin}Z`) - 1000).toISOString().slice(0, 19);
    console.log(`Ventana real: ${ventana4.inicio} a ${ventana4.fin}; lecturas un segundo antes y al cierre.`);
    await lab('/horario', { momento: antes4, modo: 'fijo' });
    comprobarLectura(await lectura(s.cocinera1.page, referencias[900101]), 900101);
    await lab('/horario', { momento: ventana4.fin, modo: 'fijo' });
    comprobarLectura(await lectura(s.cocinera1.page, referencias[900102]), 900102, 'fuera_horario');
    await comprobar('Cierre de horario sin conceder una entrega fuera de ventana', { lecturas: 2, asistencias: 1, intervenciones: 0 });

    s = await comenzar('05. Doble clic en Confirmar entrega, con respuesta demorada');
    const desconocida5 = await lectura(s.cocinera2.page, referencias[900102], { desconocida: true });
    comprobarLectura(desconocida5, null, 'no_identificado');
    await abrirIdentificacion(s.cocinera2.page, 900102);
    let envios5 = 0;
    let respuesta5;
    await s.cocinera2.page.route('**/asistencias/lecturas/*/identificar', async route => {
      envios5 += 1;
      const res = await route.fetch();
      respuesta5 = { status: res.status(), datos: await res.json() };
      await PAUSA(500);
      await route.fulfill({ response: res });
    });
    await s.cocinera2.page.getByRole('button', { name: 'Confirmar entrega', exact: true }).dblclick({ delay: 20 });
    await esperar(async () => !!respuesta5, 'No se recibió la confirmación real.');
    assert.equal(respuesta5.status, 200);
    assert.equal(respuesta5.datos.valido, true);
    await PAUSA(700);
    assert.equal(envios5, 1, 'El doble clic emitió más de una confirmación.');
    await s.cocinera2.page.getByText('Entrega registrada', { exact: true }).waitFor();
    await comprobar('Doble clic bloqueado mientras la entrega está en curso', { lecturas: 1, asistencias: 1, intervenciones: 1 }, [], { cuenta: 'cocinera2', uid: 900102 });

    s = await comenzar('06. Dos cocineras intentan identificar la misma lectura como personas distintas');
    const desconocida6 = await lectura(s.cocinera1.page, referencias[900102], { desconocida: true });
    comprobarLectura(desconocida6, null, 'no_identificado');
    const ruta6 = `/asistencias/lecturas/${desconocida6.datos.lectura_id}/identificar`;
    const resoluciones = await Promise.all([enviar(s.cocinera1.page, ruta6, { usuario_id: 900101 }),
      enviar(s.cocinera2.page, ruta6, { usuario_id: 900102 })]);
    assert.equal(resoluciones.filter(r => r.status === 200 && r.datos.valido).length, 1);
    assert.equal(resoluciones.filter(r => r.status === 409).length, 1);
    const ganador6 = resoluciones[0].datos.valido ? { cuenta: 'cocinera1', uid: 900101 } : { cuenta: 'cocinera2', uid: 900102 };
    const d6 = await comprobar('Dos cocineras, una lectura: una ganadora y conflicto trazable', { lecturas: 1, asistencias: 1, intervenciones: 2 }, [], ganador6);
    assert.equal(d6.intervenciones.filter(i => i.resultado === 'registrada').length, 1);
    assert.equal(d6.intervenciones.find(i => i.resultado === 'rechazada').motivo_rechazo, 'lectura_ya_resuelta');

    s = await comenzar('07. Identificación manual contra lectura biométrica de la misma persona');
    const desconocida7 = await lectura(s.cocinera2.page, referencias[900102], { desconocida: true });
    comprobarLectura(desconocida7, null, 'no_identificado');
    const g7 = await grupo(s.cocinera1.page, 2);
    const carrera7 = await Promise.all([
      enviar(s.cocinera2.page, `/asistencias/lecturas/${desconocida7.datos.lectura_id}/identificar`, { usuario_id: 900102 }, randomUUID(), g7),
      lectura(s.cocinera1.page, referencias[900102], { grupo: g7 })]);
    carrera7.forEach(r => assert.equal(r.status, 200));
    assert.equal(carrera7.filter(r => r.datos.valido).length, 1);
    assert.equal(carrera7.filter(r => r.datos.motivo === 'duplicado').length, 1);
    await comprobar('Aprobación manual y biométrica simultáneas: una sola ración', { lecturas: 2, asistencias: 1, intervenciones: 1 }, [[g7, 2]], carrera7[0].datos.valido ? { cuenta: 'cocinera2', uid: 900102 } : null);

    s = await comenzar('08. Pérdida de respuesta después del COMMIT y Verificar entrega');
    const desconocida8 = await lectura(s.cocinera2.page, referencias[900102], { desconocida: true });
    comprobarLectura(desconocida8, null, 'no_identificado');
    await abrirIdentificacion(s.cocinera2.page, 900102);
    const intentos8 = [];
    await s.cocinera2.page.route('**/asistencias/lecturas/*/identificar', async route => {
      const res = await route.fetch();
      const datos = await res.json();
      assert.equal(res.status(), 200);
      assert.equal(datos.valido, true);
      intentos8.push({ clave: route.request().headers()['idempotency-key'], cuerpo: route.request().postDataJSON(), datos });
      if (intentos8.length === 1) await route.abort('failed');
      else await route.fulfill({ response: res });
    });
    await s.cocinera2.page.getByRole('button', { name: 'Confirmar entrega', exact: true }).click();
    const verificar = s.cocinera2.page.getByRole('button', { name: 'Verificar entrega', exact: true });
    await verificar.waitFor();
    assert.equal(await s.cocinera2.page.locator('#identificar-persona').count(), 0, 'No se debe poder cambiar de identidad con resultado incierto.');
    await s.cocinera2.page.screenshot({ path: path.join(salida, '08-resultado-incierto.png'), fullPage: true });
    await verificar.click();
    await esperar(async () => intentos8.length === 2, 'Falta el reintento idempotente.');
    assert.equal(intentos8[0].clave, intentos8[1].clave);
    assert.deepEqual(intentos8[0].cuerpo, intentos8[1].cuerpo);
    assert.equal(intentos8[1].datos.reintento, true);
    assert.equal(intentos8[0].datos.asistencia_id, intentos8[1].datos.asistencia_id);
    await s.cocinera2.page.getByText('Entrega registrada', { exact: true }).waitFor();
    await comprobar('Respuesta perdida tras guardar: reintento recupera la misma entrega', { lecturas: 1, asistencias: 1, intervenciones: 1 }, [], { cuenta: 'cocinera2', uid: 900102 });
    console.table(resultados.map(({ caso, estado }) => ({ caso, estado })));
    console.log(`Evidencia: ${salida}`);
  } catch (error) {
    guardar(`${error.name}: ${error.message}`);
    // Solo pantallas ya autenticadas; nunca capturar el formulario de acceso.
    for (const cuenta of ['cocinera2', 'jefa']) {
      const page = sesiones[cuenta]?.page;
      if (page && !page.isClosed() && await page.locator('#login-usuario').count() === 0) {
        await page.screenshot({ path: path.join(salida, `fallo-${cuenta}.png`), fullPage: true }).catch(() => {});
      }
    }
    throw error;
  } finally {
    for (const s of Object.values(sesiones)) await s.cerrar();
    await browser.close();
    for (const cuenta of Object.keys(claves)) claves[cuenta] = null;
  }
}

if (require.main === module) main().catch(error => { console.error(error.message); process.exitCode = 1; });
module.exports = { comprobarLectura };
