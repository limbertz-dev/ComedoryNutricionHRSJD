import useValorAnimado from '../../hooks/useValorAnimado.js';
import './GaugeRaciones.css';

const RADIO = 78;
const CIRCUNFERENCIA = 2 * Math.PI * RADIO;

/**
 * Barra circular de raciones restantes.
 *
 * La animación tiene dos capas que comparten la misma duración:
 *  - el arco: transición CSS sobre `stroke-dashoffset` (ver GaugeRaciones.css)
 *  - la cifra: interpolada con useValorAnimado
 * Nunca baja "de golpe", ni siquiera con marcaciones encadenadas.
 */
export default function GaugeRaciones({ cupo, fueraDeHorario, turno }) {
  const disponibles = Boolean(cupo);
  const restantesAnimadas = useValorAnimado(cupo?.restantes ?? 0, 900);
  const proporcion = disponibles ? Math.max(0, Math.min(1, 1 - cupo.porcentaje / 100)) : 0;
  const offset = CIRCUNFERENCIA * (1 - proporcion);

  const critico = disponibles && cupo.restantes === 0;
  const bajo = disponibles && !critico && cupo.porcentaje >= 66;
  const colorArco = !disponibles || fueraDeHorario ? 'var(--c-texto-2)' : critico ? 'var(--c-error)' : bajo ? 'var(--c-aviso)' : 'var(--c-acento)';

  return (
    <figure className="gauge">
      <div className="gauge__grafico">
        <svg viewBox="0 0 200 200" role="img" aria-hidden="true" className="gauge__svg">
          <circle className="gauge__pista" cx="100" cy="100" r={RADIO} />
          <circle
            className="gauge__arco"
            cx="100"
            cy="100"
            r={RADIO}
            stroke={colorArco}
            strokeDasharray={CIRCUNFERENCIA}
            strokeDashoffset={offset}
          />
        </svg>

        <div className="gauge__centro">
          <span className="gauge__cifra" style={{ color: colorArco }}>
            {!disponibles ? '—' : Math.round(restantesAnimadas)}
          </span>
          <span className="gauge__total">{!disponibles ? (fueraDeHorario ? 'Sin comida vigente' : 'Estado no disponible') : `de ${cupo.previstas}`}</span>
        </div>
      </div>

      <figcaption className="gauge__pie">
        <span className="gauge__rotulo">{fueraDeHorario ? 'Último servicio · Cerrado' : 'Raciones restantes'}</span>
        <span className="gauge__detalle">
          {disponibles ? `${turno} · ${cupo.servidas} servidas` : 'Estado del comedor'}
        </span>
      </figcaption>

      {/* Lectura accesible equivalente, sin depender del color. */}
      <p className="solo-lectores" role="status">
        {!disponibles ? 'No hay un cupo vigente disponible.' : fueraDeHorario ? `${turno}: servicio cerrado, ${cupo.servidas} raciones servidas. No se permiten entregas.` : `Quedan ${cupo.restantes} de ${cupo.previstas} raciones previstas para ${turno}.`}
      </p>
    </figure>
  );
}
