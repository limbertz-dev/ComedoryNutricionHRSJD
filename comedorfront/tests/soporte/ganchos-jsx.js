import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { transformWithEsbuild } from 'vite';

export async function load(url, context, siguiente) {
  if (url.startsWith('file:') && url.endsWith('.css')) {
    return { format: 'module', source: '', shortCircuit: true };
  }
  if (url.startsWith('file:') && url.endsWith('.jsx')) {
    const ruta = fileURLToPath(url);
    const { code } = await transformWithEsbuild(await readFile(ruta, 'utf8'), ruta, {
      loader: 'jsx',
      jsx: 'automatic',
    });
    return { format: 'module', source: code, shortCircuit: true };
  }
  return siguiente(url, context);
}
