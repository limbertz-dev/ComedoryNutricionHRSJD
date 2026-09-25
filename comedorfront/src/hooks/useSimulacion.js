import { useCallback, useEffect, useState } from 'react';
import { consultarSimulacion } from '../simulacion.js';

/* El reloj simulado sigue corriendo en el servidor: se vuelve a leer cada tanto. */
const MS_CONSULTA = 30000;

/**
 * Reloj de simulación del servidor, o null si la API no corre en simulación.
 *
 * Cada vuelta es `consultarSimulacion` (simulacion.js). En cuanto /salud
 * dice que el entorno no es simulación, deja de consultar y el reloj queda
 * en null: nada de simulación se monta. Si /salud no responde, lo reintenta
 * en la próxima vuelta sin mostrar nada; una vuelta fallida en simulación
 * conserva el último reloj conocido.
 *
 * `aplicar` publica el estado que devuelve una acción sobre el reloj sin
 * esperar a la próxima vuelta.
 */
export default function useSimulacion({ operaReloj }) {
  const [reloj, setReloj] = useState(null);

  useEffect(() => {
    const controlador = new AbortController();
    let yaEnSimulacion = false;
    let intervalo = null;

    async function consultar() {
      try {
        const resultado = await consultarSimulacion({
          operaReloj, yaEnSimulacion, signal: controlador.signal,
        });
        if (controlador.signal.aborted) return;
        if (!resultado.simulacion) clearInterval(intervalo);
        yaEnSimulacion = resultado.simulacion;
        setReloj(resultado.reloj);
      } catch {
        // Sin respuesta se conserva lo último conocido.
      }
    }

    consultar();
    intervalo = setInterval(consultar, MS_CONSULTA);
    return () => {
      controlador.abort();
      clearInterval(intervalo);
    };
  }, [operaReloj]);

  const aplicar = useCallback((estado) => setReloj(estado), []);
  return { reloj, aplicar };
}
