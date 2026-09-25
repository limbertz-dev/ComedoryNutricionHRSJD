/*
 * Deja que `node --test` importe componentes .jsx para renderizarlos con
 * react-dom/server: transpila JSX con el esbuild que ya trae Vite y convierte
 * cada import de .css en un módulo vacío. Se carga con --import desde el
 * script "test" de package.json; no cambia nada de la app.
 */
import { register } from 'node:module';

register('./ganchos-jsx.js', import.meta.url);
