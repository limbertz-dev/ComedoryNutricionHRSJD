/* Panel del laboratorio QA. Solo habla con /_lab/api del mismo proceso que la API. */

const $ = (selector) => document.querySelector(selector);

const MOTIVOS = {
  sin_derecho: 'Sin derecho',
  duplicado: 'Duplicado',
  fuera_horario: 'Fuera de horario',
  no_identificado: 'Huella no reconocida',
};

const estado = {
  servidor: null,       // última respuesta de /estado
  recibido: 0,          // performance.now() al recibirla
  filtro: 'con_derecho',
  ocupado: false,
};

/* --- utilidades --- */

async function api(ruta, opciones = {}) {
  const respuesta = await fetch(`/_lab/api${ruta}`, {
    ...opciones,
    headers: { 'Content-Type': 'application/json', ...(opciones.headers ?? {}) },
  });
  let cuerpo = null;
  try { cuerpo = await respuesta.json(); } catch { /* sin cuerpo */ }
  if (!respuesta.ok) {
    const detalle = typeof cuerpo?.detail === 'string' ? cuerpo.detail : `Error ${respuesta.status}`;
    throw new Error(detalle);
  }
  return cuerpo;
}

const post = (ruta, datos) => api(ruta, { method: 'POST', body: JSON.stringify(datos ?? {}) });

function el(etiqueta, atributos = {}, ...hijos) {
  const nodo = document.createElement(etiqueta);
  for (const [clave, valor] of Object.entries(atributos)) {
    if (valor === null || valor === undefined || valor === false) continue;
    if (clave === 'class') nodo.className = valor;
    else if (clave.startsWith('on')) nodo.addEventListener(clave.slice(2), valor);
    else nodo.setAttribute(clave, valor === true ? '' : valor);
  }
  for (const hijo of hijos.flat()) {
    if (hijo === null || hijo === undefined || hijo === false) continue;
    nodo.append(hijo instanceof Node ? hijo : document.createTextNode(String(hijo)));
  }
  return nodo;
}

function avisar(texto, error = false) {
  const aviso = el('div', { class: `aviso${error ? ' aviso--error' : ''}`, role: error ? 'alert' : 'status' }, texto);
  $('#avisos').append(aviso);
  setTimeout(() => aviso.remove(), error ? 7000 : 4000);
}

const dosDigitos = (n) => String(n).padStart(2, '0');
const horaDe = (fecha) => `${dosDigitos(fecha.getHours())}:${dosDigitos(fecha.getMinutes())}:${dosDigitos(fecha.getSeconds())}`;
const isoLocal = (fecha) => `${fecha.getFullYear()}-${dosDigitos(fecha.getMonth() + 1)}-${dosDigitos(fecha.getDate())}T${horaDe(fecha)}`;
const FECHA_LARGA = new Intl.DateTimeFormat('es-BO', { weekday: 'long', day: '2-digit', month: 'long', year: 'numeric' });
const FECHA_CORTA = new Intl.DateTimeFormat('es-BO', { weekday: 'short', day: '2-digit', month: '2-digit' });
const fechaLocal = (iso) => new Date(`${iso.slice(0, 10)}T12:00:00`);

/** Hora del laboratorio ahora mismo, sin esperar al servidor. */
function horaLab() {
  const s = estado.servidor;
  if (!s) return null;
  const base = new Date(s.reloj.momento);
  if (s.reloj.modo === 'pausado') return base;
  return new Date(base.getTime() + (performance.now() - estado.recibido));
}

function resultadoDe(paso) {
  if (paso.valido) return { clase: 't-lima', texto: 'Aceptada', tono: 'ok' };
  if (paso.motivo === 'no_identificado') return { clase: 't-magenta', texto: 'Huella no reconocida', tono: 'desconocida' };
  return { clase: 't-rojo', texto: `Rechazada · ${MOTIVOS[paso.motivo] ?? paso.motivo ?? 'sin motivo'}`, tono: 'mal' };
}

async function conBloqueo(accion) {
  if (estado.ocupado) return;
  estado.ocupado = true;
  document.querySelectorAll('.escenario, #no-reconocida').forEach((b) => { b.disabled = true; });
  try {
    await accion();
  } catch (error) {
    avisar(error.message, true);
  } finally {
    estado.ocupado = false;
    document.querySelectorAll('.escenario, #no-reconocida').forEach((b) => { b.disabled = false; });
  }
}

/* --- estado y reloj --- */

function pintarEstado() {
  const s = estado.servidor;
  $('#base-propia').textContent = s.base.propia;
  $('#base-turnos').textContent = s.base.turnos;

  const conexion = $('#conexion');
  conexion.querySelector('.punto').className = 'punto punto--ok';
  conexion.querySelector('span').textContent = 'API en línea';

  document.querySelectorAll('#modos button').forEach((b) => {
    b.setAttribute('aria-checked', String(b.dataset.modo === s.reloj.modo));
  });
  $('.reloj').dataset.modo = s.reloj.modo;

  const servicio = $('#servicio');
  const { comida, vigente, fecha_comida: fechaComida } = s.servicio;
  servicio.className = `servicio ${vigente ? 'servicio--en-curso' : 'servicio--fuera'}`;
  servicio.querySelector('.punto').className = `punto ${vigente ? 'punto--ok' : 'punto--aviso'}`;
  servicio.querySelector('span').textContent = vigente
    ? `${comida} · en curso · ${fechaComida.split('-').reverse().join('/')}`
    : comida ? `Fuera de horario · último: ${comida}` : 'Fuera de horario';

  const comidas = $('#comidas');
  comidas.replaceChildren(
    ...s.horarios.map((h) => el('button', {
      type: 'button', class: 'comida', 'data-estado': h.estado,
      title: `Mover el reloj a ${h.sugerida.slice(11, 16)}`,
      onclick: () => moverReloj(h.sugerida),
    }, el('strong', {}, h.comida), el('small', {}, `${h.inicio}–${h.fin}`))),
    el('button', {
      type: 'button', class: 'comida comida--madrugada', title: 'Fuera de horario',
      onclick: () => moverReloj(`${s.reloj.momento.slice(0, 10)}T03:00:00`),
    }, el('strong', {}, 'Madrugada'), el('small', {}, '03:00 · sin servicio')),
  );

  $('#contadores').replaceChildren(
    'Con derecho ', el('b', {}, s.servicio.con_derecho),
    ' · pendientes ', el('b', {}, s.servicio.pendientes),
    ' · lecturas lab ', el('b', {}, s.laboratorio.lecturas),
    ' · entregas lab ', el('b', {}, s.laboratorio.entregas),
  );

  const fechaActual = s.reloj.momento.slice(0, 10);
  document.querySelectorAll('.fecha').forEach((b) => {
    if (b.dataset.fecha === fechaActual) b.setAttribute('aria-current', 'date');
    else b.removeAttribute('aria-current');
  });

  const formulario = $('#form-reloj');
  if (!formulario.contains(document.activeElement)) {
    $('#in-fecha').value = fechaActual;
    $('#in-hora').value = s.reloj.momento.slice(11, 19);
  }
}

function tic() {
  const ahora = horaLab();
  if (!ahora) return;
  $('#hora').textContent = horaDe(ahora);
  $('#fecha').textContent = FECHA_LARGA.format(ahora);
}

async function cargarEstado() {
  try {
    estado.servidor = await api('/estado');
    estado.recibido = performance.now();
    pintarEstado();
    tic();
  } catch (error) {
    const conexion = $('#conexion');
    conexion.querySelector('.punto').className = 'punto punto--mal';
    conexion.querySelector('span').textContent = 'Sin conexión';
  }
}

async function moverReloj(momento, modo) {
  const actual = estado.servidor?.reloj.modo ?? 'pausado';
  const destino = modo ?? (actual === 'real' ? 'pausado' : actual);
  try {
    estado.servidor = await post('/reloj', { momento, modo: destino });
    estado.recibido = performance.now();
    pintarEstado();
    tic();
    await Promise.all([cargarPersonas(), cargarFechas()]);
  } catch (error) {
    avisar(error.message, true);
  }
}

async function cargarFechas() {
  try {
    const fechas = await api('/fechas');
    const lista = $('#fechas');
    if (fechas.length === 0) {
      lista.replaceChildren(el('span', { class: 'tenue' }, 'Ningún día tiene turnos con comidas en esta base.'));
      return;
    }
    const actual = estado.servidor?.reloj.momento.slice(0, 10);
    lista.replaceChildren(...fechas.map((f) => {
      const personas = Math.max(...f.comidas.map((c) => c.personas));
      const hora = estado.servidor?.reloj.momento.slice(11, 19) ?? '12:00:00';
      return el('button', {
        type: 'button', class: 'fecha', 'data-fecha': f.fecha,
        'aria-current': f.fecha === actual ? 'date' : null,
        title: f.comidas.map((c) => `${c.comida}: ${c.personas}`).join(' · '),
        onclick: () => moverReloj(`${f.fecha}T${hora}`),
      }, FECHA_CORTA.format(fechaLocal(f.fecha)), ' ', el('b', {}, personas));
    }));
  } catch (error) {
    $('#fechas').replaceChildren(el('span', { class: 'tenue' }, error.message));
  }
}

/* --- padrón --- */

let temporizadorBusqueda = null;
let consultaPersonas = 0;

async function cargarPersonas() {
  const numero = ++consultaPersonas;
  const q = $('#buscar').value.trim();
  try {
    const datos = await api(`/personas?${new URLSearchParams({ q, filtro: estado.filtro, limite: '60' })}`);
    if (numero !== consultaPersonas) return;
    $('#total-personas').textContent = `${datos.personas.length} de ${datos.total}`;
    const lista = $('#personas');
    if (datos.personas.length === 0) {
      lista.replaceChildren(el('li', { class: 'tenue' },
        estado.filtro === 'con_derecho'
          ? 'Nadie tiene derecho a esta comida en esta fecha. Prueba un día con turnos.'
          : 'Sin resultados.'));
      return;
    }
    lista.replaceChildren(...datos.personas.map((p) => el('li', { class: 'persona' },
      el('div', {},
        el('p', { class: 'persona__nombre' }, p.nombre),
        el('p', { class: 'persona__meta' },
          `#${p.id} · ${p.legajo} · ${p.categoria}`,
          p.tiene_derecho ? el('span', { class: 'etiqueta t-lima' }, 'Derecho') : el('span', { class: 'etiqueta t-rojo' }, 'Sin derecho'),
          p.ya_comio ? el('span', { class: 'etiqueta t-ambar' }, 'Ya comió') : null,
          p.perfil_permitido ? null : el('span', { class: 'etiqueta t-gris' }, 'Perfil excluido'),
        ),
      ),
      el('button', {
        type: 'button', class: 'boton boton--sm', title: 'El lector reconoce a esta persona',
        onclick: () => conBloqueo(async () => {
          const paso = await post('/lectura', { usuario_id: p.id });
          mostrarPasos([paso], null);
          await refrescar();
        }),
      }, 'Marcar huella'),
    )));
  } catch (error) {
    if (numero === consultaPersonas) $('#personas').replaceChildren(el('li', { class: 't-rojo' }, error.message));
  }
}

/* --- lector y actividad --- */

function mostrarPasos(pasos, siguiente) {
  $('#ultimo').replaceChildren(
    ...pasos.map((paso) => {
      const r = resultadoDe(paso);
      return el('div', { class: 'paso' },
        el('span', { class: `etiqueta ${r.clase}` }, r.texto),
        el('strong', {}, paso.nombre ?? 'Sin identificar'),
        el('span', { class: 'tenue' },
          [paso.comida, paso.lectura_id ? `lectura #${paso.lectura_id}` : null].filter(Boolean).join(' · ')),
      );
    }),
    siguiente ? el('p', { class: 'siguiente' }, '→ ', siguiente) : null,
  );
}

async function cargarActividad() {
  try {
    const lecturas = await api('/actividad?limite=40');
    const lista = $('#actividad');
    if (lecturas.length === 0) {
      lista.replaceChildren(el('li', { class: 'tenue' }, 'Sin lecturas del laboratorio.'));
      return;
    }
    lista.replaceChildren(...lecturas.map((l) => {
      let etiqueta;
      let tono;
      if (l.entrega?.por_cocina) {
        etiqueta = el('span', { class: 'etiqueta t-lima' }, 'Entregada por cocina');
        tono = 'ok';
      } else {
        const r = resultadoDe({ valido: l.resultado === 'aceptada', motivo: l.motivo });
        etiqueta = el('span', { class: `etiqueta ${r.clase}` }, r.texto);
        tono = r.tono;
      }
      const nombre = l.nombre ?? (l.entrega?.nombre ? `${l.entrega.nombre}` : 'Sin identificar');
      return el('li', { class: `lectura lectura--${tono}` },
        el('span', { class: 'lectura__hora' }, l.hora.slice(11, 19)),
        el('div', {},
          el('p', { class: 'lectura__nombre' }, nombre),
          el('p', { class: 'lectura__detalle' }, `#${l.id} · ${l.hora.slice(0, 10).split('-').reverse().join('/')}`),
        ),
        etiqueta,
      );
    }));
  } catch {
    /* el indicador de conexión ya avisa */
  }
}

async function refrescar() {
  await Promise.all([cargarEstado(), cargarActividad(), cargarPersonas()]);
}

/* --- cuentas --- */

async function cargarCuentas() {
  try {
    const cuentas = await api('/cuentas');
    $('#cuentas').replaceChildren(el('table', {},
      el('thead', {}, el('tr', {}, el('th', {}, 'Usuario'), el('th', {}, 'Rol'), el('th', {}, 'Estado'), el('th', {}, ''))),
      el('tbody', {}, ...cuentas.map((c) => el('tr', {},
        el('td', {}, el('strong', {}, c.usuario)),
        el('td', {}, c.rol),
        el('td', {},
          !c.activa ? el('span', { class: 'etiqueta t-gris' }, 'Inactiva')
            : c.bloqueada_hasta ? el('span', { class: 'etiqueta t-rojo' }, `Bloqueada hasta ${c.bloqueada_hasta.slice(11, 16)}`)
              : c.debe_cambiar ? el('span', { class: 'etiqueta t-ambar' }, 'Clave temporal')
                : el('span', { class: 'etiqueta t-lima' }, 'Lista')),
        el('td', {}, el('button', {
          type: 'button', class: 'boton boton--sm boton--fantasma',
          onclick: () => claveTemporal(c.usuario),
        }, 'Clave temporal')),
      ))),
    ));
  } catch (error) {
    $('#cuentas').replaceChildren(el('p', { class: 't-rojo' }, error.message));
  }
}

async function claveTemporal(usuario) {
  if (!confirm(`¿Generar una clave temporal para «${usuario}»? La clave actual deja de servir y se quita el bloqueo.`)) return;
  try {
    const { clave_temporal: clave } = await post(`/cuentas/${encodeURIComponent(usuario)}/clave-temporal`);
    const caja = $('#clave');
    caja.hidden = false;
    caja.replaceChildren(
      el('p', {}, 'Clave temporal de ', el('strong', {}, usuario), ' (se muestra una sola vez):'),
      el('code', {}, clave),
      el('button', {
        type: 'button', class: 'boton boton--sm',
        onclick: async () => { await navigator.clipboard?.writeText(clave); avisar('Clave copiada.'); },
      }, 'Copiar'),
      el('p', { class: 'tenue' }, 'Al entrar con ella, la app pedirá elegir una contraseña definitiva.'),
    );
    await cargarCuentas();
  } catch (error) {
    avisar(error.message, true);
  }
}

/* --- eventos --- */

document.querySelectorAll('#modos button').forEach((boton) => {
  boton.addEventListener('click', () => {
    const modo = boton.dataset.modo;
    const momento = modo === 'real' ? null : isoLocal(horaLab() ?? new Date());
    moverReloj(momento, modo);
  });
});

$('#form-reloj').addEventListener('submit', (evento) => {
  evento.preventDefault();
  const hora = $('#in-hora').value.length === 5 ? `${$('#in-hora').value}:00` : $('#in-hora').value;
  moverReloj(`${$('#in-fecha').value}T${hora}`);
});

document.querySelectorAll('[data-escenario]').forEach((boton) => {
  boton.addEventListener('click', () => conBloqueo(async () => {
    const { pasos, siguiente } = await post('/escenario', { tipo: boton.dataset.escenario });
    mostrarPasos(pasos, siguiente);
    await Promise.all([refrescar(), cargarFechas()]);
  }));
});

$('#no-reconocida').addEventListener('click', () => conBloqueo(async () => {
  const paso = await post('/lectura', { usuario_id: null });
  mostrarPasos([paso], 'En Control Biométrico (cocinera), abre la lectura e identifica a la persona.');
  await refrescar();
}));

$('#limpiar').addEventListener('click', async () => {
  const lecturas = estado.servidor?.laboratorio.lecturas ?? 0;
  if (!confirm(`¿Borrar las ${lecturas} lecturas del laboratorio con sus entregas e intervenciones? El resto de la base no se toca.`)) return;
  try {
    const r = await post('/limpiar', { confirmar: true });
    avisar(`Limpio: ${r.lecturas} lecturas, ${r.entregas} entregas, ${r.intervenciones} intervenciones.`);
    $('#ultimo').replaceChildren(el('p', { class: 'tenue' }, 'Laboratorio limpio. Elige un caso.'));
    await refrescar();
  } catch (error) {
    avisar(error.message, true);
  }
});

document.querySelectorAll('#filtros button').forEach((boton) => {
  boton.addEventListener('click', () => {
    estado.filtro = boton.dataset.filtro;
    document.querySelectorAll('#filtros button').forEach((b) => b.setAttribute('aria-checked', String(b === boton)));
    cargarPersonas();
  });
});

$('#buscar').addEventListener('input', () => {
  clearTimeout(temporizadorBusqueda);
  temporizadorBusqueda = setTimeout(cargarPersonas, 250);
});

$('#seccion-cuentas').addEventListener('toggle', (evento) => {
  if (evento.target.open) cargarCuentas();
});

/* --- arranque --- */

await cargarEstado();
await Promise.all([cargarFechas(), cargarPersonas(), cargarActividad()]);
setInterval(tic, 250);
setInterval(cargarEstado, 5000);
setInterval(cargarActividad, 3000);
