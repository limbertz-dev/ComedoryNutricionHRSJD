/*
 * URL de la API. Por omisión, la de siempre (http://127.0.0.1:8000); se
 * cambia por entorno con VITE_API_URL, por ejemplo para apuntar el front al
 * backend de simulación, que corre en otro puerto:
 *
 *   VITE_API_URL=http://127.0.0.1:8001 npm run dev
 *
 * Vite reemplaza `import.meta.env` al compilar; en node (tests) no existe y
 * queda el valor por omisión.
 */
export const API_BASE_URL_POR_OMISION = 'http://127.0.0.1:8000';

/** URL base a partir de las variables de entorno; vacía o ausente, la de siempre. */
export function resolverApiBaseUrl(env) {
  const configurada = typeof env?.VITE_API_URL === 'string' ? env.VITE_API_URL.trim() : '';
  return configurada ? configurada.replace(/\/+$/, '') : API_BASE_URL_POR_OMISION;
}

export const API_BASE_URL = resolverApiBaseUrl(import.meta.env);
