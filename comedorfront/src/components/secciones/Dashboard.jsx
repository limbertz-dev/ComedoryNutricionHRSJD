import { Bar, BarChart, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import Tarjeta from '../ui/Tarjeta.jsx';
import Etiqueta from '../ui/Etiqueta.jsx';
import { IconoCheck, IconoEquis } from '../ui/Iconos.jsx';
import './Dashboard.css';

/* Una sola serie => un solo color para todas las barras (nunca un color por barra). */
/* Recharts pinta atributos SVG: aqui van los literales que reflejan tokens.css. */
const COLOR_BARRA = '#00b473';      /* --c-acento */
const COLOR_EJE = '#cfd8d5';        /* --c-borde-fuerte */
const COLOR_TICK = '#64748b';       /* --c-texto-2 */
const COLOR_ETIQUETA = '#12233d';   /* --c-texto */

function TooltipConsumo({ active, payload, label }) {
  if (!active || !payload || payload.length === 0) return null;

  return (
    <div className="grafico__tooltip">
      <p className="grafico__tooltip-titulo">{label}</p>
      <p className="grafico__tooltip-valor">
        <span className="grafico__tooltip-punto" aria-hidden="true" />
        {payload[0].value} raciones
      </p>
    </div>
  );
}

/**
 * Dashboard.
 *
 * Todas las cifras salen de /pantalla/estado, incluidos los ceros y los null.
 */
export default function Dashboard({ pantalla }) {
  if (!pantalla) return <p role="status">Estado del comedor no disponible.</p>;
  const { cupo, fuera_de_horario: fueraDeHorario, comida: turno, por_categoria: consumo, totales_del_dia: totales } = pantalla;
  const porcentaje = cupo?.porcentaje;

  return (
    <>
      <div className="dashboard">
        <div className="dashboard__columna">
          <Tarjeta titulo="Turno actual" accesorio={<Etiqueta tono="acento">{fueraDeHorario ? 'Fuera de horario' : turno}</Etiqueta>}>
            <p className="turno__rotulo">Raciones servidas</p>

            <p className="turno__cifra">
              {cupo?.servidas ?? '—'}
              <span className="turno__previstas">{fueraDeHorario ? ' · Sin comida vigente' : ` / ${cupo.previstas} previstas`}</span>
            </p>

            {cupo ? <div
              className="turno__medidor"
              role="img"
              aria-label={`${cupo.servidas} de ${cupo.previstas} raciones previstas servidas (${porcentaje} por ciento)`}
            >
              <span className="turno__medidor-relleno" style={{ width: `${Math.min(100, Math.max(0, porcentaje))}%` }} />
            </div> : null}

            <p className="turno__pie">
              {fueraDeHorario ? 'No se pueden registrar asistencias en este momento.' : <>{porcentaje}% del cupo del turno · quedan <strong>{cupo.restantes}</strong></>}
            </p>
          </Tarjeta>

          <div className="dashboard__tiles">
            <article className="tile">
              <span className="tile__icono">
                <IconoCheck tamano={24} />
              </span>
              <div>
                <span className="tile__rotulo">Lecturas aceptadas</span>
                <strong className="tile__valor tile__valor--exito">{totales.aceptadas}</strong>
              </div>
            </article>

            <article className="tile">
              <span className="tile__icono tile__icono--error">
                <IconoEquis tamano={24} />
              </span>
              <div>
                <span className="tile__rotulo">Lecturas rechazadas</span>
                <strong className="tile__valor tile__valor--error">{totales.rechazadas}</strong>
              </div>
            </article>
          </div>
        </div>

        <Tarjeta
          titulo="Raciones consumidas hoy por categoría"
          accesorio={`${totales.raciones_servidas} raciones · Padrón: ${pantalla.padron}`}
          className="dashboard__grafico"
        >
          <div className="grafico__lienzo">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={consumo} margin={{ top: 28, right: 8, bottom: 4, left: 8 }}>
                <YAxis hide domain={[0, 'dataMax']} allowDecimals={false} />
                <XAxis
                  dataKey="categoria"
                  tickLine={false}
                  axisLine={{ stroke: COLOR_EJE }}
                  tick={{ fill: COLOR_TICK, fontSize: 15 }}
                  tickMargin={10}
                />
                <Tooltip
                  content={<TooltipConsumo />}
                  cursor={{ fill: 'rgba(0, 180, 115, 0.07)' }}
                />
                <Bar
                  dataKey="raciones"
                  name="Raciones"
                  fill={COLOR_BARRA}
                  maxBarSize={24}
                  radius={[4, 4, 0, 0]}
                  animationDuration={700}
                >
                  <LabelList
                    dataKey="raciones"
                    position="top"
                    offset={10}
                    fill={COLOR_ETIQUETA}
                    fontSize={16}
                    fontWeight={650}
                  />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Misma información en texto, para lectores de pantalla. */}
          <table className="solo-lectores">
            <caption>Raciones consumidas hoy por categoría</caption>
            <thead>
              <tr>
                <th scope="col">Categoría</th>
                <th scope="col">Raciones</th>
              </tr>
            </thead>
            <tbody>
              {consumo.map((fila) => (
                <tr key={fila.categoria}>
                  <th scope="row">{fila.categoria}</th>
                  <td>{fila.raciones}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Tarjeta>
      </div>
    </>
  );
}
