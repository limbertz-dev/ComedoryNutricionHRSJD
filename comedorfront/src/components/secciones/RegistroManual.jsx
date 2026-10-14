import { useEffect, useRef, useState } from 'react';
import Boton from '../ui/Boton.jsx';
import { IconoBuscar } from '../ui/Iconos.jsx';
import { autorizarMarcacionManual, marcacionIncierta } from '../../api.js';
import './RegistroManual.css';

/** true si `persona` es un comensal del padrón con id válido. */
function personaValida(persona) {
  return Number.isInteger(persona?.id) && persona.id > 0;
}

/** Comensales del padrón cuyo nombre o legajo contiene `busqueda`. */
export function filtrarPadron(personal = [], busqueda = '') {
  const termino = busqueda.trim().toLowerCase();
  if (!termino) return personal;
  return personal.filter((persona) => (persona.nombre ?? '').toLowerCase().includes(termino)
    || String(persona.legajo ?? '').toLowerCase().includes(termino));
}

/**
 * Comensal elegido solo si está entre las opciones visibles: las del padrón
 * actual que coinciden con la búsqueda. Si la búsqueda o el padrón lo dejan
 * fuera, no hay comensal (nunca se elige otro en su lugar).
 */
export function personaVisible(personal = [], busqueda = '', elegido = '') {
  if (!elegido) return null;
  const persona = filtrarPadron(personal, busqueda).find((p) => String(p.id) === String(elegido)) ?? null;
  return personaValida(persona) ? persona : null;
}

/** Misma identidad que se mostró al confirmar: id, nombre, categoría y legajo. */
export function mismaIdentidad(a, b) {
  return Boolean(a && b) && a.id === b.id && a.nombre === b.nombre
    && a.categoria === b.categoria && a.legajo === b.legajo;
}

/**
 * Aviso para la respuesta del servidor. Solo `valido === true` es un registro
 * exitoso: un 200 con `valido: false` es un rechazo de negocio y no registra
 * ninguna ración.
 */
export function avisoDeRegistroManual(resultado, persona) {
  const quien = persona?.nombre ? `${persona.nombre}: ` : '';
  if (resultado?.valido === true) {
    return {
      tipo: 'exito',
      titulo: resultado.titulo || 'Ración registrada',
      detalle: `${quien}${resultado.detalle || 'ración registrada a mano.'}`,
    };
  }
  return {
    tipo: 'rechazo',
    titulo: resultado?.titulo || 'Registro rechazado',
    detalle: `${quien}${resultado?.detalle ? `${resultado.detalle} ` : ''}No se registró ninguna ración.`,
  };
}

/**
 * Aviso para un fallo. Sin una respuesta que lo descarte (red, tiempo de
 * espera, respuesta ilegible o error 5xx) no se sabe si la ración quedó
 * registrada: hay que verificarlo antes de intentar de nuevo, y nada se
 * reenvía solo. Solo un 4xx dice que no se registró.
 */
export function avisoDeFalloRegistro(error) {
  if (marcacionIncierta(error)) {
    return {
      tipo: 'error',
      titulo: 'No se pudo confirmar el registro',
      detalle: 'No llegó una respuesta válida del servidor. Revise en la tabla si la ración '
        + 'quedó registrada antes de volver a intentarlo; el registro no se reenvía automáticamente.',
    };
  }
  return { tipo: 'error', titulo: 'No se registró la ración', detalle: error.message };
}

/**
 * Registro manual con un solo envío a la vez: mientras un POST está en vuelo,
 * otro clic no hace nada. Justo antes del POST, `vigente(persona)` confirma
 * que la identidad mostrada sigue siendo la elegida; si no, no se envía.
 * Con la respuesta (o el fallo) avisa con `alResultado`, llama `alExito`
 * solo si `valido === true` y después relee los datos con `refrescar`. Un
 * fallo de ese refresco no cambia el aviso del registro: lo informa quien
 * refresca.
 */
export function crearRegistroManual({
  registrar = autorizarMarcacionManual,
  vigente = () => true,
  alResultado = () => {},
  alExito = () => {},
  refrescar = async () => {},
}) {
  let enCurso = false;
  return async function registrarComensal(persona) {
    if (enCurso || !personaValida(persona) || !vigente(persona)) return null;
    enCurso = true;
    let aviso;
    let valido = false;
    try {
      const resultado = await registrar(persona.id, { persona });
      valido = resultado?.valido === true;
      aviso = avisoDeRegistroManual(resultado, persona);
    } catch (error) {
      aviso = avisoDeFalloRegistro(error);
    } finally {
      enCurso = false;
    }
    alResultado(aviso);
    if (valido) alExito();
    try {
      await refrescar();
    } catch {
      // El refresco informa su propio fallo; el aviso del registro se queda.
    }
    return aviso;
  };
}

/**
 * «Registrar ración manual» de Supervisión (jefa y sistemas): elegir un
 * comensal del padrón, ver su identidad y confirmar. Envía solo
 * { usuario_id, metodo: 'manual' } y el servidor decide, con su hora actual,
 * la comida vigente y si corresponde la ración. No necesita una lectura
 * previa ni simula una autorización excepcional.
 */
export default function RegistroManual({
  personal = [],
  cargandoPadron = false,
  errorPadron = '',
  registrar = autorizarMarcacionManual,
  onAviso = () => {},
  onExito = () => {},
  onRefrescar = async () => {},
  abiertoInicial = false,
  elegidoInicial = '',
  busquedaInicial = '',
}) {
  const [abierto, setAbierto] = useState(abiertoInicial);
  const [busqueda, setBusqueda] = useState(busquedaInicial);
  const [elegido, setElegido] = useState(String(elegidoInicial));
  const [enviando, setEnviando] = useState(false);

  /* Callbacks y selección al día sin rearmar el registro (que guarda el
     envío en vuelo): justo antes del POST se vuelve a validar la identidad
     contra el padrón y la búsqueda vigentes. */
  const actuales = useRef({});
  actuales.current = { registrar, onAviso, onExito, onRefrescar, personal, busqueda, elegido };
  const registro = useRef(null);
  if (registro.current === null) {
    registro.current = crearRegistroManual({
      registrar: (...argumentos) => actuales.current.registrar(...argumentos),
      vigente: (confirmada) => {
        const { personal: padron, busqueda: texto, elegido: id } = actuales.current;
        return mismaIdentidad(personaVisible(padron, texto, id), confirmada);
      },
      alResultado: (aviso) => {
        setEnviando(false);
        if (aviso.tipo === 'exito') setElegido('');
        actuales.current.onAviso(aviso);
      },
      alExito: () => actuales.current.onExito(),
      refrescar: () => actuales.current.onRefrescar(),
    });
  }
  const montado = useRef(true);
  useEffect(() => () => { montado.current = false; }, []);

  /* Si el padrón cambia y el elegido ya no está entre las opciones
     visibles, se limpia la selección. */
  useEffect(() => {
    setElegido((actual) => (actual && !personaVisible(personal, actuales.current.busqueda, actual) ? '' : actual));
  }, [personal]);

  const opciones = filtrarPadron(personal, busqueda);
  const persona = personaVisible(personal, busqueda, elegido);

  function cambiarBusqueda(texto) {
    setBusqueda(texto);
    if (elegido && !personaVisible(personal, texto, elegido)) setElegido('');
  }

  async function confirmar() {
    if (enviando || !persona) return;
    setEnviando(true);
    await registro.current(persona);
    if (montado.current) setEnviando(false);
  }

  function cerrar() {
    setAbierto(false);
    setBusqueda('');
    setElegido('');
  }

  if (!abierto) {
    return (
      <div className="registro-manual__barra">
        <Boton onClick={() => setAbierto(true)}>Registrar ración manual</Boton>
      </div>
    );
  }

  let contenido;
  if (cargandoPadron) {
    contenido = <p className="registro-manual__estado" role="status">Cargando padrón…</p>;
  } else if (errorPadron) {
    contenido = (
      <p className="registro-manual__estado registro-manual__estado--error" role="alert">
        No se puede registrar: el padrón no se cargó. {errorPadron}
      </p>
    );
  } else if (personal.length === 0) {
    contenido = (
      <p className="registro-manual__estado" role="status">
        El padrón no tiene comensales para elegir.
      </p>
    );
  } else {
    contenido = (
      <>
        <div className="registro-manual__campos">
          <div className="supervision__buscador registro-manual__buscador">
            <span className="supervision__buscador-icono" aria-hidden="true">
              <IconoBuscar tamano={15} />
            </span>
            <input
              type="text"
              className="supervision__buscador-input"
              value={busqueda}
              onChange={(e) => cambiarBusqueda(e.target.value)}
              placeholder="Buscar por nombre o legajo…"
              aria-label="Buscar comensal en el padrón"
              disabled={enviando}
            />
          </div>
          <label className="registro-manual__etiqueta" htmlFor="registro-manual-comensal">
            Comensal
          </label>
          <select
            id="registro-manual-comensal"
            className="supervision__select-padron registro-manual__select"
            value={persona ? elegido : ''}
            onChange={(e) => setElegido(e.target.value)}
            disabled={enviando}
          >
            <option value="">
              {opciones.length === 0 ? 'Ningún comensal coincide' : 'Seleccione comensal del padrón…'}
            </option>
            {opciones.map((p) => (
              <option key={p.id} value={String(p.id)}>
                {p.nombre} — {p.categoria} ({p.legajo})
              </option>
            ))}
          </select>
        </div>

        {persona ? (
          <div className="registro-manual__confirmacion">
            <p className="registro-manual__identidad">
              <strong>{persona.nombre}</strong>
              <span>{persona.categoria} · Legajo {persona.legajo}</span>
            </p>
            <div className="registro-manual__acciones">
              <Boton onClick={confirmar} disabled={enviando}>
                {enviando ? 'Registrando…' : 'Confirmar registro'}
              </Boton>
            </div>
          </div>
        ) : null}
      </>
    );
  }

  return (
    <section className="registro-manual" aria-label="Registrar ración manual">
      <header className="registro-manual__cabecera">
        <h2 className="registro-manual__titulo">Registrar ración manual</h2>
        <Boton variante="secundario" onClick={cerrar} disabled={enviando}>Cerrar</Boton>
      </header>
      <p className="registro-manual__nota">
        Se registra para el momento actual del servidor, aunque la tabla esté mostrando otra
        comida: el servidor decide qué comida rige y si al comensal le corresponde la ración.
      </p>
      {contenido}
    </section>
  );
}
