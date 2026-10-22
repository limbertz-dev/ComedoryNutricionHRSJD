import test, { afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { obtenerPersonal, marcarAsistencia, obtenerEstadoPantalla,
  obtenerUltimasMarcaciones, obtenerComidasDelDia,
  obtenerHistorialDiarioPersonal, obtenerHistorialMensualPersonal, obtenerDiaPersonal,
  obtenerPeriodos, obtenerGestiones, obtenerMesesDeGestion,
  obtenerRegistroDiario, obtenerInformeMensual, obtenerResumenGestion,
  obtenerInformeRaciones, etiquetaDeRango } from '../src/api.js';
import { notasDeInforme } from '../src/exportaciones.js';

const fetchOriginal = globalThis.fetch;
afterEach(() => { globalThis.fetch = fetchOriginal; });
const comensal = (id) => ({
  usuario_id: id, nombre_completo: `Persona ${id}`, numero_item: `ITEM-${id}`,
  categoria: 'Categoría hospital', categoria_reporte: 'Médico', tiene_ficha: true,
});
const persona = { id: 3, nombre: 'Persona 3', categoria: 'Médico', legajo: 'ITEM-3', yaMarcoHoy: true };
const json = (datos, status = 200) => new Response(JSON.stringify(datos), { status });

test('reúne todas las páginas, conserva users.id y hace visible la ficha incompleta', async () => {
  const offsets = [];
  globalThis.fetch = async (ruta) => {
    const offset = Number(new URL(ruta).searchParams.get('desplazamiento'));
    offsets.push(offset);
    return json({ total: 3, datos: offset === 0
      ? [comensal(10), comensal(20)]
      : [{ usuario_id: 30, nombre_completo: null, tiene_ficha: false, categoria_reporte: null }] });
  };
  const personal = await obtenerPersonal();
  assert.deepEqual(offsets, [0, 2]);
  assert.deepEqual(personal.map(({ id }) => id), [10, 20, 30]);
  assert.equal(personal[0].categoria, 'Médico');
  assert.equal(personal[0].legajo, 'ITEM-10');
  assert.equal(personal[2].nombre, 'Usuario 30 (sin ficha)');
  assert.equal(personal[2].categoria, 'Sin clasificar');
});

test('un padrón vacío es válido; una página incompleta no se publica como padrón completo', async () => {
  globalThis.fetch = async () => json({ total: 0, datos: [] });
  assert.deepEqual(await obtenerPersonal(), []);
  globalThis.fetch = async () => json({ total: 5, datos: [] });
  await assert.rejects(obtenerPersonal(), /página incompleta/);
});

test('los errores HTTP, de red y JSON no se sustituyen por personal ficticio', async () => {
  globalThis.fetch = async () => json({}, 503);
  await assert.rejects(obtenerPersonal(), /HTTP 503/);
  globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
  await assert.rejects(obtenerPersonal(), /No se pudo conectar/);
  globalThis.fetch = async () => new Response('<html>error</html>');
  await assert.rejects(obtenerPersonal(), /respuesta inválida/);
});

test('registra la identidad elegida sin aplicar las reglas locales del mock', async () => {
  let peticiones = 0;
  globalThis.fetch = async (ruta, opciones) => {
    peticiones += 1;
    assert.equal(new URL(ruta).pathname, '/asistencias');
    assert.equal(opciones.method, 'POST');
    assert.deepEqual(JSON.parse(opciones.body), { usuario_id: 3, metodo: 'manual' });
    return json({ valido: true, motivo: null, usuario_id: 3, nombre: 'Nombre del servidor',
      comida: 'Almuerzo', titulo: 'Marcación válida', detalle: 'Habilitada', raciones_restantes: null });
  };
  const evento = await marcarAsistencia(3, { persona });
  assert.equal(peticiones, 1);
  assert.equal(evento.valido, true);
  assert.equal(evento.persona.id, 3);
  assert.equal(evento.persona.nombre, 'Nombre del servidor');
  assert.equal(evento.tiempo, 'Almuerzo');
  assert.equal(evento.motivo, 'ok');
  assert.equal(evento.raciones_restantes, null);
});

test('las últimas marcaciones traen la fecha pedida y los rechazos con motivo legible', async () => {
  const rutas = [];
  globalThis.fetch = async (ruta) => {
    rutas.push(new URL(ruta).search);
    return json([
      { id: 8, fecha_hora: '2026-09-10T12:30:05', usuario_id: 3, nombre: 'Persona 3',
        categoria: 'Médico', resultado: 'aceptada', motivo: null, valido: true, dispositivo: 'lector-01',
        origen: 'lectura_biometrica', clave_evento: 'lectura_biometrica:8' },
      { id: 7, fecha_hora: '2026-09-10T12:29:00', usuario_id: 4, nombre: null, categoria: null,
        resultado: 'rechazada', motivo: 'duplicado', valido: false, dispositivo: 'lector-01',
        origen: 'lectura_biometrica', clave_evento: 'lectura_biometrica:7' },
    ]);
  };
  const dehoy = await obtenerUltimasMarcaciones();
  const delDia = await obtenerUltimasMarcaciones({ fecha: '2026-09-01', limite: 5 });
  const deCena = await obtenerUltimasMarcaciones({ comidaId: 4 });
  assert.deepEqual(rutas, ['?limite=20', '?limite=5&fecha=2026-09-01', '?limite=20&comida_id=4']);
  assert.equal(dehoy.length, 2);
  assert.equal(dehoy[0].valido, true);
  assert.equal(dehoy[0].titulo, 'Marcación válida');
  assert.match(dehoy[0].hora, /^\d{2}:\d{2}:\d{2}$/);
  assert.equal(dehoy[1].titulo, 'Ya recibió su comida');
  assert.equal(dehoy[1].persona.nombre, 'Desconocido');
  assert.equal(dehoy[1].persona.categoria, 'Sin clasificar');
  assert.equal(delDia.length, 2);
  assert.equal(deCena.length, 2);

  globalThis.fetch = async () => json({ datos: [] });
  await assert.rejects(obtenerUltimasMarcaciones(), /lista de marcaciones inválida/);
  globalThis.fetch = async () => json([{ fecha_hora: '2026-09-10T12:30:05' }]);
  await assert.rejects(obtenerUltimasMarcaciones(), /sin identificador/);
  globalThis.fetch = async () => json({}, 500);
  await assert.rejects(obtenerUltimasMarcaciones(), /HTTP 500/);
});

test('las últimas marcaciones exponen la comida para el filtro de la tarjeta', async () => {
  globalThis.fetch = async () => json([
    { id: 1, fecha_hora: '2026-09-10T19:20:59', usuario_id: 3, nombre: 'Persona 3',
      categoria: 'Técnicos', comida_id: 5, comida: 'Cena', resultado: 'aceptada',
      motivo: null, valido: true, dispositivo: 'lector-01', origen: 'lectura_biometrica', clave_evento: 'lectura_biometrica:1' },
    { id: 2, fecha_hora: '2026-09-10T23:59:00', usuario_id: 4, nombre: 'Persona 4',
      categoria: 'Médico', comida_id: null, comida: null, resultado: 'rechazada',
      motivo: 'fuera_horario', valido: false, dispositivo: 'lector-01', origen: 'lectura_biometrica', clave_evento: 'lectura_biometrica:2' },
  ]);
  const [conCena, sinComida] = await obtenerUltimasMarcaciones();
  assert.equal(conCena.comida, 'Cena');
  assert.equal(conCena.comidaId, 5);
  assert.equal(sinComida.comida, null);
  assert.equal(sinComida.comidaId, null);
});

test('conserva rechazos de negocio 200 y traduce los motivos ya usados por el front', async () => {
  for (const [motivo, esperado] of [['duplicado', 'ya_marco'],
    ['fuera_horario', 'fuera_horario'], ['sin_derecho', 'sin_derecho']]) {
    globalThis.fetch = async () => json({ valido: false, motivo, usuario_id: 3,
      titulo: 'Marcación rechazada', detalle: 'Texto del servidor', comida: null });
    const evento = await marcarAsistencia(3, { persona });
    assert.equal(evento.valido, false);
    assert.equal(evento.motivo, esperado);
    assert.equal(evento.detalle, 'Texto del servidor');
  }
});

test('no envía una persona al azar ni reintenta automáticamente un POST fallido', async () => {
  let peticiones = 0;
  globalThis.fetch = async () => { peticiones += 1; throw new TypeError('Offline'); };
  await assert.rejects(marcarAsistencia(-1), /Seleccione/);
  assert.equal(peticiones, 0);
  await assert.rejects(marcarAsistencia(3, { persona }), /Verifique el registro/);
  assert.equal(peticiones, 1);
});

test('rechaza una respuesta de marcación inválida o de otro usuario', async () => {
  globalThis.fetch = async () => json({ valido: 'true' });
  await assert.rejects(marcarAsistencia(3, { persona }), /marcación inválida/);
  globalThis.fetch = async () => json({ valido: true, usuario_id: 9, titulo: 'OK', detalle: 'OK' });
  await assert.rejects(marcarAsistencia(3, { persona }), /marcación inválida/);
});

test('permite cancelar una carga en curso', async () => {
  globalThis.fetch = (_ruta, { signal }) => new Promise((_resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('Cancelado', 'AbortError')));
  });
  const controlador = new AbortController();
  const promesa = obtenerPersonal({ signal: controlador.signal });
  controlador.abort();
  await assert.rejects(promesa, { name: 'AbortError' });
});

test('conserva sin límite, cupo agotado, fuera de horario y todas las categorías de la API', async () => {  for (const cupo of [{ previstas: null, restantes: null, porcentaje: null, servidas: 27 },
    { previstas: 10, restantes: 0, porcentaje: 100, servidas: 10 }, null]) {
    const respuesta = { comida: cupo ? 'Cena' : null, fuera_de_horario: cupo === null,
      cupo, totales_del_dia: { raciones_servidas: 27 },
      por_categoria: [{ categoria: 'Médico', raciones: 20 }, { categoria: 'Sin clasificar', raciones: 7 }] };
    globalThis.fetch = async (ruta) => {
      assert.equal(new URL(ruta).pathname, '/pantalla/estado');
      return json(respuesta);
    };
    assert.deepEqual(await obtenerEstadoPantalla(), respuesta);
  }
});

test('estado acepta fecha opcional como Date o YYYY-MM-DD local', async () => {
  const respuesta = { comida: 'Almuerzo', fuera_de_horario: false,
    cupo: { previstas: null, restantes: null, porcentaje: null, servidas: 0 },
    totales_del_dia: { raciones_servidas: 0 }, por_categoria: [] };
  const rutas = [];
  globalThis.fetch = async (ruta) => {
    rutas.push(new URL(ruta).pathname + new URL(ruta).search);
    return json(respuesta);
  };
  await obtenerEstadoPantalla();
  await obtenerEstadoPantalla({ fecha: '2026-09-05' });
  await obtenerEstadoPantalla({ fecha: new Date(2026, 7, 27, 12) });
  assert.deepEqual(rutas, [
    '/pantalla/estado',
    '/pantalla/estado?fecha=2026-09-05',
    '/pantalla/estado?fecha=2026-08-27',
  ]);
});

test('estado rechaza fecha inválida sin llamar a la API', async () => {
  let peticiones = 0;
  globalThis.fetch = async () => { peticiones += 1; return json({}); };
  await assert.rejects(obtenerEstadoPantalla({ fecha: '05/09/2026' }), /Fecha inválida/);
  await assert.rejects(obtenerEstadoPantalla({ fecha: 20260905 }), /Fecha inválida/);
  assert.equal(peticiones, 0);
});

const columnas = ['Desayuno', 'Almuerzo', 'Té', 'Cena'].map((nombre, i) => ({ comida_id: i + 1, nombre, codigo: `c${i}` }));
const filaDiaria = (id) => ({ usuario_id: id, nombre_completo: `Persona ${id}`, categoria: null,
  turno: null, comidas: columnas.map((c, i) => ({ ...c, estado: ['recibida', 'no_recibida', 'pendiente', 'no_aplica'][i] })).reverse() });

test('historial diario respeta página, fecha local, orden de columnas y los cuatro estados', async () => {
  globalThis.fetch = async (ruta) => {
    const url = new URL(ruta);
    assert.equal(url.pathname, '/historial/diario');
    assert.equal(url.searchParams.get('fecha'), '2026-09-09');
    assert.equal(url.searchParams.get('desplazamiento'), '50');
    return json({
      total: 1081,
      limite: 50,
      desplazamiento: 50,
      comidas: columnas,
      datos: [{ ...filaDiaria(51), servicio: 'Cirugía' }],
    });
  };
  const pagina = await obtenerHistorialDiarioPersonal({ fecha: new Date(2026, 8, 9), desplazamiento: 50 });
  assert.equal(pagina.total, 1081);
  assert.equal(pagina.desplazamiento, 50);
  assert.deepEqual(pagina.datos[0].comidas.map(c => [c.id, c.aplica, c.estado]),
    [[1, true, true], [2, true, false], [3, true, null], [4, false, null]]);
  assert.equal(pagina.datos[0].turno, null);
  assert.equal(pagina.datos[0].servicio, 'Cirugía');
});

test('historial diario aplica Sin servicio por defecto si falta en el backend', async () => {
  globalThis.fetch = async () => json({
    total: 1,
    limite: 50,
    desplazamiento: 0,
    comidas: columnas,
    datos: [filaDiaria(1)],
  });
  const pagina = await obtenerHistorialDiarioPersonal({ fecha: '2026-09-09' });
  assert.equal(pagina.datos[0].servicio, 'Sin servicio');
});

test('historial mensual envía mes 1 a 12 y usa los totales del servidor', async () => {
  globalThis.fetch = async (ruta) => {
    const url = new URL(ruta);
    assert.equal(url.searchParams.get('mes'), '1');
    assert.equal(url.searchParams.get('gestion'), '2025');
    return json({ total: 1, limite: 50, desplazamiento: 0, comidas: columnas, datos: [{
      usuario_id: 7, nombre_completo: 'Persona 7', total_asignadas: 18, total_recibidas: 9,
      total_no_recibidas: 6, total_pendientes: 3,
      totales: columnas.map(c => ({ ...c, asignadas: 8, recibidas: 5, no_recibidas: 2, pendientes: 1 })),
    }] });
  };
  const pagina = await obtenerHistorialMensualPersonal({ gestion: 2025, mesIndice: 0 });
  assert.equal(pagina.datos[0].totalAsignadas, 18);
  assert.equal(pagina.datos[0].totalRecibidas, 9);
  assert.equal(pagina.datos[0].totalNoRecibidas, 6);
  assert.equal(pagina.datos[0].totales[0].noRecibidas, 2);
  assert.equal(pagina.datos[0].servicio, 'Sin servicio');
});

test('historial mensual conserva servicio del backend', async () => {
  globalThis.fetch = async () => json({
    total: 1, limite: 50, desplazamiento: 0, comidas: columnas, datos: [{
      usuario_id: 7, nombre_completo: 'Persona 7', servicio: 'COLOPROCTOLOGIA',
      total_asignadas: 18, total_recibidas: 9, total_no_recibidas: 6, total_pendientes: 3,
      totales: columnas.map(c => ({ ...c, asignadas: 8, recibidas: 5, no_recibidas: 2, pendientes: 1 })),
    }],
  });
  const pagina = await obtenerHistorialMensualPersonal({ gestion: 2026, mesIndice: 4 });
  assert.equal(pagina.datos[0].servicio, 'COLOPROCTOLOGIA');
});

test('la ficha del día sale de /pantalla/dia-personal con fecha solo si se pide', async () => {
  const rutas = [];
  globalThis.fetch = async (ruta) => {
    const url = new URL(ruta);
    rutas.push(url.pathname + url.search);
    return json({ total: 1, limite: 1, desplazamiento: 0, comidas: columnas,
      datos: [filaDiaria(Number(url.searchParams.get('persona_id')))] });
  };
  const ficha = await obtenerDiaPersonal(2);
  await obtenerDiaPersonal(2, { fecha: '2026-09-05' });
  await obtenerDiaPersonal(2, { fecha: new Date(2026, 7, 27, 12) });
  assert.deepEqual(rutas, [
    '/pantalla/dia-personal?persona_id=2',
    '/pantalla/dia-personal?persona_id=2&fecha=2026-09-05',
    '/pantalla/dia-personal?persona_id=2&fecha=2026-08-27',
  ]);
  assert.equal(ficha.id, 2);
  assert.equal(ficha.turno, null);
  assert.deepEqual(ficha.comidas.map(c => [c.id, c.aplica, c.estado]),
    [[1, true, true], [2, true, false], [3, true, null], [4, false, null]]);
});

test('la ficha del día es null si ese día no figura o la persona no existe', async () => {
  globalThis.fetch = async () => json({ total: 0, limite: 1, desplazamiento: 0, comidas: columnas, datos: [] });
  assert.equal(await obtenerDiaPersonal(3), null);
  globalThis.fetch = async () => json({ detail: 'No existe ese comensal' }, 404);
  assert.equal(await obtenerDiaPersonal(999), null);
  globalThis.fetch = async () => json({}, 503);
  await assert.rejects(obtenerDiaPersonal(3), /HTTP 503/);
});

test('historial vacío no genera datos y estados desconocidos producen error', async () => {
  globalThis.fetch = async () => json({ total: 0, limite: 50, desplazamiento: 0, comidas: columnas, datos: [] });
  assert.equal((await obtenerHistorialDiarioPersonal()).datos.length, 0);
  const fila = filaDiaria(1);
  fila.comidas[0].estado = 'nuevo_estado';
  globalThis.fetch = async () => json({ total: 1, limite: 50, desplazamiento: 0, comidas: columnas, datos: [fila] });
  await assert.rejects(obtenerHistorialDiarioPersonal(), /Estado de comida inválido/);
});

test('los selectores usan una sola consulta y distinguen calendario, cierre y raciones', async () => {
  let llamadas = 0;
  globalThis.fetch = async () => {
    llamadas += 1;
    return json([{ gestion: 2024, activo: true, situacion: 'cerrado', raciones: 5,
      meses: Array.from({ length: 12 }, (_, i) => ({ mes: i + 1, nombre: `Mes ${i + 1}`,
        situacion: 'cerrado', cerrado: i === 0, raciones: i === 0 ? 5 : 0 })) }]);
  };
  const periodos = await obtenerPeriodos();
  assert.deepEqual(obtenerGestiones(periodos).map(p => p.gestion), [2024]);
  const meses = obtenerMesesDeGestion(2024, periodos);
  assert.equal(meses[0].indice, 0);
  assert.equal(meses[1].situacion, 'cerrado');
  assert.equal(meses[1].cerrado, false);
  assert.equal(meses[1].raciones, 0);
  assert.equal(llamadas, 1);
  assert.deepEqual(obtenerMesesDeGestion(2030, periodos), []);
});

test('los nuevos endpoints propagan los fallos HTTP', async () => {
  globalThis.fetch = async () => json({}, 503);
  for (const consultar of [obtenerEstadoPantalla, obtenerHistorialDiarioPersonal, obtenerHistorialMensualPersonal, obtenerPeriodos]) {
    await assert.rejects(consultar(), /HTTP 503/);
  }
});

const informeBase = (tipo, extra = {}) => ({
  tipo, gestion: 2026, mes: 9, mes_nombre: 'Septiembre',
  desde: '2026-09-01', hasta: '2026-09-30', situacion: 'curso', cerrado: false,
  categorias: ['Médico', 'Servicio'], grupos: [], total_equivalente: null,
  totales_por_categoria: [2, 1], total_general: 3, sin_clasificar: 0, sin_coeficiente: 0,
  ...extra,
});
const hoyFijo = new Date(2026, 8, 10, 12);

test('registro diario adapta snake_case a la forma de la UI sin tocar componentes', async () => {
  let rutaPedida = '';
  globalThis.fetch = async (ruta) => {
    rutaPedida = new URL(ruta).pathname + new URL(ruta).search;
    return json(informeBase('registro_diario', { filas: [
      { etiqueta: '1', celdas: [2, 1], total: 3, registrado: true },
      { etiqueta: '2', celdas: [0, 0], total: 0, registrado: true },
      { etiqueta: '11', celdas: [0, 0], total: 0, registrado: false },
    ] }));
  };
  const informe = await obtenerRegistroDiario({ mesIndice: 8, gestion: 2026, hoy: hoyFijo });
  assert.equal(rutaPedida, '/reportes/registro-diario?gestion=2026&mes=9');
  assert.equal(informe.tipo, 'registro');
  assert.equal(informe.titulo, 'Registro diario de raciones servidas al personal');
  assert.equal(informe.mes, 'Septiembre');
  assert.equal(informe.mesIndice, 8);
  assert.equal(informe.dias, 30);
  assert.equal(informe.diasRegistrados, 2);
  assert.deepEqual(informe.filas[0], { dia: 1, celdas: [2, 1], total: 3, registrado: true, esHoy: false });
  assert.equal(informe.filas[2].esHoy, false);
  assert.deepEqual(informe.encabezados, ['Fecha', 'Médico', 'Servicio', 'Total']);
  assert.deepEqual(informe.periodo, { principal: 'Septiembre', secundario: 'Gestión 2026' });
  assert.deepEqual(informe.encabezado, { rotulo: 'MES :', valor: 'SEPTIEMBRE' });
  assert.equal(informe.cierre[0].valor, 3);
  assert.equal(informe.archivo, 'registro-diario-raciones-septiembre-2026');
  assert.equal(informe.sinClasificar, 0);
  assert.equal(informe.sinCoeficiente, 0);
  assert.match(informe.generado, /10\/09\/2026/);
});

test('registro diario marca el día en curso y conserva sin_clasificar', async () => {
  globalThis.fetch = async () => json(informeBase('registro_diario', {
    sin_clasificar: 4, filas: [{ etiqueta: '10', celdas: [2, 1], total: 3, registrado: true }],
  }));
  const informe = await obtenerRegistroDiario({ mesIndice: 8, gestion: 2026, hoy: hoyFijo });
  assert.equal(informe.filas[0].esHoy, true);
  assert.equal(informe.sinClasificar, 4);
  assert.deepEqual(notasDeInforme(informe), [
    '4 raciones pendientes de clasificación. Están incluidas en el total del informe.',
  ]);
});

test('mensual mapea grupos a etiqueta y cierra con el equivalente', async () => {
  globalThis.fetch = async () => json(informeBase('mensual', {
    filas: [{ etiqueta: 'Desayuno', celdas: [2, 1], total: 3, registrado: true }],
    grupos: [{ grupo: 'Desayuno', servidas: 3, coeficiente: 0.15, equivalente: 0.45 }],
    total_equivalente: 0.45, sin_coeficiente: 2,
  }));
  const informe = await obtenerInformeMensual({ mesIndice: 8, gestion: 2026, hoy: hoyFijo });
  assert.equal(informe.tipo, 'mensual');
  assert.deepEqual(informe.filas, [{ tiempo: 'Desayuno', celdas: [2, 1], total: 3, registrado: true }]);
  assert.deepEqual(informe.grupos, [{ etiqueta: 'Desayuno', servidas: 3, coeficiente: 0.15, equivalente: 0.45 }]);
  assert.equal(informe.totalEquivalente, 0.45);
  assert.equal(informe.cierre[0].valor, 0.45);
  assert.equal(informe.diasRegistrados, 10);
  assert.equal(notasDeInforme(informe).length, 1);
  assert.match(notasDeInforme(informe)[0], /sin coeficiente asignado/);
});

test('mensual conserva el equivalente historico con coeficientes variables', async () => {
  globalThis.fetch = async () => json(informeBase('mensual', {
    filas: [{ etiqueta: 'Almuerzo', celdas: [2, 1], total: 3, registrado: true }],
    grupos: [{ grupo: 'Almuerzo', servidas: 3, coeficiente: 1.2, equivalente: 3.2, coeficientes_mixtos: true }],
    total_equivalente: 3.2,
  }));
  const informe = await obtenerInformeMensual({ mesIndice: 8, gestion: 2026, hoy: hoyFijo });
  assert.equal(informe.grupos[0].coeficienteVariable, true);
  assert.equal(informe.grupos[0].equivalente, 3.2);
  assert.notEqual(informe.grupos[0].servidas * informe.grupos[0].coeficiente, 3.2);
});

test('gestión cuenta meses registrados y marca el mes en curso', async () => {
  const nombres = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
    'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'];
  const filas = nombres.map((etiqueta, i) => i === 0
    ? { etiqueta, celdas: [2, 1], total: 3, registrado: true }
    : { etiqueta, celdas: [0, 0], total: 0, registrado: i < 9 });
  globalThis.fetch = async () => json({ ...informeBase('gestion'),
    mes: null, mes_nombre: null, desde: '2026-01-01', hasta: '2026-12-31', filas });
  const informe = await obtenerResumenGestion({ gestion: 2026, hoy: hoyFijo });
  assert.equal(informe.tipo, 'gestion');
  assert.equal(informe.mesesRegistrados, 9);
  assert.deepEqual(informe.filas[0], { mes: 'Enero', mesIndice: 0, celdas: [2, 1], total: 3, registrado: true, esHoy: false });
  assert.equal(informe.filas[8].esHoy, true);
  assert.equal(informe.filas[9].registrado, false);
  assert.equal(informe.cierre[0].valor, 3);
  assert.equal(informe.archivo, 'resumen-gestion-raciones-2026');
});

test('informes rechazan tipo, período, totales y días incoherentes', async () => {
  const base = informeBase('registro_diario', { filas: [{ etiqueta: '1', celdas: [2, 1], total: 3, registrado: true }] });
  globalThis.fetch = async () => json({ ...base, tipo: 'mensual' });
  await assert.rejects(obtenerRegistroDiario({ mesIndice: 8, gestion: 2026 }), /informe inválido/);
  globalThis.fetch = async () => json({ ...base, mes: 8 });
  await assert.rejects(obtenerRegistroDiario({ mesIndice: 8, gestion: 2026 }), /otro período/);
  globalThis.fetch = async () => json({ ...base, filas: [{ etiqueta: '1', celdas: [2, 1], total: 9, registrado: true }] });
  await assert.rejects(obtenerRegistroDiario({ mesIndice: 8, gestion: 2026 }), /fila de informe inválida/);
  globalThis.fetch = async () => json({ ...base, total_general: 99 });
  await assert.rejects(obtenerRegistroDiario({ mesIndice: 8, gestion: 2026 }), /no cuadran/);
  globalThis.fetch = async () => json({ ...base, filas: [{ etiqueta: '31', celdas: [2, 1], total: 3, registrado: true }] });
  await assert.rejects(obtenerRegistroDiario({ mesIndice: 8, gestion: 2026 }), /fuera del mes/);
});

test('informes propagan HTTP y cancelación como el resto de endpoints', async () => {
  globalThis.fetch = async () => json({}, 503);
  await assert.rejects(obtenerRegistroDiario({ mesIndice: 8, gestion: 2026 }), /HTTP 503/);
  await assert.rejects(obtenerInformeMensual({ mesIndice: 8, gestion: 2026 }), /HTTP 503/);
  await assert.rejects(obtenerResumenGestion({ gestion: 2026 }), /HTTP 503/);
  globalThis.fetch = (_ruta, { signal }) => new Promise((_resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('Cancelado', 'AbortError')));
  });
  const controlador = new AbortController();
  const promesa = obtenerRegistroDiario({ mesIndice: 8, gestion: 2026, signal: controlador.signal });
  controlador.abort();
  await assert.rejects(promesa, { name: 'AbortError' });
});

/* --------------- Informe por rango: la vista única de Reportes -------------- */

const informeDeRango = (extra = {}) => ({
  tipo: 'informe', desde: '2026-09-01', hasta: '2026-09-10',
  categorias: ['Médico', 'Servicio'],
  filas: [
    { etiqueta: 'Desayuno', celdas: [2, 1], total: 3, registrado: true },
    { etiqueta: 'Almuerzo', celdas: [4, 0], total: 4, registrado: true },
  ],
  grupos: [
    { grupo: 'Desayuno', servidas: 3, coeficiente: 0.15, equivalente: 0.45 },
    { grupo: 'Almuerzo', servidas: 4, coeficiente: 0.5, equivalente: 2 },
  ],
  totales_por_categoria: [6, 1], total_general: 7, total_equivalente: 2.45,
  sin_clasificar: 0, sin_coeficiente: 0,
  ...extra,
});

test('el informe por rango pide desde/hasta y arma el formulario de Estadística', async () => {
  let rutaPedida = '';
  globalThis.fetch = async (ruta) => {
    rutaPedida = new URL(ruta).pathname + new URL(ruta).search;
    return json(informeDeRango());
  };
  const informe = await obtenerInformeRaciones({ desde: '2026-09-01', hasta: '2026-09-10', hoy: hoyFijo });
  assert.equal(rutaPedida, '/reportes/informe?desde=2026-09-01&hasta=2026-09-10');
  assert.equal(informe.tipo, 'informe');
  assert.equal(informe.titulo, 'Informe de raciones servidas al personal');
  assert.deepEqual(informe.encabezados, ['Tiempo de comida', 'Médico', 'Servicio', 'Total']);
  assert.deepEqual(informe.filas[0], { tiempo: 'Desayuno', celdas: [2, 1], total: 3, registrado: true });
  assert.deepEqual(informe.grupos[0], { etiqueta: 'Desayuno', servidas: 3, coeficiente: 0.15, equivalente: 0.45 });
  assert.equal(informe.dias, 10);
  /* Sin dias_registrados de la API, cuentan los días del rango ya vividos. */
  assert.equal(informe.diasRegistrados, 10);
  assert.equal(informe.gestion, 2026);
  assert.equal(informe.cierre[0].valor, 2.45);
  assert.equal(informe.cierre[1].valor, 2.45 / 10);
  assert.equal(informe.archivo, 'informe-raciones-2026-09-01-a-2026-09-10');
});

test('el rango se lee corto dentro de una gestión, completo si la cruza, y un día es un día', async () => {
  globalThis.fetch = async () => json(informeDeRango());
  const informe = await obtenerInformeRaciones({ desde: '2026-09-01', hasta: '2026-09-10', hoy: hoyFijo });
  assert.equal(informe.periodo.principal, etiquetaDeRango('2026-09-01', '2026-09-10'));
  assert.equal(informe.periodo.secundario, '10 días');
  assert.match(etiquetaDeRango('2026-09-16', '2026-09-16'), /^16 \w+ 2026$/);
  assert.match(etiquetaDeRango('2026-09-01', '2026-09-16'), /^01 \w+ – 16 \w+ 2026$/);
  assert.match(etiquetaDeRango('2025-12-28', '2026-01-04'), /^28 \w+ 2025 – 04 \w+ 2026$/);
});

test('el informe por rango respeta dias_registrados y recorta el rango sin vivir', async () => {
  globalThis.fetch = async () => json(informeDeRango({ dias_registrados: 4 }));
  const conDato = await obtenerInformeRaciones({ desde: '2026-09-01', hasta: '2026-09-10', hoy: hoyFijo });
  assert.equal(conDato.diasRegistrados, 4);
  assert.equal(conDato.cierre[1].valor, 2.45 / 4);

  globalThis.fetch = async () => json(informeDeRango({ desde: '2026-09-05', hasta: '2026-09-20' }));
  const aFuturo = await obtenerInformeRaciones({ desde: '2026-09-05', hasta: '2026-09-20', hoy: hoyFijo });
  assert.equal(aFuturo.dias, 16);
  assert.equal(aFuturo.diasRegistrados, 6); /* del 5 al 10, que es hoy */
});

test('el informe por rango valida el rango pedido y la respuesta de la API', async () => {
  await assert.rejects(obtenerInformeRaciones({ desde: '01-09-2026', hasta: '2026-09-10' }), /Rango de fechas inválido/);
  await assert.rejects(obtenerInformeRaciones({ desde: '2026-09-11', hasta: '2026-09-10' }), /no puede ser posterior/);

  globalThis.fetch = async () => json(informeDeRango({ tipo: 'gestion' }));
  await assert.rejects(obtenerInformeRaciones({ desde: '2026-09-01', hasta: '2026-09-10' }), /informe inválido/);
  globalThis.fetch = async () => json(informeDeRango({ hasta: '2026-09-11' }));
  await assert.rejects(obtenerInformeRaciones({ desde: '2026-09-01', hasta: '2026-09-10' }), /otro período/);
  globalThis.fetch = async () => json(informeDeRango({ total_general: 99 }));
  await assert.rejects(obtenerInformeRaciones({ desde: '2026-09-01', hasta: '2026-09-10' }), /no cuadran/);
  globalThis.fetch = async () => json({}, 503);
  await assert.rejects(obtenerInformeRaciones({ desde: '2026-09-01', hasta: '2026-09-10' }), /HTTP 503/);
});

test('el aviso de coeficientes también sale en el informe por rango', async () => {
  globalThis.fetch = async () => json(informeDeRango({ sin_clasificar: 2, sin_coeficiente: 1 }));
  const informe = await obtenerInformeRaciones({ desde: '2026-09-01', hasta: '2026-09-10', hoy: hoyFijo });
  const notas = notasDeInforme(informe);
  assert.equal(notas.length, 2);
  assert.match(notas[1], /sin coeficiente asignado/);
});

test('las comidas del día llegan en camelCase con estado, servidas y rechazos por motivo', async () => {
  const rutas = [];
  globalThis.fetch = async (ruta) => {
    rutas.push(new URL(ruta).pathname + new URL(ruta).search);
    assert.equal(new URL(ruta).pathname, '/pantalla/comidas-del-dia');
    return json({
      fecha: '2026-09-28',
      comidas: [
        {
          comida_id: 1, comida: 'Desayuno', hora_inicio: '07:00', hora_fin: '09:00',
          estado: 'cerrada', previstas: 120, servidas: 118, manuales: 2,
          rechazos_por_motivo: { no_identificado: 1, sin_derecho: 0, duplicado: 3 },
        },
        {
          comida_id: 2, comida: 'Almuerzo', hora_inicio: '12:00', hora_fin: '14:00',
          estado: 'en_curso', previstas: null, servidas: 60, manuales: 0,
          rechazos_por_motivo: { no_identificado: 0, sin_derecho: 2, duplicado: 0 },
        },
      ],
      rechazos_sin_comida: 4,
    });
  };
  const dia = await obtenerComidasDelDia();
  const delDia = await obtenerComidasDelDia({ fecha: '2026-09-01' });
  assert.deepEqual(rutas, ['/pantalla/comidas-del-dia', '/pantalla/comidas-del-dia?fecha=2026-09-01']);
  assert.equal(dia.fecha, '2026-09-28');
  assert.equal(dia.comidas.length, 2);
  assert.deepEqual(dia.comidas[0], {
    comidaId: 1, comida: 'Desayuno', horaInicio: '07:00', horaFin: '09:00',
    estado: 'cerrada', previstas: 120, servidas: 118, manuales: 2,
    rechazos: { noIdentificado: 1, sinDerecho: 0, duplicado: 3 },
  });
  assert.equal(dia.comidas[1].estado, 'en_curso');
  assert.equal(dia.comidas[1].previstas, null);
  assert.equal(dia.rechazosSinComida, 4);
  assert.equal(delDia.fecha, '2026-09-28');
});

test('las comidas del día con forma inválida se rechazan con error', async () => {
  globalThis.fetch = async () => json({ fecha: '2026-09-28', comidas: [], rechazos_sin_comida: 0 });
  assert.deepEqual((await obtenerComidasDelDia()).comidas, []);
  globalThis.fetch = async () => json({ comidas: [] });
  await assert.rejects(obtenerComidasDelDia(), /comidas del día inválidas/);
  globalThis.fetch = async () => json({
    fecha: '2026-09-28',
    comidas: [{
      comida_id: 2, comida: 'Almuerzo', estado: 'sirviendo', previstas: null,
      servidas: 60, manuales: 0,
      rechazos_por_motivo: { no_identificado: 0, sin_derecho: 0, duplicado: 0 },
    }],
    rechazos_sin_comida: 0,
  });
  await assert.rejects(obtenerComidasDelDia(), /comida del día inválida/);
  globalThis.fetch = async () => json({
    fecha: '2026-09-28',
    comidas: [{
      comida_id: 2, comida: 'Almuerzo', estado: 'en_curso', previstas: null,
      servidas: 60, manuales: 0, rechazos_por_motivo: { no_identificado: 0, sin_derecho: 0 },
    }],
    rechazos_sin_comida: 0,
  });
  await assert.rejects(obtenerComidasDelDia(), /comida del día inválida/);
  await assert.rejects(obtenerComidasDelDia({ fecha: '01-09-2026' }), /Fecha inválida/);
});
