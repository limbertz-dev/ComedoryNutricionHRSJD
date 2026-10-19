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
 * vuelve a comprobar derecho, servicio y duplicado.
 *
 * Si no se sabe qué quedó (resultado incierto u otra intervención en curso),
 * el intento sigue vivo con su persona y su clave: cerrar el panel no lo
 * cancela, sigue listado en «Por verificar» aunque la huella salga de los
 * pendientes, y al reabrirlo solo se ofrece verificarlo con la misma persona.
 *
 * `abierta` (id de la lectura) y `onAbrir` los controla Control Biométrico,
 * para que el resultado del lector pueda abrir directamente su huella.
 * `identificador` reemplaza al propio (para las pruebas); `identificar`
 * reemplaza solo el POST.
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
  onCambiarPersona = () => {},
  identificar,
  identificador: identificadorExterno = null,
  elegidoInicial = '',
  busquedaInicial = '',
  avisoInicial = null,
}) {
  const [busqueda, setBusqueda] = useState(busquedaInicial);
  const [elegido, setElegido] = useState(String(elegidoInicial));
  const [enviando, setEnviando] = useState(false);
  const [aviso, setAviso] = useState(avisoInicial);

  /* Un solo identificador mientras la pantalla esté montada: guarda los
     intentos sin resolver (con su clave y su persona) y bloquea el doble
     envío. No es global: otra sesión en la misma PC empieza sin intentos
     ajenos, porque la clave vale por cuenta. */
  const propio = useRef(null);
  if (identificadorExterno === null && propio.current === null) {
    propio.current = crearIdentificador(identificar ? { identificar } : {});
  }
  const identificador = identificadorExterno ?? propio.current;
  const montado = useRef(true);
  useEffect(() => () => { montado.current = false; }, []);

  /* Al cambiar de lectura desde Marcaciones del turno, limpia búsqueda y
     selección previa para no preseleccionar ni arrastrar otro comensal. */
  const abiertaPrevia = useRef(abierta);
  useEffect(() => {
    if (abiertaPrevia.current === abierta) return;
    abiertaPrevia.current = abierta;
    setBusqueda('');
    setElegido('');
  }, [abierta]);

  const lecturas = pendientes?.lecturas ?? [];
  const sinResolver = identificador.pendientes();
  const lecturaAbierta = abierta === null ? null : lecturas.find((lectura) => lectura.id === abierta) ?? null;
  const intento = abierta === null ? null : identificador.pendiente(abierta);
  /* Con un intento sin resolver, la persona es la del intento (su copia, no
     el padrón): verificar es repetir esa misma decisión. */
  const persona = intento ? intento.persona : personaVisible(personal, busqueda, elegido);
  const opciones = filtrarPadron(personal, busqueda);
  const puedeEnviar = !enviando && persona !== null && (intento !== null || lecturaAbierta !== null);
  const porVerificar = sinResolver.filter((pendiente) => pendiente.lecturaId !== abierta);

  const idPersonaActiva = abierta !== null && persona?.id ? persona.id : null;
  useEffect(() => {
    onCambiarPersona(idPersonaActiva);
  }, [idPersonaActiva, onCambiarPersona]);

  function abrir(lecturaId) {
    setAviso(null);
    setBusqueda('');
    setElegido('');
    onAbrir(lecturaId);
  }

  /* Cerrar solo oculta el panel: un intento sin resolver queda en «Por verificar». */
  function cerrar() {
    if (enviando) return;
    setBusqueda('');
    setElegido('');
    onAbrir(null);
  }

  async function confirmar() {
    if (!puedeEnviar) return;
    setEnviando(true);
    const resultado = intento
      ? await identificador.verificar(abierta)
      : await identificador.confirmar(lecturaAbierta, persona);
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
  const total = pendientes?.total ?? 0;

  return (
    <section
      className={`identificar${abierta !== null ? ' identificar--abierta' : ''}`}
      aria-label="Huellas por identificar"
    >
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
        <Etiqueta tono={lecturas.length > 0 ? 'aviso' : 'neutro'}>{String(total)}</Etiqueta>
      </header>

      {aviso ? <AvisoIdentificacion aviso={aviso} onCerrar={() => setAviso(null)} /> : null}

      {porVerificar.length > 0 ? (
        <div className="identificar__verificar" role="group" aria-label="Entregas por verificar">
          <p className="identificar__verificar-titulo">
            <IconoAlerta tamano={16} /> Por verificar
          </p>
          <ul className="identificar__lista">
            {porVerificar.map((pendiente) => (
              <li key={pendiente.lecturaId} className="identificar__fila identificar__fila--verificar">
                <div className="identificar__fila-datos">
                  <strong className="identificar__hora">{pendiente.persona.nombre ?? `Comensal ${pendiente.usuarioId}`}</strong>
                  <span className="identificar__sub">
                    {['Huella', pendiente.lectura.hora, pendiente.lectura.comida].filter(Boolean).join(' · ')}
                  </span>
                </div>
                <Boton tamano="sm" onClick={() => abrir(pendiente.lecturaId)} disabled={enviando}>
                  Verificar
                </Boton>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {error ? (
        <p className="identificar__estado identificar__estado--error" role="alert">
          {lecturas.length > 0 ? 'Sin actualizar: se muestran las últimas huellas recibidas. ' : ''}
          {error}
        </p>
      ) : null}

      {!pendientes && !error ? (
        <p className="identificar__estado" role="status">Consultando huellas por identificar…</p>
      ) : null}

      {pendientes && lecturas.length === 0 && abierta === null && sinResolver.length === 0 ? (
        <p className="identificar__estado" role="status">
          No hay huellas sin reconocer pendientes en este servicio.
        </p>
      ) : null}

      {lecturas.length > 0 ? (
        <ul className="identificar__lista">
          {lecturas.map((lectura) => {
            const activa = lectura.id === abierta;
            const conIntento = sinResolver.some((pendiente) => pendiente.lecturaId === lectura.id);
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
                    {conIntento ? 'Verificar' : 'Identificar'}
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
          {lecturaAbierta ? (
            <div className="identificar__lectura-bloque">
              <div className="identificar__lectura-encabezado">
                <span className="identificar__paso">1. Lectura seleccionada</span>
                <Etiqueta tono="aviso">Huella no reconocida</Etiqueta>
              </div>
              <p className="identificar__lectura">
                Huella no reconocida de las <strong>{lecturaAbierta.hora}</strong>
                {[lecturaAbierta.comida, lecturaAbierta.dispositivo].filter(Boolean).length > 0
                  ? ` · ${[lecturaAbierta.comida, lecturaAbierta.dispositivo].filter(Boolean).join(' · ')}`
                  : ''}
                {lecturaAbierta.identificableHasta
                  ? ` · hasta las ${horaCortaServidor(lecturaAbierta.identificableHasta)}`
                  : ''}
              </p>
              <p className="identificar__lectura-aclaracion">
                El lector no reconoció la huella: la identidad aún se desconoce y esto no demuestra falta de turno.
              </p>
            </div>
          ) : intento ? (
            <p className="identificar__estado identificar__estado--aviso" role="status">
              Esta huella ya no figura como pendiente. Eso no confirma la entrega: pudo terminar el
              servicio. Verifíquela con la misma solicitud para saber qué quedó.
            </p>
          ) : (
            <p className="identificar__estado identificar__estado--aviso" role="status">
              Esta huella ya no está pendiente: la resolvió alguien o terminó el servicio.
            </p>
          )}

          {intento ? (
            <p className="identificar__bloqueo" role="status">
              Entrega por verificar con esta persona. No se puede elegir a otra hasta verificarla.
            </p>
          ) : !lecturaAbierta ? null : cargandoPadron ? (
            <p className="identificar__estado" role="status">Cargando padrón…</p>
          ) : errorPadron ? (
            <p className="identificar__estado identificar__estado--error" role="alert">
              No se puede identificar: el padrón no se cargó. {errorPadron}
            </p>
          ) : personal.length === 0 ? (
            <p className="identificar__estado" role="status">El padrón no tiene comensales para elegir.</p>
          ) : (
            <div className="identificar__campos">
              <span className="identificar__paso">2. Buscar y elegir comensal del padrón</span>
              <div className="identificar__controles">
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
                    disabled={enviando}
                  />
                </div>
                <label className="solo-lectores" htmlFor="identificar-persona">Persona</label>
                <select
                  id="identificar-persona"
                  className="identificar__select"
                  value={persona ? elegido : ''}
                  onChange={(e) => setElegido(e.target.value)}
                  disabled={enviando}
                >
                  <option value="">
                    {opciones.length === 0 ? 'Ninguna persona coincide' : 'Seleccione a la persona…'}
                  </option>
                  {opciones.map((p) => (
                    <option key={p.id} value={String(p.id)}>
                      {p.nombre} — {p.categoria} (Legajo {p.legajo})
                    </option>
                  ))}
                </select>
              </div>
            </div>
          )}

          {persona ? (
            <div className="identificar__identidad" aria-label="Comensal seleccionado">
              <span className="identificar__identidad-etiqueta">
                {intento ? 'Identidad del intento por verificar' : '3. Identidad seleccionada'}
              </span>
              <strong>{persona.nombre ?? `Comensal ${persona.id}`}</strong>
              <span className="identificar__identidad-meta">
                {[persona.categoria, persona.legajo ? `Legajo ${persona.legajo}` : null].filter(Boolean).join(' · ')}
              </span>
            </div>
          ) : lecturaAbierta && !cargandoPadron && !errorPadron && personal.length > 0 ? (
            <p className="identificar__identidad identificar__identidad--vacia">
              3. Sin comensal preseleccionado: busque por nombre o legajo y elija a la persona para confirmar la entrega.
            </p>
          ) : null}

          <div className="identificar__acciones">
            <Boton onClick={confirmar} disabled={!puedeEnviar} icono={<IconoCheck tamano={18} />}>
              {enviando ? 'Confirmando…' : intento ? 'Verificar entrega' : 'Confirmar entrega'}
            </Boton>
            <Boton variante="secundario" onClick={cerrar} disabled={enviando}>
              {lecturaAbierta && !intento ? 'Cancelar' : 'Cerrar'}
            </Boton>
          </div>
        </div>
      ) : null}
    </section>
  );
}

/** Resultado de un intento: entrega, rechazo, aviso para verificar o error. */
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
