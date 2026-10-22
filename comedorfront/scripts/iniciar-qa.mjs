import { execFileSync } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import { createServer } from 'vite';

/** @returns {Promise<void>} */
async function iniciarQa() {
  const root = fileURLToPath(new URL('../', import.meta.url));
  const rama = execFileSync('git', ['-C', root, 'branch', '--show-current'], {
    encoding: 'utf8',
  }).trim();

  if (rama !== 'qa') {
    throw new Error('El frontend de pruebas requiere la rama qa.');
  }

  process.env.VITE_API_URL = 'http://127.0.0.1:8001';
  const server = await createServer({
    root,
    configFile: false,
    envFile: false,
    plugins: [react(), {
      name: 'enlace-laboratorio-qa',
      configureServer(servidor) {
        servidor.middlewares.use(async (peticion, respuesta, siguiente) => {
          const activos = { '/_qa/modal.js': 'modal.js', '/_qa/modal.css': 'modal.css', '/_qa/arranque.js': 'arranque.js',
            '/_qa/tokens.css': '../../../comedorfront/src/styles/tokens.css' };
          const archivo = activos[new URL(peticion.url, 'http://127.0.0.1:5173').pathname];
          if (!archivo) { siguiente(); return; }
          try {
            const contenido = await readFile(new URL(`../../qa/prueba-basica/laboratorio/${archivo}`, import.meta.url));
            respuesta.setHeader('Content-Type', archivo.endsWith('.js') ? 'text/javascript; charset=utf-8' : 'text/css; charset=utf-8');
            respuesta.setHeader('Cache-Control', 'no-store');
            respuesta.end(contenido);
          } catch (error) { siguiente(error); }
        });
      },
      transformIndexHtml() {
        return [
          { tag: 'link', attrs: { rel: 'stylesheet', href: '/_qa/tokens.css' }, injectTo: 'head' },
          { tag: 'link', attrs: { rel: 'stylesheet', href: '/_qa/modal.css' }, injectTo: 'head' },
          { tag: 'section', attrs: { id: 'qa-arranque', role: 'status', 'aria-live': 'polite' },
            children: '<span id="qa-arranque-giro" aria-hidden="true"></span><h1 id="qa-arranque-titulo">Cargando…</h1><p id="qa-arranque-detalle" hidden></p><a id="qa-recargar" href="/?qa_recargar=1" hidden>Volver a cargar</a><noscript><p>Activa JavaScript para abrir la aplicación.</p></noscript>', injectTo: 'body' },
          { tag: 'button', attrs: { id: 'qa-abrir', type: 'button', hidden: true }, children: 'Simular escenarios QA', injectTo: 'body' },
          {
            tag: 'dialog', attrs: { id: 'qa-modal', 'aria-labelledby': 'qa-modal-titulo' },
            children: '<header><h2 id="qa-modal-titulo">Simular escenarios QA</h2><button id="qa-cerrar" type="button">Cerrar</button></header><iframe id="qa-marco" title="Controles de simulación QA"></iframe>',
            injectTo: 'body',
          },
          { tag: 'script', attrs: { type: 'module', src: '/_qa/modal.js' }, injectTo: 'body' },
          { tag: 'script', attrs: { type: 'module', src: '/_qa/arranque.js', async: true }, injectTo: 'body' },
        ];
      },
    }],
    // El plugin de React excluye node_modules. La caché optimizada debe seguir
    // dentro de ese árbol para no volver a transformar React y ReactDOM.
    cacheDir: fileURLToPath(new URL('../node_modules/.vite-qa', import.meta.url)),
    server: { host: '127.0.0.1', port: 5173, strictPort: true, open: false,
      headers: { 'Cache-Control': 'no-store' } },
  });

  await server.listen();
  console.log(`Frontend QA: ${root}`);
  console.log(`API QA: ${process.env.VITE_API_URL}`);
  server.printUrls();
}

await iniciarQa();
