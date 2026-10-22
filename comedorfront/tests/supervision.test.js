import test, { afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import Header from '../src/components/layout/Header.jsx';
import Supervision, {
  LIMITE_SUPERVISION,
  filtrarMarcaciones,
  metodoDeMarcacion,
  pestanaPorDefecto,
  programarRefrescoSupervision,
  rechazosDeComida,
} from '../src/components/secciones/Supervision.jsx';
import {
  autorizarMarcacionManual,
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

const diaFixture = (cambios = {}) => ({
  fecha: '2026-09-28',
  comidas: [
    {
      comidaId: 1, comida: 'Desayuno', horaInicio: '07:00', horaFin: '09:00',
      estado: 'cerrada', previstas: 120, servidas: 118, manuales: 2,
      rechazos: { noIdentificado: 1, sinDerecho: 0, duplicado: 3 },
    },
    {
      comidaId: 2, comida: 'Almuerzo', horaInicio: '12:00', horaFin: '14:00',
      estado: 'en_curso', previstas: null, servidas: 60, manuales: 0,
      rechazos: { noIdentificado: 0, sinDerecho: 2, duplicado: 0 },
    },
  ],
  rechazosSinComida: 4,
  ...cambios,
});

const marcacionFixture = (cambios = {}) => ({
  id: 701,
  origen: 'lectura_biometrica',
  clave: `${cambios.origen ?? 'lectura_biometrica'}:${cambios.id ?? 701}`,
  usuarioId: 1,
  valido: true,
  titulo: 'Marcación válida',
  motivo: null,
  dispositivo: 'lector-1',
  hora: '12:05:00',
  comidaId: 2,
  comida: 'Almuerzo',
  persona: { id: 1, nombre: 'Comensal Exito', categoria: 'Médico' },
  ...cambios,
});

// -------------------------------------------------------------
// 1. Permisos
// -------------------------------------------------------------
test('permisos: cocinera sigue en [vivo], la jefa abre supervision y ya no vivo, sistemas ya no ve supervision', () => {
  // Cocinera sigue en ['vivo']
  assert.deepEqual(seccionesPermitidas('cocinera'), ['vivo']);
  assert.equal(puedeVerSeccion('cocinera', 'vivo'), true);
  assert.equal(puedeVerSeccion('cocinera', 'supervision'), false);

  // La jefa abre 'supervision' y ya no 'vivo'; sistemas conserva solo sus tres secciones
  assert.deepEqual(seccionesPermitidas('jefa'), ['supervision', 'dashboard', 'historial', 'reportes', 'cuentas']);
  assert.deepEqual(seccionesPermitidas('sistemas'), ['reglas', 'admin', 'monitoreo']);
  assert.equal(puedeVerSeccion('jefa', 'supervision'), true);
  assert.equal(puedeVerSeccion('jefa', 'vivo'), false);
  assert.equal(puedeVerSeccion('sistemas', 'supervision'), false);
  assert.equal(puedeVerSeccion('sistemas', 'vivo'), false);

  // Sección guardada 'vivo' -> 'supervision' para la jefa; sistemas cae en Reglas
  assert.equal(resolverSeccionGuardada('jefa', 'vivo'), 'supervision');
  assert.equal(resolverSeccionGuardada('sistemas', 'vivo'), 'reglas');

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
        origen: 'lectura_biometrica',
        clave_evento: 'lectura_biometrica:101',
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
        origen: 'lectura_biometrica',
        clave_evento: 'lectura_biometrica:102',
      },
    ]);
  };

  const lista = await obtenerUltimasMarcaciones({ fecha: '2026-09-28', limite: 20 });
  assert.equal(lista.length, 2);

  // Campos existentes conservados intactos
  assert.equal(lista[0].id, 101);
  assert.equal(lista[0].valido, false);
  // El motivo guardado de una huella sin usuario se lee como tal.
  assert.equal(lista[0].titulo, 'Huella no reconocida');
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
// 3. El registro manual de jefatura envía {usuario_id, metodo:'manual'} sin momento
// -------------------------------------------------------------
test('el registro manual independiente envía {usuario_id, metodo: manual} sin momento', async () => {
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
// 4. Las filas de rechazo son de consulta: sin Autorizar ni peticiones
// -------------------------------------------------------------
test('un rechazo sin_derecho o no_identificado no ofrece Autorizar ni hace peticiones', async () => {
  let llamadasFetch = 0;
  globalThis.fetch = async () => {
    llamadasFetch += 1;
    return json({});
  };

  const marcacionSinDerecho = marcacionFixture({
    id: 55,
    dispositivo: 'lector-1',
    hora: '12:40:00',
    valido: false,
    motivo: 'sin_derecho',
    titulo: 'Sin derecho en este turno',
    persona: { id: 10, nombre: 'Comensal Rechazado', categoria: 'Adm' },
  });

  const html = renderToStaticMarkup(
    h(Supervision, {
      cargandoInicial: false,
      comidasIniciales: diaFixture(),
      marcacionesIniciales: [
        marcacionSinDerecho,
        marcacionFixture({ id: 56, valido: false, motivo: 'no_identificado', persona: { id: null, nombre: 'Huella no reconocida', categoria: 'Sin identificar' } }),
      ],
    })
  );

  // Ni el Autorizar viejo ni la excepción pendiente: la huella la identifica cocina.
  assert.doesNotMatch(html, /Autorizar|Requiere excepción de jefatura|Confirmar ración manual/);
  assert.doesNotMatch(html, /<th scope="col">Acción<\/th>/);

  // No se realizó ninguna llamada a la API
  assert.equal(llamadasFetch, 0, 'No debe realizar ninguna petición HTTP');
});

// -------------------------------------------------------------
// 5. Render de Supervisión en carga, vacío y error
// -------------------------------------------------------------
test('render de Supervisión en carga, vacío y error', () => {
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
      comidasIniciales: diaFixture({ comidas: [], rechazosSinComida: 0 }),
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
});

// -------------------------------------------------------------
// 6. Pestañas: Todas + una por comida, defecto en_curso
// -------------------------------------------------------------
test('pestañas muestran nombre, estado, servidas y rechazos; el punto verde marca la comida en curso', () => {
  const html = renderToStaticMarkup(
    h(Supervision, {
      cargandoInicial: false,
      comidasIniciales: diaFixture(),
      marcacionesIniciales: [],
    })
  );

  // "Todas" + una por comida, en el orden recibido
  assert.match(html, /<span class="supervision__pestana-nombre">Todas<\/span>/);
  const posicionTodas = html.indexOf('>Todas<');
  const posicionDesayuno = html.indexOf('>Desayuno<');
  const posicionAlmuerzo = html.indexOf('>Almuerzo<');
  assert.ok(posicionTodas < posicionDesayuno && posicionDesayuno < posicionAlmuerzo);

  // Estados legibles
  assert.match(html, /Cerrada/);
  assert.match(html, /En curso/);
  assert.doesNotMatch(html, /en_curso/);

  // Un solo punto verde: la comida en curso
  assert.equal(html.match(/supervision__punto-curso/g).length, 1);

  // Servidas y rechazos (suma de motivos) por comida
  assert.match(html, />118</); // servidas del Desayuno
  assert.match(html, />4</); // rechazos del Desayuno: 1 + 0 + 3
  assert.match(html, />60</); // servidas del Almuerzo
  assert.match(html, />2</); // rechazos del Almuerzo: 0 + 2 + 0

  // Nota discreta de rechazos fuera de franja
  assert.match(html, /4 rechazos fuera de franja/);
});

test('pestaña por defecto: la comida en curso, o Todas si no hay ninguna', () => {
  assert.equal(pestanaPorDefecto(diaFixture().comidas), 2);
  assert.equal(pestanaPorDefecto(diaFixture({ comidas: [] }).comidas), null);
  const sinCurso = diaFixture({
    comidas: [diaFixture().comidas[0]],
    rechazosSinComida: 0,
  });
  assert.equal(pestanaPorDefecto(sinCurso.comidas), null);

  // Con comida en curso, su pestaña abre seleccionada
  const htmlCurso = renderToStaticMarkup(
    h(Supervision, {
      cargandoInicial: false,
      comidasIniciales: diaFixture(),
      marcacionesIniciales: [],
    })
  );
  assert.match(htmlCurso, /<button[^>]*role="tab"[^>]*aria-selected="true"[^>]*>[\s\S]*?Almuerzo/);

  // Sin comida en curso, abre "Todas"
  const htmlTodas = renderToStaticMarkup(
    h(Supervision, {
      cargandoInicial: false,
      comidasIniciales: sinCurso,
      marcacionesIniciales: [],
    })
  );
  assert.match(htmlTodas, /<button[^>]*role="tab"[^>]*aria-selected="true"[^>]*>[\s\S]*?Todas/);
  assert.doesNotMatch(htmlTodas, /fuera de franja/);

  // Suma de rechazos por motivo
  assert.equal(rechazosDeComida(diaFixture().comidas[0]), 4);
  assert.equal(rechazosDeComida(diaFixture().comidas[1]), 2);
});

// -------------------------------------------------------------
// 7. Tabla: columnas, resultado, motivo, método y filas de rechazo
// -------------------------------------------------------------
test('la tabla muestra Hora, Comensal, Categoría, Comida, Resultado, Motivo, Método y Acción', () => {
  const filas = [
    marcacionFixture({}),
    marcacionFixture({
      id: 702, dispositivo: 'lector-2', hora: '12:10:00', valido: false,
      motivo: 'no_identificado', titulo: 'Huella no reconocida',
      persona: { id: null, nombre: 'Huella no reconocida', categoria: 'Sin identificar' },
    }),
    marcacionFixture({
      id: 703, origen: 'asistencia_manual', dispositivo: 'registro-manual', hora: '12:15:00', valido: false,
      motivo: 'sin_derecho', titulo: 'Sin derecho en este turno',
      persona: { id: 10, nombre: 'Comensal Sin Derecho', categoria: 'Adm' },
    }),
    marcacionFixture({
      id: 704, dispositivo: 'lector-1', hora: '12:20:00', valido: false,
      motivo: 'duplicado', titulo: 'Ya recibió su comida',
      persona: { id: 11, nombre: 'Comensal Duplicado', categoria: 'Planta' },
    }),
  ];
  const html = renderToStaticMarkup(
    h(Supervision, {
      cargandoInicial: false,
      comidasIniciales: diaFixture(),
      marcacionesIniciales: filas,
    })
  );

  // Cabeceras en orden
  for (const columna of ['Hora', 'Comensal', 'Categoría', 'Comida', 'Resultado', 'Motivo', 'Método']) {
    assert.match(html, new RegExp(`<th scope="col">${columna}</th>`));
  }

  // Insignias de resultado
  assert.match(html, /etiqueta--exito[^>]*>\s*Aceptada/);
  assert.match(html, /etiqueta--error[^>]*>\s*Rechazada/);

  // Motivos legibles; la aceptada lleva guion
  assert.match(html, /Huella no reconocida \(no identificado\)/);
  assert.match(html, /Sin derecho en este turno/);
  assert.match(html, /Ya recibió su comida \(duplicado\)/);
  assert.match(html, /<td>—<\/td>/);

  // Método: según el origen declarado, nunca según el texto del dispositivo
  assert.equal(html.match(/<td>Registro manual<\/td>/g).length, 1);
  assert.equal(html.match(/<td>Lectura biométrica<\/td>/g).length, 3);
  assert.equal(metodoDeMarcacion({ origen: 'asistencia_manual', dispositivo: 'lector-1' }), 'Registro manual');
  assert.equal(metodoDeMarcacion({ origen: 'lectura_biometrica', dispositivo: 'registro-manual' }), 'Lectura biométrica');

  // Las tres rechazadas llevan fondo de rechazo
  assert.equal(html.match(/supervision__fila--rechazada/g).length, 3);

  // Sin «Autorizar»: la tabla es de consulta (la huella la identifica cocina)
  assert.doesNotMatch(html, /Autorizar/);
  assert.doesNotMatch(html, /<th scope="col">Acción<\/th>/);

  // Sin aviso de truncado con pocas filas
  assert.doesNotMatch(html, /Mostrando las últimas/);
});

test('solo avisa truncado al llegar al límite de la consulta', () => {
  const cien = Array.from({ length: LIMITE_SUPERVISION }, (_, i) => marcacionFixture({
    id: 1000 + i,
    persona: { id: 1000 + i, nombre: `Comensal ${1000 + i}`, categoria: 'Planta' },
  }));
  const htmlCien = renderToStaticMarkup(
    h(Supervision, {
      cargandoInicial: false,
      comidasIniciales: diaFixture(),
      marcacionesIniciales: cien,
    })
  );
  assert.match(htmlCien, /Mostrando las últimas 1000/);

  const htmlNoventa = renderToStaticMarkup(
    h(Supervision, {
      cargandoInicial: false,
      comidasIniciales: diaFixture(),
      marcacionesIniciales: cien.slice(0, 150),
    })
  );
  assert.doesNotMatch(htmlNoventa, /Mostrando las últimas/);
});

// -------------------------------------------------------------
// 8. Filtros de resultado y búsqueda por nombre
// -------------------------------------------------------------
test('la barra trae segmentado, búsqueda, Actualizado y Actualizar; el filtrado es por resultado y nombre', () => {
  const html = renderToStaticMarkup(
    h(Supervision, {
      cargandoInicial: false,
      comidasIniciales: diaFixture(),
      marcacionesIniciales: [marcacionFixture({})],
      actualizadoInicial: new Date(2026, 8, 28, 9, 4, 7),
    })
  );
  assert.match(html, /Filtrar por resultado/);
  assert.match(html, />Aceptadas</);
  assert.match(html, />Rechazadas</);
  assert.match(html, /placeholder="Buscar por nombre…"/);
  assert.match(html, /Actualizado 09:04:07/);
  assert.match(html, /<span class="boton__texto">Actualizar<\/span>/);

  const filas = [
    marcacionFixture({ id: 1, valido: true, persona: { id: 1, nombre: 'Ana Gomez', categoria: 'Médico' } }),
    marcacionFixture({ id: 2, valido: false, motivo: 'duplicado', persona: { id: 2, nombre: 'Luis Perez', categoria: 'Planta' } }),
    marcacionFixture({ id: 3, valido: false, motivo: 'sin_derecho', persona: { id: 3, nombre: 'Ana Torres', categoria: 'Adm' } }),
  ];
  assert.deepEqual(filtrarMarcaciones(filas, { resultado: 'todas' }).map((m) => m.id), [1, 2, 3]);
  assert.deepEqual(filtrarMarcaciones(filas, { resultado: 'aceptadas' }).map((m) => m.id), [1]);
  assert.deepEqual(filtrarMarcaciones(filas, { resultado: 'rechazadas' }).map((m) => m.id), [2, 3]);
  assert.deepEqual(filtrarMarcaciones(filas, { busqueda: 'ana' }).map((m) => m.id), [1, 3]);
  assert.deepEqual(filtrarMarcaciones(filas, { resultado: 'rechazadas', busqueda: 'ana' }).map((m) => m.id), [3]);
  assert.deepEqual(filtrarMarcaciones(filas, { busqueda: 'nadie' }), []);
});

// -------------------------------------------------------------
// 9. Huella identificada por cocina: decisión original y resultado final
// -------------------------------------------------------------
test('una huella que identificó cocina muestra el rechazo original y la entrega aparte', () => {
  const fila = marcacionFixture({
    id: 702, dispositivo: 'lector-2', valido: false, motivo: 'no_identificado',
    persona: { id: null, nombre: 'Huella no reconocida', categoria: 'Sin identificar' },
    estadoFinal: 'racion_servida',
    resultadoFinal: { via: 'identificacion_manual', asistenciaId: 9, comensal: { usuarioId: 99, nombre: 'Ana Gomez' } },
    intervencion: { revision: 1, resuelta: true, resueltaPorMi: false, registradaPor: { cuentaId: 4, usuario: 'maria.cocina', nombre: 'María Cocina' }, intentosRechazados: 0 },
  });
  const html = renderToStaticMarkup(
    h(Supervision, {
      cargandoInicial: false,
      comidasIniciales: diaFixture(),
      marcacionesIniciales: [fila],
      personal: [{ id: 99, nombre: 'Ana Gomez', categoria: 'Bioquimica', legajo: 'B-99' }],
    })
  );
  // La decisión del lector no cambia: sigue siendo un rechazo de huella no reconocida.
  assert.match(html, /etiqueta--error[^>]*>\s*Rechazada/);
  assert.match(html, /Huella no reconocida \(no identificado\)/);
  // El resultado final va aparte, con la persona y quién lo registró.
  assert.match(html, /Entregada por cocina/);
  assert.match(html, /Ana Gomez · registró María Cocina/);
  // Y nada que aprobar.
  assert.doesNotMatch(html, /Autorizar|Confirmar ración manual|supervision__fila-autorizar/);
});

// -------------------------------------------------------------
// 10. Header: título, turno y fecha de este equipo
// -------------------------------------------------------------
test('el header muestra el título de la sección, el turno y la fecha', () => {
  const seccion = { id: 'supervision', titulo: 'Supervisión del comedor', descripcion: 'Control y supervisión del comedor' };
  const html = renderToStaticMarkup(h(Header, { seccion, turno: 'Almuerzo' }));
  assert.match(html, /Supervisión del comedor/);
  assert.match(html, /header__pastilla--turno/);
  assert.match(html, /Turno Almuerzo/);
  assert.match(html, new RegExp(String(new Date().getFullYear())));
});

// -------------------------------------------------------------
// 11. Avisos: solo el de un refresco fallido (no hay acciones de escritura)
// -------------------------------------------------------------
test('Supervisión no muestra avisos de acciones: solo el de un refresco que falló', () => {
  const html = renderToStaticMarkup(
    h(Supervision, {
      cargandoInicial: false,
      comidasIniciales: diaFixture(),
      marcacionesIniciales: [marcacionFixture({})],
      /* Props de la versión anterior: ya no existen y no pintan nada. */
      avisoAccionInicial: { tipo: 'exito', titulo: 'Ración autorizada', detalle: 'x' },
      puedeRegistrarManual: true,
      errorRefrescoInicial: 'HTTP 500',
    })
  );
  assert.doesNotMatch(html, /Ración autorizada|supervision__aviso-accion--exito|supervision__aviso-accion--rechazo/);
  assert.match(html, /supervision__aviso-accion--error/);
  assert.match(html, /No se pudo actualizar/);
  assert.match(html, /Se muestran los datos anteriores\. HTTP 500/);
});

// -------------------------------------------------------------
// 12. Refresco automático y botón Actualizar
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
      comidasIniciales: diaFixture(),
      marcacionesIniciales: [],
    })
  );
  assert.match(htmlConDatos, /<span class="boton__texto">Actualizar<\/span>/);

  // En vista vacía
  const htmlVacio = renderToStaticMarkup(
    h(Supervision, {
      cargandoInicial: false,
      comidasIniciales: diaFixture({ comidas: [], rechazosSinComida: 0 }),
      marcacionesIniciales: [],
    })
  );
  assert.match(htmlVacio, /<span class="boton__texto">Actualizar<\/span>/);
  assert.match(htmlVacio, /No hay registros de supervisión para este día/);
});
