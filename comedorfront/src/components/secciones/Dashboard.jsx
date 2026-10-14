import { Bar, BarChart, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import Tarjeta from '../ui/Tarjeta.jsx';
import Etiqueta from '../ui/Etiqueta.jsx';
import { IconoCheck, IconoEquis, IconoHuella, IconoReloj } from '../ui/Iconos.jsx';
import { anchoDeMedidor, cupoLegible, periodosDeResumen } from '../../resumen.js';
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
 * Resumen.
 *
 * Todas las cifras salen de /pantalla/estado, incluidos los ceros y los null,
 * y cada bloque dice a qué período corresponde: turno actual, raciones del
 * día y lecturas del lector son tres conteos distintos (ver resumen.js) y no
 * se presentan como si fueran el mismo.
 */
export default function Dashboard({ pantalla }) {
  if (!pantalla) {
    return (
      <div className="resumen">
        <p className="resumen__vacio" role="status">Estado del comedor no disponible.</p>
      </div>
    );
  }

  const { fuera_de_horario: fueraDeHorario, comida: turno, por_categoria: consumo, totales_del_dia: totales } = pantalla;
  const periodos = periodosDeResumen(pantalla);
  const cupo = cupoLegible(pantalla.cupo);

  return (
    <div className="resumen">
      <p className="resumen__corte" role="status">
        <IconoReloj tamano={16} /> {periodos.corte}
      </p>

      <div className="resumen__principal">
        <Tarjeta
          titulo="Turno actual"
          accesorio={<Etiqueta tono={fueraDeHorario ? 'aviso' : 'acento'}>{fueraDeHorario ? 'Fuera de horario' : turno}</Etiqueta>}
          className="resumen__turno"
        >
          {fueraDeHorario || !cupo ? (
            <div className="resumen__aparte">
              <p className="resumen__aparte-titulo">Sin comida vigente</p>
              <p>No hay una comida en curso, así que no se pueden registrar asistencias.</p>
            </div>
          ) : (
            <>
              <p className="resumen__periodo">{periodos.turno}</p>
              <p className="turno__rotulo">Raciones servidas</p>

              <p className="turno__cifra">
                {cupo.servidas}
                <span className="turno__previstas">
                  {cupo.previstas === null ? ' · sin cupo cargado' : ` / ${cupo.previstas} previstas`}
                </span>
              </p>

              {cupo.porcentaje === null ? null : (
                <div
                  className="turno__medidor"
                  role="img"
                  aria-label={`${cupo.servidas} de ${cupo.previstas} raciones previstas servidas (${cupo.porcentaje} por ciento)`}
                >
                  <span className="turno__medidor-relleno" style={{ width: `${anchoDeMedidor(cupo.porcentaje)}%` }} />
                </div>
              )}

              <p className="turno__pie">
                {cupo.porcentaje === null
                  ? 'No hay un cupo cargado para esta comida: no tiene límite.'
                  : <>{cupo.porcentaje}% del cupo del turno{cupo.restantes === null ? null : <> · quedan <strong>{cupo.restantes}</strong></>}</>}
                {cupo.supera ? <> <Etiqueta tono="aviso">Supera lo previsto</Etiqueta></> : null}
              </p>
            </>
          )}
        </Tarjeta>

        <div className="resumen__cifras">
          <article className="tile tile--grande">
            <span className="tile__icono">
              <IconoCheck tamano={24} />
            </span>
            <div>
              <span className="tile__rotulo">Raciones servidas del día</span>
              <strong className="tile__valor tile__valor--exito">{totales.raciones_servidas}</strong>
              <span className="tile__periodo">{periodos.raciones}</span>
              <span className="tile__periodo">Padrón: {pantalla.padron}</span>
            </div>
          </article>

          <article className="tile tile--lecturas" aria-label="Lecturas del lector">
            <span className="tile__icono tile__icono--neutro">
              <IconoHuella tamano={24} />
            </span>
            <div>
              <span className="tile__rotulo">Lecturas del lector</span>
              <span className="tile__periodo">{periodos.lecturas}</span>
              <dl className="tile__lecturas">
                <div>
                  <dt><IconoCheck tamano={14} /> Aceptadas</dt>
                  <dd className="tile__valor tile__valor--exito">{totales.aceptadas}</dd>
                </div>
                <div>
                  <dt><IconoEquis tamano={14} /> Rechazadas</dt>
                  <dd className="tile__valor tile__valor--error">{totales.rechazadas}</dd>
                </div>
                {Number.isInteger(totales.lecturas) ? (
                  <div>
                    <dt>Total</dt>
                    <dd className="tile__valor">{totales.lecturas}</dd>
                  </div>
                ) : null}
              </dl>
              <span className="tile__periodo">Toques de dedo: no son raciones.</span>
            </div>
          </article>
        </div>
      </div>

      <Tarjeta
        titulo="Raciones del día por categoría"
        accesorio={`${totales.raciones_servidas} raciones · ${periodos.raciones}`}
        className="resumen__grafico"
      >
        {consumo.length === 0 ? (
          <p className="resumen__vacio resumen__vacio--interno" role="status">
            No hay categorías de reporte activas para mostrar.
          </p>
        ) : consumo.every((fila) => fila.raciones === 0) ? (
          <p className="resumen__vacio resumen__vacio--interno" role="status">
            {totales.raciones_servidas > 0
              ? 'Las raciones del día todavía no están clasificadas por categoría.'
              : 'Todavía no se sirvió ninguna ración en este día.'}
          </p>
        ) : (
          <>
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
              <caption>Raciones del día por categoría</caption>
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
          </>
        )}
      </Tarjeta>
    </div>
  );
}
