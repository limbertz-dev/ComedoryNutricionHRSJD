const abrir = document.querySelector('#qa-abrir');
const modal = document.querySelector('#qa-modal');
const cerrar = document.querySelector('#qa-cerrar');
const marco = document.querySelector('#qa-marco');
let restaurarFoco = true;
let leyendo = false;
const CLAVE_LECTURA = 'qa_relectura_pendiente';

/** @returns {object | null} */
function lecturaPendiente() {
  try { return JSON.parse(sessionStorage.getItem(CLAVE_LECTURA)); } catch { return null; }
}

/** @param {object} datos @returns {void} */
function notificar(datos) {
  marco.contentWindow?.postMessage(datos, 'http://127.0.0.1:8002');
}

/** Reenvía la misma solicitud tras una respuesta incierta; nunca repite a ciegas.
 * @param {object} datos @returns {Promise<void>} */
async function leerDeNuevo(datos) {
  if (leyendo) return;
  leyendo = true;
  try {
    let sesion;
    try { sesion = JSON.parse(sessionStorage.getItem('comedor_sesion')); } catch { /* Sin sesión válida. */ }
    if (!sesion?.access) {
      notificar({ tipo: 'resultado-lectura-caso-qa', incierto: Boolean(lecturaPendiente()), error: 'Inicia sesión como cocinera antes de leer la huella.' });
      return;
    }
    const pendiente = lecturaPendiente();
    if (pendiente && (pendiente.referencia !== datos.referencia || pendiente.usuario !== sesion.usuario)) {
      notificar({ tipo: 'resultado-lectura-caso-qa', incierto: true, error: 'Verifica el intento anterior con la misma cuenta y persona.' });
      return;
    }
    const intento = pendiente || { solicitud: crypto.randomUUID(), referencia: datos.referencia, usuario: sesion.usuario };
    sessionStorage.setItem(CLAVE_LECTURA, JSON.stringify(intento));
    try {
      const res = await fetch('http://127.0.0.1:8001/_qa/enrolamiento/lecturas', {
        method: 'POST', headers: { Authorization: `Bearer ${sesion.access}`, 'Content-Type': 'application/json', 'Idempotency-Key': intento.solicitud },
        body: JSON.stringify({ referencia: intento.referencia }), signal: AbortSignal.timeout(15000),
      });
      if (res.status >= 500 || res.status === 408) throw new Error('incierto');
      if (!res.ok) {
        if (!pendiente) sessionStorage.removeItem(CLAVE_LECTURA);
        notificar({ tipo: 'resultado-lectura-caso-qa', incierto: Boolean(pendiente), error: res.status === 401
          ? 'La sesión expiró. Vuelve a iniciar sesión para leer.' : 'La lectura no pudo ejecutarse. Revisa tu sesión de cocinera y el ensayo.' });
        return;
      }
      const resultado = await res.json();
      if (resultado.usuario_id !== 900101 || typeof resultado.valido !== 'boolean'
          || !Number.isSafeInteger(resultado.lectura_id) || resultado.lectura_id <= 0) throw new Error('incierto');
      sessionStorage.removeItem(CLAVE_LECTURA);
      notificar({ tipo: 'resultado-lectura-caso-qa', registrada: resultado.valido, duplicado: resultado.motivo === 'duplicado' });
    } catch {
      notificar({ tipo: 'resultado-lectura-caso-qa', incierto: true });
    }
  } finally { leyendo = false; }
}

/** @returns {void} */
function abrirLaboratorio() {
  if (!marco.getAttribute('src')) marco.src = 'http://127.0.0.1:8002';
  if (!modal.open) modal.showModal();
  cerrar.focus();
  marco.contentWindow?.postMessage({ tipo: 'actualizar-laboratorio-qa' }, 'http://127.0.0.1:8002');
  if (lecturaPendiente()) notificar({ tipo: 'resultado-lectura-caso-qa', incierto: true });
}

abrir.addEventListener('click', abrirLaboratorio);
marco.addEventListener('load', () => {
  notificar({ tipo: 'actualizar-laboratorio-qa' });
  if (lecturaPendiente()) notificar({ tipo: 'resultado-lectura-caso-qa', incierto: true });
});
window.addEventListener('qa:volver-simulador', abrirLaboratorio);
cerrar.addEventListener('click', () => modal.close());
modal.addEventListener('close', () => {
  if (restaurarFoco) abrir.focus();
  restaurarFoco = true;
});
window.addEventListener('message', evento => {
  if (evento.origin !== 'http://127.0.0.1:8002' || evento.source !== marco.contentWindow) return;
  if (evento.data?.tipo === 'panel-listo-qa' && lecturaPendiente()) notificar({ tipo: 'resultado-lectura-caso-qa', incierto: true });
  if (evento.data?.tipo === 'leer-huella-caso-qa' && modal.open) {
    const datos = evento.data;
    if (datos.caso !== 'qa01' || datos.usuario_id !== 900101
        || !/^SIM-HUELLA-[0-9a-f-]{36}$/.test(datos.referencia)) return;
    leerDeNuevo(datos);
  }
  if (evento.data?.tipo === 'cerrar-laboratorio-qa' && modal.open) modal.close();
  if (evento.data?.tipo === 'registrar-huella-caso-qa' && modal.open) {
    const { caso, usuario_id: usuarioId } = evento.data;
    if (!['qa01', 'qa02'].includes(caso) || { qa01: 900101, qa02: 900102 }[caso] !== usuarioId) return;
    const atendido = !window.dispatchEvent(new CustomEvent('qa:registrar-huella', {
      detail: { caso, usuarioId }, cancelable: true,
    }));
    if (atendido) { restaurarFoco = false; modal.close(); }
    else marco.contentWindow.postMessage({ tipo: 'registro-huella-no-disponible-qa' }, evento.origin);
  }
});
