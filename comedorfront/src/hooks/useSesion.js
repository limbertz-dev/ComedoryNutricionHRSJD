import { createContext, createElement, useCallback, useContext, useEffect, useMemo, useReducer } from 'react';
import { cambiarContrasena, iniciarSesion, obtenerUsuarioActual } from '../api.js';
import {
  SESION_INICIAL,
  accionDeAviso,
  accionDeIngreso,
  borrarTokens,
  escucharSesion,
  leerTokens,
  reductorSesion,
} from '../sesion.js';

const ContextoSesion = createContext(null);

/**
 * Acción con la que arranca la app: sin tokens guardados, al Login; con
 * tokens, GET /auth/yo decide el rol. Un 401 ya vació los tokens en
 * `api.js` y se ve como «Sesión expirada»; un 428, como cambio obligatorio.
 */
export async function restaurarSesion({ signal } = {}) {
  const tokens = leerTokens();
  if (!tokens) return { tipo: 'SIN_SESION' };
  try {
    const { rol } = await obtenerUsuarioActual({ signal });
    return { tipo: 'INGRESO', rol, usuario: tokens.usuario };
  } catch (error) {
    if (error.status === 401) return { tipo: 'EXPIRADA' };
    if (error.status === 428) return { tipo: 'CAMBIO_REQUERIDO', usuario: tokens.usuario };
    return { tipo: 'SIN_CONEXION' };
  }
}

/** Envuelve la app: una sola sesión compartida por App, Login y Sidebar. */
export function ProveedorSesion({ children }) {
  const [estado, despachar] = useReducer(reductorSesion, SESION_INICIAL);

  useEffect(() => escucharSesion((aviso) => {
    const accion = accionDeAviso(aviso);
    if (accion) despachar(accion);
  }), []);

  useEffect(() => {
    const controlador = new AbortController();
    restaurarSesion({ signal: controlador.signal }).then((accion) => {
      if (!controlador.signal.aborted) despachar(accion);
    });
    return () => controlador.abort();
  }, []);

  /** Devuelve el resultado de `iniciarSesion` para que el Login pinte 401 / 423. */
  const login = useCallback(async (usuario, contrasena) => {
    const resultado = await iniciarSesion(usuario, contrasena);
    const accion = accionDeIngreso(resultado, usuario);
    if (accion) despachar(accion);
    return resultado;
  }, []);

  const cambiarPassword = useCallback(async ({ usuario, actual, nueva }) => {
    const resultado = await cambiarContrasena({ usuario, actual, nueva });
    const accion = accionDeIngreso(resultado, usuario);
    if (accion) despachar(accion);
    return resultado;
  }, []);

  /* El contrato no trae endpoint de salida: basta con olvidar los tokens. */
  const logout = useCallback(() => {
    borrarTokens();
    despachar({ tipo: 'SIN_SESION' });
  }, []);

  const valor = useMemo(
    () => ({ ...estado, login, cambiarPassword, logout }),
    [estado, login, cambiarPassword, logout],
  );
  return createElement(ContextoSesion.Provider, { value: valor }, children);
}

/** `{ fase, rol, usuario, aviso, login(), cambiarPassword(), logout() }` */
export default function useSesion() {
  const sesion = useContext(ContextoSesion);
  if (!sesion) throw new Error('useSesion se usa dentro de <ProveedorSesion>.');
  return sesion;
}
