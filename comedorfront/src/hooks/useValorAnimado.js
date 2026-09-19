import { useEffect, useRef, useState } from 'react';

/**
 * Interpola un número hacia su valor destino con requestAnimationFrame.
 *
 * Se usa para que el contador del gauge de raciones no salte de golpe: el arco
 * del SVG se anima con una transición CSS y la cifra se anima con este hook,
 * de modo que ambos recorren el mismo tramo de tiempo.
 *
 * Si el valor cambia a mitad de la animación, arranca desde donde iba (no
 * desde el valor anterior), así encadenar marcaciones rápidas no produce saltos.
 */
export default function useValorAnimado(valorDestino, duracion = 900) {
  const [valor, setValor] = useState(valorDestino);
  const valorActual = useRef(valorDestino);
  const frame = useRef(0);

  useEffect(() => {
    const desde = valorActual.current;
    const hasta = valorDestino;

    if (desde === hasta) return undefined;

    const inicio = performance.now();

    const paso = (ahora) => {
      const avance = Math.min((ahora - inicio) / duracion, 1);
      const suavizado = 1 - Math.pow(1 - avance, 3); // easeOutCubic
      const intermedio = desde + (hasta - desde) * suavizado;

      valorActual.current = avance < 1 ? intermedio : hasta;
      setValor(valorActual.current);

      if (avance < 1) {
        frame.current = requestAnimationFrame(paso);
      }
    };

    frame.current = requestAnimationFrame(paso);
    return () => cancelAnimationFrame(frame.current);
  }, [valorDestino, duracion]);

  return valor;
}
