import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import Etiqueta from '../ui/Etiqueta.jsx';
import GaugeRaciones from '../ui/GaugeRaciones.jsx';
import Tarjeta from '../ui/Tarjeta.jsx';
import { obtenerDiaPersonal, obtenerLecturasPorIdentificar, obtenerUltimasMarcaciones } from '../../api.js';
import { LIMITE_MARCACIONES_COCINA, programarCicloCocina } from '../../cocinaEnVivo.js';
import { revisionesCambiadas } from '../../identificacion.js';
import IdentificarLectura from './IdentificarLectura.jsx';
import useConsultaApi from '../../hooks/useConsultaApi.js';
import Boton from '../ui/Boton.jsx';
import { IconoBuscar, IconoCheck, IconoEquis, IconoHuella } from '../ui/Iconos.jsx';
import './PantallaEnVivo.css';

/** Modificador de color de `.comida` según el estado, con el mismo vocabulario del historial. */
function estadoDeComida(comida) {
  if (!comida.aplica) return 'no-aplica';
  if (comida.estado === true) return 'recibida';
  if (comida.estado === false) return 'no-recibida';
  return 'pendiente';
}

/** Estado de una comida del día, con el mismo vocabulario del historial. */
function EstadoComida({ comida }) {
  if (!comida.aplica) {
    return (
      <span className="comida__estado" data-tooltip="No corresponde a su turno">
        — No aplica
      </span>
    );
  }

  if (comida.estado === true) {
    return (
      <span className="comida__estado">
        <IconoCheck tamano={15} />
        Recibió
      </span>
    );
  }

  if (comida.estado === false) {
    return (
      <span className="comida__estado">
        <IconoEquis tamano={15} />
        No recibió
      </span>
    );
  }

  return (
    <span className="comida__estado">
      <span className="comida__punto" aria-hidden="true" />
      Pendiente
    </span>
  );
}

/** Las cuatro comidas reales del hospital: únicas opciones del filtro. */
const COMIDAS_FILTRO = ['Desayuno', 'Almuerzo', 'Té', 'Cena'];

/** Comida de `COMIDAS_FILTRO` que corresponde a `comida`, sin importar mayúsculas. */
function comidaValida(comida) {
  return COMIDAS_FILTRO.find((opcion) => opcion.toLowerCase() === comida?.toLowerCase()) ?? null;
}

/**
 * Chips para acotar la tarjeta de marcaciones a un solo tiempo de comida.
 *
 * Las opciones son siempre las cuatro comidas del hospital: así la jefa de
 * nutrición puede pedir "Cena" aunque todavía no haya ninguna marcación de
 * cena cargada, y ver el aviso de que no hubo ninguna.
 */
function FiltroComida({ activo, onCambiar }) {
  return (
    <div className="filtro-comida" role="tablist" aria-label="Filtrar marcaciones por comida">
      {COMIDAS_FILTRO.map((opcion) => (
        <button
          key={opcion}
          type="button"
          role="tab"
          aria-selected={activo === opcion}
          className={`filtro-comida__chip${activo === opcion ? ' filtro-comida__chip--activo' : ''}`}
          onClick={() => onCambiar(opcion)}
        >
          {opcion}
        </button>
      ))}
    </div>
  );
}

/** Texto del origen de una marcación; null si no dejó fila persistida. */
export function etiquetaDeOrigen(origen) {
  if (origen === 'asistencia_manual') return 'Registro manual';
  if (origen === 'lectura_biometrica') return 'Lectura biométrica';
  return null;
}

/** La huella no reconocida terminó en una entrega identificada por cocina. */
export function identificadaPorCocina(fila) {
  return fila?.resultadoFinal?.via === 'identificacion_manual';
}

/**
 * Fila de la lista con la misma forma que la marcación en vivo, para que el
 * escenario y la barra de comidas la muestren igual. `id` es la clave del
 * evento: el id numérico se repite entre lecturas y asistencias manuales.
 *
 * Una huella no reconocida que cocina identificó se muestra por su resultado
 * final (la entrega, con la persona identificada), sin decir nunca que el
 * lector la reconoció: la decisión original sigue siendo un rechazo.
 */
export function eventoDeFila(fila) {
  if (identificadaPorCocina(fila)) {
    const comensal = fila.resultadoFinal.comensal;
    return {
      id: fila.clave,
      origen: fila.origen ?? null,
      valido: true,
      titulo: 'Entrega registrada por cocina',
      detalle: 'El lector no reconoció la huella; cocina identificó a la persona',
      hora: fila.hora,
      persona: {
        id: comensal.usuarioId ?? null,
        nombre: comensal.nombre ?? 'Persona identificada',
        categoria: 'Identificada por cocina',
        legajo: '—',
      },
    };
  }
  const manual = fila.origen === 'asistencia_manual';
  return {
    id: fila.clave,
    origen: fila.origen ?? null,
    valido: fila.valido,
    titulo: manual && fila.valido ? 'Registro manual' : fila.titulo,
    detalle: manual
      ? 'Ración registrada a mano desde Supervisión'
      : fila.valido
        ? 'Ración habilitada — comensal registrado'
        : 'Marcación no habilitada para este turno',
    hora: fila.hora,
    persona: {
      id: fila.persona?.id ?? null,
      nombre: fila.persona?.nombre,
      categoria: fila.persona?.categoria,
      legajo: fila.persona?.legajo ?? '—',
    },
  };
}

/**
 * Lista de la tarjeta: las filas del servidor y, al tope, la marcación que
 * envió esta pantalla mientras su fila guardada no llegue. Se deduplica por
 * `claveEvento` (origen + id): una asistencia manual con el mismo id numérico
 * que la lectura enviada es otro evento y no la reemplaza.
 */
export function filasConPropia(marcaciones, evento) {
  const guardadas = marcaciones ?? [];
  if (!evento) return guardadas;
  if (evento.claveEvento && guardadas.some((fila) => fila.clave === evento.claveEvento)) {
    return guardadas;
  }
  return [{
    id: `local-${evento.id}`,
    clave: `local-${evento.id}`,
    origen: evento.origen ?? null,
    valido: evento.valido,
    titulo: evento.titulo,
    hora: evento.hora,
    // evento.tiempo y evento.comida_id vienen de la misma respuesta de
    // marcarAsistencia que ya usa el resto de la pantalla.
    comida: evento.tiempo ?? null,
    comidaId: evento.comida_id ?? null,
    persona: {
      id: evento.persona.id,
      nombre: evento.persona.nombre,
      categoria: evento.persona.categoria,
    },
  }, ...guardadas];
}

/**
 * Sección principal: emula el puesto de control del comedor.
 *
 * Las raciones y la última marcación se reciben desde App, así que cambiar de
 * sección y volver no reinicia nada. Las marcaciones de la tarjeta lateral, en
 * cambio, salen del servidor: son las lecturas ya guardadas de hoy, y por eso
 * sobreviven a un F5.
 *
 * El simulador del lector no vive acá: se monta en el header (ver App.jsx),
 * para que "Apoyar huella" quede siempre visible sin importar el scroll.
 *
 * Este puesto de control opera siempre sobre el turno en vivo de hoy: no
 * hay selector de fecha, ni falta hace, porque acá lo que importa es lo que
 * está pasando ahora mismo frente al lector.
 *
 * En simulación, `fechaServidor` es el día del reloj del servidor
 * ("YYYY-MM-DD") y `versionReloj` cambia cada vez que alguien mueve ese
 * reloj; fuera de simulación no llegan y todo sigue como siempre.
 *
 * La lista y el estado del comedor (`recargarEstado`, de App) se releen en
 * ciclos de 3 s (`programarCicloCocina`): así llega a cocina lo registrado
 * en otro puesto, como la ración manual de la jefa. Una marcación no prueba
 * que haya un lector conectado.
 */
export default function PantallaEnVivo({
  evento,
  leyendo,
  pantalla,
  turno,
  personaSeleccionada,
  onMarcarManual,
  fechaServidor,
  versionReloj = 0,
  recargarEstado,
  puedeIdentificar = false,
  personal = [],
  cargandoPadron = false,
  errorPadron = '',
}) {
  /*
   * Lo que se muestra como «recién ocurrido»: la marcación que envió esta
   * pantalla (`evento`, de App) o la novedad que trajo el ciclo. Al montar,
   * el evento que App ya tenía se muestra sin flash: al volver desde otra
   * sección no debe parecer que el lector acaba de leer una huella.
   */
  const [enVivo, setEnVivo] = useState(() => (
    evento ? { llave: `local-${evento.id}`, evento, flash: false } : null
  ));

  /* El flash es la reacción a una marcación en vivo, nunca a elegir una
     fila de la lista. */
  const mostrarFlash = !leyendo && enVivo?.flash === true;

  /* Fila de la lista elegida a mano (por su clave): mientras haya una, manda
     sobre la marcación en vivo en el escenario y en la barra de comidas. */
  const [claveSeleccionada, setClaveSeleccionada] = useState(null);

  /* Texto para acotar la lista por nombre o legajo, sobre lo ya cargado. */
  const [busqueda, setBusqueda] = useState('');

  /* Tiempo de comida por el que se acota la tarjeta de marcaciones. Arranca
     en la comida vigente del turno (o Desayuno si no hay una vigente válida);
     el filtrado es local, sobre lo ya cargado para la fecha elegida, así que
     cambiar de chip nunca dispara una consulta nueva. */
  const [filtroComida, setFiltroComida] = useState(() => comidaValida(pantalla?.comida) ?? COMIDAS_FILTRO[0]);

  /* Una vez que la nutricionista elige un chip a mano, el turno ya no debe
     pisarle la elección: solo se sincroniza automáticamente hasta el primer
     cambio manual. */
  const filtroTocado = useRef(false);
  function manejarFiltroComida(opcion) {
    filtroTocado.current = true;
    setFiltroComida(opcion);
  }

  const comidaTurno = pantalla?.comida;
  useEffect(() => {
    if (filtroTocado.current) return;
    const valida = comidaValida(comidaTurno);
    if (valida) setFiltroComida(valida);
  }, [comidaTurno]);

  /*
   * Lecturas y registros manuales de hoy (sin fecha, el servidor consulta el
   * día actual), en ciclos junto con el estado del comedor. Un fallo conserva
   * la lista anterior con un aviso de desactualización.
   */
  const [marcaciones, setMarcaciones] = useState(null);
  const [errorMarcaciones, setErrorMarcaciones] = useState('');

  /* Solo cocinera: las huellas no reconocidas identificables ahora, aparte de
     la ventana de marcaciones (que corta por fecha y en 100 filas). */
  const [pendientes, setPendientes] = useState(null);
  const [errorPendientes, setErrorPendientes] = useState('');
  const [lecturaAbierta, setLecturaAbierta] = useState(null);
  /* `intervencion.revision` de cada fila en la consulta anterior. */
  const revisiones = useRef(null);
  const cargandoMarcaciones = marcaciones === null && !errorMarcaciones;

  const idEvento = evento?.id ?? null;
  const eventoRecargado = useRef(idEvento);
  /* Mientras se lee una huella o App trae un evento que esta pantalla todavía
     no registró como propio, el ciclo no anuncia novedades: la marcación
     propia no debe aparecer dos veces como «recién llegada». */
  const deteccionEnPausa = useRef(false);
  deteccionEnPausa.current = leyendo || idEvento !== eventoRecargado.current;
  const recargarEstadoRef = useRef(recargarEstado);
  recargarEstadoRef.current = recargarEstado;
  const ciclo = useRef(null);

  useEffect(() => {
    const control = programarCicloCocina({
      consultarMarcaciones: ({ signal }) => obtenerUltimasMarcaciones({
        limite: LIMITE_MARCACIONES_COCINA, signal,
      }),
      // App ya pide el estado al montar la sección.
      refrescarEstado: ({ origen, signal }) => (origen === 'inicial'
        ? undefined
        : recargarEstadoRef.current?.({ conservar: true, signal })),
      puedeDetectar: () => !deteccionEnPausa.current,
      consultarPendientes: puedeIdentificar
        ? ({ signal }) => obtenerLecturasPorIdentificar({ signal })
        : null,
      alActualizarPendientes: ({ resultado, error }) => {
        if (error) {
          setErrorPendientes(error);
          return;
        }
        setPendientes(resultado);
        setErrorPendientes('');
      },
      alActualizar: ({ filas: recibidas, error, nueva }) => {
        if (error) {
          setErrorMarcaciones(error);
          return;
        }
        setMarcaciones(recibidas);
        setErrorMarcaciones('');
        /* Una fila que ya existía cambió (alguien registró su entrega): si es
           la que está a la vista, se redibuja con su resultado final, sin
           flash, porque no es una marcación nueva. */
        const { revisiones: actuales, cambiadas } = revisionesCambiadas(revisiones.current, recibidas);
        revisiones.current = actuales;
        if (cambiadas.length > 0) {
          setEnVivo((previo) => {
            if (!previo) return previo;
            const clave = previo.evento?.claveEvento ?? previo.llave;
            const fila = cambiadas.includes(clave) ? recibidas.find((r) => r.clave === clave) : null;
            return fila ? { ...previo, evento: { ...eventoDeFila(fila), claveEvento: fila.clave }, flash: false } : previo;
          });
        }
        if (nueva) {
          setEnVivo({ llave: nueva.clave, evento: eventoDeFila(nueva), flash: true });
          setClaveSeleccionada(null);
        }
      },
    });
    ciclo.current = control;
    return () => {
      control.cancelar();
      ciclo.current = null;
    };
  }, []);

  /*
   * Marcación enviada desde esta pantalla: pasa a ser lo «recién ocurrido»,
   * su clave queda como propia (el ciclo no la vuelve a anunciar) y se pide
   * un ciclo para traer la fila guardada y el cupo. La marca evita repetirlo
   * al volver a la sección con un evento viejo todavía en el estado de App.
   */
  useEffect(() => {
    if (idEvento === null || eventoRecargado.current === idEvento) return;
    eventoRecargado.current = idEvento;
    deteccionEnPausa.current = leyendo;
    ciclo.current?.registrarPropia(evento.claveEvento);
    setEnVivo({ llave: `local-${idEvento}`, evento, flash: true });
    setClaveSeleccionada(null);
    ciclo.current?.solicitar();
  }, [idEvento, evento, leyendo]);

  /* Mover el reloj de simulación cambia el día o la franja: la lista se
     vuelve a pedir y lo que traiga no se anuncia como recién ocurrido. */
  const versionRecargada = useRef(versionReloj);
  useEffect(() => {
    if (versionRecargada.current === versionReloj) return;
    versionRecargada.current = versionReloj;
    ciclo.current?.reiniciarReferencia();
    ciclo.current?.solicitar();
  }, [versionReloj]);

  /*
   * Mientras el ciclo no trae la fila guardada, la marcación recién enviada
   * se muestra al tope por su cuenta. `claveEvento` es la clave de esa fila
   * (lectura o asistencia manual, nunca el id numérico solo), así que en
   * cuanto la lista la trae, la copia local desaparece y no se ve dos veces.
   */
  const filas = useMemo(() => filasConPropia(marcaciones, evento), [marcaciones, evento]);

  /* Filtro estricto por tiempo de comida, más el texto de búsqueda por
     nombre o legajo, sobre lo ya cargado: nunca se muestran marcaciones de
     otra comida que la elegida, y buscar nunca dispara una consulta nueva. */
  const filasFiltradas = useMemo(() => {
    const termino = busqueda.trim().toLowerCase();
    return filas.filter((fila) => {
      const coincideComida = fila.comida?.toLowerCase() === filtroComida.toLowerCase();
      if (!coincideComida) return false;
      if (!termino) return true;
      const nombre = fila.persona?.nombre?.toLowerCase() ?? '';
      const legajo = fila.persona?.legajo?.toLowerCase() ?? '';
      return nombre.includes(termino) || legajo.includes(termino);
    });
  }, [filas, filtroComida, busqueda]);

  /* Fila elegida a mano en la lista, con la misma forma que el evento en
     vivo: así el escenario y la barra de comidas muestran cualquiera de los
     dos sin distinguir de dónde vino. */
  const eventoSeleccionado = useMemo(() => {
    if (claveSeleccionada === null) return null;
    const fila = filas.find((f) => f.clave === claveSeleccionada);
    return fila ? eventoDeFila(fila) : null;
  }, [claveSeleccionada, filas]);

  /* Lo que manda en el escenario y en la barra de comidas: la fila elegida a
     mano si hay una, o si no, la marcación en vivo. */
  const eventoMostrado = eventoSeleccionado ?? enVivo?.evento ?? null;
  /* La huella a la vista sigue pendiente de identificar: su resultado ofrece
     abrirla directamente en «Huellas por identificar». */
  const claveMostrada = eventoSeleccionado ? claveSeleccionada : enVivo?.evento?.claveEvento ?? enVivo?.llave;
  const lecturaMostradaPendiente = puedeIdentificar && eventoMostrado && !eventoMostrado.valido
    ? (pendientes?.lecturas ?? []).find((lectura) => lectura.clave === claveMostrada) ?? null
    : null;
  const origenMostrado = etiquetaDeOrigen(eventoMostrado?.origen);
  const mostrarResultado = !leyendo && eventoMostrado !== null;
  const personaMostrada = eventoMostrado?.persona;

  /* Comidas del día de hoy del comensal mostrado. */
  const usuarioIdConsultar = personaMostrada?.id;
  const consultarDia = useCallback(
    (signal) => usuarioIdConsultar
      ? obtenerDiaPersonal(usuarioIdConsultar, { fecha: fechaServidor, signal })
      : Promise.resolve(null),
    [usuarioIdConsultar, fechaServidor],
  );
  const { datos: dia, cargando: cargandoDia, error: errorDia, recargar: recargarDia } = useConsultaApi(consultarDia);

  return (
    <div className="vivo">
      {/*
        Flash de color a pantalla completa: fijo al viewport desde el borde del
        sidebar, así que cubre el contenido y también el header. Se dibuja en
        <body> mediante un portal porque la animación de entrada de sección
        aplica un `transform` al contenedor, y un ancestro transformado deja de
        ser el viewport para `position: fixed`: el flash se recortaba al área
        del main. La `key` reinicia la animación en cada marcación, incluso si
        el resultado se repite.
      */}
      {mostrarFlash
        ? createPortal(
            <div
              key={enVivo.llave}
              className={`vivo__flash vivo__flash--${enVivo.evento.valido ? 'exito' : 'error'}`}
              aria-hidden="true"
            />,
            document.body,
          )
        : null}

      <div className="vivo__grid">
        <div className="vivo__columna-izquierda">
          <section className="escenario">
            <header className="escenario__barra">
              {/* Rótulo neutral: la pantalla no sabe si hay un lector
                  conectado, así que no muestra un indicador de conexión. */}
              <span className="escenario__lector">
                Control de raciones · Comedor planta baja
              </span>
              <Etiqueta tono="neutro">
                {pantalla ? `${pantalla.totales_del_dia.raciones_servidas} raciones del día` : 'Consultando estado'}
              </Etiqueta>
            </header>

            <div className="escenario__cuerpo">
              {/* Las raciones viven junto al lector, no en una tarjeta aparte:
                  así se leen de un vistazo mientras se espera la marcación. */}
              <div className="escenario__gauge">
                <GaugeRaciones
                  cupo={pantalla?.cupo}
                  fueraDeHorario={pantalla?.fuera_de_horario}
                  turno={turno}
                />

                {/* Autoriza una ración sin pasar por el lector: mismas reglas
                    de turno y derecho, aplicadas por el servidor. Sin
                    `onMarcarManual` (rol cocinera) el bloque no existe. */}
                {onMarcarManual ? (
                  <div className="escenario__manual">
                    <span className="escenario__manual-etiqueta">Modo manual</span>
                    <p className="escenario__manual-nombre">
                      {personaSeleccionada ? personaSeleccionada.nombre : 'Seleccione comensal en barra'}
                    </p>
                    <Boton
                      variante="secundario"
                      anchoCompleto
                      onClick={() => onMarcarManual(personaSeleccionada.id)}
                      disabled={!personaSeleccionada || leyendo}
                    >
                      Aceptar ración manual
                    </Boton>
                  </div>
                ) : null}
              </div>

              <div className="escenario__principal">
                {leyendo ? (
                  <div className="escenario__estado escenario__estado--leyendo">
                    <span className="escenario__huella escenario__huella--activa">
                      <IconoHuella tamano={104} />
                    </span>
                    <p className="escenario__titulo-estado">Registrando asistencia…</p>
                    <p className="escenario__ayuda">Validando la marcación contra el padrón del turno.</p>
                  </div>
                ) : null}

                {!leyendo && eventoMostrado === null ? (
                  <div className="escenario__estado">
                    <span className="escenario__huella">
                      <IconoHuella tamano={104} />
                    </span>
                    <p className="escenario__titulo-estado">{pantalla?.fuera_de_horario ? 'Fuera de horario' : 'Esperando marcación'}</p>
                    <p className="escenario__ayuda">
                      {pantalla?.fuera_de_horario ? 'No hay una comida vigente. El registro de asistencias está deshabilitado.' : 'Aquí se mostrará el resultado de la marcación.'}
                    </p>
                  </div>
                ) : null}

                {mostrarResultado ? (
                  <div
                    key={eventoMostrado.id}
                    className={`resultado resultado--${eventoMostrado.valido ? 'exito' : 'error'}`}
                    role="status"
                  >
                    <span className="resultado__sello">
                      {eventoMostrado.valido ? <IconoCheck tamano={92} /> : <IconoEquis tamano={92} />}
                    </span>

                    <p className="resultado__titulo">{eventoMostrado.titulo}</p>
                    <p className="resultado__nombre">{personaMostrada?.nombre ?? 'Huella no reconocida'}</p>

                    <div className="resultado__meta">
                      {origenMostrado ? <Etiqueta tono="neutro">{origenMostrado}</Etiqueta> : null}
                      <Etiqueta tono="neutro">{personaMostrada.categoria}</Etiqueta>
                      <span className="resultado__legajo">Legajo {personaMostrada.legajo}</span>
                      <span className="resultado__hora">{eventoMostrado.hora}</span>
                    </div>

                    <p className="resultado__detalle">{eventoMostrado.detalle}</p>

                    {lecturaMostradaPendiente && lecturaAbierta !== lecturaMostradaPendiente.id ? (
                      <Boton onClick={() => setLecturaAbierta(lecturaMostradaPendiente.id)}>
                        Identificar a la persona
                      </Boton>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </div>
          </section>

          {/*
            Día del comensal mostrado: las comidas del turno con su estado,
            como en el historial. Se rearma al cambiar de persona —de ahí la
            `key`— para que las casillas entren escalonadas y se vea el
            cambio, sea por una marcación en vivo o por elegir una fila de la
            lista. Ocupa el mismo ancho que el lector: es su barra de estado,
            no una franja aparte.
          */}
          <footer className="vivo__dia" key={eventoMostrado?.id ?? 'sin-marcacion'}>
            {dia ? (
              <ul className="vivo__comidas">
                {dia.comidas.map((comida, indice) => (
                  <li
                    key={comida.id}
                    className={`comida comida--${estadoDeComida(comida)}`}
                    style={{ '--retraso': `${indice * 80}ms` }}
                  >
                    <span className="comida__nombre">{comida.etiqueta}</span>
                    <EstadoComida comida={comida} />
                  </li>
                ))}
              </ul>
            ) : (
              <div className="vivo__dia-vacio">
                {errorDia ? <p role="alert">{errorDia} <Boton variante="fantasma" onClick={recargarDia}>Reintentar historial</Boton></p>
                  : <p role="status">{eventoMostrado && cargandoDia ? 'Consultando las comidas del comensal…' : eventoMostrado ? 'No hay registro de este comensal para la fecha consultada.' : 'Cuando alguien marque, aquí se consultarán las comidas de su día.'}</p>}
              </div>
            )}
          </footer>
        </div>

        <aside className="vivo__lateral">
          {puedeIdentificar ? (
            <IdentificarLectura
              pendientes={pendientes}
              error={errorPendientes}
              personal={personal}
              cargandoPadron={cargandoPadron}
              errorPadron={errorPadron}
              abierta={lecturaAbierta}
              onAbrir={setLecturaAbierta}
              onResultado={() => ciclo.current?.solicitar()}
            />
          ) : null}

          <Tarjeta
            titulo="Marcaciones del turno"
            accesorio={`${filasFiltradas.length}`}
            className="vivo__tarjeta-historial"
          >
            <FiltroComida activo={filtroComida} onCambiar={manejarFiltroComida} />

            <div className="marcaciones__buscador">
              <span className="marcaciones__buscador-icono" aria-hidden="true">
                <IconoBuscar tamano={15} />
              </span>
              <input
                type="text"
                value={busqueda}
                onChange={(e) => setBusqueda(e.target.value)}
                placeholder="Buscar por nombre o legajo…"
                className="marcaciones__buscador-input"
                aria-label="Buscar comensal en las marcaciones del turno"
              />
              {busqueda ? (
                <button
                  type="button"
                  className="marcaciones__buscador-limpiar"
                  onClick={() => setBusqueda('')}
                  aria-label="Limpiar búsqueda"
                >
                  ×
                </button>
              ) : null}
            </div>

            {errorMarcaciones && filas.length > 0 ? (
              <p className="marcaciones__desactualizado" role="alert">
                Sin actualizar: se muestran las últimas marcaciones recibidas. {errorMarcaciones}
              </p>
            ) : null}

            {errorMarcaciones && filas.length === 0 ? (
              <p className="historial__vacio" role="alert">
                {errorMarcaciones}{' '}
                <Boton variante="fantasma" onClick={() => ciclo.current?.solicitar()}>Reintentar</Boton>
              </p>
            ) : cargandoMarcaciones && filas.length === 0 ? (
              <p className="historial__vacio" role="status">Consultando las marcaciones del día…</p>
            ) : filas.length === 0 ? (
              <p className="historial__vacio">
                Todavía no se registraron marcaciones hoy.
              </p>
            ) : filasFiltradas.length === 0 ? (
              <p className="historial__vacio">
                {busqueda.trim()
                  ? `No se encontraron marcaciones para «${busqueda}» en ${filtroComida}.`
                  : `No se registraron marcaciones de ${filtroComida} hoy.`}
              </p>
            ) : (
              <ul className="historial">
                {filasFiltradas.map((registro) => (
                  <li
                    key={registro.clave}
                    role="button"
                    tabIndex={0}
                    aria-pressed={claveSeleccionada === registro.clave}
                    className={`historial__fila historial__fila--${
                      registro.valido || identificadaPorCocina(registro) ? 'exito' : 'error'
                    }${claveSeleccionada === registro.clave ? ' historial__fila--activa' : ''}`}
                    onClick={() => setClaveSeleccionada(registro.clave)}
                    onKeyDown={(e) => {
                      if (e.key !== 'Enter' && e.key !== ' ') return;
                      e.preventDefault();
                      setClaveSeleccionada(registro.clave);
                    }}
                  >
                    <span className="historial__textos">
                      <span className="historial__nombre">{registro.persona.nombre}</span>
                      <span className="historial__sub">
                        {registro.persona.categoria}
                        {' · '}{registro.hora}
                        {registro.origen === 'asistencia_manual' ? ' · Registro manual' : null}
                        {identificadaPorCocina(registro)
                          ? ` · Identificada por cocina: ${registro.resultadoFinal.comensal.nombre ?? 'persona identificada'}`
                          : null}
                      </span>
                    </span>
                    {identificadaPorCocina(registro) ? (
                      <span className="historial__marca" aria-label="Entrega registrada por cocina" data-tooltip="Entrega registrada por cocina">
                        <IconoCheck tamano={16} />
                      </span>
                    ) : (
                      <span className="historial__marca" aria-label={registro.titulo} data-tooltip={registro.titulo}>
                        {registro.valido ? <IconoCheck tamano={16} /> : <IconoEquis tamano={16} />}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Tarjeta>
        </aside>
      </div>
    </div>
  );
}
