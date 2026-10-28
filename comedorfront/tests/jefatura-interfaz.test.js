/*
 * Interfaz de jefatura: Supervisión, Resumen, Reportes y Cuentas.
 *
 * Render real con react-dom/server (JSX y CSS los resuelve
 * tests/soporte/cargador-jsx.js), sin API ni navegador. Prueba lo que el
 * rediseño no puede romper: qué ve cada rol, que las cifras se rotulen con su
 * período sin duplicarse, y que Reportes y Cuentas conserven su alcance.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import Supervision, {
  esManual,
  filtrarMarcaciones,
  resumenDePestana,
} from '../src/components/secciones/Supervision.jsx';
import Dashboard from '../src/components/secciones/Dashboard.jsx';
import Reportes from '../src/components/secciones/Reportes.jsx';
import CuentasLectura from '../src/components/secciones/CuentasLectura.jsx';
import { contarCuentasPorEstado } from '../src/cuentas.js';
import { diaLegible } from '../src/dias.js';
import {
  anchoDeMedidor,
  cupoLegible,
  horaDelEstado,
  periodosDeResumen,
} from '../src/resumen.js';
import {
  puedeMarcarManual,
  puedeVerSeccion,
  seccionesPermitidas,
} from '../src/permisos.js';

const leer = (ruta) => readFileSync(new URL(ruta, import.meta.url), 'utf8');

const dia = () => ({
  fecha: '2026-09-28',
  comidas: [
    {
      comidaId: 1, comida: 'Desayuno', horaInicio: '07:00:00', horaFin: '09:00:00',
      estado: 'cerrada', previstas: 120, servidas: 118, manuales: 2,
      rechazos: { noIdentificado: 1, sinDerecho: 0, duplicado: 3 },
    },
    {
      comidaId: 2, comida: 'Almuerzo', horaInicio: '12:00:00', horaFin: '14:00:00',
      estado: 'en_curso', previstas: null, servidas: 60, manuales: 5,
      rechazos: { noIdentificado: 0, sinDerecho: 2, duplicado: 0 },
    },
  ],
  rechazosSinComida: 0,
});

const marcacion = (cambios = {}) => ({
  id: 1,
  origen: 'lectura_biometrica',
  clave: `${cambios.origen ?? 'lectura_biometrica'}:${cambios.id ?? 1}`,
  usuarioId: 1,
  valido: true,
  titulo: 'Marcación válida',
  motivo: null,
  dispositivo: 'lector-1',
  hora: '12:05:00',
  comidaId: 2,
  comida: 'Almuerzo',
  persona: { id: 1, nombre: 'Ana Gomez', categoria: 'Médico' },
  ...cambios,
});

const supervision = (props = {}) => renderToStaticMarkup(h(Supervision, {
  cargandoInicial: false,
  comidasIniciales: dia(),
  marcacionesIniciales: [],
  ...props,
}));

/* ---------------------------------------------------------------- permisos */

test('jefa abre solo lo suyo: cuentas en lectura sí; reglas, administración y lector no', () => {
  assert.deepEqual(seccionesPermitidas('jefa'), ['supervision', 'dashboard', 'historial', 'reportes', 'cuentas']);
  for (const id of ['reglas', 'admin', 'monitoreo', 'vivo']) {
    assert.equal(puedeVerSeccion('jefa', id), false, `jefa no abre ${id}`);
  }
  assert.equal(puedeMarcarManual('jefa'), true);
});

test('sistemas y cocinera no ven la interfaz de jefatura; Administración sigue siendo de sistemas', () => {
  for (const id of ['supervision', 'dashboard', 'reportes', 'cuentas']) {
    assert.equal(puedeVerSeccion('sistemas', id), false, `sistemas no abre ${id}`);
    assert.equal(puedeVerSeccion('cocinera', id), false, `cocinera no abre ${id}`);
  }
  assert.equal(puedeVerSeccion('sistemas', 'admin'), true);
  assert.equal(puedeVerSeccion('jefa', 'admin'), false);
  assert.equal(puedeMarcarManual('sistemas'), false);
  assert.equal(puedeMarcarManual('cocinera'), false);
  assert.deepEqual(seccionesPermitidas('rol-inventado'), []);
});

/* ------------------------------------------------------------- Supervisión */

test('resumen de pestaña: aceptadas, rechazadas y manuales salen del servidor, sin recalcular', () => {
  const desayuno = resumenDePestana(dia(), 1);
  assert.equal(desayuno.servidas, 118);
  assert.equal(desayuno.manuales, 2);
  assert.equal(desayuno.rechazadas, 4);
  assert.equal(desayuno.previstas, 120);
  assert.deepEqual(desayuno.motivos.map(({ clave, cantidad }) => [clave, cantidad]), [
    ['noIdentificado', 1],
    ['duplicado', 3],
  ]);

  const todas = resumenDePestana(dia(), null);
  assert.equal(todas.servidas, 178);
  assert.equal(todas.manuales, 7);
  assert.equal(todas.rechazadas, 6);
  assert.equal(todas.previstas, null);
  assert.equal(todas.comida, null);

  assert.equal(resumenDePestana(dia(), 99), null, 'una pestaña que ya no existe no inventa cifras');
  assert.equal(resumenDePestana(null, null).servidas, 0);
});

test('Supervisión muestra aceptadas, rechazadas y manuales con el período de la comida activa', () => {
  const html = supervision();
  /* Abre en la comida en curso: Almuerzo. */
  assert.match(html, /<h2 class="supervision__periodo-titulo">Almuerzo<\/h2>/);
  assert.match(html, /12:00 – 14:00 · En curso · lunes,? 28 de septiembre de 2026/);
  assert.match(html, /Aceptadas<\/dt><dd>60<\/dd>/);
  assert.match(html, /Rechazadas<\/dt><dd>2<\/dd>/);
  assert.match(html, /Manuales<\/dt><dd>5<\/dd>/);
  assert.match(html, /Incluidas en las aceptadas/);
  /* Sin cupo previsto no se escribe «de null previstas». */
  assert.doesNotMatch(html, /null|undefined|NaN/);
});

test('el segmento «Manuales» filtra por origen, no por resultado ni por dispositivo', () => {
  const filas = [
    marcacion({ id: 1 }),
    marcacion({ id: 2, origen: 'asistencia_manual', dispositivo: 'lector-1' }),
    marcacion({ id: 3, valido: false, motivo: 'duplicado', dispositivo: 'registro-manual' }),
  ];
  assert.deepEqual(filtrarMarcaciones(filas, { resultado: 'manuales' }).map((m) => m.id), [2]);
  assert.equal(esManual(filas[2]), false);
  assert.deepEqual(filtrarMarcaciones(filas, { resultado: 'todas' }).map((m) => m.id), [1, 2, 3]);

  const html = supervision({ marcacionesIniciales: filas });
  assert.match(html, />Manuales</);
  assert.equal(html.match(/etiqueta--manual/g).length, 1, 'una sola fila lleva la marca «Manual»');
  assert.equal(html.match(/supervision__fila--manual/g).length, 1);
});

test('Supervisión no ofrece registro manual y consulta intervenciones solo con permiso', () => {
  const html = supervision({ puedeRegistrarManual: true });
  assert.doesNotMatch(html, /Registrar ración manual/);

  /* Sin el permiso de consulta (sistemas, o un rol futuro) no hay apartado. */
  assert.doesNotMatch(html, /Intervenciones de cocina/);
  const pagina = {
    desde: '2026-09-28', hasta: '2026-09-28', total: 0, limite: 50, desplazamiento: 0,
    totales: { registradas: 0, rechazadas: 0 }, datos: [],
  };
  assert.match(supervision({ puedeConsultarIntervenciones: true, intervencionesIniciales: { pagina } }), /Intervenciones de cocina/);
});

test('Supervisión es SOLO LECTURA: ningún control registra, autoriza ni modifica raciones', () => {
  const pagina = {
    desde: '2026-09-28', hasta: '2026-09-28', total: 1, limite: 50, desplazamiento: 0,
    totales: { registradas: 1, rechazadas: 0 },
    datos: [{
      id: 56, clave: 'intervencion_lectura:56', resultado: 'registrada', motivoRechazo: null, momento: '2026-09-28T12:30:00',
      decisionOriginal: { lecturaId: 9, resultado: 'rechazada', motivo: 'no_identificado', fechaHora: '2026-09-28T12:29:00', dispositivo: 'lector-pb' },
      cuenta: { id: 4, usuario: 'maria.cocina', nombre: 'María Cocina' },
      comensal: { usuarioId: 99, nombre: 'Ana Gomez', categoria: 'Médico' },
      servicio: { comidaId: 2, comida: 'Almuerzo', fechaComida: '2026-09-28', reconstruido: true },
      entregaRegistrada: true, asistenciaId: 31, lecturaResuelta: true,
    }],
  };
  const html = supervision({
    puedeRegistrarManual: true,
    puedeConsultarIntervenciones: true,
    intervencionesIniciales: { pagina },
    marcacionesIniciales: [
      marcacion({ id: 1 }),
      marcacion({ id: 2, valido: false, motivo: 'no_identificado', persona: { id: null, nombre: 'Huella no reconocida', categoria: 'Sin identificar' } }),
      marcacion({ id: 3, origen: 'asistencia_manual' }),
    ],
  });

  /* Sin textos ni controles de escritura. */
  assert.doesNotMatch(html, /Registrar|Autorizar|Confirmar|Aprobar|Anular|Deshacer|Guardar|Eliminar/);
  assert.doesNotMatch(html, /<select|<form|<textarea|registro-manual/);
  assert.equal(html.match(/<input/g).length, 1, 'solo el buscador por nombre');

  /* Todo botón es de consulta: pestañas, filtros, Actualizar y los de Intervenciones. */
  const textos = [...html.matchAll(/<button[^>]*>([\s\S]*?)<\/button>/g)]
    .map(([, interior]) => interior.replace(/<[^>]+>/g, '').trim());
  const permitidos = new Set([
    'Todas', 'Aceptadas', 'Rechazadas', 'Manuales', 'Actualizar',
    'Entregas registradas', 'Intentos rechazados',
  ]);
  for (const texto of textos) {
    const esPestana = /^(Todas|Desayuno|Almuerzo)/.test(texto);
    // El selector del día que se supervisa: solo cambia lo que se consulta.
    const esSelectorDia = /^Fecha seleccionada/.test(texto);
    assert.ok(esPestana || esSelectorDia || permitidos.has(texto), `botón inesperado en Supervisión: «${texto}»`);
  }

  /* Conserva la consulta: pestañas, filtros, búsqueda, actualización e intervenciones. */
  assert.match(html, /Día que se supervisa/);
  assert.match(html, /Filtrar por comida/);
  assert.match(html, /Filtrar por resultado/);
  assert.match(html, /placeholder="Buscar por nombre…"/);
  assert.match(html, /<span class="boton__texto">Actualizar<\/span>/);
  assert.match(html, /3 de 3 marcaciones/);
  assert.match(html, /Intervenciones de cocina/);
  assert.match(html, /Filtrar intervenciones por resultado/);
});

test('Supervisión e Intervenciones solo importan lecturas de la API y App no les pasa escritura', () => {
  const importadas = (ruta) => {
    const fuente = leer(ruta);
    const bloque = /import\s*\{([^}]*)\}\s*from\s*'\.\.\/\.\.\/api\.js'/.exec(fuente);
    return bloque ? bloque[1].split(',').map((nombre) => nombre.trim()).filter(Boolean) : [];
  };
  assert.deepEqual(importadas('../src/components/secciones/Supervision.jsx').sort(), ['obtenerComidasDelDia', 'obtenerUltimasMarcaciones']);
  assert.deepEqual(importadas('../src/components/secciones/IntervencionesCocina.jsx'), ['obtenerIntervencionesCocina']);
  const supervision = leer('../src/components/secciones/Supervision.jsx');
  assert.doesNotMatch(supervision, /RegistroManual|autorizarMarcacionManual|marcarAsistencia|identificarLectura|method:/);

  /* App monta Supervisión sin props de escritura. */
  const app = leer('../src/App.jsx');
  const montaje = app.slice(app.indexOf('<Supervision'), app.indexOf('/>', app.indexOf('<Supervision')));
  assert.doesNotMatch(montaje, /puedeRegistrarManual|onMarcacionExitosa|personal=|registrar/);
});

test('la tabla de Supervisión es de consulta: sin «Autorizar» ni columna de acción', () => {
  const html = supervision({
    marcacionesIniciales: [
      marcacion({ id: 1 }),
      marcacion({ id: 2, valido: false, motivo: 'no_identificado', persona: { id: null, nombre: 'Huella no reconocida', categoria: 'Sin identificar' } }),
      marcacion({ id: 3, valido: false, motivo: 'sin_derecho' }),
    ],
  });
  assert.doesNotMatch(html, /Autorizar|Sin acción disponible|<th scope="col">Acción<\/th>/);
  assert.match(html, /3 de 3 marcaciones/);
});

test('con filtros que no coinciden se ofrece limpiar; sin filtros no', () => {
  const sinFiltros = supervision({ marcacionesIniciales: [marcacion()] });
  assert.doesNotMatch(sinFiltros, /Limpiar filtros/);
  assert.match(sinFiltros, /1 de 1 marcación</);
});

/* ----------------------------------------------------------------- Resumen */

const pantalla = (cambios = {}) => ({
  momento: '2026-09-28T12:05:00',
  fecha_comida: '2026-09-28',
  comida_id: 2,
  comida: 'Almuerzo',
  fuera_de_horario: false,
  cupo: { previstas: 100, servidas: 60, restantes: 40, porcentaje: 60 },
  padron: 150,
  totales_del_dia: { raciones_servidas: 178, lecturas: 190, aceptadas: 170, rechazadas: 20 },
  por_categoria: [
    { categoria: 'Médicos', raciones: 100 },
    { categoria: 'Enfermería', raciones: 78 },
  ],
  ...cambios,
});

test('el Resumen rotula cada conteo con su período y no repite las raciones', () => {
  const html = renderToStaticMarkup(h(Dashboard, { pantalla: pantalla() }));
  assert.match(html, /Datos de las 12:05/);
  assert.match(html, /Solo esta comida · lunes,? 28 de septiembre de 2026/);
  assert.match(html, /Todas las comidas · lunes,? 28 de septiembre de 2026/);
  assert.match(html, /Día del reloj · lunes,? 28 de septiembre de 2026/);
  /* Las lecturas se declaran como toques de dedo, no como raciones. */
  assert.match(html, /Toques de dedo: no son raciones/);
  assert.equal(html.match(/Raciones servidas del día/g).length, 1);
  assert.equal(html.match(/>Lecturas del lector</g).length, 1);
  /* Turno: 60 de 100 previstas, tal cual lo entrega el servidor. */
  assert.match(html, /60<span class="turno__previstas"> \/ 100 previstas<\/span>/);
  assert.match(html, /60% del cupo del turno/);
  assert.match(html, /quedan <strong>40<\/strong>/);
});

test('el Resumen distingue fuera de horario, sin cupo cargado y sin raciones', () => {
  const fuera = renderToStaticMarkup(h(Dashboard, {
    pantalla: pantalla({ fuera_de_horario: true, cupo: null, comida: null }),
  }));
  assert.match(fuera, /Fuera de horario/);
  assert.match(fuera, /Sin comida vigente/);
  assert.doesNotMatch(fuera, /previstas/);

  const sinCupo = renderToStaticMarkup(h(Dashboard, {
    pantalla: pantalla({ cupo: { previstas: null, servidas: 12, restantes: null, porcentaje: null } }),
  }));
  assert.match(sinCupo, /sin cupo cargado/);
  assert.match(sinCupo, /no tiene límite/);
  assert.doesNotMatch(sinCupo, /turno__medidor|null|NaN|undefined/);

  const vacio = renderToStaticMarkup(h(Dashboard, {
    pantalla: pantalla({
      totales_del_dia: { raciones_servidas: 0, lecturas: 0, aceptadas: 0, rechazadas: 0 },
      por_categoria: [{ categoria: 'Médicos', raciones: 0 }, { categoria: 'Enfermería', raciones: 0 }],
    }),
  }));
  assert.match(vacio, /Todavía no se sirvió ninguna ración en este día/);
  assert.doesNotMatch(vacio, /grafico__lienzo/);

  const sinClasificar = renderToStaticMarkup(h(Dashboard, {
    pantalla: pantalla({ por_categoria: [{ categoria: 'Médicos', raciones: 0 }] }),
  }));
  assert.match(sinClasificar, /todavía no están clasificadas por categoría/);

  assert.match(renderToStaticMarkup(h(Dashboard, { pantalla: null })), /Estado del comedor no disponible/);
});

test('resumen.js rotula períodos y no inventa porcentajes', () => {
  assert.equal(horaDelEstado('2026-09-28T12:05:00'), '12:05');
  assert.equal(horaDelEstado('sin hora'), '');
  assert.deepEqual(periodosDeResumen({}), {
    turno: 'Solo esta comida',
    raciones: 'Todas las comidas del día',
    lecturas: 'Día del reloj',
    corte: 'Datos del servidor',
  });

  assert.equal(cupoLegible(null), null);
  assert.deepEqual(cupoLegible({ previstas: null, servidas: 3, restantes: null, porcentaje: null }), {
    servidas: 3, previstas: null, restantes: null, porcentaje: null, supera: false,
  });
  assert.equal(cupoLegible({ previstas: 10, servidas: 12, restantes: 0, porcentaje: 120 }).supera, true);
  assert.equal(cupoLegible({ previstas: 10, servidas: 10, restantes: 0, porcentaje: 100 }).supera, false);

  assert.equal(anchoDeMedidor(120), 100);
  assert.equal(anchoDeMedidor(-5), 0);
  assert.equal(anchoDeMedidor(null), 0);
  assert.equal(anchoDeMedidor(37), 37);
});

test('diaLegible lee el calendario local y descarta fechas que no existen', () => {
  assert.match(diaLegible('2026-09-28'), /28 de septiembre de 2026/);
  assert.match(diaLegible('2026-09-28T23:59:00'), /28 de septiembre de 2026/);
  assert.equal(diaLegible('2026-02-31'), '');
  assert.equal(diaLegible(null), '');
  assert.equal(diaLegible('28/09/2026'), '');
});

/* ---------------------------------------------------------------- Reportes */

test('Reportes muestra una sola vista: el informe del personal con Excel y PDF', () => {
  const html = renderToStaticMarkup(h(Reportes, { ahora: new Date(2026, 8, 28, 12) }));
  assert.doesNotMatch(html, /reportes__selector|selector-reporte|aria-pressed/);
  assert.doesNotMatch(html, /Tipo de reporte/);
  /* Se conserva el informe del personal y sus dos exportaciones. */
  assert.match(html, /Informe de raciones servidas al personal/);
  assert.match(html, /<span class="boton__texto">Excel<\/span>/);
  assert.match(html, /<span class="boton__texto">PDF<\/span>/);
  assert.match(html, /FECHA INICIAL/);
  assert.match(html, /FECHA FINAL/);
});

test('el período del informe es una sola línea y no agranda el control', () => {
  const html = renderToStaticMarkup(h(Reportes, { ahora: new Date(2026, 8, 28, 12) }));
  assert.match(html, /class="informe__periodo"/);
  /* Sin datos todavía no hay línea secundaria: nada que inflar. */
  assert.doesNotMatch(html, /informe__periodo-gestion/);
});

test('fechas, período, Excel y PDF comparten la altura de control', () => {
  const informe = leer('../src/components/secciones/InformeRaciones.css');
  const filtro = leer('../src/components/ui/FiltroRangoFechas.css');
  const tokens = leer('../src/styles/tokens.css');
  assert.match(tokens, /--alto-control:\s*46px/);

  const bloque = (css, selector) => {
    const inicio = css.indexOf(`${selector} {`);
    assert.ok(inicio >= 0, `falta ${selector}`);
    return css.slice(inicio, css.indexOf('}', inicio));
  };
  assert.match(bloque(informe, '.informe__periodo'), /height:\s*var\(--alto-control\)/);
  assert.match(bloque(informe, '.informe__acciones .boton'), /height:\s*var\(--alto-control\)/);
  assert.match(bloque(filtro, '.order-calendar-trigger'), /height:\s*var\(--alto-control\)/);
  assert.match(bloque(filtro, '.report-filter > button'), /height:\s*var\(--alto-control\)/);
  /* La línea secundaria ya no se apila: el período no puede crecer a dos filas. */
  assert.doesNotMatch(bloque(informe, '.informe__periodo'), /display:\s*grid/);
});

/* ------------------------------------------------------------------ Cuentas */

const cuentas = [
  { id: 7, username: 'maria.cocina', nombre: 'María Cocina', rol: 'cocinera', activo: true, debeCambiar: false, ultimoIngreso: '2026-09-28T07:55:00' },
  { id: 8, username: 'jefa.nutri', nombre: 'Nadia Tarifa', rol: 'jefa', activo: true, debeCambiar: true, ultimoIngreso: null },
  { id: 9, username: 'baja.vieja', nombre: null, rol: 'cocinera', activo: false, debeCambiar: false, ultimoIngreso: null },
];

test('Cuentas cuenta por estado con el mismo criterio de la columna Estado', () => {
  assert.deepEqual(contarCuentasPorEstado(cuentas), { activas: 1, claveTemporal: 1, inactivas: 1 });
  assert.deepEqual(contarCuentasPorEstado([]), { activas: 0, claveTemporal: 0, inactivas: 0 });
});

test('Cuentas sigue siendo solo lectura: un buscador y Actualizar, sin formularios ni acciones', () => {
  const html = renderToStaticMarkup(h(CuentasLectura, { cargandoInicial: false, cuentasIniciales: cuentas }));
  assert.equal(html.match(/<input/g).length, 1, 'solo el buscador');
  assert.doesNotMatch(html, /<select|<form|<textarea|type="password"|type="checkbox"/);
  assert.doesNotMatch(html, /Nueva cuenta|Reiniciar|Desactivar|Reactivar|Acciones|Vínculo|Editar|Eliminar/);
  assert.match(html, /Solo lectura/);
  assert.match(html, /3 de 3 cuentas/);
  assert.match(html, /Activas 1/);
  assert.match(html, /Clave temporal 1/);
  assert.match(html, /Inactivas 1/);
  /* Cada celda trae su rótulo para la vista de tarjeta en pantallas pequeñas. */
  assert.equal(html.match(/data-label="Último ingreso"/g).length, 3);

  /* Ni Administración ni su hoja de estilo entran en esta vista. */
  assert.doesNotMatch(leer('../src/components/secciones/CuentasLectura.jsx'), /import[^;]*Administracion/);
  assert.doesNotMatch(leer('../src/components/secciones/CuentasLectura.css'), /@import[^;]*Administracion/);
});

test('Cuentas distingue cargando, error, vacío y búsqueda sin resultados', () => {
  assert.match(renderToStaticMarkup(h(CuentasLectura, { cargandoInicial: true })), /Cargando cuentas…/);
  const error = renderToStaticMarkup(h(CuentasLectura, { cargandoInicial: false, errorInicial: 'Sin conexión' }));
  assert.match(error, /role="alert"/);
  assert.match(error, /Reintentar cuentas/);
  assert.match(renderToStaticMarkup(h(CuentasLectura, { cargandoInicial: false, cuentasIniciales: [] })), /No hay cuentas registradas/);

  const sinCoincidencia = renderToStaticMarkup(h(CuentasLectura, {
    cargandoInicial: false, cuentasIniciales: cuentas, busquedaInicial: 'zzz',
  }));
  assert.match(sinCoincidencia, /Ninguna cuenta coincide con la búsqueda/);
  assert.match(sinCoincidencia, /0 de 3 cuentas/);
  assert.match(sinCoincidencia, /Limpiar búsqueda/);
});

/* ------------------------------------------------------------ Accesibilidad */

test('las hojas de estilo rediseñadas respetan prefers-reduced-motion', () => {
  for (const ruta of [
    '../src/components/secciones/Supervision.css',
    '../src/components/secciones/Dashboard.css',
    '../src/components/secciones/CuentasLectura.css',
    '../src/components/ui/FiltroRangoFechas.css',
    '../src/components/ui/Boton.css',
  ]) {
    assert.match(leer(ruta), /@media \(prefers-reduced-motion: reduce\)/, ruta);
  }
  /* El latido del punto «en curso» es lo único que se anima solo. */
  assert.match(leer('../src/components/secciones/Supervision.css'), /punto-curso,[\s\S]*animation: none/);
});
