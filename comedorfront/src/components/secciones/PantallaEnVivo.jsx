import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import Etiqueta from '../ui/Etiqueta.jsx';
import GaugeRaciones from '../ui/GaugeRaciones.jsx';
import Tarjeta from '../ui/Tarjeta.jsx';
import { obtenerDiaPersonal, obtenerLecturasPorIdentificar, obtenerUltimasMarcaciones } from '../../api.js';
import { LIMITE_MARCACIONES_COCINA, programarCicloCocina } from '../../cocinaEnVivo.js';
import { crearIdentificador, revisionesCambiadas } from '../../identificacion.js';
import IdentificarLectura from './IdentificarLectura.jsx';
import RegistrarHuella from './RegistrarHuella.jsx';
import { ENROLAMIENTO_QA_ACTIVO } from '../../config.js';
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
  if (origen === 'racion_policia') return 'Policía';
  return null;
}

/** La huella no reconocida terminó en una entrega identificada por cocina. */
export function identificadaPorCocina(fila) {
  return ['identificacion_manual', 'identificacion_policia'].includes(fila?.resultadoFinal?.via);
}

/**
 * Distingue una huella no reconocida de un rechazo por falta de turno:
 * que el lector no haya reconocido la huella solo significa que aún no se
 * conoce la identidad del comensal, no que carezca de derecho en el turno.
 */
export function esHuellaNoReconocida(fila) {
  if (!fila || fila.valido || identificadaPorCocina(fila)) return false;
  const motivo = fila.motivo ?? fila.decisionOriginal?.motivo ?? null;
  if (motivo === 'no_identificado' || motivo === 'desconocida') return true;
  if (fila.titulo === 'Huella no reconocida') return true;
  return fila.origen === 'lectura_biometrica' && (fila.persona?.id ?? fila.usuarioId ?? null) === null;
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
  if (fila?.resultadoFinal?.via === 'identificacion_policia') {
    return {
      id: fila.clave,
      origen: fila.origen ?? null,
      valido: true,
      sinIdentificar: false,
      titulo: 'Policía registrado por cocina',
      detalle: 'El lector no reconoció la huella; cocina identificó al policía — cuenta en la columna Policías',
      hora: fila.hora,
      persona: { id: null, nombre: fila.resultadoFinal.comensal.nombre ?? 'Policía', categoria: 'Policías', legajo: '—' },
    };
  }
  if (identificadaPorCocina(fila)) {
    const comensal = fila.resultadoFinal.comensal;
    return {
      id: fila.clave,
      origen: fila.origen ?? null,
      valido: true,
      sinIdentificar: false,
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
  if (fila.origen === 'racion_policia') {
    // Huella de policía: vía libre, sin persona del padrón. Cuenta en Policías.
    return {
      id: fila.clave,
      origen: fila.origen,
      valido: true,
      sinIdentificar: false,
      titulo: 'Policía registrado',
      detalle: 'Ración de policía habilitada — vía libre, cuenta en la columna Policías',
      hora: fila.hora,
      persona: { id: null, nombre: fila.persona?.nombre || 'Policía', categoria: 'Policías', legajo: '—' },
    };
  }
  const manual = fila.origen === 'asistencia_manual';
  const sinIdentificar = esHuellaNoReconocida(fila);
  const motivo = fila.motivo ?? fila.decisionOriginal?.motivo ?? null;
  return {
    id: fila.clave,
    origen: fila.origen ?? null,
    valido: fila.valido,
    sinIdentificar,
    titulo: manual && fila.valido ? 'Registro manual' : fila.titulo,
    detalle: manual
      ? 'Ración registrada a mano desde Supervisión'
      : fila.valido
        ? 'Ración habilitada — comensal registrado'
        : sinIdentificar
          ? 'El lector no reconoció la huella — identidad aún no determinada (no implica falta de turno)'
          : motivo === 'duplicado'
            ? 'El comensal ya recibió su ración en este turno'
            : motivo === 'fuera_horario'
              ? 'Lectura realizada fuera del horario de servicio'
              : 'Marcación no habilitada para este turno',
    hora: fila.hora,
    persona: {
      id: fila.persona?.id ?? null,
      nombre: sinIdentificar && (!fila.persona?.nombre || fila.persona.nombre === 'Huella no reconocida' || fila.persona.nombre === 'Desconocido')
        ? 'Comensal sin identificar'
        : fila.persona?.nombre,
      categoria: sinIdentificar && (!fila.persona?.categoria || fila.persona.categoria === 'Sin clasificar')
        ? 'Sin identificar'
        : fila.persona?.categoria,
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
    // evento.tiempo y evento.comida_id vienen de la respuesta de la marcación.
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
 * Este puesto de control opera siempre sobre el turno en vivo de hoy: no
 * hay selector de fecha, ni falta hace, porque acá lo que importa es lo que
 * está pasando ahora mismo frente al lector.
 *
 * La lista y el estado del comedor (`recargarEstado`, de App) se releen en
 * ciclos de 3 s (`programarCicloCocina`): así llega a cocina lo registrado
 * en otro puesto, como la ración manual de la jefa. Una marcación no prueba
 * que haya un lector conectado.
 */
export default function PantallaEnVivo({
  evento,
  pantalla,
  turno,
  recargarEstado,
  puedeIdentificar = false,
  puedeEnrolar = ENROLAMIENTO_QA_ACTIVO,
  registroHuellaInicial = false,
  personal = [],
  cargandoPadron = false,
  errorPadron = '',
  marcacionesIniciales = null,
  pendientesIniciales = null,
  claveSeleccionadaInicial = null,
  lecturaAbiertaInicial = null,
  identificador: identificadorExterno = null,
}) {
  const [registrandoHuella, setRegistrandoHuella] = useState(registroHuellaInicial);
  const [casoHuella, setCasoHuella] = useState(null);
  const nuevoRef = useRef(null);

  function cerrarRegistroHuella() {
    setRegistrandoHuella(false);
    if (casoHuella) window.dispatchEvent(new Event('qa:volver-simulador'));
    else nuevoRef.current?.focus();
    setCasoHuella(null);
  }

  useEffect(() => {
    if (!puedeEnrolar || !puedeIdentificar) return undefined;
    function abrirCaso(evento) {
      const { caso, usuarioId } = evento.detail ?? {};
      if (!['qa01', 'qa02'].includes(caso) || !Number.isSafeInteger(usuarioId) || usuarioId <= 0) return;
      evento.preventDefault();
      setCasoHuella({ caso, usuarioId });
      setRegistrandoHuella(true);
    }
    window.addEventListener('qa:registrar-huella', abrirCaso);
    return () => window.removeEventListener('qa:registrar-huella', abrirCaso);
  }, [puedeEnrolar, puedeIdentificar]);
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
  const mostrarFlash = enVivo?.flash === true && !registrandoHuella;

  /* Fila de la lista elegida a mano (por su clave): mientras haya una, manda
     sobre la marcación en vivo en el escenario y en la barra de comidas. */
  const [claveSeleccionada, setClaveSeleccionada] = useState(claveSeleccionadaInicial);

  /* Texto para acotar la lista por nombre o legajo, sobre lo ya cargado. */
  const [busqueda, setBusqueda] = useState('');

  /* Tiempo de comida por el que se acota la tarjeta de marcaciones. Arranca
     en la comida vigente o la ultima cerrada, segun el servidor;
     el filtrado es local, sobre lo ya cargado para la fecha elegida, así que
     cambiar de chip nunca dispara una consulta nueva. */
  const [filtroComida, setFiltroComida] = useState(() => comidaValida(pantalla?.comida));

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
  const [marcaciones, setMarcaciones] = useState(marcacionesIniciales);
  const [errorMarcaciones, setErrorMarcaciones] = useState('');

  /* Solo cocinera: las huellas no reconocidas identificables ahora, aparte de
     la ventana de marcaciones (que corta por fecha y en 100 filas). */
  const [pendientes, setPendientes] = useState(pendientesIniciales);
  const [errorPendientes, setErrorPendientes] = useState('');
  const [lecturaAbierta, setLecturaAbierta] = useState(lecturaAbiertaInicial);
  const [lecturaCerradaManual, setLecturaCerradaManual] = useState(null);
  const [idPersonaEnIdentificacion, setIdPersonaEnIdentificacion] = useState(null);

  const identificadorPropio = useRef(null);
  if (puedeIdentificar && identificadorExterno === null && identificadorPropio.current === null) {
    identificadorPropio.current = crearIdentificador();
  }
  const identificador = identificadorExterno ?? identificadorPropio.current;

  /* `intervencion.revision` de cada fila en la consulta anterior. */
  const revisiones = useRef(null);
  const cargandoMarcaciones = marcaciones === null && !errorMarcaciones;

  const idEvento = evento?.id ?? null;
  const eventoRecargado = useRef(idEvento);
  /* Mientras App trae un evento que esta pantalla todavía no registró como
     propio, el ciclo no anuncia novedades: la marcación propia no debe
     aparecer dos veces como «recién llegada». */
  const deteccionEnPausa = useRef(false);
  deteccionEnPausa.current = idEvento !== eventoRecargado.current;
  const recargarEstadoRef = useRef(recargarEstado);
  recargarEstadoRef.current = recargarEstado;
  const ciclo = useRef(null);
  const fechaMarcaciones = pantalla?.fecha_comida ?? null;

  useEffect(() => {
    const control = programarCicloCocina({
      consultarMarcaciones: ({ signal }) => obtenerUltimasMarcaciones({
        limite: LIMITE_MARCACIONES_COCINA, fecha: fechaMarcaciones ?? undefined, signal,
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
  }, [fechaMarcaciones, puedeIdentificar]);

  /*
   * Marcación enviada desde esta pantalla: pasa a ser lo «recién ocurrido»,
   * su clave queda como propia (el ciclo no la vuelve a anunciar) y se pide
   * un ciclo para traer la fila guardada y el cupo. La marca evita repetirlo
   * al volver a la sección con un evento viejo todavía en el estado de App.
   */
  useEffect(() => {
    if (idEvento === null || eventoRecargado.current === idEvento) return;
    eventoRecargado.current = idEvento;
    deteccionEnPausa.current = false;
    ciclo.current?.registrarPropia(evento.claveEvento);
    setEnVivo({ llave: `local-${idEvento}`, evento, flash: true });
    setClaveSeleccionada(null);
    ciclo.current?.solicitar();
  }, [idEvento, evento]);

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
      const coincideComida = filtroComida === null || fila.comida?.toLowerCase() === filtroComida.toLowerCase();
      if (!coincideComida) return false;
      if (!termino) return true;
      const nombre = fila.persona?.nombre?.toLowerCase() ?? '';
      const legajo = fila.persona?.legajo?.toLowerCase() ?? '';
      return nombre.includes(termino) || legajo.includes(termino);
    });
  }, [filas, filtroComida, busqueda]);

  const filaSeleccionada = useMemo(() => {
    if (claveSeleccionada === null) return null;
    return filas.find((f) => f.clave === claveSeleccionada) ?? null;
  }, [claveSeleccionada, filas]);

  /* Fila elegida a mano en la lista, con la misma forma que el evento en
     vivo: así el escenario y la barra de comidas muestran cualquiera de los
     dos sin distinguir de dónde vino. */
  const eventoSeleccionado = useMemo(
    () => (filaSeleccionada ? eventoDeFila(filaSeleccionada) : null),
    [filaSeleccionada],
  );

  /* Lo que manda en el escenario y en la barra de comidas: la fila elegida a
     mano si hay una, o si no, la marcación en vivo. */
  const eventoMostrado = eventoSeleccionado ?? enVivo?.evento ?? null;
  /* La huella a la vista sigue pendiente de identificar: al seleccionarla en
     las marcaciones se abre directamente en el área central. */
  const claveMostrada = eventoSeleccionado ? claveSeleccionada : enVivo?.evento?.claveEvento ?? enVivo?.llave;
  const lecturaMostradaPendiente = puedeIdentificar && eventoMostrado && !eventoMostrado.valido
    ? (pendientes?.lecturas ?? []).find((lectura) => lectura.clave === claveMostrada)
      ?? (filaSeleccionada?.origen === 'lectura_biometrica'
        && (filaSeleccionada.puedeIdentificar || Boolean(identificador?.pendiente(filaSeleccionada.id)))
        ? filaSeleccionada
        : null)
    : null;

  const lecturaSeleccionadaAbrible = puedeIdentificar
    && filaSeleccionada
    && !filaSeleccionada.valido
    && !identificadaPorCocina(filaSeleccionada)
    && filaSeleccionada.origen === 'lectura_biometrica'
    && (
      filaSeleccionada.puedeIdentificar
      || (pendientes?.lecturas ?? []).some((lectura) => lectura.id === filaSeleccionada.id)
      || Boolean(identificador?.pendiente(filaSeleccionada.id))
    )
    ? filaSeleccionada.id
    : null;

  const lecturaAbiertaEfectiva = puedeIdentificar
    ? (lecturaAbierta
      ?? (lecturaSeleccionadaAbrible !== null && lecturaCerradaManual !== lecturaSeleccionadaAbrible
        ? lecturaSeleccionadaAbrible
        : null))
    : null;

  function seleccionarFilaHistorial(registro) {
    setClaveSeleccionada(registro.clave);
    if (!puedeIdentificar) return;
    const esAbrible = registro.origen === 'lectura_biometrica'
      && !registro.valido
      && !identificadaPorCocina(registro)
      && (
        registro.puedeIdentificar
        || (pendientes?.lecturas ?? []).some((lectura) => lectura.id === registro.id)
        || Boolean(identificador?.pendiente(registro.id))
      );
    setLecturaCerradaManual(null);
    setLecturaAbierta(esAbrible ? registro.id : null);
  }

  function manejarAbrirLectura(lecturaId) {
    if (lecturaId === null) {
      if (lecturaSeleccionadaAbrible !== null) {
        setLecturaCerradaManual(lecturaSeleccionadaAbrible);
      }
      setLecturaAbierta(null);
      return;
    }
    setLecturaCerradaManual(null);
    setLecturaAbierta(lecturaId);
    const clave = `lectura_biometrica:${lecturaId}`;
    if (filas.some((f) => f.clave === clave)) {
      setClaveSeleccionada(clave);
    } else {
      setClaveSeleccionada(null);
    }
  }

  const origenMostrado = etiquetaDeOrigen(eventoMostrado?.origen);
  const mostrarResultado = eventoMostrado !== null && lecturaAbiertaEfectiva === null && !registrandoHuella;
  const personaMostrada = eventoMostrado?.persona;

  /* Comidas del día de hoy del comensal mostrado o del comensal elegido al identificar. */
  const usuarioIdConsultar = registrandoHuella ? null : (lecturaAbiertaEfectiva !== null ? idPersonaEnIdentificacion : null)
    ?? personaMostrada?.id
    ?? null;
  const consultarDia = useCallback(
    (signal) => (usuarioIdConsultar
      ? obtenerDiaPersonal(usuarioIdConsultar, { signal })
      : Promise.resolve(null)),
    [usuarioIdConsultar],
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
                {puedeIdentificar && puedeEnrolar ? (
                  <Boton variante="secundario" className="escenario__nuevo" anchoCompleto
                    ref={nuevoRef} aria-label="Nuevo registro de huella"
                    aria-expanded={registrandoHuella} aria-controls="escenario-principal"
                    onClick={() => { setCasoHuella(null); setRegistrandoHuella(true); }}>
                    <span aria-hidden="true">+</span> Nuevo
                  </Boton>
                ) : null}
              </div>

              <div
                id="escenario-principal"
                className={`escenario__principal${
                  puedeIdentificar ? ' escenario__principal--cocina' : ''
                }${lecturaAbiertaEfectiva !== null || registrandoHuella ? ' escenario__principal--identificando' : ''}`}
              >
                {registrandoHuella && puedeIdentificar && puedeEnrolar ? (
                  <RegistrarHuella key={casoHuella?.caso ?? 'libre'}
                    onCerrar={cerrarRegistroHuella} onLectura={() => ciclo.current?.solicitar()}
                    usuarioRequerido={casoHuella?.usuarioId ?? null} elegidoInicial={casoHuella?.usuarioId ?? ''}
                    volverAlSimulador={casoHuella !== null} />
                ) : null}
                {puedeIdentificar && !registrandoHuella ? (
                  <IdentificarLectura
                    pendientes={pendientes}
                    error={errorPendientes}
                    personal={personal}
                    cargandoPadron={cargandoPadron}
                    errorPadron={errorPadron}
                    abierta={lecturaAbiertaEfectiva}
                    onAbrir={manejarAbrirLectura}
                    onResultado={() => ciclo.current?.solicitar()}
                    onCambiarPersona={setIdPersonaEnIdentificacion}
                    identificador={identificador}
                  />
                ) : null}

                {!registrandoHuella && lecturaAbiertaEfectiva === null && eventoMostrado === null ? (
                  <div className="escenario__estado">
                    <span className="escenario__huella">
                      <IconoHuella tamano={104} />
                    </span>
                    <p className="escenario__titulo-estado">{pantalla?.fuera_de_horario ? 'Fuera de horario' : 'Esperando marcación'}</p>
                    <p className="escenario__ayuda">
                      {pantalla?.fuera_de_horario ? `No hay una comida vigente. ${pantalla.comida ? `Se muestra ${pantalla.comida}, el último servicio. ` : ''}El registro de asistencias está deshabilitado.` : 'Aquí se mostrará el resultado de la marcación.'}
                    </p>
                  </div>
                ) : null}

                {mostrarResultado ? (
                  <div
                    key={eventoMostrado.id}
                    className={`resultado resultado--${
                      eventoMostrado.valido ? 'exito' : eventoMostrado.sinIdentificar ? 'aviso' : 'error'
                    }`}
                    role="status"
                  >
                    <span className="resultado__sello">
                      {eventoMostrado.valido ? (
                        <IconoCheck tamano={92} />
                      ) : eventoMostrado.sinIdentificar ? (
                        <IconoHuella tamano={92} />
                      ) : (
                        <IconoEquis tamano={92} />
                      )}
                    </span>

                    <p className="resultado__titulo">{eventoMostrado.titulo}</p>
                    <p className="resultado__nombre">{personaMostrada?.nombre ?? 'Comensal sin identificar'}</p>

                    <div className="resultado__meta">
                      {origenMostrado ? <Etiqueta tono="neutro">{origenMostrado}</Etiqueta> : null}
                      <Etiqueta tono={eventoMostrado.sinIdentificar ? 'aviso' : 'neutro'}>{personaMostrada.categoria}</Etiqueta>
                      <span className="resultado__legajo">Legajo {personaMostrada.legajo}</span>
                      <span className="resultado__hora">{eventoMostrado.hora}</span>
                    </div>

                    <p className="resultado__detalle">{eventoMostrado.detalle}</p>

                    {lecturaMostradaPendiente && lecturaAbiertaEfectiva !== lecturaMostradaPendiente.id ? (
                      <Boton onClick={() => manejarAbrirLectura(lecturaMostradaPendiente.id)}>
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
            cambio, sea por una marcación en vivo, por elegir una fila de la
            lista o por seleccionar al comensal al identificar una lectura.
          */}
          <footer className="vivo__dia" key={usuarioIdConsultar ?? eventoMostrado?.id ?? 'sin-marcacion'}>
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
                  : (
                    <p role="status">
                      {usuarioIdConsultar && cargandoDia
                        ? 'Consultando las comidas del comensal…'
                        : lecturaAbiertaEfectiva !== null || eventoMostrado?.sinIdentificar
                          ? 'Huella no reconocida: aún no se determinó la identidad del comensal. Seleccione a la persona para consultar sus comidas del día.'
                          : eventoMostrado
                            ? 'No hay registro de este comensal para la fecha consultada.'
                            : 'Cuando alguien marque, aquí se consultarán las comidas de su día.'}
                    </p>
                  )}
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
                  : filtroComida ? `No se registraron marcaciones de ${filtroComida} en la fecha del servicio.` : 'Consultando el servicio y sus marcaciones…'}
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
                      registro.valido || identificadaPorCocina(registro)
                        ? 'exito'
                        : esHuellaNoReconocida(registro)
                          ? 'aviso'
                          : 'error'
                    }${claveSeleccionada === registro.clave ? ' historial__fila--activa' : ''}`}
                    onClick={() => seleccionarFilaHistorial(registro)}
                    onKeyDown={(e) => {
                      if (e.key !== 'Enter' && e.key !== ' ') return;
                      e.preventDefault();
                      seleccionarFilaHistorial(registro);
                    }}
                  >
                    <span className="historial__textos">
                      <span className="historial__nombre">{registro.persona.nombre}</span>
                      <span className="historial__sub">
                        {registro.persona.categoria}
                        {' · '}{registro.hora}
                        {registro.origen === 'asistencia_manual' ? ' · Registro manual' : null}
                        {registro.origen === 'racion_policia' ? ' · Ración de policía' : null}
                        {identificadaPorCocina(registro)
                          ? ` · Identificada por cocina: ${registro.resultadoFinal.comensal.nombre ?? 'persona identificada'}`
                          : esHuellaNoReconocida(registro) && registro.puedeIdentificar && puedeIdentificar
                            ? ' · Pendiente de identificar'
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
