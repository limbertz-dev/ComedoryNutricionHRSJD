import { useCallback, useEffect, useRef, useState } from 'react';
import { vigilarSimulacion } from '../simulacion.js';

/* La vigencia de la confirmación se recalcula cada segundo, sin consultar. */
const MS_PULSO = 1000;

/**
 * Reloj de simulación del servidor y confirmación del entorno.
 *
 * `reloj` es el último reloj conocido, o null fuera de simulación: sirve para
 * mostrar la hora del servidor, nunca como permiso. `simulacionConfirmada`
 * es lo único que habilita el simulador del lector: true solo con una
 * confirmación de /salud (200, entorno 'simulacion') de no más de 90 s, y
 * false durante la carga, tras un fallo o al volver a la pestaña hasta que
 * llegue otra (ver `vigilarSimulacion`). `simulacionVigente()` repite esa
 * comprobación en el instante en que se usa una acción.
 *
 * `aplicar` publica el estado que devuelve una acción sobre el reloj sin
 * esperar a la próxima vuelta.
 */
export default function useSimulacion({ operaReloj }) {
  const [reloj, setReloj] = useState(null);
  const [simulacionConfirmada, setSimulacionConfirmada] = useState(false);
  const vigilante = useRef(null);

  useEffect(() => {
    let control = null;
    const reflejar = () => {
      if (!control) return;
      setReloj(control.reloj());
      setSimulacionConfirmada(control.vigente());
    };
    control = vigilarSimulacion({ operaReloj, alCambiar: reflejar });
    vigilante.current = control;
    const pulso = setInterval(() => setSimulacionConfirmada(control.vigente()), MS_PULSO);
    return () => {
      clearInterval(pulso);
      control.cancelar();
      control = null;
      vigilante.current = null;
      setSimulacionConfirmada(false);
    };
  }, [operaReloj]);

  const aplicar = useCallback((estado) => setReloj(estado), []);
  const simulacionVigente = useCallback(() => vigilante.current?.vigente() ?? false, []);
  return { reloj, aplicar, simulacionConfirmada, simulacionVigente };
}
