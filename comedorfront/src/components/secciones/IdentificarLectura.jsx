import { useEffect, useRef, useState } from 'react';
import Boton from '../ui/Boton.jsx';
import Etiqueta from '../ui/Etiqueta.jsx';
import { IconoAlerta, IconoBuscar, IconoCheck, IconoHuella } from '../ui/Iconos.jsx';
import { avisoDeIdentificacion, crearIdentificador, horaCortaServidor } from '../../identificacion.js';
import { filtrarPadron, personaVisible } from './RegistroManual.jsx';
import './IdentificarLectura.css';

/**
 * «Huellas por identificar» de Control Biométrico (solo cocinera).
 *
 * Lista las huellas no reconocidas que se pueden identificar AHORA
 * (GET /pantalla/lecturas-por-identificar, que sigue el servicio aunque cruce
 * la medianoche). La cocinera abre una, elige a la persona del padrón, ve su
 * identidad y pulsa «Confirmar entrega». No hay nota ni motivo. El servidor
 * vuelve a comprobar derecho, servicio y duplicado; si no se sabe qué quedó,
 * se ofrece «Volver a confirmar» con la misma persona y la misma clave.
 *
 * `abierta` (id de la lectura) y `onAbrir` los controla Control Biométrico,
 * para que el resultado del lector pueda abrir directamente su huella.
 */
export default function IdentificarLectura({
  pendientes = null,
  error = '',
  personal = [],
  cargandoPadron = false,
  errorPadron = '',
  abierta = null,
  onAbrir = () => {},
  onResultado = () => {},
  identificar,
  elegidoInicial = '',
  busquedaInicial = '',
  avisoInicial = null,
}) {
  const [busqueda, setBusqueda] = useState(busquedaInicial);
  const [elegido, setElegido] = useState(String(elegidoInicial));
  const [enviando, setEnviando] = useState(false);
  const [aviso, setAviso] = useState(avisoInicial);

  /* Un solo identificador por pantalla: guarda la clave de cada intento para
     repetir la misma decisión, y bloquea el doble envío. */
  const identificador = useRef(null);
  if (identificador.current === null) {
    identificador.current = crearIdentificador(identificar ? { identificar } : {});
  }
  const montado = useRef(true);
  useEffect(() => () => { montado.current = false; }, []);

  const lecturas = pendientes?.lecturas ?? [];
  const lecturaAbierta = abierta === null ? null : lecturas.find((lectura) => lectura.id === abierta) ?? null;
  const intentoPendiente = abierta === null ? null : identificador.current.pendiente(abierta);
  /* Con un intento por repetir, la persona queda fija: repetir es repetir la
     misma decisión. Para elegir a otra hay que cancelar. */
  const personaFija = intentoPendiente
    ? personal.find((persona) => persona.id === intentoPendiente.usuarioId) ?? null
    : null;
  const persona = personaFija ?? personaVisible(personal, busqueda, elegido);
  const opciones = filtrarPadron(personal, busqueda);

  function abrir(lecturaId) {
    setAviso(null);
    setBusqueda('');
    setElegido('');
    onAbrir(lecturaId);
  }

  function cerrar() {
    if (enviando) return;
    if (abierta !== null) identificador.current.olvidar(abierta);
    setBusqueda('');
    setElegido('');
    onAbrir(null);
  }

  async function confirmar() {
    if (enviando || abierta === null || !persona) return;
    /* Fuera de la lista y sin intento por repetir: ya no hay nada que confirmar. */
    if (!lecturaAbierta && !intentoPendiente) return;
    setEnviando(true);
    let resultado;
    try {
      resultado = await identificador.current.confirmar(abierta, persona.id);
    } catch (fallo) {
      resultado = { estado: 'error', detalle: fallo.message };
    }
    if (!montado.current) return;
    setEnviando(false);
    if (resultado === null) return;
    const nuevo = avisoDeIdentificacion(resultado, persona);
    setAviso(nuevo);
    if (nuevo.cerrar) {
      setBusqueda('');
      setElegido('');
      onAbrir(null);
    } else if (!nuevo.repetir) {
      setElegido('');
    }
    if (!nuevo.repetir) onResultado(resultado);
  }

  const servicio = pendientes?.servicio ?? null;

  return (
    <section className="identificar" aria-label="Huellas por identificar">
      <header className="identificar__cabecera">
        <span className="identificar__icono" aria-hidden="true">
          <IconoHuella tamano={20} />
        </span>
        <div className="identificar__titulos">
          <h2 className="identificar__titulo">Huellas por identificar</h2>
          <p className="identificar__servicio">
            {servicio
              ? `${servicio.comida} · se pueden identificar hasta las ${horaCortaServidor(servicio.fin)}`
              : pendientes ? 'No hay un servicio en curso' : 'Consultando el servicio…'}
          </p>
        </div>
        <Etiqueta tono={lecturas.length > 0 ? 'aviso' : 'neutro'}>{String(pendientes?.total ?? 0)}</Etiqueta>
      </header>

      {aviso ? <AvisoIdentificacion aviso={aviso} onCerrar={() => setAviso(null)} /> : null}

      {error ? (
        <p className="identificar__estado identificar__estado--error" role="alert">
          {lecturas.length > 0 ? 'Sin actualizar: se muestran las últimas huellas recibidas. ' : ''}
          {error}
        </p>
      ) : null}

      {!pendientes && !error ? (
        <p className="identificar__estado" role="status">Consultando huellas por identificar…</p>
      ) : null}

      {pendientes && lecturas.length === 0 && abierta === null ? (
        <p className="identificar__estado" role="status">
          No hay huellas sin reconocer pendientes en este servicio.
        </p>
      ) : null}

      {lecturas.length > 0 ? (
        <ul className="identificar__lista">
          {lecturas.map((lectura) => {
            const activa = lectura.id === abierta;
            return (
              <li key={lectura.clave} className={`identificar__fila${activa ? ' identificar__fila--activa' : ''}`}>
                <div className="identificar__fila-datos">
                  <strong className="identificar__hora">{lectura.hora}</strong>
                  <span className="identificar__sub">
                    {[lectura.comida, lectura.dispositivo].filter(Boolean).join(' · ')}
                  </span>
                </div>
                {activa ? null : (
                  <Boton tamano="sm" onClick={() => abrir(lectura.id)} disabled={enviando}>
                    Identificar
                  </Boton>
                )}
              </li>
            );
          })}
        </ul>
      ) : null}

      {pendientes?.truncado ? (
        <p className="identificar__nota" role="status">
          Hay más huellas pendientes de las que caben en la lista.
        </p>
      ) : null}

      {abierta !== null ? (
        <div className="identificar__panel" role="group" aria-label="Identificar a la persona">
          {!lecturaAbierta ? (
            <p className="identificar__estado identificar__estado--aviso" role="status">
              {intentoPendiente
                ? 'Esta huella ya no figura como pendiente. Vuelva a confirmar para saber si su entrega quedó registrada.'
                : 'Esta huella ya no está pendiente: la resolvió alguien o terminó el servicio.'}
            </p>
          ) : (
            <p className="identificar__lectura">
              Huella no reconocida de las <strong>{lecturaAbierta.hora}</strong>
              {lecturaAbierta.identificableHasta
                ? ` · hasta las ${horaCortaServidor(lecturaAbierta.identificableHasta)}`
                : ''}
            </p>
          )}

          {cargandoPadron ? (
            <p className="identificar__estado" role="status">Cargando padrón…</p>
          ) : errorPadron ? (
            <p className="identificar__estado identificar__estado--error" role="alert">
              No se puede identificar: el padrón no se cargó. {errorPadron}
            </p>
          ) : personal.length === 0 ? (
            <p className="identificar__estado" role="status">El padrón no tiene comensales para elegir.</p>
          ) : personaFija ? null : (
            <div className="identificar__campos">
              <div className="identificar__buscador">
                <span className="identificar__buscador-icono" aria-hidden="true">
                  <IconoBuscar tamano={16} />
                </span>
                <input
                  type="text"
                  className="identificar__input"
                  value={busqueda}
                  onChange={(e) => {
                    setBusqueda(e.target.value);
                    if (elegido && !personaVisible(personal, e.target.value, elegido)) setElegido('');
                  }}
                  placeholder="Buscar por nombre o legajo…"
                  aria-label="Buscar a la persona en el padrón"
                  disabled={enviando || (!lecturaAbierta && !intentoPendiente)}
                />
              </div>
              <label className="solo-lectores" htmlFor="identificar-persona">Persona</label>
              <select
                id="identificar-persona"
                className="identificar__select"
                value={persona ? elegido : ''}
                onChange={(e) => setElegido(e.target.value)}
                disabled={enviando || (!lecturaAbierta && !intentoPendiente)}
              >
                <option value="">
                  {opciones.length === 0 ? 'Ninguna persona coincide' : 'Seleccione a la persona…'}
                </option>
                {opciones.map((p) => (
                  <option key={p.id} value={String(p.id)}>
                    {p.nombre} — {p.categoria} ({p.legajo})
                  </option>
                ))}
              </select>
            </div>
          )}

          {persona ? (
            <p className="identificar__identidad">
              <strong>{persona.nombre}</strong>
              <span>{persona.categoria} · Legajo {persona.legajo}</span>
            </p>
          ) : null}

          <div className="identificar__acciones">
            <Boton
              onClick={confirmar}
              disabled={enviando || !persona || (!lecturaAbierta && !intentoPendiente)}
              icono={<IconoCheck tamano={18} />}
            >
              {enviando ? 'Confirmando…' : intentoPendiente ? 'Volver a confirmar' : 'Confirmar entrega'}
            </Boton>
            <Boton variante="secundario" onClick={cerrar} disabled={enviando}>
              {lecturaAbierta || intentoPendiente ? 'Cancelar' : 'Cerrar'}
            </Boton>
          </div>
        </div>
      ) : null}
    </section>
  );
}

/** Resultado de un intento: entrega, rechazo, aviso para repetir o error. */
function AvisoIdentificacion({ aviso, onCerrar }) {
  return (
    <div
      className={`identificar__aviso identificar__aviso--${aviso.tipo}`}
      role={aviso.tipo === 'exito' ? 'status' : 'alert'}
    >
      <span className="identificar__aviso-icono" aria-hidden="true">
        {aviso.tipo === 'exito' ? <IconoCheck tamano={18} /> : <IconoAlerta tamano={18} />}
      </span>
      <div className="identificar__aviso-texto">
        <strong>{aviso.titulo}</strong>
        {aviso.detalle ? <p>{aviso.detalle}</p> : null}
      </div>
      <button type="button" className="identificar__aviso-cerrar" onClick={onCerrar} aria-label="Cerrar aviso">
        ×
      </button>
    </div>
  );
}
