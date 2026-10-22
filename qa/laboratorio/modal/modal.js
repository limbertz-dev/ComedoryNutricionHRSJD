/* Botón y modal del laboratorio QA. Lo inyecta qa/laboratorio/front.mjs solo
   cuando el front se arranca desde el laboratorio: no existe en comedorfront/src. */

const PANEL = `${window.__LAB_API__}/_lab`;

const boton = document.createElement('button');
boton.type = 'button';
boton.className = 'lab-qa-boton';
boton.title = 'Laboratorio QA (Ctrl+Shift+L)';
boton.setAttribute('aria-haspopup', 'dialog');
boton.innerHTML = '<span aria-hidden="true">⚗</span> Laboratorio QA';

const modal = document.createElement('dialog');
modal.className = 'lab-qa-modal';
modal.setAttribute('aria-labelledby', 'lab-qa-titulo');
modal.innerHTML = `
  <header class="lab-qa-modal__cabecera">
    <div>
      <h2 id="lab-qa-titulo">Laboratorio QA</h2>
      <p>Simula el lector biométrico. Los resultados aparecen en la app en unos segundos.</p>
    </div>
    <button type="button" class="lab-qa-modal__cerrar" aria-label="Cerrar laboratorio">✕</button>
  </header>
  <iframe class="lab-qa-modal__marco" title="Controles del laboratorio QA"></iframe>`;

const marco = modal.querySelector('iframe');
const cerrar = modal.querySelector('.lab-qa-modal__cerrar');

function abrir() {
  if (!marco.getAttribute('src')) marco.src = PANEL;
  if (!modal.open) modal.showModal();
}

boton.addEventListener('click', abrir);
cerrar.addEventListener('click', () => modal.close());
// Clic en el fondo oscuro (fuera del contenido) cierra.
modal.addEventListener('click', (evento) => { if (evento.target === modal) modal.close(); });
modal.addEventListener('close', () => boton.focus());
document.addEventListener('keydown', (evento) => {
  if (evento.ctrlKey && evento.shiftKey && evento.key.toLowerCase() === 'l') {
    evento.preventDefault();
    if (modal.open) modal.close(); else abrir();
  }
});

document.body.append(boton, modal);
