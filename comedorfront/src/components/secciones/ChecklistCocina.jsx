import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ErrorApi,
  desmarcarEnChecklist,
  desmarcarPoliciaEnChecklist,
  marcarEnChecklist,
  obtenerChecklist,
} from '../../api.js';
import {
  FILTROS_CHECKLIST,
  MS_CICLO_CHECKLIST,
  avisoDeMarca,
  contarChecklist,
  etiquetaDeMetodo,
  filtrarChecklist,
  horaDeEntrega,
  serviciosDeChecklist,
} from '../../checklist.js';
import AppSelect from '../ui/AppSelect.jsx';
import RegistrarPolicia from './RegistrarPolicia.jsx';
import Boton from '../ui/Boton.jsx';
import { IconoAlerta, IconoBuscar, IconoCheck, IconoEscudo, IconoRecargar } from '../ui/Iconos.jsx';
import './Supervision.css';
import './ChecklistCocina.css';

const FECHA_LARGA = new Intl.DateTimeFormat('es-BO', { weekday: 'long', day: 'numeric', month: 'long' });

function fechaLarga(iso) {
  if (typeof iso !== 'string') return '';
  const [anio, mes, dia] = iso.split('-').map(Number);
  const texto = FECHA_LARGA.format(new Date(anio, mes - 1, dia));
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}

/**
 * Checklist de cocina: pantalla principal de la cocinera mientras no esté el
 * lector. Lista a quienes les corresponde la comida en curso y marca la
 * entrega; el servidor vuelve a aplicar todas las reglas en cada marca.
 */
export default function ChecklistCocina({
  datosIniciales = null,
  filtroInicial = 'pendientes',
}) {
  const [datos, setDatos] = useState(datosIniciales);
  const [cargando, setCargando] = useState(datosIniciales === null);
  const [error, setError] = useState('');
  const [filtro, setFiltro] = useState(filtroInicial);
  const [busqueda, setBusqueda] = useState('');
  const [servicio, setServicio] = useState('todos');
  const [enCurso, setEnCurso] = useState(() => new Set());
  const [aviso, setAviso] = useState(null);
  const controlador = useRef(null);
  const buscadorRef = useRef(null);

  const cargar = useCallback(async () => {
    controlador.current?.abort();
    const propio = new AbortController();
    controlador.current = propio;
    try {
      const respuesta = await obtenerChecklist({ signal: propio.signal });
      if (propio.signal.aborted) return;
      setDatos(respuesta);
      setError('');
    } catch (causa) {
      if (!propio.signal.aborted) setError(causa.message);
    } finally {
      if (!propio.signal.aborted) setCargando(false);
    }
  }, []);

  useEffect(() => {
    cargar();
    const intervalo = setInterval(cargar, MS_CICLO_CHECKLIST);
    return () => {
      clearInterval(intervalo);
      controlador.current?.abort();
    };
  }, [cargar]);

  const personas = datos?.personas ?? [];
  const policias = datos?.policias ?? [];

  const conteo = useMemo(() => contarChecklist(personas), [personas]);
  const servicios = useMemo(() => serviciosDeChecklist(personas), [personas]);
  const visibles = useMemo(
    () => filtrarChecklist(personas, { estado: filtro, busqueda, servicio }),
    [personas, filtro, busqueda, servicio],
  );

  function ocupar(id, valor) {
    setEnCurso((actual) => {
      const siguiente = new Set(actual);
      if (valor) siguiente.add(id); else siguiente.delete(id);
      return siguiente;
    });
  }

  async function entregar(persona) {
    if (enCurso.has(persona.id)) return;
    ocupar(persona.id, true);
    try {
      const respuesta = await marcarEnChecklist(persona.id);
      setAviso(avisoDeMarca(respuesta, persona.nombre));
      // Entregó a quien buscó: el buscador queda vacío y listo para el siguiente de la fila.
      if (respuesta?.valido && busqueda) {
        setBusqueda('');
        buscadorRef.current?.focus();
      }
    } catch (causa) {
      setAviso({ tipo: 'error', texto: `No se pudo confirmar la entrega: ${causa.message} Revise la lista antes de repetir.` });
    } finally {
      ocupar(persona.id, false);
      await cargar();
    }
  }

  async function deshacer(persona) {
    if (enCurso.has(persona.id) || !persona.asistenciaId) return;
    ocupar(persona.id, true);
    try {
      await desmarcarEnChecklist(persona.asistenciaId);
      setAviso({ tipo: 'info', texto: `Se deshizo la entrega a ${persona.nombre}.` });
    } catch (causa) {
      const detalle = causa instanceof ErrorApi ? (causa.datos?.detail ?? causa.message) : causa.message;
      setAviso({ tipo: 'error', texto: detalle });
    } finally {
      ocupar(persona.id, false);
      await cargar();
    }
  }

  async function policiaRegistrado(respuesta) {
    setAviso(respuesta.valido
      ? { tipo: 'exito', texto: 'Ración de policía registrada.' }
      : { tipo: 'error', texto: respuesta.detalle || 'No se registró la ración del policía.' });
    await cargar();
  }

  async function deshacerPolicia(policia) {
    const clave = `policia:${policia.id}`;
    if (enCurso.has(clave)) return;
    ocupar(clave, true);
    try {
      await desmarcarPoliciaEnChecklist(policia.id);
      setAviso({ tipo: 'info', texto: 'Se deshizo una ración de policía.' });
    } catch (causa) {
      const detalle = causa instanceof ErrorApi ? (causa.datos?.detail ?? causa.message) : causa.message;
      setAviso({ tipo: 'error', texto: detalle });
    } finally {
      ocupar(clave, false);
      await cargar();
    }
  }

  const porcentaje = conteo.total ? Math.round((conteo.entregadas / conteo.total) * 100) : 0;

  let contenido;
  if (cargando && !datos) {
    contenido = <p className="supervision__estado" role="status">Cargando la lista de la comida…</p>;
  } else if (!datos) {
    contenido = (
      <div className="supervision__error" role="alert">
        <p>{error || 'No se pudo cargar la lista.'}</p>
        <Boton variante="secundario" tamano="sm" onClick={cargar}>Reintentar</Boton>
      </div>
    );
  } else if (datos.fueraDeHorario) {
    contenido = (
      <div className="checklist__fuera" role="status">
        <span className="checklist__fuera-icono" aria-hidden="true"><IconoAlerta tamano={26} /></span>
        <div>
          <strong>Fuera de horario</strong>
          <p>No hay una comida en curso. La lista aparece sola cuando empiece la próxima comida.</p>
        </div>
      </div>
    );
  } else {
    contenido = (
      <>
        <div className="checklist__resumen">
          <div className="checklist__comida">
            <span className="checklist__eyebrow">Comida en curso</span>
            <h2 className="checklist__titulo">{datos.comida}</h2>
            <span className="checklist__fecha">{fechaLarga(datos.fechaComida)}</span>
          </div>
          <dl className="checklist__cifras">
            <div className="checklist__cifra checklist__cifra--entregadas">
              <dt>Entregadas</dt>
              <dd>{conteo.entregadas}</dd>
            </div>
            <div className="checklist__cifra">
              <dt>Pendientes</dt>
              <dd>{conteo.pendientes}</dd>
            </div>
            <div className="checklist__cifra">
              <dt>Con derecho</dt>
              <dd>{conteo.total}</dd>
            </div>
            <div className="checklist__cifra checklist__cifra--policias">
              <dt>Policías</dt>
              <dd>{policias.length}</dd>
            </div>
          </dl>
          <div className="checklist__progreso" role="progressbar" aria-valuemin={0} aria-valuemax={100}
            aria-valuenow={porcentaje} aria-label="Avance de entregas">
            <span style={{ width: `${porcentaje}%` }} />
          </div>
        </div>

        <div className="checklist__barra">
          <div className="supervision__filtros checklist__filtros">
            <div className="supervision__chips-filtro" role="tablist" aria-label="Filtrar por entrega">
              {FILTROS_CHECKLIST.map(([valor, etiqueta]) => (
                <button
                  key={valor}
                  type="button"
                  role="tab"
                  aria-selected={filtro === valor}
                  className={`supervision__chip${filtro === valor ? ' supervision__chip--activo' : ''}`}
                  onClick={() => setFiltro(valor)}
                >
                  {etiqueta}
                  <span className="checklist__chip-cuenta">
                    {valor === 'pendientes' ? conteo.pendientes : valor === 'entregadas' ? conteo.entregadas : conteo.total}
                  </span>
                </button>
              ))}
            </div>

            <div className="supervision__buscador">
              <span className="supervision__buscador-icono" aria-hidden="true">
                <IconoBuscar tamano={16} />
              </span>
              <input
                ref={buscadorRef}
                type="text"
                className="supervision__buscador-input"
                value={busqueda}
                onChange={(e) => setBusqueda(e.target.value)}
                placeholder="Buscar por nombre…"
                aria-label="Buscar por nombre"
              />
              {busqueda ? (
                <button type="button" className="supervision__buscador-limpiar" onClick={() => setBusqueda('')}
                  aria-label="Limpiar búsqueda">
                  ×
                </button>
              ) : null}
            </div>

            {servicios.length > 1 ? (
              <AppSelect
                id="checklist-servicio"
                className="checklist__servicio"
                value={servicio}
                onChange={setServicio}
                options={[
                  { value: 'todos', label: 'Todos los servicios' },
                  ...servicios.map((s) => ({ value: s, label: s })),
                ]}
              />
            ) : null}

            <Boton variante="secundario" tamano="sm" icono={<IconoRecargar tamano={16} />} onClick={cargar}>
              Actualizar
            </Boton>
            <RegistrarPolicia onRegistrado={policiaRegistrado} />
          </div>

          {error ? <p className="checklist__aviso checklist__aviso--error" role="alert">{error}</p> : null}
          {aviso ? (
            <p className={`checklist__aviso checklist__aviso--${aviso.tipo}`} role="status">
              {aviso.texto}
            </p>
          ) : null}
        </div>

        {policias.length > 0 && !busqueda && servicio === 'todos' ? (
          <section className="checklist__policias" aria-label={`Policías en ${datos.comida}`}>
            <h3 className="checklist__policias-titulo">
              <IconoEscudo tamano={18} />
              Policías registrados
              <span className="checklist__chip-cuenta">{policias.length}</span>
            </h3>
            <ul className="checklist__lista">
              {policias.map((policia) => (
                <li key={policia.id} className="checklist__fila checklist__fila--entregada checklist__fila--policia">
                  <div className="checklist__marca">
                    <span className="checklist__casilla" aria-hidden="true"><IconoEscudo tamano={18} /></span>
                    <span className="checklist__persona">
                      <span className="checklist__nombre">{policia.nombre}</span>
                      <span className="checklist__meta">Columna Policías · sin nombre</span>
                    </span>
                  </div>
                  <div className="checklist__estado">
                    <span className="checklist__sello">
                      <IconoCheck tamano={13} />
                      {policia.origen === 'checklist' ? 'Checklist' : 'Huella'} · {horaDeEntrega(policia.fechaHora)}
                    </span>
                    {policia.anulable ? (
                      <Boton variante="secundario" tamano="sm" disabled={enCurso.has(`policia:${policia.id}`)}
                        onClick={() => deshacerPolicia(policia)}
                        tooltip="Solo si se registró por error; vale hasta que termine esta comida">
                        Deshacer
                      </Boton>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {visibles.length === 0 ? (
          <p className="supervision__vacio" role="status">
            {conteo.total === 0 ? 'Nadie tiene derecho a esta comida.'
              : filtro === 'pendientes' && !busqueda && servicio === 'todos'
                ? 'Todas las raciones de esta comida ya fueron entregadas.'
                : 'No hay personas con ese filtro.'}
          </p>
        ) : (
          <ul className="checklist__lista" aria-label={`Personas con derecho a ${datos.comida}`}>
            {visibles.map((persona) => {
              const ocupada = enCurso.has(persona.id);
              const meta = [persona.categoria, persona.servicio, persona.turno].filter(Boolean).join(' · ');
              return (
                <li key={persona.id} className={`checklist__fila${persona.servida ? ' checklist__fila--entregada' : ''}`}>
                  <button
                    type="button"
                    className="checklist__marca"
                    role="checkbox"
                    aria-checked={persona.servida}
                    aria-label={persona.servida ? `${persona.nombre}: ración entregada` : `Entregar ración a ${persona.nombre}`}
                    disabled={persona.servida || ocupada}
                    onClick={() => entregar(persona)}
                  >
                    <span className="checklist__casilla" aria-hidden="true">
                      {persona.servida ? <IconoCheck tamano={18} /> : null}
                    </span>
                    <span className="checklist__persona">
                      <span className="checklist__nombre">{persona.nombre}</span>
                      {meta ? <span className="checklist__meta">{meta}</span> : null}
                    </span>
                    {persona.servida ? null : (
                      <span className="checklist__cta" aria-hidden="true">
                        {ocupada ? 'Registrando…' : 'Entregar'}
                      </span>
                    )}
                  </button>
                  {persona.servida ? (
                    <div className="checklist__estado">
                      <span className="checklist__sello">
                        <IconoCheck tamano={13} />
                        {etiquetaDeMetodo(persona.metodo)} · {horaDeEntrega(persona.fechaHora)}
                      </span>
                      {persona.anulable ? (
                        <Boton variante="secundario" tamano="sm" disabled={ocupada} onClick={() => deshacer(persona)}
                          tooltip="Solo si se marcó por error; vale hasta que termine esta comida">
                          Deshacer
                        </Boton>
                      ) : null}
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}

      </>
    );
  }

  return (
    <section className="checklist" aria-label="Checklist de comida">
      {contenido}
    </section>
  );
}
