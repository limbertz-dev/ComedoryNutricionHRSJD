import { useCallback, useEffect, useMemo, useState } from 'react';
import Boton from '../ui/Boton.jsx';
import Etiqueta from '../ui/Etiqueta.jsx';
import Tarjeta from '../ui/Tarjeta.jsx';
import { IconoBuscar, IconoCheck, IconoEquis, IconoAlerta } from '../ui/Iconos.jsx';
import {
  autorizarMarcacionManual,
  obtenerResumenComidas,
  obtenerUltimasMarcaciones,
} from '../../api.js';
import './Supervision.css';

const ETIQUETAS_MOTIVOS = {
  no_identificado: 'Huella no reconocida (no identificado)',
  sin_derecho: 'Sin derecho en este turno',
  duplicado: 'Ya recibió su comida (duplicado)',
  fuera_horario: 'Fuera de horario',
  desconocido: 'Rechazo no clasificado',
};

/**
 * Sección de Supervisión del Comedor (para jefa de nutrición y sistemas).
 *
 * Estructura en este orden exacto:
 * (a) Una tarjeta por comida del día.
 * (b) «Rechazos por revisar», agrupados por motivo (único lugar con acciones).
 * (c) Feed de SOLO LECTURA con filtros por comida y por resultado.
 */
export default function Supervision({
  fecha,
  hoy,
  simulacion = null,
  personal = [],
  versionReloj = 0,
  onMarcacionExitosa,
}) {
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState(null);
  const [resumenComidas, setResumenComidas] = useState([]);
  const [marcaciones, setMarcaciones] = useState([]);

  /* Filtros del feed */
  const [filtroComidaId, setFiltroComidaId] = useState(null);
  const [filtroResultado, setFiltroResultado] = useState('todas');
  const [busqueda, setBusqueda] = useState('');

  /* Comensal seleccionado para autorizar cada rechazo no_identificado { [marcacionId]: comensalId } */
  const [comensalElegido, setComensalElegido] = useState({});
  const [autorizandoId, setAutorizandoId] = useState(null);
  const [errorAccion, setErrorAccion] = useState(null);

  const cargarDatos = useCallback(async (signal) => {
    setCargando(true);
    setError(null);
    try {
      const [resumen, ultimas] = await Promise.all([
        obtenerResumenComidas({ fecha, hoy, signal }),
        obtenerUltimasMarcaciones({ fecha, limite: 100, signal }),
      ]);
      if (!signal?.aborted) {
        setResumenComidas(resumen);
        setMarcaciones(ultimas);
      }
    } catch (err) {
      if (!signal?.aborted) {
        setError(err.message);
      }
    } finally {
      if (!signal?.aborted) {
        setCargando(false);
      }
    }
  }, [fecha, hoy]);

  useEffect(() => {
    const controlador = new AbortController();
    cargarDatos(controlador.signal);
    return () => controlador.abort();
  }, [cargarDatos, versionReloj]);

  /* Acción exclusiva de rechazos no identificados */
  async function manejarAutorizarManual(marcacion, usuarioId) {
    if (!marcacion || marcacion.motivo === 'sin_derecho') {
      // Regla obligatoria: sin_derecho no hace ninguna petición
      return;
    }
    const idNumero = Number(usuarioId);
    if (!Number.isInteger(idNumero) || idNumero <= 0) return;

    setAutorizandoId(marcacion.id);
    setErrorAccion(null);
    try {
      await autorizarMarcacionManual(idNumero);
      // Tras autorizar, recargar datos desde el servidor para mostrar la hora que devuelve la API
      await cargarDatos();
      onMarcacionExitosa?.();
      setComensalElegido((prev) => {
        const copia = { ...prev };
        delete copia[marcacion.id];
        return copia;
      });
    } catch (err) {
      setErrorAccion(err.message);
    } finally {
      setAutorizandoId(null);
    }
  }

  /* Agrupamiento de rechazos por motivo para la subsección (b) */
  const rechazos = useMemo(() => marcaciones.filter((m) => !m.valido), [marcaciones]);
  const gruposRechazos = useMemo(() => {
    const grupos = {};
    for (const m of rechazos) {
      const motivo = m.motivo || 'desconocido';
      if (!grupos[motivo]) grupos[motivo] = [];
      grupos[motivo].push(m);
    }
    return grupos;
  }, [rechazos]);

  /* Filtrado del feed de solo lectura (c) */
  const marcacionesFiltradas = useMemo(() => {
    const termino = busqueda.trim().toLowerCase();
    return marcaciones.filter((m) => {
      if (filtroComidaId !== null && m.comidaId !== filtroComidaId) {
        return false;
      }
      if (filtroResultado === 'aceptadas' && !m.valido) {
        return false;
      }
      if (filtroResultado === 'rechazadas' && m.valido) {
        return false;
      }
      if (termino) {
        const nombre = (m.persona?.nombre ?? '').toLowerCase();
        const legajo = (m.persona?.legajo ?? '').toLowerCase();
        if (!nombre.includes(termino) && !legajo.includes(termino)) {
          return false;
        }
      }
      return true;
    });
  }, [marcaciones, filtroComidaId, filtroResultado, busqueda]);

  /* Estados puros: Carga, Error y Vacío */
  if (cargando) {
    return (
      <div className="supervision">
        <p className="supervision__estado" role="status">Cargando supervisión…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="supervision">
        <div className="supervision__error" role="alert">
          <p>{error}</p>
          <Boton onClick={() => cargarDatos()}>Reintentar supervisión</Boton>
        </div>
      </div>
    );
  }

  const esVacioTotal = resumenComidas.length === 0 && marcaciones.length === 0;
  if (esVacioTotal) {
    return (
      <div className="supervision">
        <p className="supervision__vacio" role="status">
          No hay registros de supervisión para este día.
        </p>
      </div>
    );
  }

  return (
    <div className="supervision">
      {/* Indicador de simulación si aplica; el reloj completo vive en el header */}
      {simulacion ? (
        <aside className="supervision__simulacion-aviso" role="status">
          <Etiqueta tono="aviso">Modo simulación</Etiqueta>
          <span>Supervisión basada en el reloj del servidor.</span>
        </aside>
      ) : null}

      {errorAccion ? (
        <div className="supervision__error-accion" role="alert">
          <IconoAlerta tamano={18} />
          <span>{errorAccion}</span>
          <button type="button" onClick={() => setErrorAccion(null)} aria-label="Cerrar error">×</button>
        </div>
      ) : null}

      {/* -----------------------------------------------------------
          (a) Una tarjeta por comida del día
          ----------------------------------------------------------- */}
      <section className="supervision__seccion" aria-label="Comidas del día">
        <header className="supervision__seccion-cabecera">
          <h2 className="supervision__seccion-titulo">Comidas del día</h2>
          <span className="supervision__seccion-ayuda">
            Seleccione una comida para filtrar el hilo inferior
          </span>
        </header>

        {resumenComidas.length === 0 ? (
          <p className="supervision__vacio">No hay comidas registradas para este día.</p>
        ) : (
          <div className="supervision__comidas-grid">
            {resumenComidas.map((item) => {
              const activa = filtroComidaId === item.comidaId && item.comidaId !== null;
              return (
                <Tarjeta
                  key={item.comidaId ?? item.comida}
                  titulo={item.comida}
                  accesorio={
                    <Etiqueta
                      tono={
                        item.estado === 'En curso'
                          ? 'acento'
                          : item.estado === 'Fuera de horario'
                            ? 'aviso'
                            : 'neutro'
                      }
                    >
                      {item.estado}
                    </Etiqueta>
                  }
                  className={`supervision__tarjeta-comida${activa ? ' supervision__tarjeta-comida--activa' : ''}${item.comidaId === null ? ' supervision__tarjeta-comida--sin-filtro' : ''}`}
                  onClick={
                    item.comidaId !== null
                      ? () => setFiltroComidaId(activa ? null : item.comidaId)
                      : undefined
                  }
                >
                  <div className="supervision__metricas-comida">
                    <div className="supervision__metrica">
                      <span className="supervision__metrica-rotulo">Servidas</span>
                      <strong className="supervision__metrica-valor">{item.servidas}</strong>
                    </div>
                    <div className="supervision__metrica">
                      <span className="supervision__metrica-rotulo">Rechazos</span>
                      <strong
                        className={`supervision__metrica-valor${
                          item.rechazos > 0 ? ' supervision__metrica-valor--error' : ''
                        }`}
                      >
                        {item.rechazosTruncados ? '100 o más' : item.rechazos}
                      </strong>
                    </div>
                  </div>
                  {item.comidaId === null ? (
                    <p className="supervision__nota-sin-filtro">Sin filtro disponible</p>
                  ) : (
                    <span className="supervision__filtro-indicador">
                      {activa ? 'Filtrando este turno' : 'Clic para filtrar'}
                    </span>
                  )}
                </Tarjeta>
              );
            })}
          </div>
        )}
      </section>

      {/* -----------------------------------------------------------
          (b) «Rechazos por revisar», agrupados por motivo (con acciones)
          ----------------------------------------------------------- */}
      <section className="supervision__seccion" aria-label="Rechazos por revisar">
        <header className="supervision__seccion-cabecera">
          <div>
            <h2 className="supervision__seccion-titulo">Rechazos por revisar</h2>
            <p className="supervision__seccion-ayuda">
              Resolución de excepciones y autorizaciones manuales
            </p>
          </div>
          <Etiqueta tono={rechazos.length > 0 ? 'error' : 'neutro'}>
            {rechazos.length} {rechazos.length === 1 ? 'rechazo' : 'rechazos'}
          </Etiqueta>
        </header>

        {rechazos.length === 0 ? (
          <p className="supervision__vacio" role="status">No hay rechazos por revisar.</p>
        ) : (
          <div className="supervision__grupos-rechazos">
            {Object.entries(gruposRechazos).map(([motivo, lista]) => (
              <article key={motivo} className="supervision__grupo-motivo">
                <header className="supervision__grupo-cabecera">
                  <h3 className="supervision__grupo-titulo">
                    {ETIQUETAS_MOTIVOS[motivo] ?? motivo}
                  </h3>
                  <span className="supervision__grupo-conteo">
                    {lista.length} {lista.length === 1 ? 'caso' : 'casos'}
                  </span>
                </header>

                <ul className="supervision__lista-rechazos">
                  {lista.map((reg) => {
                    const reactKey = `${reg.dispositivo ?? 'disp'}-${reg.id}`;
                    const esNoIdentificado = reg.motivo === 'no_identificado';
                    const esSinDerecho = reg.motivo === 'sin_derecho';
                    const comensalSel = comensalElegido[reg.id] ?? '';

                    return (
                      <li key={reactKey} className="supervision__fila-rechazo">
                        <div className="supervision__rechazo-info">
                          <span className="supervision__rechazo-icono" aria-hidden="true">
                            <IconoEquis tamano={18} />
                          </span>
                          <div>
                            <strong className="supervision__rechazo-nombre">
                              {reg.persona?.nombre ?? 'Desconocido'}
                            </strong>
                            <p className="supervision__rechazo-meta">
                              {reg.persona?.categoria ?? 'Sin clasificar'} · Legajo {reg.persona?.legajo ?? '—'} · {reg.hora} · {reg.comida ?? 'Sin comida'} · {reg.dispositivo ?? 'dispositivo'}
                            </p>
                          </div>
                        </div>

                        {/* Único lugar con acciones del módulo */}
                        <div className="supervision__rechazo-accion">
                          {esNoIdentificado ? (
                            <div className="supervision__autorizar-caja">
                              <label className="solo-lectores" htmlFor={`select-${reg.id}`}>
                                Asignar comensal
                              </label>
                              <select
                                id={`select-${reg.id}`}
                                className="supervision__select-padron"
                                value={comensalSel}
                                onChange={(e) =>
                                  setComensalElegido({
                                    ...comensalElegido,
                                    [reg.id]: e.target.value,
                                  })
                                }
                              >
                                <option value="">Seleccione comensal del padrón…</option>
                                {personal.map((p) => (
                                  <option key={p.id} value={p.id}>
                                    {p.nombre} — {p.categoria} ({p.legajo})
                                  </option>
                                ))}
                              </select>
                              <Boton
                                variante="primario"
                                disabled={!comensalSel || autorizandoId === reg.id}
                                onClick={() => manejarAutorizarManual(reg, comensalSel)}
                              >
                                {autorizandoId === reg.id ? 'Autorizando…' : 'Autorizar ración manual'}
                              </Boton>
                            </div>
                          ) : esSinDerecho ? (
                            <div className="supervision__sin-derecho-caja">
                              <Boton
                                variante="secundario"
                                disabled={true}
                                title="Requiere excepción de jefatura (pendiente)"
                              >
                                Autorizar ración manual
                              </Boton>
                              <span className="supervision__nota-pendiente">
                                Requiere excepción de jefatura (pendiente)
                              </span>
                            </div>
                          ) : (
                            <span className="supervision__rechazo-inmutable">
                              {reg.titulo}
                            </span>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </article>
            ))}
          </div>
        )}
      </section>

      {/* -----------------------------------------------------------
          (c) Feed de SOLO LECTURA con filtros por comida y resultado
          ----------------------------------------------------------- */}
      <section className="supervision__seccion" aria-label="Hilo de marcaciones">
        <header className="supervision__seccion-cabecera">
          <div>
            <h2 className="supervision__seccion-titulo">Hilo de marcaciones</h2>
            <p className="supervision__seccion-ayuda">
              Registro cronológico de lecturas biométricas y asistencias (solo lectura)
            </p>
          </div>
          <span className="supervision__conteo-feed">
            {marcacionesFiltradas.length} marcaciones
          </span>
        </header>

        {/* Controles de filtro del feed */}
        <div className="supervision__feed-filtros">
          <div className="supervision__chips-filtro" role="tablist" aria-label="Filtrar por resultado">
            <button
              type="button"
              role="tab"
              aria-selected={filtroResultado === 'todas'}
              className={`supervision__chip${filtroResultado === 'todas' ? ' supervision__chip--activo' : ''}`}
              onClick={() => setFiltroResultado('todas')}
            >
              Todas
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={filtroResultado === 'aceptadas'}
              className={`supervision__chip${filtroResultado === 'aceptadas' ? ' supervision__chip--activo' : ''}`}
              onClick={() => setFiltroResultado('aceptadas')}
            >
              Aceptadas
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={filtroResultado === 'rechazadas'}
              className={`supervision__chip${filtroResultado === 'rechazadas' ? ' supervision__chip--activo' : ''}`}
              onClick={() => setFiltroResultado('rechazadas')}
            >
              Rechazadas
            </button>
          </div>

          <div className="supervision__selector-comida">
            <label htmlFor="filtro-comida-select" className="solo-lectores">
              Filtrar por comida
            </label>
            <select
              id="filtro-comida-select"
              className="supervision__select-filtro"
              value={filtroComidaId ?? ''}
              onChange={(e) => setFiltroComidaId(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">Todas las comidas</option>
              {resumenComidas
                .filter((c) => c.comidaId !== null)
                .map((c) => (
                  <option key={c.comidaId} value={c.comidaId}>
                    {c.comida}
                  </option>
                ))}
            </select>
          </div>

          <div className="supervision__buscador">
            <span className="supervision__buscador-icono" aria-hidden="true">
              <IconoBuscar tamano={15} />
            </span>
            <input
              type="text"
              className="supervision__buscador-input"
              value={busqueda}
              onChange={(e) => setBusqueda(e.target.value)}
              placeholder="Buscar por nombre o legajo…"
              aria-label="Buscar en el hilo de marcaciones"
            />
            {busqueda ? (
              <button
                type="button"
                className="supervision__buscador-limpiar"
                onClick={() => setBusqueda('')}
                aria-label="Limpiar búsqueda"
              >
                ×
              </button>
            ) : null}
          </div>
        </div>

        {marcacionesFiltradas.length === 0 ? (
          <p className="supervision__vacio" role="status">
            No hay marcaciones que coincidan con los filtros seleccionados.
          </p>
        ) : (
          <ul className="supervision__feed" aria-label="Lista de marcaciones registradas">
            {marcacionesFiltradas.map((m) => {
              const reactKey = `${m.dispositivo ?? 'disp'}-${m.id}`;
              return (
                <li
                  key={reactKey}
                  className={`supervision__feed-item supervision__feed-item--${
                    m.valido ? 'exito' : 'error'
                  }`}
                >
                  <span className="supervision__feed-icono" aria-hidden="true">
                    {m.valido ? <IconoCheck tamano={18} /> : <IconoEquis tamano={18} />}
                  </span>

                  <div className="supervision__feed-cuerpo">
                    <div className="supervision__feed-cabecera">
                      <strong className="supervision__feed-nombre">
                        {m.persona?.nombre ?? 'Desconocido'}
                      </strong>
                      <span className="supervision__feed-hora">{m.hora}</span>
                    </div>
                    <div className="supervision__feed-detalle">
                      <span>{m.persona?.categoria ?? 'Sin clasificar'}</span>
                      <span>·</span>
                      <span>Legajo {m.persona?.legajo ?? '—'}</span>
                      <span>·</span>
                      <span>{m.comida ?? 'Sin comida asignada'}</span>
                      <span>·</span>
                      <span className="supervision__feed-dispositivo">{m.dispositivo ?? 'disp'}</span>
                    </div>
                  </div>

                  <div className="supervision__feed-estado">
                    <Etiqueta tono={m.valido ? 'exito' : 'error'}>
                      {m.titulo}
                    </Etiqueta>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
