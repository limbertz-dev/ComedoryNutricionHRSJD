import { useEffect, useRef, useState } from 'react';
import Boton from '../ui/Boton.jsx';
import { IconoReloj } from '../ui/Iconos.jsx';
import {
  avanzarReloj,
  fijarReloj,
  obtenerReloj,
  saltarAProximaFranja,
  valorFechaHoraLocal,
  volverARelojReal,
} from '../../api.js';
import { estadoDelReloj, textoDelReloj } from '../../simulacion.js';
import './ControlesReloj.css';

const FORMATO_MOMENTO = new Intl.DateTimeFormat('es-BO', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

/**
 * Controles del reloj de simulación, dentro del SimuladorLector.
 *
 * Sin `reloj` (la API no corre en simulación, o el rol no puede moverlo) no
 * se dibuja nada. La hora que se muestra y la que se propone al fijar salen
 * siempre del servidor, nunca de la PC: cada acción devuelve el estado nuevo
 * del reloj y `onCambio(estado, { movido })` lo publica en App.
 * `abiertoInicial` monta el panel ya desplegado (lo usan las pruebas).
 */
export default function ControlesReloj({ reloj, onCambio, abiertoInicial = false }) {
  return reloj ? <PanelReloj reloj={reloj} onCambio={onCambio} abiertoInicial={abiertoInicial} /> : null;
}

function PanelReloj({ reloj, onCambio, abiertoInicial }) {
  const [abierto, setAbierto] = useState(abiertoInicial);
  const [momento, setMomento] = useState(() => valorFechaHoraLocal(reloj.ahora));
  const [congelar, setCongelar] = useState(reloj.congelado === true);
  const [ocupado, setOcupado] = useState(null);
  /* { tipo: 'ok' | 'aviso' | 'error', texto }: el resultado de la última acción. */
  const [mensaje, setMensaje] = useState(null);
  const contenedor = useRef(null);

  useEffect(() => {
    if (!abierto) return undefined;
    function afuera(evento) {
      if (!contenedor.current?.contains(evento.target)) setAbierto(false);
    }
    function escape(evento) {
      if (evento.key === 'Escape') setAbierto(false);
    }
    document.addEventListener('mousedown', afuera);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('mousedown', afuera);
      document.removeEventListener('keydown', escape);
    };
  }, [abierto]);

  function publicar(estado, movido) {
    setMomento(valorFechaHoraLocal(estado.ahora));
    setCongelar(estado.congelado === true);
    onCambio(estado, { movido });
  }

  /* Al abrir se relee el reloj: la hora propuesta es la del servidor ahora. */
  async function alternar() {
    if (abierto) {
      setAbierto(false);
      return;
    }
    setAbierto(true);
    setMensaje(null);
    setMomento(valorFechaHoraLocal(reloj.ahora));
    setCongelar(reloj.congelado === true);
    try {
      publicar(await obtenerReloj(), false);
    } catch (error) {
      setMensaje({ tipo: 'error', texto: error.message });
    }
  }

  async function ejecutar(accion, operacion) {
    setOcupado(accion);
    setMensaje(null);
    try {
      setMensaje(await operacion());
    } catch (error) {
      setMensaje({ tipo: 'error', texto: error.message });
    } finally {
      setOcupado(null);
    }
  }

  const fijar = (evento) => {
    evento.preventDefault();
    ejecutar('fijar', async () => {
      const estado = await fijarReloj({ momento, congelar });
      publicar(estado, true);
      return { tipo: 'ok', texto: `Reloj fijado en ${FORMATO_MOMENTO.format(estado.ahora)}.` };
    });
  };

  const avanzar = () => ejecutar('avanzar', async () => {
    publicar(await avanzarReloj({ minutos: 15 }), true);
    return { tipo: 'ok', texto: 'Reloj adelantado 15 minutos.' };
  });

  const proximaFranja = () => ejecutar('franja', async () => {
    const resultado = await saltarAProximaFranja();
    if (resultado.tipo === 'sin_franja') return { tipo: 'aviso', texto: resultado.detalle };
    publicar(resultado.reloj, true);
    return {
      tipo: 'ok',
      texto: `Inicio de ${resultado.comida}: ${FORMATO_MOMENTO.format(resultado.inicio)}.`,
    };
  });

  const volverAReal = () => ejecutar('real', async () => {
    publicar(await volverARelojReal(), true);
    return { tipo: 'ok', texto: 'El sistema volvió a la hora real.' };
  });

  const bloqueado = ocupado !== null;

  return (
    <div className="reloj-sim" ref={contenedor}>
      <button
        type="button"
        className={`reloj-sim__disparador${abierto ? ' reloj-sim__disparador--abierto' : ''}`}
        aria-haspopup="dialog"
        aria-expanded={abierto}
        onClick={alternar}
      >
        <IconoReloj tamano={16} />
        <span>{textoDelReloj(reloj)}</span>
      </button>

      {abierto ? (
        <div className="reloj-sim__panel" role="dialog" aria-label="Reloj de simulación">
          <div className="reloj-sim__cabecera">
            <strong>Reloj del servidor</strong>
            <span className="reloj-sim__estado">{estadoDelReloj(reloj)}</span>
          </div>
          <p className="reloj-sim__ahora">{FORMATO_MOMENTO.format(reloj.ahora)}</p>

          <form className="reloj-sim__fijar" onSubmit={fijar}>
            <label className="reloj-sim__campo">
              <span>Fecha y hora</span>
              <input
                type="datetime-local"
                value={momento}
                required
                disabled={bloqueado}
                onChange={(cambio) => setMomento(cambio.target.value)}
              />
            </label>
            <label className="reloj-sim__casilla">
              <input
                type="checkbox"
                checked={congelar}
                disabled={bloqueado}
                onChange={(cambio) => setCongelar(cambio.target.checked)}
              />
              <span className="reloj-sim__marca" aria-hidden="true" />
              Congelar el reloj
            </label>
            <Boton type="submit" disabled={bloqueado || !momento} anchoCompleto>
              {ocupado === 'fijar' ? 'Fijando…' : 'Fijar'}
            </Boton>
          </form>

          <div className="reloj-sim__acciones">
            <Boton variante="secundario" onClick={avanzar} disabled={bloqueado}>
              {ocupado === 'avanzar' ? 'Avanzando…' : '+15 min'}
            </Boton>
            <Boton variante="secundario" onClick={proximaFranja} disabled={bloqueado}>
              {ocupado === 'franja' ? 'Buscando…' : 'Próxima franja'}
            </Boton>
          </div>
          <Boton
            variante="fantasma"
            onClick={volverAReal}
            disabled={bloqueado || !reloj.simulado}
            anchoCompleto
          >
            {ocupado === 'real' ? 'Volviendo…' : 'Volver a la hora real'}
          </Boton>

          {mensaje ? (
            <p
              className={`reloj-sim__mensaje reloj-sim__mensaje--${mensaje.tipo}`}
              role={mensaje.tipo === 'error' ? 'alert' : 'status'}
            >
              {mensaje.texto}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
