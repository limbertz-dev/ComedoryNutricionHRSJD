import { useEffect, useRef, useState } from 'react';
import Boton from '../ui/Boton.jsx';
import Etiqueta from '../ui/Etiqueta.jsx';
import Tarjeta from '../ui/Tarjeta.jsx';
import { IconoHuella, IconoRecargar } from '../ui/Iconos.jsx';
import { obtenerEstadoMonitoreo } from '../../api.js';
import {
  MS_REEVALUAR_VIGENCIA,
  estadoDeVista,
  medirAhora,
  programarRefrescoMonitoreo,
  textoHoraLocal,
} from '../../monitoreo.js';
import './LectorBiometrico.css';

/*
 * Lo que anuncia la región viva: solo cambia cuando cambia el estado, nunca
 * con la hora, para que el lector de pantalla no repita cada refresco.
 *
 * Ningún tono es verde: «reciente» describe la consulta, no el lector, y hoy
 * el sistema no sabe si el lector está conectado.
 */
const RESUMENES = {
  cargando: { tono: 'neutro', etiqueta: 'Consultando', texto: 'Consultando el estado del lector…' },
  vigente: {
    tono: 'neutro',
    etiqueta: 'Consulta reciente',
    texto: 'La información es reciente; lo único que el sistema sabe del lector es lo que se ve abajo.',
  },
  antiguo: {
    tono: 'aviso',
    etiqueta: 'Datos anteriores',
    texto: 'No hay una consulta reciente: lo que se ve puede no reflejar el estado actual.',
  },
  revalidando: {
    tono: 'aviso',
    etiqueta: 'Revalidando',
    texto: 'Volvió a esta pestaña: se consulta de nuevo. Lo que se ve es anterior.',
  },
  'fallo-con-datos': {
    tono: 'error',
    etiqueta: 'No se pudo actualizar',
    texto: 'Se muestran los datos de la última consulta; pueden no reflejar el estado actual.',
  },
  'sin-diagnostico': {
    tono: 'error',
    etiqueta: 'Estado no disponible',
    texto: 'No se pudo consultar el estado del lector.',
  },
};

/** Estados de la vista en los que lo que se ve ya no es una consulta reciente. */
const DATO_ANTERIOR = new Set(['antiguo', 'revalidando', 'fallo-con-datos']);

/**
 * Sección «Lector biométrico» (solo sistemas): GET /monitoreo/estado cada
 * 30 s después de terminar la consulta anterior, en pausa con la pestaña
 * oculta. La antigüedad se recalcula con los relojes del equipo.
 */
export default function LectorBiometrico({ consultar = obtenerEstadoMonitoreo }) {
  const [estadoLector, setEstadoLector] = useState(null);
  const [recepcion, setRecepcion] = useState(null);
  const [error, setError] = useState('');
  const [consultando, setConsultando] = useState(true);
  const [pendiente, setPendiente] = useState(false);
  const [, setPulso] = useState(0);
  const refresco = useRef(null);

  useEffect(() => {
    const control = programarRefrescoMonitoreo({
      consultar: async ({ signal }) => {
        setConsultando(true);
        try {
          const datos = await consultar({ signal });
          if (signal.aborted) return;
          setEstadoLector(datos.lector);
          setRecepcion(medirAhora());
          setError('');
          setPendiente(false);
        } catch (fallo) {
          if (!signal.aborted) setError(fallo.message);
        } finally {
          if (!signal.aborted) setConsultando(false);
        }
      },
      alVolver: () => setPendiente(true),
    });
    refresco.current = control;
    /* Solo dispara un nuevo cálculo de la antigüedad; sale de los relojes del equipo. */
    const pulso = setInterval(() => setPulso((vuelta) => vuelta + 1), MS_REEVALUAR_VIGENCIA);
    return () => {
      control.cancelar();
      clearInterval(pulso);
      refresco.current = null;
    };
  }, [consultar]);

  return (
    <VistaLectorBiometrico
      lector={estadoLector}
      recepcion={recepcion}
      error={error}
      consultando={consultando}
      estado={estadoDeVista({ diagnostico: estadoLector, recepcion, error, pendiente })}
      onActualizar={() => refresco.current?.actualizar()}
    />
  );
}

/** Presentación pura de la sección, para renderizarla con datos sintéticos. */
export function VistaLectorBiometrico({ lector, recepcion, error, consultando, estado, onActualizar }) {
  const resumen = RESUMENES[estado] ?? RESUMENES.cargando;

  return (
    <div className="lector" aria-busy={consultando ? 'true' : 'false'}>
      <div className="lector__barra">
        <div className="lector__resumen">
          <p className="lector__resumen-estado" role="status">
            <Etiqueta tono={resumen.tono}>{resumen.etiqueta}</Etiqueta>
            <span>{resumen.texto}</span>
          </p>
          {recepcion ? (
            <p className="lector__resumen-hora">
              Última consulta recibida en este equipo a las {textoHoraLocal(recepcion.pared)}.
              Se actualiza cada 30 s mientras esta pestaña está visible.
            </p>
          ) : null}
        </div>
        {/* aria-disabled y no disabled: el refresco automático no debe quitarle
            el foco a quien está sobre el botón. Pulsarlo durante una consulta
            se une a ella, sin lanzar otra. */}
        <Boton
          variante="secundario"
          icono={<IconoRecargar />}
          onClick={onActualizar}
          aria-disabled={consultando ? 'true' : 'false'}
        >
          {consultando ? 'Actualizando…' : 'Actualizar'}
        </Boton>
      </div>

      {error ? (
        <div className={`lector__alerta lector__alerta--${lector ? 'aviso' : 'error'}`} role="alert">
          <p className="lector__alerta-titulo">
            {lector
              ? 'No se pudo actualizar el estado del lector.'
              : 'No se pudo consultar el estado del lector.'}
          </p>
          <p className="lector__alerta-detalle">{error}</p>
        </div>
      ) : null}

      {lector ? <TarjetaLector lector={lector} anterior={DATO_ANTERIOR.has(estado)} /> : null}
    </div>
  );
}

/*
 * El contrato solo informa «desconocido / sin_telemetria»: texto neutro, sin
 * verde y sin inventar una conexión (ni su ausencia).
 */
function TarjetaLector({ lector, anterior }) {
  return (
    <Tarjeta
      className="lector__tarjeta"
      titulo="Lector de huellas"
      accesorio={anterior
        ? <Etiqueta tono="aviso">Dato anterior</Etiqueta>
        : <Etiqueta tono="neutro">Sin información de conexión</Etiqueta>}
    >
      <div className="lector__contenido">
        <span className="lector__icono" aria-hidden="true"><IconoHuella tamano={34} /></span>
        <div className="lector__detalle">
          <dl className="lector__datos">
            <div className="lector__dato">
              <dt>Estado</dt>
              <dd>{lector.estado === 'desconocido' ? 'Desconocido' : lector.estado}</dd>
            </div>
          </dl>
          <p className="lector__texto">
            El sistema todavía no recibe señales del lector, así que no puede saber si está conectado.
          </p>
          <p className="lector__nota">
            Que el estado sea desconocido no indica una falla: solo que todavía no hay información.
          </p>
        </div>
      </div>
    </Tarjeta>
  );
}
