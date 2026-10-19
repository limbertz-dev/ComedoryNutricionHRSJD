import { execFileSync } from 'node:child_process';
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
    plugins: [react()],
    cacheDir: fileURLToPath(new URL('../../qa/prueba-basica/evidencias/vite', import.meta.url)),
    server: { host: '127.0.0.1', port: 5173, strictPort: true, open: false },
  });

  await server.listen();
  console.log(`Frontend QA: ${root}`);
  console.log(`API QA: ${process.env.VITE_API_URL}`);
  server.printUrls();
}

await iniciarQa();
