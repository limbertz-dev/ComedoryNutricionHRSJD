import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import Etiqueta from '../ui/Etiqueta.jsx';
import GaugeRaciones from '../ui/GaugeRaciones.jsx';
import Tarjeta from '../ui/Tarjeta.jsx';
import { obtenerDiaPersonal, obtenerUltimasMarcaciones } from '../../api.js';
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
}) {
  /*
   * Última marcación ya conocida al entrar en la sección. El evento vive en
   * App, así que al volver desde Resumen o Reportes sigue ahí: sin esta marca,
   * el flash se dispararía de nuevo por una marcación vieja, como si el lector
   * acabara de leer una huella.
   */
  const eventoAlMontar = useRef(evento?.id ?? null);

  /* El flash es la reacción a una lectura en vivo, nunca a elegir una fila de
     la lista: por eso sigue atado al `evento` real y no al mostrado. */
  const mostrarFlash = !leyendo && evento !== null && evento.id !== eventoAlMontar.current;

  /* Fila de la lista elegida a mano: mientras haya una, manda sobre la
     marcación en vivo tanto en el escenario como en la barra de comidas. */
  const [idSeleccionado, setIdSeleccionado] = useState(null);

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

  /* Lecturas guardadas de hoy: sin fecha, el servidor ya consulta el día
     actual por su cuenta. */
  const consultarMarcaciones = useCallback(
    (signal) => obtenerUltimasMarcaciones({ signal }),
    [],
  );
  const {
    datos: marcaciones,
    cargando: cargandoMarcaciones,
    error: errorMarcaciones,
    recargar: recargarMarcaciones,
  } = useConsultaApi(consultarMarcaciones);

  /*
   * Cada marcación nueva vuelve a pedir la lista, con `conservar` para que la
   * tarjeta no parpadee: lo que ya está en pantalla sigue ahí hasta que llega
   * la respuesta. También limpia la fila elegida a mano, para que el
   * escenario vuelva a seguir la marcación recién llegada. La marca evita
   * repetir esto al cambiar de fecha o al volver a la sección con un evento
   * viejo todavía en el estado de App.
   */
  const idEvento = evento?.id ?? null;
  const eventoRecargado = useRef(idEvento);
  useEffect(() => {
    if (idEvento === null || eventoRecargado.current === idEvento) return;
    eventoRecargado.current = idEvento;
    recargarMarcaciones({ conservar: true });
    setIdSeleccionado(null);
  }, [idEvento, recargarMarcaciones]);

  /* Mover el reloj de simulación cambia el día o la franja: la lista se
     vuelve a pedir, sin vaciarse mientras llega. */
  const versionRecargada = useRef(versionReloj);
  useEffect(() => {
    if (versionRecargada.current === versionReloj) return;
    versionRecargada.current = versionReloj;
    recargarMarcaciones({ conservar: true });
  }, [versionReloj, recargarMarcaciones]);

  /*
   * Mientras esa consulta viaja, la marcación recién enviada se muestra al
   * tope por su cuenta: `lectura_id` es la fila que el servidor acaba de
   * guardar, así que en cuanto la lista la trae, la copia local desaparece
   * sola y nunca se ve dos veces.
   */
  const filas = useMemo(() => {
    const guardadas = marcaciones ?? [];
    const propia = evento
      && !guardadas.some((fila) => fila.id === evento.lectura_id)
      ? [{
          id: `local-${evento.id}`,
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
        }]
      : [];
    return [...propia, ...guardadas];
  }, [marcaciones, evento]);

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
    if (idSeleccionado === null) return null;
    const fila = filas.find((f) => f.id === idSeleccionado);
    if (!fila) return null;
    return {
      id: fila.id,
      valido: fila.valido,
      titulo: fila.titulo,
      detalle: fila.valido
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
  }, [idSeleccionado, filas]);

  /* Lo que manda en el escenario y en la barra de comidas: la fila elegida a
     mano si hay una, o si no, la marcación en vivo. */
  const eventoMostrado = eventoSeleccionado ?? evento;
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
              key={evento.id}
              className={`vivo__flash vivo__flash--${evento.valido ? 'exito' : 'error'}`}
              aria-hidden="true"
            />,
            document.body,
          )
        : null}

      <div className="vivo__grid">
        <div className="vivo__columna-izquierda">
          <section className="escenario">
            <header className="escenario__barra">
              <span className="escenario__lector">
                <span className="escenario__pulso" aria-hidden="true" />
                Lector biométrico · Comedor planta baja
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
                      <Etiqueta tono="neutro">{personaMostrada.categoria}</Etiqueta>
                      <span className="resultado__legajo">Legajo {personaMostrada.legajo}</span>
                      <span className="resultado__hora">{eventoMostrado.hora}</span>
                    </div>

                    <p className="resultado__detalle">{eventoMostrado.detalle}</p>
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

            {errorMarcaciones && filas.length === 0 ? (
              <p className="historial__vacio" role="alert">
                {errorMarcaciones}{' '}
                <Boton variante="fantasma" onClick={recargarMarcaciones}>Reintentar</Boton>
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
                    key={registro.id}
                    role="button"
                    tabIndex={0}
                    aria-pressed={idSeleccionado === registro.id}
                    className={`historial__fila historial__fila--${
                      registro.valido ? 'exito' : 'error'
                    }${idSeleccionado === registro.id ? ' historial__fila--activa' : ''}`}
                    onClick={() => setIdSeleccionado(registro.id)}
                    onKeyDown={(e) => {
                      if (e.key !== 'Enter' && e.key !== ' ') return;
                      e.preventDefault();
                      setIdSeleccionado(registro.id);
                    }}
                  >
                    <span className="historial__textos">
                      <span className="historial__nombre">{registro.persona.nombre}</span>
                      <span className="historial__sub">
                        {registro.persona.categoria}
                        {' · '}{registro.hora}
                      </span>
                    </span>
                    <span className="historial__marca" aria-label={registro.titulo} data-tooltip={registro.titulo}>
                      {registro.valido ? <IconoCheck tamano={16} /> : <IconoEquis tamano={16} />}
                    </span>
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
