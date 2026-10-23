const token = document.querySelector('meta[name="qa-control"]').content;
const aviso = document.querySelector('#aviso');
const confirmacion = document.querySelector('#confirmacion');
const selectorServicio = document.querySelector('#servicio-elegido');
let estado = null;
let ocupado = false;
let consultando = false;
let inicializado = false;
let errorConexion = false;
let accionPendiente = null;
let focoAnterior = null;
let repeticionPendiente = false;
const ORIGENES_APP = ['http://127.0.0.1:5173', 'http://localhost:5173'];
let origenPantalla = window.location.ancestorOrigins?.[0] || '';
if (!ORIGENES_APP.includes(origenPantalla) && document.referrer) {
  origenPantalla = new URL(document.referrer).origin;
}

/** @param {string} mensaje @param {boolean} error @returns {void} */
function mostrarAviso(mensaje, error = false) {
  aviso.textContent = mensaje;
  aviso.classList.toggle('error', error);
  aviso.setAttribute('role', error ? 'alert' : 'status');
}

/** @returns {object} */
function horarioElegido() {
  const hora = document.querySelector('#hora').value;
  return { momento: `${document.querySelector('#fecha').value}T${hora.length === 5 ? `${hora}:00` : hora}`,
    modo: document.querySelector('#modo').value, comida_id: Number(selectorServicio.value) };
}

/** @returns {void} */
function usarHoraSugerida() {
  const comida = estado?.comidas.find(item => item.id === Number(selectorServicio.value));
  if (comida) document.querySelector('#hora').value = comida.hora;
}

/** @returns {void} */
function dibujar() {
  for (const boton of document.querySelectorAll('button')) boton.disabled = ocupado;
  // Salir o reconectar sigue siendo posible durante una espera.
  document.querySelector('#reconectar').disabled = false;
  for (const boton of document.querySelectorAll('.ver-pantalla')) boton.disabled = false;
  if (!estado) return;
  document.querySelector('#reloj').textContent = estado.momento.replace('T', ' · ');
  document.querySelector('#modo-actual').textContent = estado.modo === 'fijo' ? 'Pausado' : 'En marcha';
  document.querySelector('#conexion').textContent = estado.api_activa ? 'Laboratorio conectado' : 'Laboratorio conectado · API detenida';
  const advertencias = document.querySelector('#advertencias');
  advertencias.textContent = (estado.advertencias ?? []).join(' ');
  advertencias.hidden = !advertencias.textContent;
  if (!inicializado) {
    document.querySelector('#fecha').value = estado.momento.slice(0, 10);
    document.querySelector('#hora').value = estado.momento.slice(11, 19);
    document.querySelector('#modo').value = estado.modo;
    selectorServicio.value = String(estado.comida_id);
    inicializado = true;
  }
  for (const boton of document.querySelectorAll('[data-comida]')) {
    boton.setAttribute('aria-pressed', String(Number(boton.dataset.comida) === estado.comida_id));
  }
  document.querySelector('#restriccion').textContent = estado.servicio_elegido_vigente
    ? `${estado.servicio}: puedes probar las lecturas. Cambiar de comida conserva las anteriores.`
    : 'Fuera de horario. Elige una comida arriba para usar su hora de prueba.';
  for (const caso of ['qa01', 'qa02']) {
    const tarjeta = document.querySelector(`#${caso}`);
    const datos = estado.casos[caso];
    tarjeta.querySelector('.estado').textContent = datos.estado;
    tarjeta.querySelector('.detalle').textContent = datos.detalle || 'Todavía no se generó una lectura.';
    tarjeta.querySelector('.lectura').textContent = datos.lectura_id ? `Lectura n.º ${datos.lectura_id}` : '';
    tarjeta.querySelector('.resultado').classList.toggle('comprobado', datos.comprobado);
    tarjeta.querySelector('.resultado').classList.toggle('pendiente', !datos.comprobado && datos.lectura_id !== null);
    tarjeta.querySelector('.alta-huella').textContent = datos.huella_registrada ? 'Huella vinculada a esta persona.' : 'Todavía no tiene huella vinculada.';
    tarjeta.querySelector('.registrar').textContent = `${datos.huella_registrada ? 'Ver' : 'Registrar'} huella de ${caso === 'qa01' ? 'QA 01' : 'QA 02'}`;
    tarjeta.querySelector('.simular').textContent = caso === 'qa01'
      ? repeticionPendiente ? 'Verificar lectura' : datos.lectura_id ? 'Volver a leer' : 'Leer huella'
      : datos.lectura_id ? 'Revisar en cocina' : 'Simular fallo de huella';
    tarjeta.querySelector('.decision').textContent = `Tu revisión: ${estado.revision[caso]?.resultado ?? 'pendiente'}`;
  }
  const policia = document.querySelector('#policia');
  const policias = estado.policias ?? { dia: 0, comida: 0 };
  const selector = document.querySelector('#policia-elegido');
  const elegido = selector.value;
  const registrados = (estado.policias_registrados ?? []).filter(p => p.nombre !== 'Policía de prueba QA');
  const firma = registrados.map(p => `${p.id}:${p.nombre}:${p.documento ?? ''}`).join('|');
  if (selector.dataset.firma !== firma) {
    selector.replaceChildren(new Option('Policía de prueba QA', ''),
      ...registrados.map(p => new Option(p.documento ? `${p.nombre} · ${p.documento}` : p.nombre, String(p.id))));
    selector.value = registrados.some(p => String(p.id) === elegido) ? elegido : '';
    selector.dataset.firma = firma;
  }
  policia.querySelector('.estado').textContent = policias.dia
    ? `${policias.comida} en ${estado.servicio} · ${policias.dia} en el día` : 'Sin simular';
  policia.querySelector('.detalle').textContent = policias.dia
    ? 'Raciones de policía de este ensayo. Cuentan en Policías del Resumen y de Reportes.'
    : 'Todavía no se registró ninguna ración de policía.';
  policia.querySelector('.resultado').classList.toggle('comprobado', policias.dia > 0);
}

/** @param {string} ruta @param {object} opciones @returns {Promise<object>} */
async function solicitar(ruta, opciones = {}) {
  let respuesta;
  try {
    respuesta = await fetch(ruta, { ...opciones, headers: { 'X-QA-Control': token, 'Content-Type': 'application/json' },
      cache: 'no-store', signal: AbortSignal.timeout(opciones.method === 'POST' ? 120000 : 8000) });
  } catch {
    throw new Error(opciones.method === 'POST'
      ? 'No se pudo confirmar la operación. Reconecta y consulta el resultado antes de volver a pulsar.'
      : 'El laboratorio no responde. Comprueba su consola y pulsa Reconectar.');
  }
  if ([403, 404].includes(respuesta.status)) throw new Error('La sesión del laboratorio cambió. Pulsa Reconectar; se conserva el ensayo.');
  const datos = await respuesta.json();
  if (!respuesta.ok) throw new Error(datos.error || 'No se pudo consultar el laboratorio.');
  return datos;
}

/** @param {string} ruta @param {object} cuerpo @returns {Promise<void>} */
async function ejecutar(ruta, cuerpo) {
  if (ocupado) return;
  ocupado = true;
  dibujar();
  mostrarAviso(ruta === '/nuevo' ? 'Archivando el ensayo y preparando la comida…' : 'Aplicando la prueba…');
  try {
    estado = await solicitar(ruta, { method: 'POST', body: JSON.stringify(cuerpo) });
    inicializado = false;
    errorConexion = false;
    mostrarAviso(estado.ultima_accion);
    if (ruta === '/nuevo') {
      repeticionPendiente = false;
      document.querySelector('#resultado-repeticion').textContent = '';
      for (const casilla of document.querySelectorAll('.revisado')) casilla.checked = false;
    }
  } catch (error) { mostrarAviso(error.message, true); }
  finally { ocupado = false; dibujar(); }
}

/** @param {() => Promise<void>} accion @returns {void} */
function confirmarPreparacion(accion) {
  focoAnterior = document.activeElement;
  accionPendiente = accion;
  document.querySelector('#nuevo-horario').textContent = `${selectorServicio.selectedOptions[0].textContent} · ${horarioElegido().momento.replace('T', ' · ')}`;
  confirmacion.hidden = false;
  confirmacion.scrollIntoView({ block: 'nearest' });
  document.querySelector('#cancelar-ensayo').focus();
}

/** @returns {void} */
function cancelarPreparacion() {
  confirmacion.hidden = true;
  accionPendiente = null;
  focoAnterior?.focus();
}

/** @param {object} datos @returns {boolean} */
function enviarAPantalla(datos) {
  if (window.parent === window || !ORIGENES_APP.includes(origenPantalla)) return false;
  window.parent.postMessage(datos, origenPantalla);
  return true;
}

/** @returns {void} */
function volverAPantalla() {
  if (!enviarAPantalla({ tipo: 'cerrar-laboratorio-qa' })) mostrarAviso('Abre «Simular escenarios QA» desde la aplicación para volver a cocina.');
}

/** @param {string} caso @returns {void} */
function registrarHuellaDelCaso(caso) {
  if (!estado) { mostrarAviso('Consulta el ensayo con Reconectar antes de registrar la huella.', true); return; }
  const datos = estado.casos[caso];
  if (!enviarAPantalla({ tipo: 'registrar-huella-caso-qa', caso, usuario_id: datos.usuario_id })) {
    mostrarAviso('Abre este panel desde la aplicación e inicia sesión como cocinera para registrar la huella.', true);
  }
}

/** @returns {boolean} */
function disponible() {
  if (ocupado) return false;
  if (!estado || errorConexion) { mostrarAviso('Pulsa Reconectar para consultar el ensayo. No se ha generado ninguna lectura.', true); return false; }
  if (!estado.api_activa) { mostrarAviso('La API QA está detenida. Vuelve a iniciar el laboratorio con probar.ps1.', true); return false; }
  return true;
}

window.addEventListener('message', evento => {
  if (evento.source !== window.parent || !['http://127.0.0.1:5173', 'http://localhost:5173'].includes(evento.origin)) return;
  origenPantalla = evento.origin;
  if (evento.data?.tipo === 'actualizar-laboratorio-qa') actualizar();
  if (evento.data?.tipo === 'registro-huella-no-disponible-qa') mostrarAviso('Inicia sesión como cocinera en Control Biométrico para registrar la huella.', true);
  if (evento.data?.tipo === 'resultado-lectura-caso-qa') {
    ocupado = false;
    repeticionPendiente = evento.data.incierto === true;
    const texto = repeticionPendiente ? 'Resultado por verificar. Pulsa Verificar lectura: se reutiliza el mismo intento.'
      : evento.data.duplicado ? 'Segunda ración rechazada: esta persona ya recibió su comida.'
      : evento.data.registrada ? 'Entrega registrada. Revisa el resultado en cocina.' : 'No se registró otra entrega. Revisa el resultado en cocina.';
    document.querySelector('#resultado-repeticion').textContent = texto;
    mostrarAviso(evento.data.error || texto, Boolean(evento.data.error) || repeticionPendiente);
    dibujar();
  }
});

for (const boton of document.querySelectorAll('[data-comida]')) boton.addEventListener('click', () => {
  if (!disponible() || repeticionPendiente) { if (repeticionPendiente) mostrarAviso('Verifica la lectura pendiente antes de cambiar de comida.', true); return; }
  selectorServicio.value = boton.dataset.comida;
  usarHoraSugerida();
  document.querySelector('#modo').value = 'fijo';
  const horario = horarioElegido();
  if (!estado.preparado_cuatro_comidas) confirmarPreparacion(() => ejecutar('/nuevo', { ...horario, confirmar: true }));
  else ejecutar('/horario', horario);
});
selectorServicio.addEventListener('change', usarHoraSugerida);
document.querySelector('#hora-sugerida').addEventListener('click', usarHoraSugerida);
document.querySelector('#form-horario').addEventListener('submit', evento => {
  evento.preventDefault();
  if (!disponible() || repeticionPendiente) return;
  const horario = horarioElegido();
  if (!estado.preparado_cuatro_comidas || horario.momento.slice(0, 10) !== estado.momento.slice(0, 10)) confirmarPreparacion(() => ejecutar('/nuevo', { ...horario, confirmar: true }));
  else ejecutar('/horario', horario);
});
document.querySelector('#nuevo').addEventListener('click', () => {
  if (!disponible()) return;
  if (repeticionPendiente) { mostrarAviso('Verifica primero la lectura pendiente antes de empezar otro ensayo.', true); return; }
  confirmarPreparacion(() => ejecutar('/nuevo', { ...horarioElegido(), confirmar: true }));
});
document.querySelector('#cancelar-ensayo').addEventListener('click', cancelarPreparacion);
document.querySelector('#confirmar-ensayo').addEventListener('click', () => {
  const accion = accionPendiente;
  confirmacion.hidden = true;
  accionPendiente = null;
  accion?.();
});
for (const boton of document.querySelectorAll('.registrar')) boton.addEventListener('click', () => registrarHuellaDelCaso(boton.dataset.caso));
for (const boton of document.querySelectorAll('.simular')) boton.addEventListener('click', () => {
  if (!disponible()) return;
  const caso = boton.dataset.caso;
  const datos = estado.casos[caso];
  if (repeticionPendiente && caso !== 'qa01') { mostrarAviso('Verifica primero la lectura pendiente de QA 01.', true); return; }
  if (!datos.huella_registrada) { registrarHuellaDelCaso(caso); return; }
  if (caso === 'qa01' && (datos.lectura_id || repeticionPendiente)) {
    ocupado = enviarAPantalla({ tipo: 'leer-huella-caso-qa', caso, usuario_id: datos.usuario_id, referencia: datos.referencia_huella });
    if (!ocupado) mostrarAviso('Abre el simulador desde la aplicación para volver a leer con tu sesión de cocinera.', true);
    dibujar();
  } else if (datos.lectura_id) volverAPantalla();
  else if (!estado.servicio_elegido_vigente || !estado.preparado_cuatro_comidas) mostrarAviso('Elige primero una comida arriba para preparar su horario.', true);
  else ejecutar('/simular', { caso });
});
document.querySelector('.simular-policia').addEventListener('click', () => {
  if (!disponible()) return;
  if (repeticionPendiente) { mostrarAviso('Verifica primero la lectura pendiente de QA 01.', true); return; }
  if (!estado.servicio_elegido_vigente) { mostrarAviso('Elige primero una comida arriba para usar su horario.', true); return; }
  const elegido = document.querySelector('#policia-elegido').value;
  ejecutar('/simular', { caso: 'policia', ...(elegido ? { vinculo_id: Number(elegido) } : {}) });
});
for (const boton of document.querySelectorAll('.aprobar, .rechazar')) boton.addEventListener('click', () => {
  if (!disponible()) return;
  const caso = boton.dataset.caso;
  ejecutar('/revision', { caso, resultado: boton.classList.contains('aprobar') ? 'aprobado' : 'rechazado', revisado: document.querySelector(`#${caso} .revisado`).checked });
});
for (const boton of document.querySelectorAll('.ver-pantalla')) boton.addEventListener('click', volverAPantalla);
document.querySelector('#reconectar').addEventListener('click', () => window.location.reload());
document.addEventListener('keydown', evento => {
  if (evento.key !== 'Escape') return;
  if (!confirmacion.hidden) cancelarPreparacion(); else volverAPantalla();
});

/** @returns {Promise<void>} */
async function actualizar() {
  if (ocupado || consultando) return;
  consultando = true;
  try {
    estado = await solicitar('/estado');
    if (errorConexion || aviso.textContent === 'Consultando el ensayo…') mostrarAviso('Elige una comida y prueba el lector.');
    errorConexion = false;
    dibujar();
  } catch (error) {
    errorConexion = true;
    document.querySelector('#conexion').textContent = 'No se pudo actualizar el ensayo';
    mostrarAviso(error.message, true);
  } finally { consultando = false; }
}
await actualizar();
enviarAPantalla({ tipo: 'panel-listo-qa' });
setInterval(actualizar, 4000);
