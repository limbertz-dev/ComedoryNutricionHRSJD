import { useEffect, useRef, useState } from 'react';
import Boton from '../ui/Boton.jsx';
import { IconoBuscar, IconoCheck, IconoHuella } from '../ui/Iconos.jsx';
import { capturarHuellaQa, leerHuellaQa, nuevaClaveIdempotencia, obtenerPersonasEnrolamiento } from '../../api.js';
import { filtrarPadron } from './RegistroManual.jsx';
import './RegistrarHuella.css';

/** El titular se elige antes de iniciar la captura; una captura incierta conserva su identidad. */
export default function RegistrarHuella({
  onCerrar,
  consultar = obtenerPersonasEnrolamiento,
  capturar = capturarHuellaQa,
  leer = leerHuellaQa,
  onLectura = () => {},
  personasIniciales = null,
  elegidoInicial = '',
  resultadoInicial = null,
  usuarioRequerido = null,
  volverAlSimulador = false,
}) {
  const [personas, setPersonas] = useState(personasIniciales);
  const [busqueda, setBusqueda] = useState('');
  const [categoria, setCategoria] = useState('');
  const [servicio, setServicio] = useState('');
  const [elegido, setElegido] = useState(String(elegidoInicial));
  const [error, setError] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [incierto, setIncierto] = useState(false);
  const [resultado, setResultado] = useState(resultadoInicial);
  const [lectura, setLectura] = useState(null);
  const [leyendo, setLeyendo] = useState(false);
  const [lecturaIncierta, setLecturaIncierta] = useState(false);
  const solicitudLectura = useRef(null);
  const [recarga, setRecarga] = useState(0);
  const solicitud = useRef(null);
  const enCurso = useRef(false);
  const montado = useRef(true);
  const titulo = useRef(null);

  useEffect(() => {
    montado.current = true;
    titulo.current?.focus();
    return () => { montado.current = false; };
  }, []);

  useEffect(() => {
    if (personasIniciales !== null && recarga === 0) return undefined;
    const controlador = new AbortController();
    setError('');
    consultar({ signal: controlador.signal }).then(datos => {
      if (!controlador.signal.aborted) setPersonas(usuarioRequerido === null ? datos : datos.filter(p => p.id === usuarioRequerido));
    }).catch(fallo => {
      if (!controlador.signal.aborted) setError(fallo.message);
    });
    return () => controlador.abort();
  }, [consultar, personasIniciales, recarga, usuarioRequerido]);

  const perfiles = (personas ?? []).filter(p => (!categoria || p.categoria === categoria)
    && (!servicio || (p.servicio ?? 'Sin servicio') === servicio));
  const opciones = filtrarPadron(perfiles, busqueda);
  const categorias = [...new Set((personas ?? []).map(p => p.categoria))].sort();
  const servicios = [...new Set((personas ?? []).filter(p => !categoria || p.categoria === categoria)
    .map(p => p.servicio ?? 'Sin servicio'))].sort();
  const persona = (personas ?? []).find(p => String(p.id) === elegido) ?? null;
  const bloqueado = enviando || incierto || resultado !== null;

  function seleccionar(valor) {
    if (bloqueado) return;
    setElegido(valor);
    solicitud.current = null;
    setError('');
  }

  async function registrar() {
    if (enCurso.current || !persona || resultado) return;
    solicitud.current ??= { usuarioId: persona.id, clave: nuevaClaveIdempotencia() };
    enCurso.current = true;
    setEnviando(true);
    setError('');
    try {
      const datos = await capturar(solicitud.current.usuarioId, solicitud.current.clave);
      if (montado.current) { setResultado(datos); setIncierto(false); }
    } catch (fallo) {
      if (montado.current) {
        const definitivo = fallo.status >= 400 && fallo.status < 500;
        setIncierto(!definitivo);
        setError(fallo.message);
        if (definitivo) solicitud.current = null;
      }
    } finally {
      enCurso.current = false;
      if (montado.current) setEnviando(false);
    }
  }

  async function probarLectura() {
    if (enCurso.current || !resultado?.referencia) return;
    solicitudLectura.current ??= nuevaClaveIdempotencia();
    enCurso.current = true;
    setLeyendo(true);
    setError('');
    let registrada = null;
    try {
      const datos = await leer(resultado.referencia, solicitudLectura.current);
      if (montado.current) {
        setLectura(datos);
        setLecturaIncierta(false);
        solicitudLectura.current = null;
        registrada = datos;
      }
    } catch (fallo) {
      if (montado.current) {
        setError(fallo.message);
        const definitivo = fallo.status >= 400 && fallo.status < 500;
        setLecturaIncierta(!definitivo);
        if (definitivo) solicitudLectura.current = null;
      }
    } finally {
      enCurso.current = false;
      if (montado.current) setLeyendo(false);
    }
    if (registrada) onLectura(registrada);
  }

  return (
    <section className="registro-huella" aria-labelledby="registro-huella-titulo">
      <header className="registro-huella__cabecera">
        <div>
          <span className="registro-huella__modo">Captura simulada · QA</span>
          <h2 id="registro-huella-titulo" ref={titulo} tabIndex={-1}>
            {resultado ? 'Huella registrada' : 'Registrar huella'}
          </h2>
        </div>
        <Boton variante="secundario" onClick={onCerrar} disabled={enviando || leyendo || lecturaIncierta}>
          {volverAlSimulador ? 'Volver al simulador' : resultado ? 'Volver a marcaciones' : 'Cancelar'}
        </Boton>
      </header>

      {resultado ? (
        <div className="registro-huella__exito" role="status">
          <IconoCheck tamano={64} />
          <h3>{persona?.nombre}</h3>
          <p>Legajo {persona?.legajo}</p>
          <p>{resultado.ya_registrada ? 'Esta persona ya tenía una huella de prueba registrada.' : 'La huella de prueba quedó vinculada a esta persona.'}</p>
          {!lectura && !leyendo && !lecturaIncierta ? <p>El vínculo se conserva al volver a entrar. El alta no registra ninguna comida.</p> : null}
          {volverAlSimulador ? <Boton onClick={onCerrar}>Continuar con el caso</Boton> : <Boton onClick={probarLectura} disabled={leyendo}>
            {leyendo ? 'Leyendo…' : lecturaIncierta ? 'Verificar lectura' : lectura ? 'Volver a leer' : 'Leer huella de prueba'}
          </Boton>}
          {lectura ? <div className={`registro-huella__lectura${lectura.valido ? '' : ' registro-huella__lectura--rechazada'}`} role="status">
            <strong>{lectura.valido ? 'Huella reconocida · Entrega registrada' : 'Huella reconocida · Entrega rechazada'}</strong>
            <p>{lectura.detalle}</p>
          </div> : null}
          {lecturaIncierta ? <p role="status">No se pudo confirmar la entrega. Verifica esta misma lectura antes de iniciar otra.</p> : null}
        </div>
      ) : (
        <>
          <div className="registro-huella__seleccion">
            <label className="registro-huella__paso" htmlFor="huella-persona">1. Selecciona a la persona</label>
            {personas === null ? <p role="status">{error ? 'No se pudo cargar el padrón.' : 'Cargando padrón…'}</p> : (
              <>
                <div className="registro-huella__filtros">
                  <label>Categoría<select aria-label="Filtrar por categoría" value={categoria} disabled={bloqueado}
                    onChange={e => { setCategoria(e.target.value); setServicio(''); seleccionar(''); }}>
                    <option value="">Todas las permitidas</option>
                    {categorias.map(c => <option key={c}>{c}</option>)}
                  </select></label>
                  <label>Servicio<select aria-label="Filtrar por servicio" value={servicio} disabled={bloqueado}
                    onChange={e => { setServicio(e.target.value); seleccionar(''); }}>
                    <option value="">Todos los servicios</option>
                    {servicios.map(s => <option key={s}>{s}</option>)}
                  </select></label>
                </div>
                <div className="registro-huella__controles">
                  <label className="registro-huella__busqueda">
                    <IconoBuscar tamano={18} />
                    <span className="solo-lectores">Buscar persona por nombre o legajo</span>
                    <input value={busqueda} disabled={bloqueado} placeholder="Buscar por nombre o legajo…"
                      onChange={e => { setBusqueda(e.target.value); seleccionar(''); }} />
                  </label>
                  <select id="huella-persona" value={elegido} disabled={bloqueado}
                    onChange={e => seleccionar(e.target.value)}>
                    <option value="">{opciones.length ? 'Selecciona a la persona…' : 'No hay coincidencias'}</option>
                    {opciones.map(p => <option key={p.id} value={String(p.id)}>
                      {p.nombre} · {p.legajo}{p.huella_registrada ? ' · Huella registrada' : ''}
                    </option>)}
                  </select>
                </div>
                {persona ? (
                  <div className="registro-huella__identidad">
                    <strong>{persona.nombre}</strong>
                    <span>{persona.categoria} · {persona.servicio ?? 'Sin servicio'} · Legajo {persona.legajo}</span>
                  </div>
                ) : <p className="registro-huella__ayuda">Elige a la persona antes de capturar su huella.</p>}
              </>
            )}
          </div>
          <div className="registro-huella__captura" aria-busy={enviando}>
            <span className="registro-huella__paso">2. Registra su huella</span>
            <IconoHuella tamano={88} />
            <h3>{enviando ? 'Registrando huella…' : incierto ? 'Verifica el registro' : 'Preparado para la captura'}</h3>
            <p>Mientras no haya un lector conectado, puedes registrar una huella de prueba.</p>
            {incierto ? <p role="status">Se conserva la persona seleccionada. Verifica con la misma solicitud antes de cambiarla.</p> : null}
            <Boton icono={<IconoHuella tamano={20} />} onClick={registrar} disabled={!persona || enviando}>
              {enviando ? 'Registrando…' : incierto ? 'Verificar registro' : 'Simular captura'}
            </Boton>
          </div>
        </>
      )}
      {error ? <div className="registro-huella__error" role="alert">
        <p>{error}</p>
        {personas === null ? <Boton variante="secundario" onClick={() => setRecarga(r => r + 1)}>Volver a cargar</Boton> : null}
      </div> : null}
    </section>
  );
}
