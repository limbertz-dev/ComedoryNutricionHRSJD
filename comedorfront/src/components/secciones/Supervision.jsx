import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Boton from '../ui/Boton.jsx';
import Etiqueta from '../ui/Etiqueta.jsx';
import { IconoBuscar, IconoCheck, IconoEquis, IconoAlerta, IconoUsuario } from '../ui/Iconos.jsx';
import {
  obtenerComidasDelDia,
  obtenerUltimasMarcaciones,
} from '../../api.js';
import { diaLegible } from '../../dias.js';
import IntervencionesCocina from './IntervencionesCocina.jsx';
import HuellasRegistradas from './HuellasRegistradas.jsx';
import './Supervision.css';

/** Filas por consulta: alcanza para el día completo del comedor (≈450 lecturas). */
export const LIMITE_SUPERVISION = 1000;

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

/** "Actualizado HH:MM:SS": hora de la ultima actualizacion. */
function horaCorta(fecha) {
  return FORMATO_HORA.format(fecha);
}

/**
 * La marcación la registró la jefatura a mano. Sale del `origen` que declara
 * la API, nunca del texto del dispositivo.
 */
export function esManual(marcacion) {
  return marcacion.origen === 'asistencia_manual';
}

/**
 * Método de la marcación según su `origen` declarado por la API, nunca según
 * el texto del dispositivo. Una lectura no prueba que el lector esté conectado.
 */
export function metodoDeMarcacion(marcacion) {
  return esManual(marcacion) ? 'Registro manual' : 'Lectura biométrica';
}

const MOTIVOS_RESUMEN = [
  ['noIdentificado', 'Huella no reconocida'],
  ['sinDerecho', 'Sin derecho'],
  ['duplicado', 'Ya recibió su comida'],
];

/**
 * Cifras de la pestaña activa, sumadas tal cual las entrega el servidor (sin
 * recalcular nada): `servidas` ya incluye las `manuales`, por eso se muestran
 * como parte de las aceptadas y no como un tercer total. `null` en "Todas"
 * suma el día; si la pestaña ya no existe, devuelve null.
 */
export function resumenDePestana(dia, pestana) {
  const comidas = dia?.comidas ?? [];
  const elegidas = pestana === null ? comidas : comidas.filter((comida) => comida.comidaId === pestana);
  if (pestana !== null && elegidas.length === 0) return null;

  const rechazos = { noIdentificado: 0, sinDerecho: 0, duplicado: 0 };
  let servidas = 0;
  let manuales = 0;
  for (const comida of elegidas) {
    servidas += comida.servidas;
    manuales += comida.manuales;
    for (const clave of Object.keys(rechazos)) rechazos[clave] += comida.rechazos[clave];
  }
  const comida = pestana === null ? null : elegidas[0];
  return {
    comida,
    servidas,
    manuales,
    rechazadas: rechazos.noIdentificado + rechazos.sinDerecho + rechazos.duplicado,
    motivos: MOTIVOS_RESUMEN
      .map(([clave, etiqueta]) => ({ clave, etiqueta, cantidad: rechazos[clave] }))
      .filter((motivo) => motivo.cantidad > 0),
    previstas: comida?.previstas ?? null,
  };
}

/**
 * La huella no reconocida terminó en una entrega que identificó cocina. La
 * decisión original (el rechazo del lector) no cambia: esto es el resultado
 * final, aparte.
 */
export function entregadaPorCocina(marcacion) {
  return marcacion?.resultadoFinal?.via === 'identificacion_manual';
}

/** Segmentos de la barra de filtros, en el orden en que se leen. */
const FILTROS_RESULTADO = [
  ['todas', 'Todas'],
  ['aceptadas', 'Aceptadas'],
  ['rechazadas', 'Rechazadas'],
  ['manuales', 'Manuales'],
];

/**
 * Filtrado local de la tabla por resultado y nombre del comensal. «Manuales»
 * son las marcaciones registradas a mano, sea cual sea su resultado.
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
    if (resultado === 'manuales' && !esManual(m)) {
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
 * Sección de Supervisión del Comedor (jefa de nutrición). SOLO LECTURA.
 *
 * Una sola tabla en vivo: arriba, las pestañas de las comidas del día
 * ("Todas" + una por comida); debajo, la barra de filtros y la tabla de
 * marcaciones de la pestaña activa. Nada aquí registra, autoriza ni modifica
 * raciones: las huellas no reconocidas las identifica la cocinera y aquí solo
 * se ve su resultado final. Las únicas peticiones son lecturas (GET). Con
 * `puedeConsultarIntervenciones`, al pie se consultan las intervenciones de
 * cocina, sin aprobar nada.
 */
export default function Supervision({
  fecha,
  puedeConsultarIntervenciones = false,
  puedeConsultarHuellas = false,
  cargandoInicial = true,
  errorInicial = null,
  comidasIniciales = null,
  marcacionesIniciales = [],
  actualizadoInicial = null,
  errorRefrescoInicial = '',
  intervencionesIniciales = undefined,
  huellasIniciales = undefined,
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
      const ultimas = await obtenerUltimasMarcaciones({ fecha, limite: LIMITE_SUPERVISION, comidaId: tab, signal });
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
  }, [cargarDatos]);

  function manejarPestana(comidaId) {
    pestanaTocada.current = true;
    setPestana(comidaId);
    cargarDatos({ esRefresco: true, comidaId });
  }

  /* El único aviso de la sección: un refresco que falló. */
  const avisos = errorRefresco ? (
    <AvisoAccion
      aviso={{
        tipo: 'error',
        titulo: 'No se pudo actualizar',
        detalle: `Se muestran los datos anteriores. ${errorRefresco}`,
      }}
      onCerrar={() => setErrorRefresco('')}
    />
  ) : null;

  /* Filtrado local sobre las filas de la pestaña activa */
  const marcacionesFiltradas = useMemo(
    () => filtrarMarcaciones(marcaciones, { resultado: filtroResultado, busqueda }),
    [marcaciones, filtroResultado, busqueda],
  );
  // Las altas no dependen del dia ni de la comida seleccionada.
  const registroHuellas = puedeConsultarHuellas ? <HuellasRegistradas
    version={actualizado?.getTime?.() ?? 0} inicial={huellasIniciales}
  /> : null;

  /* Estados puros: Carga, Error y Vacío */
  if (cargando) {
    return (
      <div className="supervision">
        <p className="supervision__estado" role="status">Cargando supervisión…</p>
        {registroHuellas}
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
        {registroHuellas}
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
            tamano="sm"
            onClick={() => cargarDatos({ esRefresco: true })}
            disabled={actualizando}
          >
            {actualizando ? 'Actualizando…' : 'Actualizar'}
          </Boton>
        </div>
        {avisos}
        {registroHuellas}
      </div>
    );
  }

  const hayFiltros = filtroResultado !== 'todas' || busqueda.trim() !== '';
  const textoActualizado = actualizado ? `Actualizado ${horaCorta(actualizado)}` : 'Actualizado —';
  const resumen = resumenDePestana(dia, pestana);
  const limpiarFiltros = () => {
    setFiltroResultado('todas');
    setBusqueda('');
  };

  return (
    <div className="supervision">

      {avisos}

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
          <span className="supervision__pestana-estado">Todo el día</span>
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
              <span className={`supervision__pestana-estado${enCurso ? ' supervision__pestana-estado--curso' : ''}`}>
                {enCurso ? <span className="supervision__punto-curso" aria-hidden="true" /> : null}
                {ETIQUETAS_ESTADO[comida.estado] ?? comida.estado}
              </span>
              <span className="supervision__pestana-cifras">
                <span
                  className="supervision__pestana-cifra supervision__pestana-cifra--exito"
                  data-tooltip="Aceptadas"
                >
                  <IconoCheck tamano={14} />
                  <span className="solo-lectores">Aceptadas: </span>
                  {comida.servidas}
                </span>
                <span
                  className="supervision__pestana-cifra supervision__pestana-cifra--error"
                  data-tooltip="Rechazadas"
                >
                  <IconoEquis tamano={14} />
                  <span className="solo-lectores">Rechazadas: </span>
                  {rechazosDeComida(comida)}
                </span>
                <span
                  className="supervision__pestana-cifra supervision__pestana-cifra--manual"
                  data-tooltip="Manuales (ya incluidas en las aceptadas)"
                >
                  <IconoUsuario tamano={14} />
                  <span className="solo-lectores">Manuales: </span>
                  {comida.manuales}
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

      {/* Aceptadas, rechazadas y manuales de la pestaña activa, con su período. */}
      {resumen && comidas.length > 0 ? <ResumenPestana resumen={resumen} dia={dia} /> : null}

      {/* Barra: resultado, búsqueda por nombre, actualizado y actualización. */}
      <div className="supervision__filtros">
        <div className="supervision__chips-filtro" role="tablist" aria-label="Filtrar por resultado">
          {FILTROS_RESULTADO.map(([valor, etiqueta]) => (
            <button
              key={valor}
              type="button"
              role="tab"
              aria-selected={filtroResultado === valor}
              className={`supervision__chip${filtroResultado === valor ? ' supervision__chip--activo' : ''}`}
              onClick={() => setFiltroResultado(valor)}
            >
              {etiqueta}
            </button>
          ))}
        </div>

        <div className="supervision__buscador">
          <span className="supervision__buscador-icono" aria-hidden="true">
            <IconoBuscar tamano={16} />
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

        <span
          className="supervision__actualizado"
          role="status"
          data-tooltip="Se actualiza sola cada 30 segundos"
          data-tooltip-pos="bottom"
        >
          {textoActualizado}
        </span>

        <Boton
          variante="secundario"
          tamano="sm"
          onClick={() => cargarDatos({ esRefresco: true })}
          disabled={actualizando}
        >
          {actualizando ? 'Actualizando…' : 'Actualizar'}
        </Boton>
      </div>

      <section className="supervision__panel" aria-label="Marcaciones de la comida seleccionada">
        <header className="supervision__panel-cabecera">
          <p className="supervision__conteo" role="status">
            {`${marcacionesFiltradas.length} de ${marcaciones.length} ${marcaciones.length === 1 ? 'marcación' : 'marcaciones'}`}
          </p>
          {marcaciones.length >= LIMITE_SUPERVISION ? (
            <p className="supervision__nota-truncada" role="status">{`Mostrando las últimas ${LIMITE_SUPERVISION}`}</p>
          ) : null}
          {hayFiltros ? (
            <Boton variante="fantasma" tamano="sm" onClick={limpiarFiltros}>Limpiar filtros</Boton>
          ) : null}
        </header>

        {marcacionesFiltradas.length === 0 ? (
          <p className="supervision__vacio supervision__vacio--tabla" role="status">
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
                </tr>
              </thead>
              <tbody>
                {marcacionesFiltradas.map((m) => (
                  <tr key={m.clave} className={claseDeFila(m)}>
                    <td>{m.hora}</td>
                    <td>{m.persona?.nombre ?? 'Desconocido'}</td>
                    <td>{m.persona?.categoria ?? 'Sin clasificar'}</td>
                    <td>{m.comida ?? '—'}</td>
                    <td>
                      <span className="supervision__resultado">
                        <Etiqueta tono={m.valido ? 'exito' : 'error'}>
                          {m.valido ? 'Aceptada' : 'Rechazada'}
                        </Etiqueta>
                        {esManual(m) ? <Etiqueta tono="manual">Manual</Etiqueta> : null}
                        {entregadaPorCocina(m) ? <ResultadoFinalCocina marcacion={m} /> : null}
                      </span>
                    </td>
                    <td>{m.valido ? '—' : (ETIQUETAS_MOTIVOS[m.motivo] ?? m.motivo ?? ETIQUETAS_MOTIVOS.desconocido)}</td>
                    <td>{metodoDeMarcacion(m)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Consulta de lo que hizo cocina con las huellas no reconocidas: solo
          jefa, sin botones de aprobación. Acotada a la pestaña activa y
          refrescada con el resto de la sección. */}
      {puedeConsultarIntervenciones ? (
        <IntervencionesCocina
          key={pestana ?? 'todas'}
          fecha={fecha}
          comidaId={pestana}
          comida={resumen?.comida?.comida ?? null}
          version={actualizado?.getTime?.() ?? 0}
          inicial={intervencionesIniciales}
        />
      ) : null}
      {registroHuellas}
    </div>
  );
}

/**
 * Resultado final de una huella que identificó cocina: la entrega, a quién y,
 * para la jefa, qué cuenta la registró. Nunca dice que el lector la reconoció.
 */
function ResultadoFinalCocina({ marcacion }) {
  const nombre = marcacion.resultadoFinal?.comensal?.nombre;
  const cuenta = marcacion.intervencion?.registradaPor;
  const quien = cuenta ? cuenta.nombre || cuenta.usuario : null;
  return (
    <span className="supervision__final-cocina">
      <Etiqueta tono="exito">Entregada por cocina</Etiqueta>
      <span className="supervision__final-detalle">
        {[nombre, quien ? `registró ${quien}` : null].filter(Boolean).join(' · ')}
      </span>
    </span>
  );
}

/** Clases de una fila: tinte de rechazo y marca de registro manual. */
function claseDeFila(marcacion) {
  const clases = [
    marcacion.valido ? '' : 'supervision__fila--rechazada',
    esManual(marcacion) ? 'supervision__fila--manual' : '',
  ].filter(Boolean);
  return clases.length > 0 ? clases.join(' ') : undefined;
}

/**
 * Aceptadas, rechazadas y manuales de la pestaña activa, con el período al
 * que corresponden. Las manuales ya están dentro de las aceptadas: se
 * muestran aparte para verlas, no para sumarlas.
 */
function ResumenPestana({ resumen, dia }) {
  const { comida } = resumen;
  const fecha = diaLegible(dia?.fecha);
  const horario = comida?.horaInicio && comida?.horaFin
    ? `${comida.horaInicio.slice(0, 5)} – ${comida.horaFin.slice(0, 5)}`
    : null;
  const periodo = comida
    ? [horario, ETIQUETAS_ESTADO[comida.estado] ?? comida.estado, fecha].filter(Boolean).join(' · ')
    : ['Todas las comidas', fecha].filter(Boolean).join(' · ');

  return (
    <section className="supervision__resumen" aria-label={`Resumen de ${comida?.comida ?? 'todo el día'}`}>
      <div className="supervision__periodo">
        <h2 className="supervision__periodo-titulo">{comida?.comida ?? 'Todo el día'}</h2>
        <p className="supervision__periodo-detalle">{periodo}</p>
      </div>

      <dl className="supervision__cifras">
        <div className="supervision__cifra supervision__cifra--exito">
          <dt>
            <IconoCheck tamano={16} /> Aceptadas
          </dt>
          <dd>{resumen.servidas}</dd>
          <small>
            {resumen.previstas !== null ? `de ${resumen.previstas} previstas` : 'Raciones servidas'}
          </small>
        </div>

        <div className="supervision__cifra supervision__cifra--error">
          <dt>
            <IconoEquis tamano={16} /> Rechazadas
          </dt>
          <dd>{resumen.rechazadas}</dd>
          <small>
            {resumen.motivos.length === 0
              ? 'Sin rechazos'
              : resumen.motivos.map(({ etiqueta, cantidad }) => `${etiqueta} ${cantidad}`).join(' · ')}
          </small>
        </div>

        <div className="supervision__cifra supervision__cifra--manual">
          <dt>
            <IconoUsuario tamano={16} /> Manuales
          </dt>
          <dd>{resumen.manuales}</dd>
          <small>Incluidas en las aceptadas</small>
        </div>
      </dl>
    </section>
  );
}

/** Aviso con cierre manual (hoy, solo el de un refresco fallido). */
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
