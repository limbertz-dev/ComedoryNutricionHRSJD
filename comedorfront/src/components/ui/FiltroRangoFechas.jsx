import { useEffect, useRef, useState } from 'react';
import { IconoCalendario } from './Iconos.jsx';
import './FiltroRangoFechas.css';

const DIAS_SEMANA = ['Lu', 'Ma', 'Mi', 'Ju', 'Vi', 'Sá', 'Do'];

const FORMATO_FECHA_LARGA = new Intl.DateTimeFormat('es-BO', {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
});

const FORMATO_MES_ANIO = new Intl.DateTimeFormat('es-BO', { month: 'long', year: 'numeric' });
const FORMATO_FECHA_ARIA = new Intl.DateTimeFormat('es-BO', { dateStyle: 'full' });
const FORMATO_MES_CORTO = new Intl.DateTimeFormat('es-BO', { month: 'short' });
const FORMATO_MES_LARGO = new Intl.DateTimeFormat('es-BO', { month: 'long', year: 'numeric' });

/** «Ene», «Feb»… sin el punto que mete Intl en algunos meses. */
function mesCorto(fecha) {
  const texto = FORMATO_MES_CORTO.format(fecha).replace('.', '');
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}

/** Fecha local en formato API: "2026-09-10" (nunca UTC, para no mover el día). */
function valorFecha(fecha) {
  const dos = (numero) => String(numero).padStart(2, '0');
  return `${fecha.getFullYear()}-${dos(fecha.getMonth() + 1)}-${dos(fecha.getDate())}`;
}

function fechaDesdeValor(valor) {
  const [gestion, mes, dia] = valor.split('-').map(Number);
  return new Date(gestion, mes - 1, dia, 12);
}

function inicioDelMes(fecha) {
  return new Date(fecha.getFullYear(), fecha.getMonth(), 1, 12);
}

function sumarDias(fecha, cantidad) {
  return new Date(fecha.getFullYear(), fecha.getMonth(), fecha.getDate() + cantidad, 12);
}

function moverMes(fecha, cantidad) {
  return new Date(fecha.getFullYear(), fecha.getMonth() + cantidad, 1, 12);
}

function moverAnio(fecha, cantidad) {
  return new Date(fecha.getFullYear() + cantidad, fecha.getMonth(), 1, 12);
}

function diasDeCalendario(mesVisible) {
  const primerDia = inicioDelMes(mesVisible);
  const desplazamiento = (primerDia.getDay() + 6) % 7;
  return Array.from({ length: 42 }, (_, indice) => sumarDias(primerDia, indice - desplazamiento));
}

/** "1 de septiembre de 2026", a partir de una fecha en formato API. */
function formatoFechaLargo(valor) {
  return FORMATO_FECHA_LARGA.format(fechaDesdeValor(valor));
}

/**
 * Disparador + popover de un solo día, con el diseño de "Reportes" de
 * LA Aguilar Silva (`.order-calendar-*`). `limiteMin`/`limiteMax` deshabilitan
 * días fuera de rango, para que "Fecha inicial" nunca pueda quedar después de
 * "Fecha final" ni viceversa.
 *
 * Se abre siempre en los días. Pulsar el mes de la cabecera cambia a la
 * cuadrícula de doce meses con el año navegable —el mismo atajo que ya tiene
 * el calendario de Historial de comidas—, para no tener que dar doce clics en
 * la flechita cuando el informe que se busca es de hace un año.
 */
function SelectorFecha({ valor, etiqueta, onCambiar, limiteMin, limiteMax }) {
  const [abierto, setAbierto] = useState(false);
  const [vista, setVista] = useState('dias');
  const [mesVisible, setMesVisible] = useState(() => inicioDelMes(fechaDesdeValor(valor)));
  const contenedorRef = useRef(null);

  useEffect(() => {
    if (!abierto) return undefined;

    function cerrarAlSalir(evento) {
      if (!contenedorRef.current?.contains(evento.target)) cerrar();
    }

    function cerrarConEscape(evento) {
      if (evento.key === 'Escape') cerrar();
    }

    document.addEventListener('pointerdown', cerrarAlSalir);
    document.addEventListener('keydown', cerrarConEscape);
    return () => {
      document.removeEventListener('pointerdown', cerrarAlSalir);
      document.removeEventListener('keydown', cerrarConEscape);
    };
  }, [abierto]);

  /* Cerrar deja el popover como se abrirá la próxima vez: en los días. */
  function cerrar() {
    setAbierto(false);
    setVista('dias');
  }

  function alternar() {
    setMesVisible(inicioDelMes(fechaDesdeValor(valor)));
    setVista('dias');
    setAbierto((actual) => !actual);
  }

  function elegir(dia) {
    onCambiar(valorFecha(dia));
    cerrar();
  }

  /* Elegir mes no cierra: deja los días de ese mes para rematar la fecha. */
  function elegirMes(indice) {
    setMesVisible((actual) => new Date(actual.getFullYear(), indice, 1, 12));
    setVista('dias');
  }

  const enMeses = vista === 'meses';
  const dias = diasDeCalendario(mesVisible);
  const hoyValor = valorFecha(new Date());

  return (
    <div className="order-calendar-picker" ref={contenedorRef}>
      <button
        type="button"
        className={`order-calendar-trigger${abierto ? ' active' : ''}`}
        aria-haspopup="dialog"
        aria-expanded={abierto}
        onClick={alternar}
      >
        <IconoCalendario tamano={18} />
        <span>
          <small>{etiqueta}</small>
          <strong>{formatoFechaLargo(valor)}</strong>
        </span>
        <span className="order-calendar-chevron" aria-hidden="true">⌄</span>
      </button>

      {abierto ? (
        <div className="order-calendar-popover" role="dialog" aria-label={etiqueta}>
          <div className="order-calendar-header">
            <button
              type="button"
              aria-label={enMeses ? 'Gestión anterior' : 'Mes anterior'}
              onClick={() => setMesVisible((actual) => (
                enMeses ? moverAnio(actual, -1) : moverMes(actual, -1)
              ))}
            >
              ‹
            </button>

            {/* El mes es el interruptor entre las dos vistas del popover. */}
            <button
              type="button"
              className="order-calendar-title"
              aria-expanded={enMeses}
              aria-label={enMeses
                ? `Volver a los días de ${FORMATO_MES_ANIO.format(mesVisible)}`
                : `Elegir mes y año (${FORMATO_MES_ANIO.format(mesVisible)})`}
              onClick={() => setVista(enMeses ? 'dias' : 'meses')}
            >
              {enMeses ? mesVisible.getFullYear() : FORMATO_MES_ANIO.format(mesVisible)}
            </button>

            <button
              type="button"
              aria-label={enMeses ? 'Gestión siguiente' : 'Mes siguiente'}
              onClick={() => setMesVisible((actual) => (
                enMeses ? moverAnio(actual, 1) : moverMes(actual, 1)
              ))}
            >
              ›
            </button>
          </div>

          {enMeses ? (
            <div className="order-calendar-months">
              {Array.from({ length: 12 }, (_, indice) => {
                const fechaMes = new Date(mesVisible.getFullYear(), indice, 1, 12);
                const activo = indice === mesVisible.getMonth();
                return (
                  <button
                    type="button"
                    key={indice}
                    className={activo ? 'selected' : undefined}
                    aria-label={FORMATO_MES_LARGO.format(fechaMes)}
                    aria-pressed={activo}
                    onClick={() => elegirMes(indice)}
                  >
                    {mesCorto(fechaMes)}
                  </button>
                );
              })}
            </div>
          ) : (
            <>
              <div className="order-calendar-weekdays" aria-hidden="true">
                {DIAS_SEMANA.map((dia) => <span key={dia}>{dia}</span>)}
              </div>

              <div className="order-calendar-days">
                {dias.map((dia) => {
                  const claveDia = valorFecha(dia);
                  const fueraDelMes = dia.getMonth() !== mesVisible.getMonth();
                  const deshabilitado = Boolean(
                    (limiteMin && claveDia < limiteMin) || (limiteMax && claveDia > limiteMax),
                  );

                  return (
                    <button
                      type="button"
                      key={claveDia}
                      className={[
                        fueraDelMes ? 'outside' : '',
                        claveDia === hoyValor ? 'today' : '',
                        claveDia === valor ? 'selected' : '',
                      ].filter(Boolean).join(' ')}
                      aria-label={FORMATO_FECHA_ARIA.format(dia)}
                      aria-pressed={claveDia === valor}
                      disabled={deshabilitado}
                      onClick={() => elegir(dia)}
                    >
                      {dia.getDate()}
                    </button>
                  );
                })}
              </div>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}

/**
 * Filtro de rango de fechas para "Reportes", con el mismo diseño que ya usa
 * LA Aguilar Silva para su propio reporte de caja: períodos rápidos a la
 * izquierda y dos selectores de fecha más el botón de actualizar a la
 * derecha.
 *
 * Es autocontenido: guarda su propio `desde`/`hasta` (inicializados desde las
 * props, o el primer día del mes y hoy si no llegan) y solo avisa al padre
 * cuando se confirma con "Actualizar resumen" — elegir un día o un período
 * rápido no dispara nada por sí solo, para no relanzar la consulta con cada
 * clic mientras se sigue ajustando el rango.
 */
export default function FiltroRangoFechas({ fechaInicio, fechaFin, onActualizar }) {
  const [hoy] = useState(() => new Date());
  const [desde, setDesde] = useState(() => fechaInicio ?? valorFecha(inicioDelMes(hoy)));
  const [hasta, setHasta] = useState(() => fechaFin ?? valorFecha(hoy));

  const hoyValor = valorFecha(hoy);
  const inicioSemanaValor = valorFecha(sumarDias(hoy, -6));
  const inicioMesValor = valorFecha(inicioDelMes(hoy));

  /* null cuando el rango no coincide con ningún atajo: es una fecha elegida a mano. */
  const periodoActivo = desde === hoyValor && hasta === hoyValor ? 'hoy'
    : desde === inicioSemanaValor && hasta === hoyValor ? 'semana'
      : desde === inicioMesValor && hasta === hoyValor ? 'mes' : null;

  function elegirPeriodo(periodo) {
    setHasta(hoyValor);
    if (periodo === 'hoy') setDesde(hoyValor);
    else if (periodo === 'semana') setDesde(inicioSemanaValor);
    else setDesde(inicioMesValor);
  }

  function enviar(evento) {
    evento.preventDefault();
    onActualizar({ desde, hasta });
  }

  return (
    <div className="report-controls">
      <div className="period-shortcuts">
        <span>Periodo rápido</span>
        <div>
          <button
            type="button"
            className={periodoActivo === 'hoy' ? 'active' : undefined}
            onClick={() => elegirPeriodo('hoy')}
          >
            Hoy
          </button>
          <button
            type="button"
            className={periodoActivo === 'semana' ? 'active' : undefined}
            onClick={() => elegirPeriodo('semana')}
          >
            Últimos 7 días
          </button>
          <button
            type="button"
            className={periodoActivo === 'mes' ? 'active' : undefined}
            onClick={() => elegirPeriodo('mes')}
          >
            Este mes
          </button>
        </div>
      </div>

      <form className="report-filter" onSubmit={enviar}>
        <SelectorFecha valor={desde} etiqueta="FECHA INICIAL" limiteMax={hasta} onCambiar={setDesde} />
        <SelectorFecha valor={hasta} etiqueta="FECHA FINAL" limiteMin={desde} onCambiar={setHasta} />
        <button type="submit">Actualizar informe</button>
      </form>
    </div>
  );
}
