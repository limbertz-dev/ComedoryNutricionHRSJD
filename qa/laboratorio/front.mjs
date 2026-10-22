/* El front de siempre (comedorfront, su vite.config.js) más el botón y el modal
   del laboratorio. Nada de esto se copia a comedorfront: se inyecta al servir.

     node qa/laboratorio/front.mjs [puertoApi]
*/
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const FRONT = fileURLToPath(new URL('../../comedorfront/', import.meta.url));
const MODAL = fileURLToPath(new URL('./modal/', import.meta.url));
const API = `http://127.0.0.1:${process.argv[2] ?? '8000'}`;

// Vite se resuelve desde comedorfront: este archivo no tiene node_modules propio.
const { createServer } = await import(pathToFileURL(join(FRONT, 'node_modules/vite/dist/node/index.js')).href);

/** @returns {import('vite').Plugin} */
function modalLaboratorio() {
  const archivos = { '/__lab/modal.js': 'text/javascript', '/__lab/modal.css': 'text/css' };
  return {
    name: 'modal-laboratorio-qa',
    configureServer(servidor) {
      servidor.middlewares.use(async (peticion, respuesta, siguiente) => {
        const tipo = archivos[peticion.url];
        if (!tipo) { siguiente(); return; }
        try {
          const contenido = await readFile(join(MODAL, peticion.url.slice('/__lab/'.length)));
          respuesta.setHeader('Content-Type', `${tipo}; charset=utf-8`);
          respuesta.setHeader('Cache-Control', 'no-store');
          respuesta.end(contenido);
        } catch (error) { siguiente(error); }
      });
    },
    transformIndexHtml() {
      return [
        { tag: 'link', attrs: { rel: 'stylesheet', href: '/__lab/modal.css' }, injectTo: 'head' },
        { tag: 'script', children: `window.__LAB_API__ = ${JSON.stringify(API)};`, injectTo: 'body' },
        { tag: 'script', attrs: { type: 'module', src: '/__lab/modal.js' }, injectTo: 'body' },
      ];
    },
  };
}

process.env.VITE_API_URL = API;
const servidor = await createServer({
  root: FRONT,
  configFile: join(FRONT, 'vite.config.js'),
  plugins: [modalLaboratorio()],
  server: { port: 5173, strictPort: true },
});
await servidor.listen();
console.log('\n  FRONT + LABORATORIO QA');
console.log(`  App : http://localhost:5173   (botón «Laboratorio QA» abajo a la izquierda)`);
console.log(`  API : ${API}\n`);
