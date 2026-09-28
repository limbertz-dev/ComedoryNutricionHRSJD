import test, { afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import Header from '../src/components/layout/Header.jsx';
import Supervision, {
  ejecutarAutorizacionManual,
  programarRefrescoSupervision,
} from '../src/components/secciones/Supervision.jsx';
import {
  autorizarMarcacionManual,
  obtenerResumenComidas,
  obtenerUltimasMarcaciones,
} from '../src/api.js';
import {
  puedeVerSeccion,
  resolverSeccionGuardada,
  seccionesPermitidas,
} from '../src/permisos.js';

const fetchOriginal = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = fetchOriginal;
});

const json = (datos, status = 200) => new Response(JSON.stringify(datos), { status });

// -------------------------------------------------------------
// 1. Permisos
// -------------------------------------------------------------
test('permisos: cocinera sigue en [vivo], jefa y sistemas abren supervision y ya no vivo, seccion guardada vivo -> supervision', () => {
  // Cocinera sigue en ['vivo']
  assert.deepEqual(seccionesPermitidas('cocinera'), ['vivo']);
  assert.equal(puedeVerSeccion('cocinera', 'vivo'), true);
  assert.equal(puedeVerSeccion('cocinera', 'supervision'), false);

  // Jefa y Sistemas abren 'supervision' y ya no 'vivo'
  assert.deepEqual(seccionesPermitidas('jefa'), ['supervision', 'dashboard', 'historial', 'reportes']);
  assert.deepEqual(seccionesPermitidas('sistemas'), ['supervision', 'dashboard', 'historial', 'reportes']);
  assert.equal(puedeVerSeccion('jefa', 'supervision'), true);
  assert.equal(puedeVerSeccion('jefa', 'vivo'), false);
  assert.equal(puedeVerSeccion('sistemas', 'supervision'), true);
  assert.equal(puedeVerSeccion('sistemas', 'vivo'), false);

  // Sección guardada 'vivo' -> 'supervision' para jefa y sistemas
  assert.equal(resolverSeccionGuardada('jefa', 'vivo'), 'supervision');
  assert.equal(resolverSeccionGuardada('sistemas', 'vivo'), 'supervision');

  // Cocinera con 'vivo' guardada permanece en 'vivo'
  assert.equal(resolverSeccionGuardada('cocinera', 'vivo'), 'vivo');
  // Cocinera con 'supervision' guardada vuelve a 'vivo'
  assert.equal(resolverSeccionGuardada('cocinera', 'supervision'), 'vivo');
});

// -------------------------------------------------------------
// 2. Adaptador obtenerUltimasMarcaciones aditivo
// -------------------------------------------------------------
test('obtenerUltimasMarcaciones conserva campos existentes y agrega aditivamente motivo y dispositivo', async () => {
  globalThis.fetch = async (url) => {
    assert.equal(new URL(url).pathname, '/pantalla/ultimas-marcaciones');
    return json([
      {
        id: 101,
        fecha_hora: '2026-09-28T12:30:00',
        usuario_id: null,
        nombre: 'Huella no reconocida',
        categoria: 'Sin identificar',
        comida_id: 2,
        comida: 'Almuerzo',
        resultado: 'rechazada',
        motivo: 'no_identificado',
        valido: false,
        dispositivo: 'lector-pb',
      },
      {
        id: 102,
        fecha_hora: '2026-09-28T12:31:00',
        usuario_id: 15,
        nombre: 'Juan Perez',
        categoria: 'Planta',
        comida_id: 2,
        comida: 'Almuerzo',
        resultado: 'rechazada',
        motivo: 'sin_derecho',
        valido: false,
        dispositivo: 'lector-pb',
      },
    ]);
  };

  const lista = await obtenerUltimasMarcaciones({ fecha: '2026-09-28', limite: 20 });
  assert.equal(lista.length, 2);

  // Campos existentes conservados intactos
  assert.equal(lista[0].id, 101);
  assert.equal(lista[0].valido, false);
  assert.equal(lista[0].titulo, 'no_identificado');
  assert.equal(lista[0].comidaId, 2);
  assert.equal(lista[0].comida, 'Almuerzo');
  assert.equal(lista[0].persona.nombre, 'Huella no reconocida');

  // Nuevos campos aditivos
  assert.equal(lista[0].motivo, 'no_identificado');
  assert.equal(lista[0].dispositivo, 'lector-pb');

  assert.equal(lista[1].motivo, 'sin_derecho');
  assert.equal(lista[1].dispositivo, 'lector-pb');
  assert.equal(lista[1].titulo, 'Sin derecho en este turno');
});

// -------------------------------------------------------------
// 3. Adaptador obtenerResumenComidas con catálogo real
// -------------------------------------------------------------
test('obtenerResumenComidas obtiene catalogo real de /historial/diario, une con /reportes/informe y consulta rechazos', async () => {
  const peticiones = [];
  globalThis.fetch = async (ruta) => {
    const url = new URL(ruta);
    peticiones.push({ pathname: url.pathname, searchParams: url.searchParams });

    if (url.pathname === '/pantalla/estado') {
      return json({
        momento: '2026-09-28T12:45:00',
        fecha_comida: '2026-09-28',
        comida_id: 2,
        comida: 'Almuerzo',
        fuera_de_horario: false,
        cupo: { previstas: 150, servidas: 80, restantes: 70, porcentaje: 53 },
        padron: 200,
        totales_del_dia: { raciones_servidas: 80, lecturas: 85, aceptadas: 80, rechazadas: 5 },
        por_categoria: [],
      });
    }

    if (url.pathname === '/reportes/informe') {
      assert.equal(url.searchParams.get('desde'), '2026-09-28');
      assert.equal(url.searchParams.get('hasta'), '2026-09-28');
      return json({
        tipo: 'informe',
        gestion: 2026,
        mes: 9,
        desde: '2026-09-28',
        hasta: '2026-09-28',
        situacion: 'curso',
        cerrado: false,
        categorias: ['Planta'],
        filas: [
          { etiqueta: 'Desayuno', celdas: [20], total: 20, registrado: true },
          { etiqueta: 'Almuerzo', celdas: [60], total: 60, registrado: true },
          { etiqueta: 'Cena Especial', celdas: [0], total: 0, registrado: true }, // no existe en catálogo
        ],
        totales_por_categoria: [80],
        total_general: 80,
        sin_clasificar: 0,
        sin_coeficiente: 0,
        grupos: [],
      });
    }

    if (url.pathname === '/historial/diario') {
      return json({
        total: 0,
        limite: 1,
        desplazamiento: 0,
        comidas: [
          { comida_id: 1, codigo: 'DES', nombre: 'Desayuno' },
          { comida_id: 2, codigo: 'ALM', nombre: 'Almuerzo' },
        ],
        datos: [],
      });
    }

    if (url.pathname === '/pantalla/ultimas-marcaciones') {
      const cid = Number(url.searchParams.get('comida_id'));
      assert.equal(url.searchParams.get('limite'), '100');
      if (cid === 2) {
        // Almuerzo tiene 3 rechazadas de 4 marcaciones
        return json([
          { id: 1, fecha_hora: '2026-09-28T12:00:00', usuario_id: 1, valido: true, resultado: 'aceptada' },
          { id: 2, fecha_hora: '2026-09-28T12:01:00', usuario_id: null, valido: false, motivo: 'no_identificado' },
          { id: 3, fecha_hora: '2026-09-28T12:02:00', usuario_id: 2, valido: false, motivo: 'sin_derecho' },
          { id: 4, fecha_hora: '2026-09-28T12:03:00', usuario_id: 3, valido: false, motivo: 'duplicado' },
        ]);
      }
      return json([]);
    }

    throw new Error(`Ruta no esperada: ${url.pathname}`);
  };

  const resumen = await obtenerResumenComidas({ fecha: '2026-09-28' });
  assert.equal(resumen.length, 3);

  // Desayuno
  assert.deepEqual(resumen[0], {
    comidaId: 1,
    comida: 'Desayuno',
    servidas: 20,
    rechazos: 0,
    rechazosTruncados: false,
    estado: '—',
  });

  // Almuerzo: está en curso según /pantalla/estado
  assert.deepEqual(resumen[1], {
    comidaId: 2,
    comida: 'Almuerzo',
    servidas: 60,
    rechazos: 3,
    rechazosTruncados: false,
    estado: 'En curso',
  });

  // Cena Especial: no encontrada en catálogo real -> comidaId = null, sin filtro supuesto
  assert.deepEqual(resumen[2], {
    comidaId: null,
    comida: 'Cena Especial',
    servidas: 0,
    rechazos: 0,
    rechazosTruncados: false,
    estado: '—',
  });
});

test('obtenerResumenComidas detecta rechazosTruncados=true si vuelven 100 filas y fuera_de_horario', async () => {
  globalThis.fetch = async (ruta) => {
    const url = new URL(ruta);
    if (url.pathname === '/pantalla/estado') {
      return json({
        momento: '2026-09-28T15:00:00',
        fecha_comida: '2026-09-28',
        comida_id: 2,
        comida: 'Almuerzo',
        fuera_de_horario: true,
        cupo: null,
        padron: 200,
        totales_del_dia: { raciones_servidas: 10, lecturas: 120, aceptadas: 10, rechazadas: 110 },
        por_categoria: [],
      });
    }
    if (url.pathname === '/reportes/informe') {
      return json({
        tipo: 'informe',
        gestion: 2026,
        mes: 9,
        desde: '2026-09-28',
        hasta: '2026-09-28',
        situacion: 'curso',
        cerrado: false,
        categorias: ['Planta'],
        filas: [{ etiqueta: 'Almuerzo', celdas: [10], total: 10, registrado: true }],
        totales_por_categoria: [10],
        total_general: 10,
        sin_clasificar: 0,
        sin_coeficiente: 0,
        grupos: [],
      });
    }
    if (url.pathname === '/historial/diario') {
      return json({
        total: 0,
        limite: 1,
        desplazamiento: 0,
        comidas: [{ comida_id: 2, codigo: 'ALM', nombre: 'Almuerzo' }],
        datos: [],
      });
    }
    if (url.pathname === '/pantalla/ultimas-marcaciones') {
      // 100 filas rechazadas
      const filas = Array.from({ length: 100 }, (_, i) => ({
        id: i + 1,
        fecha_hora: '2026-09-28T12:00:00',
        usuario_id: i + 1,
        valido: false,
        motivo: 'sin_derecho',
      }));
      return json(filas);
    }
    throw new Error(`Ruta inesperada: ${url.pathname}`);
  };

  const resumen = await obtenerResumenComidas({ fecha: '2026-09-28' });
  assert.equal(resumen.length, 1);
  assert.equal(resumen[0].rechazos, 100);
  assert.equal(resumen[0].rechazosTruncados, true);
  assert.equal(resumen[0].estado, 'Fuera de horario');
});

// -------------------------------------------------------------
// 4. Autorizar no_identificado envía {usuario_id, metodo:'manual'} sin momento
// -------------------------------------------------------------
test('autorizar no_identificado envía {usuario_id, metodo: manual} sin momento', async () => {
  const peticiones = [];
  globalThis.fetch = async (ruta, opciones) => {
    peticiones.push({ ruta: new URL(ruta).pathname, opciones });
    if (new URL(ruta).pathname === '/personal/42') {
      return json({ usuario_id: 42, nombre_completo: 'Laura Medico', tiene_ficha: true, categoria: 'Médico' });
    }
    if (new URL(ruta).pathname === '/asistencias') {
      return json({
        valido: true,
        titulo: 'Ración autorizada',
        detalle: 'Comensal habilitado',
        usuario_id: 42,
        nombre: 'Laura Medico',
        comida: 'Almuerzo',
      });
    }
    throw new Error(`Ruta inesperada: ${ruta}`);
  };

  const resultado = await autorizarMarcacionManual(42);
  assert.equal(resultado.valido, true);

  // Validar la llamada a /asistencias
  const peticionAsistencia = peticiones.find((p) => p.ruta === '/asistencias');
  assert.ok(peticionAsistencia, 'Debe llamar a /asistencias');
  assert.equal(peticionAsistencia.opciones.method, 'POST');

  const cuerpo = JSON.parse(peticionAsistencia.opciones.body);
  assert.equal(cuerpo.usuario_id, 42);
  assert.equal(cuerpo.metodo, 'manual');
  // Estricto: el campo momento NO debe existir en el cuerpo enviado
  assert.equal(cuerpo.momento, undefined, 'El momento no debe enviarse');
});

// -------------------------------------------------------------
// 5. sin_derecho no hace ninguna petición
// -------------------------------------------------------------
test('sin_derecho no hace ninguna petición HTTP', async () => {
  let llamadasFetch = 0;
  globalThis.fetch = async () => {
    llamadasFetch += 1;
    return json({});
  };

  // Simulación del render con marcación sin_derecho
  const marcacionSinDerecho = {
    id: 55,
    dispositivo: 'lector-1',
    hora: '12:40',
    valido: false,
    motivo: 'sin_derecho',
    titulo: 'Sin derecho en este turno',
    persona: { id: 10, nombre: 'Comensal Rechazado', categoria: 'Adm', legajo: 'ADM-10' },
  };

  const html = renderToStaticMarkup(
    h(Supervision, {
      cargandoInicial: false,
      resumenInicial: [],
      marcacionesIniciales: [marcacionSinDerecho],
    })
  );

  // El botón está desactivado con el texto requerido
  assert.match(html, /Requiere excepción de jefatura \(pendiente\)/);
  assert.match(html, /disabled/);

  // No se realizó ninguna llamada a la API
  assert.equal(llamadasFetch, 0, 'No debe realizar ninguna petición HTTP');
});

// -------------------------------------------------------------
// 6. Render de Supervisión en carga, vacío, error y simulación
// -------------------------------------------------------------
test('render de Supervisión en carga, vacío, error y simulación', () => {
  // Estado CARGA
  const htmlCarga = renderToStaticMarkup(
    h(Supervision, { cargandoInicial: true })
  );
  assert.match(htmlCarga, /role="status"/);
  assert.match(htmlCarga, /Cargando supervisión…/);
  assert.doesNotMatch(htmlCarga, /No hay registros/);

  // Estado VACÍO (sin demo ni mocks)
  const htmlVacio = renderToStaticMarkup(
    h(Supervision, {
      cargandoInicial: false,
      resumenInicial: [],
      marcacionesIniciales: [],
    })
  );
  assert.match(htmlVacio, /No hay registros de supervisión para este día/);
  assert.doesNotMatch(htmlVacio, /Cargando/);
  assert.doesNotMatch(htmlVacio, /role="alert"/);

  // Estado ERROR
  const htmlError = renderToStaticMarkup(
    h(Supervision, {
      cargandoInicial: false,
      errorInicial: 'Fallo de conexión con el servidor',
    })
  );
  assert.match(htmlError, /role="alert"/);
  assert.match(htmlError, /Fallo de conexión con el servidor/);
  assert.match(htmlError, /Reintentar supervisión/);

  // Estado SIMULACIÓN
  const reloj = {
    ahora: new Date(2020, 1, 3, 12, 30),
    real: new Date(2026, 8, 28, 9, 0),
    simulado: true,
    congelado: false,
  };
  const htmlSim = renderToStaticMarkup(
    h(Supervision, {
      cargandoInicial: false,
      simulacion: reloj,
      resumenInicial: [{ comidaId: 1, comida: 'Desayuno', servidas: 5, rechazos: 0, rechazosTruncados: false, estado: '—' }],
      marcacionesIniciales: [],
    })
  );
  assert.match(htmlSim, /Modo simulación/);
  assert.match(htmlSim, /Supervisión basada en el reloj del servidor/);

  // Fuera de simulación
  const htmlSinSim = renderToStaticMarkup(
    h(Supervision, {
      cargandoInicial: false,
      simulacion: null,
      resumenInicial: [{ comidaId: 1, comida: 'Desayuno', servidas: 5, rechazos: 0, rechazosTruncados: false, estado: '—' }],
      marcacionesIniciales: [],
    })
  );
  assert.doesNotMatch(htmlSinSim, /Modo simulación/);
});

// -------------------------------------------------------------
// 7. Render de estructura, keys y feed de solo lectura
// -------------------------------------------------------------
test('render de Supervisión contiene tarjetas por comida, rechazos por revisar y feed de solo lectura con keys dispositivo-id', () => {
  const resumen = [
    { comidaId: 1, comida: 'Desayuno', servidas: 25, rechazos: 1, rechazosTruncados: false, estado: '—' },
    { comidaId: 2, comida: 'Almuerzo', servidas: 90, rechazos: 100, rechazosTruncados: true, estado: 'En curso' },
  ];
  const marcaciones = [
    {
      id: 701,
      dispositivo: 'lector-1',
      hora: '12:05',
      valido: true,
      titulo: 'Marcación válida',
      comidaId: 2,
      comida: 'Almuerzo',
      persona: { id: 1, nombre: 'Comensal Exito', categoria: 'Médico', legajo: 'M-1' },
    },
    {
      id: 702,
      dispositivo: 'lector-2',
      hora: '12:10',
      valido: false,
      motivo: 'no_identificado',
      titulo: 'Huella no reconocida',
      comidaId: 2,
      comida: 'Almuerzo',
      persona: { id: null, nombre: 'Huella no reconocida', categoria: 'Sin identificar', legajo: '—' },
    },
  ];

  const html = renderToStaticMarkup(
    h(Supervision, {
      cargandoInicial: false,
      resumenInicial: resumen,
      marcacionesIniciales: marcaciones,
      personal: [{ id: 99, nombre: 'Ana Gomez', categoria: 'Bioquimica', legajo: 'B-99' }],
    })
  );

  // Subsección (a) Comidas del día
  assert.match(html, /Comidas del día/);
  assert.match(html, /Desayuno/);
  assert.match(html, /Almuerzo/);
  assert.match(html, /100 o más/); // rechazos truncados
  assert.match(html, /En curso/);

  // Subsección (b) Rechazos por revisar (agrupados por motivo, con acción para no_identificado)
  assert.match(html, /Rechazos por revisar/);
  assert.match(html, /Huella no reconocida \(no identificado\)/);
  assert.match(html, /Autorizar ración manual/);
  assert.match(html, /Seleccione comensal del padrón/);
  assert.match(html, /Ana Gomez/);

  // Subsección (c) Hilo de marcaciones (feed de solo lectura)
  assert.match(html, /Hilo de marcaciones/);
  assert.match(html, /Comensal Exito/);
  assert.match(html, /lector-1/);
  assert.match(html, /lector-2/);
});

// -------------------------------------------------------------
// 8. Header en vivo (cocinera) intacto vs en supervisión
// -------------------------------------------------------------
test('el header de vivo de la cocinera se dibuja igual que antes, y en supervision unifica fecha y hora del servidor', () => {
  const reloj = {
    ahora: new Date(2020, 1, 3, 12, 5),
    real: new Date(2026, 8, 28, 9, 0),
    simulado: true,
    congelado: false,
  };

  // Header en 'vivo' (la cocinera): se dibuja igual que antes
  const seccionVivo = { id: 'vivo', titulo: 'Control Biométrico', descripcion: 'Marcaciones en vivo' };
  const htmlVivo = renderToStaticMarkup(
    h(Header, { seccion: seccionVivo, turno: 'Almuerzo', simulacion: reloj })
  );
  assert.match(htmlVivo, /Control Biométrico/);
  assert.match(htmlVivo, /header__pastilla--simulacion/);
  assert.match(htmlVivo, /<strong>Simulación<\/strong>.*12:05/);
  assert.match(htmlVivo, /header__pastilla--turno/);
  assert.match(htmlVivo, /Turno Almuerzo/);
  // En vivo conserva la pastilla separada con fecha y año
  assert.match(htmlVivo, /03 feb.*2020/);

  // Header en 'supervision': un solo indicador de fecha y hora del servidor (sin pastilla separada de fecha)
  const seccionSupervision = { id: 'supervision', titulo: 'Supervisión del comedor', descripcion: 'Control y supervisión del comedor' };
  const htmlSupervision = renderToStaticMarkup(
    h(Header, { seccion: seccionSupervision, turno: 'Almuerzo', simulacion: reloj })
  );
  assert.match(htmlSupervision, /Supervisión del comedor/);
  assert.match(htmlSupervision, /header__pastilla--simulacion/);
  assert.match(htmlSupervision, /<strong>Simulación<\/strong>.*12:05/);
  assert.match(htmlSupervision, /Turno Almuerzo/);
  // No renderiza la pastilla separada de fecha de calendario (no repite la fecha)
  assert.doesNotMatch(htmlSupervision, /2020/);
});

// -------------------------------------------------------------
// 9. Respuesta de autorizar manual (éxito y rechazo de negocio)
// -------------------------------------------------------------
test('autorizar con respuesta { valido: false, motivo: "duplicado" } muestra el rechazo y no el éxito, y conserva selección', async () => {
  let recargado = false;
  let exitoNotificado = false;
  let comensalEstado = { 101: '42' };
  let avisoRecibido = null;

  const respuestaRechazo = {
    valido: false,
    motivo: 'duplicado',
    titulo: 'Ya recibió su comida',
    detalle: 'Comensal ya almorzó a las 12:15',
  };

  await ejecutarAutorizacionManual({
    marcacion: { id: 101, motivo: 'no_identificado' },
    usuarioId: 42,
    autorizarFn: async () => respuestaRechazo,
    cargarDatosFn: async () => { recargado = true; },
    setAvisoAccion: (aviso) => { avisoRecibido = aviso; },
    setComensalElegido: (fn) => { comensalEstado = fn(comensalEstado); },
    setAutorizandoId: () => {},
    onMarcacionExitosa: () => { exitoNotificado = true; },
  });

  // Emite aviso de rechazo con titulo y detalle del servidor
  assert.deepEqual(avisoRecibido, {
    tipo: 'rechazo',
    titulo: 'Ya recibió su comida',
    detalle: 'Comensal ya almorzó a las 12:15',
  });
  // NO limpia la selección del comensal
  assert.equal(comensalEstado[101], '42');
  // NO notifica marcación exitosa
  assert.equal(exitoNotificado, false);
  // Recarga siempre después
  assert.equal(recargado, true);

  // Render en UI: muestra aviso de rechazo y no el de éxito
  const html = renderToStaticMarkup(
    h(Supervision, {
      cargandoInicial: false,
      resumenInicial: [],
      marcacionesIniciales: [{ id: 101, motivo: 'no_identificado', valido: false, hora: '12:00' }],
      avisoAccionInicial: avisoRecibido,
    })
  );
  assert.match(html, /Ya recibió su comida/);
  assert.match(html, /Comensal ya almorzó a las 12:15/);
  assert.match(html, /supervision__aviso-accion--rechazo/);
  assert.doesNotMatch(html, /supervision__aviso-accion--exito/);
});

test('autorizar con respuesta { valido: true } muestra el éxito y limpia la selección', async () => {
  let recargado = false;
  let exitoNotificado = false;
  let comensalEstado = { 101: '42' };
  let avisoRecibido = null;

  const respuestaExito = {
    valido: true,
    motivo: 'ok',
    titulo: 'Ración autorizada',
    detalle: 'Comensal habilitado para Almuerzo',
  };

  await ejecutarAutorizacionManual({
    marcacion: { id: 101, motivo: 'no_identificado' },
    usuarioId: 42,
    autorizarFn: async () => respuestaExito,
    cargarDatosFn: async () => { recargado = true; },
    setAvisoAccion: (aviso) => { avisoRecibido = aviso; },
    setComensalElegido: (fn) => { comensalEstado = fn(comensalEstado); },
    setAutorizandoId: () => {},
    onMarcacionExitosa: () => { exitoNotificado = true; },
  });

  // Emite aviso de éxito con titulo y detalle
  assert.deepEqual(avisoRecibido, {
    tipo: 'exito',
    titulo: 'Ración autorizada',
    detalle: 'Comensal habilitado para Almuerzo',
  });
  // Limpia la selección del comensal
  assert.equal(comensalEstado[101], undefined);
  // Notifica éxito
  assert.equal(exitoNotificado, true);
  // Recarga siempre después
  assert.equal(recargado, true);

  // Render en UI: muestra aviso de éxito y no el de rechazo
  const html = renderToStaticMarkup(
    h(Supervision, {
      cargandoInicial: false,
      resumenInicial: [],
      marcacionesIniciales: [],
      avisoAccionInicial: avisoRecibido,
    })
  );
  assert.match(html, /Ración autorizada/);
  assert.match(html, /Comensal habilitado para Almuerzo/);
  assert.match(html, /supervision__aviso-accion--exito/);
  assert.doesNotMatch(html, /supervision__aviso-accion--rechazo/);
});

// -------------------------------------------------------------
// 10. Refresco automático y botón Actualizar
// -------------------------------------------------------------
test('refresco automático cada 30s programa carga inicial, refrescos y cancela al desmontar', () => {
  const llamadas = [];
  let limpiadoIntervaloId = null;
  let intervalCallback = null;

  const originalSetInterval = globalThis.setInterval;
  const originalClearInterval = globalThis.clearInterval;

  globalThis.setInterval = (fn, ms) => {
    assert.equal(ms, 30000, 'El intervalo debe ser de 30 segundos');
    intervalCallback = fn;
    return 777;
  };
  globalThis.clearInterval = (id) => {
    limpiadoIntervaloId = id;
  };

  try {
    const cancelar = programarRefrescoSupervision({
      cargarDatos: ({ signal, esRefresco }) => {
        llamadas.push({ signal, esRefresco });
      },
      intervaloMs: 30000,
    });

    // 1. Carga inicial inmediata con esRefresco: false
    assert.equal(llamadas.length, 1);
    assert.equal(llamadas[0].esRefresco, false);
    assert.equal(llamadas[0].signal.aborted, false);

    // 2. Disparo de un tick del intervalo: debe abortar el anterior y llamar con esRefresco: true
    intervalCallback();
    assert.equal(llamadas.length, 2);
    assert.equal(llamadas[1].esRefresco, true);
    assert.equal(llamadas[0].signal.aborted, true, 'El controlador previo debe abortarse');
    assert.equal(llamadas[1].signal.aborted, false);

    // 3. Desmontar / cancelar: limpia intervalo y aborta el controlador activo
    cancelar();
    assert.equal(limpiadoIntervaloId, 777, 'Debe llamar a clearInterval con el ID del intervalo');
    assert.equal(llamadas[1].signal.aborted, true, 'El controlador activo debe abortarse al cancelar');
  } finally {
    globalThis.setInterval = originalSetInterval;
    globalThis.clearInterval = originalClearInterval;
  }
});

test('botón Actualizar visible en la sección de Supervisión (vista normal y vacía)', () => {
  // En vista con datos
  const htmlConDatos = renderToStaticMarkup(
    h(Supervision, {
      cargandoInicial: false,
      resumenInicial: [{ comidaId: 1, comida: 'Desayuno', servidas: 10, rechazos: 0, rechazosTruncados: false, estado: '—' }],
      marcacionesIniciales: [],
    })
  );
  assert.match(htmlConDatos, /Actualizar/);
  assert.match(htmlConDatos, /supervision__acciones-barra/);

  // En vista vacía
  const htmlVacio = renderToStaticMarkup(
    h(Supervision, {
      cargandoInicial: false,
      resumenInicial: [],
      marcacionesIniciales: [],
    })
  );
  assert.match(htmlVacio, /Actualizar/);
  assert.match(htmlVacio, /No hay registros de supervisión para este día/);
});

// -------------------------------------------------------------
// 11. Fuera de horario cuando comida es null
// -------------------------------------------------------------
test('cuando /pantalla/estado viene con fuera_de_horario=true y comida null, muestra aviso en cabecera de tarjetas', async () => {
  globalThis.fetch = async (ruta) => {
    const url = new URL(ruta);
    if (url.pathname === '/pantalla/estado') {
      return json({
        momento: '2026-09-28T05:00:00',
        fecha_comida: '2026-09-28',
        comida_id: null,
        comida: null,
        fuera_de_horario: true,
        cupo: null,
        padron: 200,
        totales_del_dia: { raciones_servidas: 0, lecturas: 0, aceptadas: 0, rechazadas: 0 },
        por_categoria: [],
      });
    }
    if (url.pathname === '/reportes/informe') {
      return json({
        tipo: 'informe',
        gestion: 2026,
        mes: 9,
        desde: '2026-09-28',
        hasta: '2026-09-28',
        situacion: 'curso',
        cerrado: false,
        categorias: ['Planta'],
        filas: [
          { etiqueta: 'Desayuno', celdas: [0], total: 0, registrado: true },
          { etiqueta: 'Almuerzo', celdas: [0], total: 0, registrado: true },
        ],
        totales_por_categoria: [0],
        total_general: 0,
        sin_clasificar: 0,
        sin_coeficiente: 0,
        grupos: [],
      });
    }
    if (url.pathname === '/historial/diario') {
      return json({
        total: 0,
        limite: 1,
        desplazamiento: 0,
        comidas: [
          { comida_id: 1, codigo: 'DES', nombre: 'Desayuno' },
          { comida_id: 2, codigo: 'ALM', nombre: 'Almuerzo' },
        ],
        datos: [],
      });
    }
    if (url.pathname === '/pantalla/ultimas-marcaciones') {
      return json([]);
    }
    throw new Error(`Ruta inesperada: ${url.pathname}`);
  };

  const resumen = await obtenerResumenComidas({ fecha: '2026-09-28' });
  assert.equal(resumen.length, 2);
  assert.equal(resumen[0].estado, '—');
  assert.equal(resumen[1].estado, '—');
  assert.equal(resumen.fueraDeHorario, true, 'El adaptador debe marcar fueraDeHorario como true');

  // En el render del componente:
  const html = renderToStaticMarkup(
    h(Supervision, {
      cargandoInicial: false,
      resumenInicial: resumen,
      marcacionesIniciales: [],
      fueraDeHorarioInicial: resumen.fueraDeHorario,
    })
  );

  assert.match(html, /Comidas del día/);
  // Aviso "Fuera de horario" presente en la cabecera de las tarjetas
  assert.match(html, /supervision__aviso-fuera-horario/);
  assert.match(html, /Fuera de horario/);
});

