/** Vigilancia exclusiva de QA: no depende de React ni borra la sesión. */
const raiz = document.querySelector('#root');
const aviso = document.querySelector('#qa-arranque');
const boton = document.querySelector('#qa-abrir');
let temporizador;

/** @returns {boolean} */
function comprobarArranque() {
  const lista = Boolean(raiz?.childElementCount);
  aviso.hidden = lista;
  boton.hidden = !lista;
  if (lista) clearTimeout(temporizador);
  return lista;
}

/** @returns {void} */
function falloArranque() {
  if (comprobarArranque()) return;
  aviso.setAttribute('role', 'alert');
  document.querySelector('#qa-arranque-giro').hidden = true;
  document.querySelector('#qa-arranque-titulo').textContent = 'No se pudo cargar la aplicación';
  document.querySelector('#qa-arranque-detalle').hidden = false;
  document.querySelector('#qa-recargar').hidden = false;
  document.querySelector('#qa-arranque-detalle').textContent = 'Falló la carga del frontend. Pulsa «Volver a cargar». El ensayo, las huellas y las contraseñas se conservan.';
}

if (raiz) new MutationObserver(comprobarArranque).observe(raiz, { childList: true });
window.addEventListener('error', falloArranque, true);
window.addEventListener('unhandledrejection', falloArranque);
document.querySelector('#qa-recargar').href = `/?qa_recargar=${Date.now()}`;
if (!comprobarArranque()) temporizador = setTimeout(falloArranque, 12000);
