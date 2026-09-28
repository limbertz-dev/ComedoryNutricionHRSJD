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
 * Convierte el resultado devuelto por la API al autorizar una ración en el aviso
 * correspondiente (éxito o rechazo del servidor).
 */
export function resolverAvisoAutorizacion(resultado) {
  if (resultado?.valido) {
    return {
      tipo: 'exito',
      titulo: resultado.titulo || 'Ración autorizada',
      detalle: resultado.detalle || '',
    };
  }
  return {
    tipo: 'rechazo',
    titulo: resultado?.titulo || 'Marcación rechazada',
    detalle: resultado?.detalle || '',
  };
}

/**
 * Ejecuta la autorización manual gestionando estado, avisos y recarga:
 * - Si es válido, emite aviso de éxito, limpia el comensal seleccionado y notifica éxito.
 * - Si es rechazo del servidor (200 con valido: false), emite aviso de rechazo y NO limpia la selección.
 * - En cualquier caso, recarga los datos desde la API.
 */
export async function ejecutarAutorizacionManual({
  marcacion,
  usuarioId,
  autorizarFn = autorizarMarcacionManual,
  cargarDatosFn,
  setAvisoAccion,
  setComensalElegido,
  setAutorizandoId,
  onMarcacionExitosa,
}) {
  if (!marcacion || marcacion.motivo === 'sin_derecho') {
    // Regla obligatoria: sin_derecho no hace ninguna petición
    return;
  }
  const idNumero = Number(usuarioId);
  if (!Number.isInteger(idNumero) || idNumero <= 0) return;

  setAutorizandoId?.(marcacion.id);
  setAvisoAccion?.(null);
  try {
    const resultado = await autorizarFn(idNumero);
    const aviso = resolverAvisoAutorizacion(resultado);
    setAvisoAccion?.(aviso);

    if (resultado?.valido) {
      setComensalElegido?.((prev) => {
        const copia = { ...prev };
        delete copia[marcacion.id];
        return copia;
      });
      onMarcacionExitosa?.();
    }
  } catch (err) {
    setAvisoAccion?.({
      tipo: 'error',
      titulo: 'Error al autorizar',
      detalle: err.message,
    });
  } finally {
    setAutorizandoId?.(null);
    await cargarDatosFn?.();
  }
}

/**
 * Programa el ciclo de vida del refresco de supervisión:
 * - Realiza una carga inicial inmediata ({ esRefresco: false }).
 * - Programa un refresco cada intervaloMs ({ esRefresco: true }) con AbortController nuevo.
 * - Devuelve la función de limpieza que cancela el intervalo y aborta peticiones en vuelo.
 */
export function programarRefrescoSupervision({ cargarDatos, intervaloMs = 30000 }) {
  let controlador = new AbortController();

  cargarDatos({ signal: controlador.signal, esRefresco: false });

  const intervalo = setInterval(() => {
    controlador.abort();
    controlador = new AbortController();
    cargarDatos({ signal: controlador.signal, esRefresco: true });
  }, intervaloMs);

  return function cancelar() {
    clearInterval(intervalo);
    controlador.abort();
  };
}

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
  cargandoInicial = true,
  errorInicial = null,
  resumenInicial = [],
  marcacionesIniciales = [],
  avisoAccionInicial = null,
  fueraDeHorarioInicial = false,
}) {
  const [cargando, setCargando] = useState(cargandoInicial);
  const [actualizando, setActualizando] = useState(false);
  const [error, setError] = useState(errorInicial);
  const [resumenComidas, setResumenComidas] = useState(resumenInicial);
  const [marcaciones, setMarcaciones] = useState(marcacionesIniciales);
  const [fueraDeHorario, setFueraDeHorario] = useState(
    fueraDeHorarioInicial || Boolean(resumenInicial?.fueraDeHorario)
  );

  /* Filtros del feed */
  const [filtroComidaId, setFiltroComidaId] = useState(null);
  const [filtroResultado, setFiltroResultado] = useState('todas');
  const [busqueda, setBusqueda] = useState('');

  /* Comensal seleccionado para autorizar cada rechazo no_identificado { [marcacionId]: comensalId } */
  const [comensalElegido, setComensalElegido] = useState({});
  const [autorizandoId, setAutorizandoId] = useState(null);
  const [avisoAccion, setAvisoAccion] = useState(avisoAccionInicial);

  const cargarDatos = useCallback(async ({ signal, esRefresco = false } = {}) => {
    if (!esRefresco) {
      setCargando(true);
      setError(null);
    } else {
      setActualizando(true);
    }
    try {
      const [resumen, ultimas] = await Promise.all([
        obtenerResumenComidas({ fecha, hoy, signal }),
        obtenerUltimasMarcaciones({ fecha, limite: 100, signal }),
      ]);
      if (!signal?.aborted) {
        setResumenComidas(resumen);
        setMarcaciones(ultimas);
        setFueraDeHorario(Boolean(resumen?.fueraDeHorario));
      }
    } catch (err) {
      if (!signal?.aborted) {
        if (!esRefresco) {
          setError(err.message);
        } else {
          setAvisoAccion({
            tipo: 'error',
            titulo: 'No se pudo actualizar',
            detalle: err.message,
          });
        }
      }
    } finally {
      if (!signal?.aborted) {
        if (!esRefresco) {
          setCargando(false);
        } else {
          setActualizando(false);
        }
      }
    }
  }, [fecha, hoy]);

  useEffect(() => {
    return programarRefrescoSupervision({
      cargarDatos,
      intervaloMs: 30000,
    });
  }, [cargarDatos, versionReloj]);

  /* Acción exclusiva de rechazos no identificados */
  async function manejarAutorizarManual(marcacion, usuarioId) {
    await ejecutarAutorizacionManual({
      marcacion,
      usuarioId,
      autorizarFn: autorizarMarcacionManual,
      cargarDatosFn: () => cargarDatos({ esRefresco: true }),
      setAvisoAccion,
      setComensalElegido,
      setAutorizandoId,
      onMarcacionExitosa,
    });
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
        <div className="supervision__barra-superior">
          <p className="supervision__vacio" role="status">
            No hay registros de supervisión para este día.
          </p>
          <div className="supervision__acciones-barra">
            <Boton
              variante="secundario"
              onClick={() => cargarDatos({ esRefresco: true })}
              disabled={actualizando}
            >
              {actualizando ? 'Actualizando…' : 'Actualizar'}
            </Boton>
          </div>
        </div>
        {avisoAccion ? (
          <div
            className={`supervision__aviso-accion supervision__aviso-accion--${avisoAccion.tipo}`}
            role={avisoAccion.tipo === 'exito' ? 'status' : 'alert'}
          >
            {avisoAccion.tipo === 'exito' ? (
              <span className="supervision__aviso-icono" aria-hidden="true">
                <IconoCheck tamano={18} />
              </span>
            ) : (
              <span className="supervision__aviso-icono" aria-hidden="true">
                <IconoAlerta tamano={18} />
              </span>
            )}
            <div className="supervision__aviso-contenido">
              <strong className="supervision__aviso-titulo">{avisoAccion.titulo}</strong>
              {avisoAccion.detalle ? (
                <p className="supervision__aviso-detalle">{avisoAccion.detalle}</p>
              ) : null}
            </div>
            <button
              type="button"
              className="supervision__aviso-cerrar"
              onClick={() => setAvisoAccion(null)}
              aria-label="Cerrar aviso"
            >
              ×
            </button>
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div className="supervision">
      {/* Barra superior con simulación y botón de actualización visible */}
      <div className="supervision__barra-superior">
        {simulacion ? (
          <aside className="supervision__simulacion-aviso" role="status">
            <Etiqueta tono="aviso">Modo simulación</Etiqueta>
            <span>Supervisión basada en el reloj del servidor.</span>
          </aside>
        ) : <div />}

        <div className="supervision__acciones-barra">
          <Boton
            variante="secundario"
            onClick={() => cargarDatos({ esRefresco: true })}
            disabled={actualizando}
          >
            {actualizando ? 'Actualizando…' : 'Actualizar'}
          </Boton>
        </div>
      </div>

      {avisoAccion ? (
        <div
          className={`supervision__aviso-accion supervision__aviso-accion--${avisoAccion.tipo}`}
          role={avisoAccion.tipo === 'exito' ? 'status' : 'alert'}
        >
          {avisoAccion.tipo === 'exito' ? (
            <span className="supervision__aviso-icono" aria-hidden="true">
              <IconoCheck tamano={18} />
            </span>
          ) : (
            <span className="supervision__aviso-icono" aria-hidden="true">
              <IconoAlerta tamano={18} />
            </span>
          )}
          <div className="supervision__aviso-contenido">
            <strong className="supervision__aviso-titulo">{avisoAccion.titulo}</strong>
            {avisoAccion.detalle ? (
              <p className="supervision__aviso-detalle">{avisoAccion.detalle}</p>
            ) : null}
          </div>
          <button
            type="button"
            className="supervision__aviso-cerrar"
            onClick={() => setAvisoAccion(null)}
            aria-label="Cerrar aviso"
          >
            ×
          </button>
        </div>
      ) : null}

      {/* -----------------------------------------------------------
          (a) Una tarjeta por comida del día
          ----------------------------------------------------------- */}
      <section className="supervision__seccion" aria-label="Comidas del día">
        <header className="supervision__seccion-cabecera">
          <div>
            <h2 className="supervision__seccion-titulo">Comidas del día</h2>
            <span className="supervision__seccion-ayuda">
              Seleccione una comida para filtrar el hilo inferior
            </span>
          </div>
          {fueraDeHorario ? (
            <div className="supervision__aviso-fuera-horario">
              <Etiqueta tono="aviso">Fuera de horario</Etiqueta>
            </div>
          ) : null}
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
