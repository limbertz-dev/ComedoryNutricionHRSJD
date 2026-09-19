import { useCallback, useEffect, useRef, useState } from 'react';

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
   */
  const recargar = useCallback(async (opciones) => {
    const conservar = opciones?.conservar === true;
    pendiente.current?.abort();
    const controlador = new AbortController();
    pendiente.current = controlador;
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
