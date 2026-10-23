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
import { guardarSeccionActiva } from '../navegacion.js';

const ContextoSesion = createContext(null);

/*
 * Un ingreso nuevo de la cocinera empieza siempre en el checklist; F5 (que
 * restaura la sesión sin pasar por aquí) conserva su última pantalla.
 */
export function prepararIngreso(resultado) {
  if (resultado?.tipo === 'ok' && resultado.rol === 'cocinera') guardarSeccionActiva('checklist');
}

/**
 * Acción con la que arranca la app: sin tokens guardados, al Login; con
 * tokens, GET /auth/yo decide el rol (un 401 token_expirado ya se reintentó
 * con refresh dentro de `api.js`). Un 401 vació los tokens y se ve como
 * «Sesión expirada»; un 428 o un 403 cambio_password_pendiente, como cambio.
 */
export async function restaurarSesion({ signal } = {}) {
  const tokens = leerTokens();
  if (!tokens) return { tipo: 'SIN_SESION' };
  try {
    const yo = await obtenerUsuarioActual({ signal });
    const usuario = yo.username ?? tokens.usuario;
    if (yo.debeCambiar) return { tipo: 'CAMBIO_REQUERIDO', usuario };
    return { tipo: 'INGRESO', rol: yo.rol, usuario };
  } catch (error) {
    if (error.status === 401) return { tipo: 'EXPIRADA' };
    if (error.status === 428) return { tipo: 'CAMBIO_REQUERIDO', usuario: tokens.usuario };
    if (error.status === 403 && error.datos?.motivo === 'cambio_password_pendiente') {
      return { tipo: 'CAMBIO_REQUERIDO', usuario: tokens.usuario };
    }
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
    prepararIngreso(resultado);
    const accion = accionDeIngreso(resultado, usuario);
    if (accion) despachar(accion);
    return resultado;
  }, []);

  const cambiarPassword = useCallback(async ({ usuario, actual, nueva }) => {
    const resultado = await cambiarContrasena({ usuario, actual, nueva });
    prepararIngreso(resultado);
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
