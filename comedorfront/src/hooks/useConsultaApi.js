import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Aborta `controlador` cuando se aborta `externa` (o ya, si ya lo estaba).
 * Sin una AbortSignal no hace nada: `recargar` también se usa como handler
 * de clic y recibe el evento.
 */
export function enlazarCancelacion(externa, controlador) {
  if (!(externa instanceof AbortSignal)) return;
  if (externa.aborted) controlador.abort();
  else externa.addEventListener('abort', () => controlador.abort(), { once: true });
}

/** Cancela consultas obsoletas al cambiar de período o salir de la sección. */
export default function useConsultaApi(consultar) {
  const [datos, setDatos] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');
  const pendiente = useRef(null);
  const origen = useRef(null);

  /**
   * `{ conservar: true }` repite la misma consulta sin vaciar lo que ya se
   * muestra: es el refresco que dispara una marcación, donde el cupo anterior
   * debe seguir en pantalla hasta que llegue el nuevo para que el gauge baje
   * con su transición en vez de saltar a "—" y volver. Sin la opción, cambiar
   * de período sigue limpiando los datos viejos antes de pedir los nuevos.
   *
   * `{ signal }` enlaza la consulta con la cancelación de quien la pide (por
   * ejemplo, el ciclo de cocina): si esa señal se aborta, esta consulta se
   * aborta y su respuesta tardía no se publica.
   */
  const recargar = useCallback(async (opciones) => {
    const conservar = opciones?.conservar === true;
    pendiente.current?.abort();
    const controlador = new AbortController();
    pendiente.current = controlador;
    enlazarCancelacion(opciones?.signal, controlador);
    origen.current = consultar;
    if (!conservar) {
      setCargando(true);
      setDatos(null);
    }
    setError('');
    try {
      const respuesta = await consultar(controlador.signal);
      if (!controlador.signal.aborted) setDatos(respuesta);
      return controlador.signal.aborted ? null : respuesta;
    } catch (fallo) {
      if (!controlador.signal.aborted) setError(fallo.message);
      return null;
    } finally {
      if (!controlador.signal.aborted && !conservar) setCargando(false);
    }
  }, [consultar]);

  useEffect(() => {
    recargar();
    return () => pendiente.current?.abort();
  }, [recargar]);

  // En el primer render de un período nuevo aún no corrió el efecto. Nunca
  // entregue filas diarias al render mensual, ni datos del período anterior.
  const corresponde = origen.current === consultar;
  return { datos: corresponde ? datos : null, cargando: !corresponde || cargando,
    error: corresponde ? error : '', recargar };
}
