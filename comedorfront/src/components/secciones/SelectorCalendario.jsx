import { useEffect, useRef, useState } from 'react';
import { IconoCalendario } from '../ui/Iconos.jsx';
import './SelectorCalendario.css';

const DIAS_SEMANA = ['Lu', 'Ma', 'Mi', 'Ju', 'Vi', 'Sá', 'Do'];

const FORMATO_FECHA_BOTON = new Intl.DateTimeFormat('es-BO', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
});

const FORMATO_FECHA_ARIA = new Intl.DateTimeFormat('es-BO', {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
  year: 'numeric',
});

const FORMATO_MES = new Intl.DateTimeFormat('es-BO', {
  month: 'long',
  year: 'numeric',
});

const FORMATO_MES_CORTO = new Intl.DateTimeFormat('es-BO', { month: 'short' });

/** Fecha local en formato API: "2026-09-10" (nunca UTC, para no mover el día). */
export function valorFecha(fecha) {
  const dos = (numero) => String(numero).padStart(2, '0');
  return `${fecha.getFullYear()}-${dos(fecha.getMonth() + 1)}-${dos(fecha.getDate())}`;
}

function fechaDesdeValor(valor) {
  const [gestion, mes, dia] = valor.split('-').map(Number);
  return new Date(gestion, mes - 1, dia, 12);
}

function valorMes(fecha) {
  return valorFecha(fecha).slice(0, 7);
}

function inicioDelDia(fecha) {
  return new Date(fecha.getFullYear(), fecha.getMonth(), fecha.getDate(), 12);
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

function mismaFecha(a, b) {
  return valorFecha(a) === valorFecha(b);
}

function mismoMes(a, b) {
  return valorMes(a) === valorMes(b);
}

function diasDeCalendario(mesVisible) {
  const primerDia = inicioDelMes(mesVisible);
  const desplazamiento = (primerDia.getDay() + 6) % 7;
  return Array.from({ length: 42 }, (_, indice) => sumarDias(primerDia, indice - desplazamiento));
}

/**
 * Calendario desplegable del selector de período (día o mes).
 *
 * Lo comparten Historial de comidas y Control Biométrico: mismas clases y
 * mismo aspecto en ambas secciones. Por defecto no deja elegir futuro
 * (historial); con `permitirFuturo` también se puede consultar adelante
 * (turnos ya planificados en Control Biométrico).
 *
 * El calendario de días abre en los días, y pulsar el mes de la cabecera lleva
 * a la cuadrícula de los doce meses con la gestión navegable —el mismo atajo
 * que el filtro de fechas de Reportes—: elegir un mes ahí no selecciona nada,
 * solo mueve el calendario a ese mes para rematar el día. El de meses ya es
 * esa cuadrícula, así que no tiene nada que alternar.
 */
export default function SelectorCalendario({ alcance, fecha, mes, hoy, onFecha, onMes, permitirFuturo = false }) {
  const fechaSeleccionada = alcance === 'diario' ? fechaDesdeValor(fecha) : fechaDesdeValor(`${mes}-01`);
  const [abierto, setAbierto] = useState(false);
  /* Solo cuenta en el calendario de días: el de meses ya es la cuadrícula. */
  const [vista, setVista] = useState('dias');
  const [periodoVisible, setPeriodoVisible] = useState(() => inicioDelMes(fechaSeleccionada));
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

  /* Cerrar deja el calendario como se abrirá la próxima vez: en los días. */
  function cerrar() {
    setAbierto(false);
    setVista('dias');
  }

  function alternar() {
    setPeriodoVisible(inicioDelMes(fechaSeleccionada));
    setVista('dias');
    setAbierto((actual) => !actual);
  }

  function seleccionarFecha(nuevaFecha) {
    onFecha(valorFecha(nuevaFecha));
    cerrar();
  }

  function seleccionarMes(nuevoMes) {
    onMes(valorMes(nuevoMes));
    cerrar();
  }

  /* En el calendario de días, el mes solo mueve la vista: el día lo elige el
     siguiente clic, no este. */
  function irAlMes(nuevoMes) {
    setPeriodoVisible(nuevoMes);
    setVista('dias');
  }

  const hoyDia = inicioDelDia(hoy);
  const hoyMes = inicioDelMes(hoy);
  /* El calendario de meses siempre está en la cuadrícula; el de días, cuando
     se pulsa el mes de la cabecera. */
  const enMeses = alcance !== 'diario' || vista === 'meses';
  const dias = alcance === 'diario' ? diasDeCalendario(periodoVisible) : [];
  /* Las flechas mueven lo que se está viendo: meses en la vista de días,
     gestiones en la cuadrícula de meses. */
  const puedeAvanzar = permitirFuturo ? true : enMeses
    ? periodoVisible.getFullYear() < hoy.getFullYear()
    : moverMes(periodoVisible, 1) <= hoyMes;
  const valorVisible = alcance === 'diario'
    ? `${mismaFecha(fechaSeleccionada, hoy) ? 'Hoy · ' : ''}${FORMATO_FECHA_BOTON.format(fechaSeleccionada)}`
    : FORMATO_MES.format(fechaSeleccionada);

  return (
    <div className="historial__periodo" ref={contenedorRef}>
      <button
        type="button"
        className={`historial__periodo-disparador${abierto ? ' historial__periodo-disparador--abierto' : ''}`}
        aria-haspopup="dialog"
        aria-expanded={abierto}
        onClick={alternar}
      >
        <span className="historial__periodo-icono"><IconoCalendario tamano={19} /></span>
        <span className="historial__periodo-texto">
          <small>{alcance === 'diario' ? 'Fecha seleccionada' : 'Mes seleccionado'}</small>
          <strong>{valorVisible}</strong>
        </span>
        <span className="historial__periodo-chevron" aria-hidden="true">⌄</span>
      </button>

      {abierto ? (
        <div className="historial__calendario" role="dialog" aria-label={alcance === 'diario' ? 'Seleccionar fecha' : 'Seleccionar mes'}>
          <div className="historial__calendario-atajos">
            {alcance === 'diario' ? (
              <>
                <button type="button" onClick={() => seleccionarFecha(hoyDia)}>Hoy</button>
                <button type="button" onClick={() => seleccionarFecha(sumarDias(hoyDia, -1))}>Ayer</button>
                <button type="button" onClick={() => seleccionarFecha(sumarDias(hoyDia, -7))}>Hace 7 días</button>
              </>
            ) : (
              <>
                <button type="button" onClick={() => seleccionarMes(hoyMes)}>Este mes</button>
                <button type="button" onClick={() => seleccionarMes(moverMes(hoyMes, -1))}>Anterior</button>
                <button type="button" onClick={() => seleccionarMes(moverMes(hoyMes, -3))}>Hace 3 meses</button>
              </>
            )}
          </div>

          <div className="historial__calendario-navegacion">
            <button
              type="button"
              aria-label={enMeses ? 'Gestión anterior' : 'Mes anterior'}
              onClick={() => setPeriodoVisible((actual) => (
                enMeses ? moverAnio(actual, -1) : moverMes(actual, -1)
              ))}
            >
              ‹
            </button>

            {/* En el calendario de días el mes es el interruptor entre las dos
                vistas; en el de meses es solo el rótulo de la gestión. */}
            {alcance === 'diario' ? (
              <button
                type="button"
                className="historial__calendario-titulo"
                aria-expanded={enMeses}
                aria-label={enMeses
                  ? `Volver a los días de ${FORMATO_MES.format(periodoVisible)}`
                  : `Elegir mes y gestión (${FORMATO_MES.format(periodoVisible)})`}
                onClick={() => setVista(enMeses ? 'dias' : 'meses')}
              >
                {enMeses ? periodoVisible.getFullYear() : FORMATO_MES.format(periodoVisible)}
              </button>
            ) : (
              <strong>{periodoVisible.getFullYear()}</strong>
            )}

            <button
              type="button"
              aria-label={enMeses ? 'Gestión siguiente' : 'Mes siguiente'}
              disabled={!puedeAvanzar}
              onClick={() => setPeriodoVisible((actual) => (
                enMeses ? moverAnio(actual, 1) : moverMes(actual, 1)
              ))}
            >
              ›
            </button>
          </div>

          {!enMeses ? (
            <>
              <div className="historial__calendario-semana" aria-hidden="true">
                {DIAS_SEMANA.map((dia) => <span key={dia}>{dia}</span>)}
              </div>
              <div className="historial__calendario-dias">
                {dias.map((dia) => {
                  const fueraDelMes = dia.getMonth() !== periodoVisible.getMonth();
                  const seleccionada = mismaFecha(dia, fechaSeleccionada);
                  const esHoy = mismaFecha(dia, hoyDia);
                  const esFutura = !permitirFuturo && dia > hoyDia;

                  return (
                    <button
                      type="button"
                      key={valorFecha(dia)}
                      className={`${fueraDelMes ? 'historial__calendario-dia--externo ' : ''}${seleccionada ? 'historial__calendario-dia--seleccionado ' : ''}${esHoy ? 'historial__calendario-dia--hoy' : ''}`}
                      aria-label={FORMATO_FECHA_ARIA.format(dia)}
                      aria-pressed={seleccionada}
                      disabled={esFutura}
                      onClick={() => seleccionarFecha(dia)}
                    >
                      {dia.getDate()}
                    </button>
                  );
                })}
              </div>
            </>
          ) : (
            <div className="historial__calendario-meses">
              {Array.from({ length: 12 }, (_, indice) => {
                const fechaMes = new Date(periodoVisible.getFullYear(), indice, 1, 12);
                /* En el calendario de días, el mes marcado es el que se está
                   hojeando; en el de meses, el que ya está elegido. */
                const seleccionada = mismoMes(fechaMes, alcance === 'diario' ? periodoVisible : fechaSeleccionada);
                const esFuturo = !permitirFuturo && fechaMes > hoyMes;
                return (
                  <button
                    type="button"
                    key={indice}
                    className={seleccionada ? 'historial__calendario-mes--seleccionado' : ''}
                    aria-label={FORMATO_MES.format(fechaMes)}
                    aria-pressed={seleccionada}
                    disabled={esFuturo}
                    onClick={() => (alcance === 'diario' ? irAlMes(fechaMes) : seleccionarMes(fechaMes))}
                  >
                    {FORMATO_MES_CORTO.format(fechaMes).replace('.', '')}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
