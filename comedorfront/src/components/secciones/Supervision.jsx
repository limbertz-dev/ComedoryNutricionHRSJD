import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Boton from '../ui/Boton.jsx';
import Etiqueta from '../ui/Etiqueta.jsx';
import { IconoBuscar, IconoCheck, IconoEquis, IconoAlerta } from '../ui/Iconos.jsx';
import {
  autorizarMarcacionManual,
  obtenerComidasDelDia,
  obtenerUltimasMarcaciones,
} from '../../api.js';
import RegistroManual from './RegistroManual.jsx';
import './Supervision.css';

const ETIQUETAS_MOTIVOS = {
  no_identificado: 'Huella no reconocida (no identificado)',
  sin_derecho: 'Sin derecho en este turno',
  duplicado: 'Ya recibió su comida (duplicado)',
  fuera_horario: 'Fuera de horario',
  desconocido: 'Rechazo no clasificado',
};

const ETIQUETAS_ESTADO = {
  pendiente: 'Pendiente',
  en_curso: 'En curso',
  cerrada: 'Cerrada',
};

/**
 * Pestaña con la que abre la tabla: la comida en curso, o "Todas" (null) si
 * ninguna lo está.
 */
export function pestanaPorDefecto(comidas = []) {
  return comidas.find((comida) => comida.estado === 'en_curso')?.comidaId ?? null;
}

/** Rechazos de una comida: suma de no_identificado + sin_derecho + duplicado. */
export function rechazosDeComida(comida) {
  const rechazos = comida.rechazos;
  return rechazos.noIdentificado + rechazos.sinDerecho + rechazos.duplicado;
}

const FORMATO_HORA = new Intl.DateTimeFormat('es-BO', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});

/** "Actualizado HH:MM:SS": en simulación, la hora del reloj del servidor. */
function horaCorta(fecha) {
  return FORMATO_HORA.format(fecha);
}

/**
 * Método de la marcación según su `origen` declarado por la API, nunca según
 * el texto del dispositivo. Una lectura no prueba que el lector esté conectado.
 */
export function metodoDeMarcacion(marcacion) {
  return marcacion.origen === 'asistencia_manual' ? 'Registro manual' : 'Lectura biométrica';
}

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
 * La fila se identifica por su `clave` (origen:id): el id numérico se repite
 * entre lecturas y asistencias manuales.
 * Devuelve el resultado del servidor para que la tabla sepa si cerrar la fila.
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
    return undefined;
  }
  const idNumero = Number(usuarioId);
  if (!Number.isInteger(idNumero) || idNumero <= 0) return undefined;

  setAutorizandoId?.(marcacion.clave);
  setAvisoAccion?.(null);
  try {
    const resultado = await autorizarFn(idNumero);
    const aviso = resolverAvisoAutorizacion(resultado);
    setAvisoAccion?.(aviso);

    if (resultado?.valido) {
      setComensalElegido?.((prev) => {
        const copia = { ...prev };
        delete copia[marcacion.clave];
        return copia;
      });
      onMarcacionExitosa?.();
    }
    return resultado;
  } catch (err) {
    setAvisoAccion?.({
      tipo: 'error',
      titulo: 'Error al autorizar',
      detalle: err.message,
    });
    return undefined;
  } finally {
    setAutorizandoId?.(null);
    await cargarDatosFn?.();
  }
}

/**
 * Filtrado local de la tabla por resultado y nombre del comensal.
 */
export function filtrarMarcaciones(marcaciones, { resultado = 'todas', busqueda = '' } = {}) {
  const termino = busqueda.trim().toLowerCase();
  return marcaciones.filter((m) => {
    if (resultado === 'aceptadas' && !m.valido) {
      return false;
    }
    if (resultado === 'rechazadas' && m.valido) {
      return false;
    }
    if (termino && !(m.persona?.nombre ?? '').toLowerCase().includes(termino)) {
      return false;
    }
    return true;
  });
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
 * Una sola tabla en vivo: arriba, las pestañas de las comidas del día
 * ("Todas" + una por comida); debajo, la barra de filtros y la tabla de
 * marcaciones de la pestaña activa. La acción de fila vive en la columna
 * Acción, solo para huellas no identificadas. Aparte, con
 * `puedeRegistrarManual` (jefa y sistemas), «Registrar ración manual» no
 * depende de ninguna fila.
 */
export default function Supervision({
  fecha,
  simulacion = null,
  personal = [],
  cargandoPadron = false,
  errorPadron = '',
  puedeRegistrarManual = false,
  registrarManual = autorizarMarcacionManual,
  versionReloj = 0,
  onMarcacionExitosa,
  cargandoInicial = true,
  errorInicial = null,
  comidasIniciales = null,
  marcacionesIniciales = [],
  avisoAccionInicial = null,
  actualizadoInicial = null,
  filaExpandidaInicial = null,
  errorRefrescoInicial = '',
}) {
  const [cargando, setCargando] = useState(cargandoInicial);
  const [actualizando, setActualizando] = useState(false);
  const [error, setError] = useState(errorInicial);
  /* Fallo del último refresco: aparte del aviso de una acción, para que un
     refresco fallido nunca tape que un registro tuvo éxito. */
  const [errorRefresco, setErrorRefresco] = useState(errorRefrescoInicial);
  const [dia, setDia] = useState(comidasIniciales);
  const [marcaciones, setMarcaciones] = useState(marcacionesIniciales);
  const [actualizado, setActualizado] = useState(actualizadoInicial);

  /* Pestaña activa: null es "Todas". Arranca en la comida en curso. */
  const [pestana, setPestana] = useState(() => pestanaPorDefecto(comidasIniciales?.comidas ?? []));
  const pestanaTocada = useRef(false);
  const pestanaRef = useRef(pestana);
  pestanaRef.current = pestana;

  /* Filtros de la tabla */
  const [filtroResultado, setFiltroResultado] = useState('todas');
  const [busqueda, setBusqueda] = useState('');

  /* Fila con el selector de comensal abierto + comensal por fila */
  const [filaExpandida, setFilaExpandida] = useState(filaExpandidaInicial);
  const [comensalElegido, setComensalElegido] = useState({});
  const [autorizandoId, setAutorizandoId] = useState(null);
  const [avisoAccion, setAvisoAccion] = useState(avisoAccionInicial);

  const cargarDatos = useCallback(async ({ signal, esRefresco = false, comidaId } = {}) => {
    if (!esRefresco) {
      setCargando(true);
      setError(null);
    } else {
      setActualizando(true);
    }
    try {
      const diaServidor = await obtenerComidasDelDia({ fecha, signal });
      if (signal?.aborted) return;
      /* La pestaña por defecto sale de las comidas recién llegadas, salvo que
         ya se haya elegido una a mano. */
      let tab = comidaId !== undefined ? comidaId : pestanaRef.current;
      if (comidaId === undefined && !pestanaTocada.current) {
        tab = pestanaPorDefecto(diaServidor.comidas);
        setPestana(tab);
      }
      const ultimas = await obtenerUltimasMarcaciones({ fecha, limite: 100, comidaId: tab, signal });
      if (signal?.aborted) return;
      setDia(diaServidor);
      setMarcaciones(ultimas);
      setActualizado(new Date());
      setErrorRefresco('');
    } catch (err) {
      if (!signal?.aborted) {
        if (!esRefresco) {
          setError(err.message);
        } else {
          setErrorRefresco(err.message);
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
  }, [fecha]);

  useEffect(() => {
    return programarRefrescoSupervision({
      cargarDatos,
      intervaloMs: 30000,
    });
  }, [cargarDatos, versionReloj]);

  function manejarPestana(comidaId) {
    pestanaTocada.current = true;
    setPestana(comidaId);
    setFilaExpandida(null);
    cargarDatos({ esRefresco: true, comidaId });
  }

  /* Acción exclusiva de rechazos no identificados */
  async function manejarAutorizarManual(marcacion, usuarioId) {
    const resultado = await ejecutarAutorizacionManual({
      marcacion,
      usuarioId,
      autorizarFn: autorizarMarcacionManual,
      cargarDatosFn: () => cargarDatos({ esRefresco: true }),
      setAvisoAccion,
      setComensalElegido,
      setAutorizandoId,
      onMarcacionExitosa,
    });
    if (resultado?.valido) setFilaExpandida(null);
  }

  /* Registro manual independiente de las filas: el aviso es el de cualquier
     acción y el refresco posterior informa su fallo por separado. */
  const registroManual = puedeRegistrarManual ? (
    <RegistroManual
      personal={personal}
      cargandoPadron={cargandoPadron}
      errorPadron={errorPadron}
      registrar={registrarManual}
      onAviso={setAvisoAccion}
      onExito={() => onMarcacionExitosa?.()}
      onRefrescar={() => cargarDatos({ esRefresco: true })}
    />
  ) : null;
  const avisos = (
    <>
      {avisoAccion ? <AvisoAccion aviso={avisoAccion} onCerrar={() => setAvisoAccion(null)} /> : null}
      {errorRefresco ? (
        <AvisoAccion
          aviso={{
            tipo: 'error',
            titulo: 'No se pudo actualizar',
            detalle: `Se muestran los datos anteriores. ${errorRefresco}`,
          }}
          onCerrar={() => setErrorRefresco('')}
        />
      ) : null}
    </>
  );

  /* Filtrado local sobre las filas de la pestaña activa */
  const marcacionesFiltradas = useMemo(
    () => filtrarMarcaciones(marcaciones, { resultado: filtroResultado, busqueda }),
    [marcaciones, filtroResultado, busqueda],
  );

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
        {avisoAccion ? <AvisoAccion aviso={avisoAccion} onCerrar={() => setAvisoAccion(null)} /> : null}
        {registroManual}
      </div>
    );
  }

  const comidas = dia?.comidas ?? [];
  const esVacioTotal = comidas.length === 0 && marcaciones.length === 0;
  if (esVacioTotal) {
    return (
      <div className="supervision">
        <div className="supervision__barra-superior">
          <p className="supervision__vacio" role="status">
            No hay registros de supervisión para este día.
          </p>
          <Boton
            variante="secundario"
            onClick={() => cargarDatos({ esRefresco: true })}
            disabled={actualizando}
          >
            {actualizando ? 'Actualizando…' : 'Actualizar'}
          </Boton>
        </div>
        {avisos}
        {registroManual}
      </div>
    );
  }

  const hayFiltros = filtroResultado !== 'todas' || busqueda.trim() !== '';
  const textoActualizado = simulacion
    ? `Actualizado ${horaCorta(simulacion.ahora)}`
    : actualizado ? `Actualizado ${horaCorta(actualizado)}` : 'Actualizado —';

  return (
    <div className="supervision">
      {simulacion ? (
        <aside className="supervision__simulacion-aviso" role="status">
          <Etiqueta tono="aviso">Modo simulación</Etiqueta>
          <span>Supervisión basada en el reloj del servidor.</span>
        </aside>
      ) : null}

      {avisos}

      {registroManual}

      {/* Pestañas: "Todas" + una por comida del día, en el orden recibido. */}
      <div className="supervision__pestanas" role="tablist" aria-label="Filtrar por comida">
        <button
          type="button"
          role="tab"
          aria-selected={pestana === null}
          className={`supervision__pestana${pestana === null ? ' supervision__pestana--activa' : ''}`}
          onClick={() => manejarPestana(null)}
        >
          <span className="supervision__pestana-nombre">Todas</span>
        </button>
        {comidas.map((comida) => {
          const activa = pestana === comida.comidaId;
          const enCurso = comida.estado === 'en_curso';
          return (
            <button
              key={comida.comidaId}
              type="button"
              role="tab"
              aria-selected={activa}
              className={`supervision__pestana${activa ? ' supervision__pestana--activa' : ''}`}
              onClick={() => manejarPestana(comida.comidaId)}
            >
              <span className="supervision__pestana-nombre">{comida.comida}</span>
              <span className="supervision__pestana-estado">
                {enCurso ? <span className="supervision__punto-curso" aria-hidden="true" /> : null}
                {ETIQUETAS_ESTADO[comida.estado] ?? comida.estado}
              </span>
              <span className="supervision__pestana-cifras">
                <span className="supervision__pestana-cifra supervision__pestana-cifra--exito">
                  <IconoCheck tamano={14} />
                  {comida.servidas}
                </span>
                <span className="supervision__pestana-cifra supervision__pestana-cifra--error">
                  <IconoEquis tamano={14} />
                  {rechazosDeComida(comida)}
                </span>
              </span>
            </button>
          );
        })}
      </div>
      {(dia?.rechazosSinComida ?? 0) > 0 ? (
        <p className="supervision__nota-fuera-franja" role="status">
          {dia.rechazosSinComida === 1
            ? '1 rechazo fuera de franja'
            : `${dia.rechazosSinComida} rechazos fuera de franja`}
        </p>
      ) : null}

      {/* Barra: resultado, búsqueda por nombre, actualizado y actualización. */}
      <div className="supervision__filtros">
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

        <div className="supervision__buscador">
          <span className="supervision__buscador-icono" aria-hidden="true">
            <IconoBuscar tamano={15} />
          </span>
          <input
            type="text"
            className="supervision__buscador-input"
            value={busqueda}
            onChange={(e) => setBusqueda(e.target.value)}
            placeholder="Buscar por nombre…"
            aria-label="Buscar por nombre"
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

        <span className="supervision__actualizado" role="status">{textoActualizado}</span>

        <Boton
          variante="secundario"
          onClick={() => cargarDatos({ esRefresco: true })}
          disabled={actualizando}
        >
          {actualizando ? 'Actualizando…' : 'Actualizar'}
        </Boton>
      </div>

      {marcaciones.length >= 100 ? (
        <p className="supervision__nota-truncada" role="status">Mostrando las últimas 100</p>
      ) : null}

      {marcacionesFiltradas.length === 0 ? (
        <p className="supervision__vacio" role="status">
          {hayFiltros
            ? 'No hay marcaciones que coincidan con los filtros seleccionados.'
            : 'No hay marcaciones registradas.'}
        </p>
      ) : (
        <div className="supervision__tabla-caja">
          <table className="supervision__tabla" aria-label="Marcaciones de la comida seleccionada">
            <thead>
              <tr>
                <th scope="col">Hora</th>
                <th scope="col">Comensal</th>
                <th scope="col">Categoría</th>
                <th scope="col">Comida</th>
                <th scope="col">Resultado</th>
                <th scope="col">Motivo</th>
                <th scope="col">Método</th>
                <th scope="col">Acción</th>
              </tr>
            </thead>
            <tbody>
              {marcacionesFiltradas.map((m) => (
                <Fragment key={m.clave}>
                  <tr className={m.valido ? undefined : 'supervision__fila--rechazada'}>
                    <td>{m.hora}</td>
                    <td>{m.persona?.nombre ?? 'Desconocido'}</td>
                    <td>{m.persona?.categoria ?? 'Sin clasificar'}</td>
                    <td>{m.comida ?? '—'}</td>
                    <td>
                      <Etiqueta tono={m.valido ? 'exito' : 'error'}>
                        {m.valido ? 'Aceptada' : 'Rechazada'}
                      </Etiqueta>
                    </td>
                    <td>{m.valido ? '—' : (ETIQUETAS_MOTIVOS[m.motivo] ?? m.motivo ?? ETIQUETAS_MOTIVOS.desconocido)}</td>
                    <td>{metodoDeMarcacion(m)}</td>
                    <td>
                      <AccionFila
                        marcacion={m}
                        expandida={filaExpandida === m.clave}
                        onAutorizar={() => setFilaExpandida(filaExpandida === m.clave ? null : m.clave)}
                      />
                    </td>
                  </tr>
                  {filaExpandida === m.clave && m.motivo === 'no_identificado' ? (
                    <tr className="supervision__fila-autorizar">
                      <td colSpan={8}>
                        <div className="supervision__autorizar-caja">
                          <label className="supervision__autorizar-etiqueta" htmlFor={`autorizar-${m.clave}`}>
                            Comensal
                          </label>
                          <select
                            id={`autorizar-${m.clave}`}
                            className="supervision__select-padron"
                            value={comensalElegido[m.clave] ?? ''}
                            onChange={(e) => setComensalElegido({
                              ...comensalElegido,
                              [m.clave]: e.target.value,
                            })}
                          >
                            <option value="">Seleccione comensal del padrón…</option>
                            {personal.map((p) => (
                              <option key={p.id} value={p.id}>
                                {p.nombre} — {p.categoria} ({p.legajo})
                              </option>
                            ))}
                          </select>
                          <Boton
                            disabled={!(comensalElegido[m.clave] ?? '') || autorizandoId === m.clave}
                            onClick={() => manejarAutorizarManual(m, comensalElegido[m.clave])}
                          >
                            {autorizandoId === m.clave ? 'Autorizando…' : 'Confirmar ración manual'}
                          </Boton>
                          <Boton variante="secundario" onClick={() => setFilaExpandida(null)}>
                            Cancelar
                          </Boton>
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/**
 * Acción de una fila: "Autorizar" solo para huellas no identificadas (abre el
 * selector debajo de la fila); en sin_derecho, botón desactivado sin petición;
 * en las demás filas, nada.
 */
function AccionFila({ marcacion, expandida, onAutorizar }) {
  if (marcacion.motivo === 'no_identificado') {
    return (
      <Boton variante="primario" onClick={onAutorizar} aria-expanded={expandida}>
        Autorizar
      </Boton>
    );
  }
  if (marcacion.motivo === 'sin_derecho') {
    return (
      <Boton
        variante="secundario"
        disabled
        title="Requiere excepción de jefatura (pendiente)"
      >
        Autorizar
      </Boton>
    );
  }
  return null;
}

/** Aviso de éxito, rechazo o error tras una acción, con cierre manual. */
function AvisoAccion({ aviso, onCerrar }) {
  return (
    <div
      className={`supervision__aviso-accion supervision__aviso-accion--${aviso.tipo}`}
      role={aviso.tipo === 'exito' ? 'status' : 'alert'}
    >
      {aviso.tipo === 'exito' ? (
        <span className="supervision__aviso-icono" aria-hidden="true">
          <IconoCheck tamano={18} />
        </span>
      ) : (
        <span className="supervision__aviso-icono" aria-hidden="true">
          <IconoAlerta tamano={18} />
        </span>
      )}
      <div className="supervision__aviso-contenido">
        <strong className="supervision__aviso-titulo">{aviso.titulo}</strong>
        {aviso.detalle ? (
          <p className="supervision__aviso-detalle">{aviso.detalle}</p>
        ) : null}
      </div>
      <button
        type="button"
        className="supervision__aviso-cerrar"
        onClick={onCerrar}
        aria-label="Cerrar aviso"
      >
        ×
      </button>
    </div>
  );
}
