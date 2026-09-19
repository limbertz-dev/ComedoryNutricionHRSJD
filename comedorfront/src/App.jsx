import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import Boton from './components/ui/Boton.jsx';
import Header from './components/layout/Header.jsx';
import Sidebar from './components/layout/Sidebar.jsx';
import PantallaEnVivo from './components/secciones/PantallaEnVivo.jsx';
import SimuladorLector from './components/secciones/SimuladorLector.jsx';
import Dashboard from './components/secciones/Dashboard.jsx';
import Reportes from './components/secciones/Reportes.jsx';
import Historial from './components/secciones/Historial.jsx';
import Login from './components/secciones/Login.jsx';
import { SECCION_INICIAL, buscarSeccion, guardarSeccionActiva, leerSeccionGuardada } from './navegacion.js';
import {
  marcarAsistencia,
  obtenerEstadoPantalla,
  obtenerPersonal,
} from './api.js';

import useConsultaApi from './hooks/useConsultaApi.js';

/*
 * Duración mínima del estado "leyendo". El lector físico tarda en resolver una
 * huella; la API responde en decenas de milisegundos, así que sin este piso la
 * animación de lectura aparecería y desaparecería sin que nadie la vea.
 */
const MS_LECTURA = 700;

const esperar = (ms) => new Promise((resolver) => setTimeout(resolver, ms));

/**
 * Estado compartido del módulo.
 *
 * Vive aquí, en el padre, y no dentro de cada sección: por eso cambiar de
 * sección en el sidebar y volver a "Pantalla en vivo" no reinicia el padrón ni
 * la última marcación mostrada.
 *
 * La lista de marcaciones no se guarda aquí: la sirve el servidor desde
 * `lecturas_biometricas`, de modo que sobrevive a un F5 y sigue a la fecha que
 * se esté consultando, cosa que un historial en memoria nunca podría hacer.
 */
function estadoInicial() {
  return { personal: [], ultimoEvento: null };
}

function reductorComedor(estado, accion) {
  switch (accion.tipo) {
    case 'PERSONAL_CARGADO':
      return { ...estado, personal: accion.personal };
    case 'MARCACION':
      return { ...estado, ultimoEvento: accion.evento };
    default:
      return estado;
  }
}

export default function App() {
  const [sesionIniciada, setSesionIniciada] = useState(true);
  /* Persistida en localStorage: un F5 en Historial o Reportes no debe
     devolver forzadamente a Control Biométrico. */
  const [seccionActiva, setSeccionActiva] = useState(leerSeccionGuardada);
  const [estado, despachar] = useReducer(reductorComedor, undefined, estadoInicial);

  const [cargandoPersonal, setCargandoPersonal] = useState(true);
  const [errorApi, setErrorApi] = useState('');
  const [leyendo, setLeyendo] = useState(false);
  const [errorMarcacion, setErrorMarcacion] = useState('');
  /* A quién le toca apoyar la huella en el simulador. Vive aquí, no en
     PantallaEnVivo: el simulador ahora se monta desde el header. */
  const [seleccionado, setSeleccionado] = useState('');
  const consultaEstado = useCallback((signal) => {
    // Cada entrada a una sección vuelve a consultar el reloj y los cupos del servidor.
    return obtenerEstadoPantalla({ signal });
  }, [seccionActiva, sesionIniciada]);
  const { datos: pantalla, cargando: cargandoEstado, error: errorEstado, recargar: recargarEstado } = useConsultaApi(consultaEstado);
  const turno = pantalla?.fuera_de_horario ? 'Fuera de horario' : pantalla?.comida ?? 'Consultando…';

  useEffect(() => {
    const controlador = new AbortController();
    setCargandoPersonal(true);
    setErrorApi('');
    obtenerPersonal({ signal: controlador.signal })
      .then((personal) => {
        if (!controlador.signal.aborted) despachar({ tipo: 'PERSONAL_CARGADO', personal });
      })
      .catch((error) => {
        if (!controlador.signal.aborted) setErrorApi(error.message);
      })
      .finally(() => {
        if (!controlador.signal.aborted) setCargandoPersonal(false);
      });
    return () => controlador.abort();
  }, []);

  /*
   * Marcación disparada desde el simulador del lector. Vive aquí, junto al
   * resto del estado compartido: el evento y el historial sobreviven al cambio
   * de sección, y el refresco del cupo usa la misma consulta que alimenta al
   * gauge.
   */
  const marcando = useRef(false);
  async function manejarMarcacion(personaId) {
    if (marcando.current) return;
    marcando.current = true;
    setErrorMarcacion('');
    setLeyendo(true);
    try {
      const persona = estado.personal.find(({ id }) => id === personaId);
      const [evento] = await Promise.all([
        marcarAsistencia(personaId, { persona, metodo: 'biometrico' }),
        esperar(MS_LECTURA),
      ]);
      despachar({ tipo: 'MARCACION', evento });
      /* El cupo lo lleva el servidor: se vuelve a consultar en el acto para
         que el gauge reste la ración sin recargar la página. `conservar`
         mantiene el valor anterior hasta que llega el nuevo, para que el arco
         y la cifra bajen con su transición. */
      recargarEstado({ conservar: true });
    } catch (error) {
      setErrorMarcacion(error.message);
    } finally {
      setLeyendo(false);
      marcando.current = false;
    }
  }

  /*
   * Huella que el lector no llega a resolver contra nadie del padrón: no hay
   * comensal que enviar, así que viaja con `personaId: null`. No recarga el
   * cupo porque una lectura no identificada nunca consume una ración.
   */
  async function manejarFallaBiometrica() {
    if (marcando.current) return;
    marcando.current = true;
    setErrorMarcacion('');
    setLeyendo(true);
    try {
      const [evento] = await Promise.all([
        marcarAsistencia(null, { metodo: 'biometrico' }),
        esperar(MS_LECTURA),
      ]);
      despachar({ tipo: 'MARCACION', evento });
    } catch (error) {
      setErrorMarcacion(error.message);
    } finally {
      setLeyendo(false);
      marcando.current = false;
    }
  }

  /*
   * Ración autorizada a mano desde el "Modo manual" de Control Biométrico,
   * sin pasar por el lector: el servidor aplica las mismas reglas de turno
   * y derecho que a una marcación biométrica, así que un comensal sin
   * derecho recibe el mismo rechazo.
   */
  async function manejarMarcacionManual(personaId) {
    if (marcando.current) return;
    marcando.current = true;
    setErrorMarcacion('');
    try {
      const persona = estado.personal.find(({ id }) => id === personaId);
      const evento = await marcarAsistencia(personaId, { persona, metodo: 'manual' });
      despachar({ tipo: 'MARCACION', evento });
      recargarEstado({ conservar: true });
    } catch (error) {
      setErrorMarcacion(error.message);
    } finally {
      marcando.current = false;
    }
  }

  const esPantallaEnVivo = seccionActiva === 'vivo';
  const seccion = buscarSeccion(seccionActiva);

  function manejarCambiarSeccion(id) {
    setSeccionActiva(id);
    guardarSeccionActiva(id);
  }

  function manejarIngreso() {
    setSeccionActiva(SECCION_INICIAL);
    guardarSeccionActiva(SECCION_INICIAL);
    setSesionIniciada(true);
  }

  function manejarCerrarSesion() {
    setSeccionActiva(SECCION_INICIAL);
    guardarSeccionActiva(SECCION_INICIAL);
    setSesionIniciada(false);
  }

  if (!sesionIniciada) {
    return <Login onIngresar={manejarIngreso} />;
  }

  return (
    <div className="app">
      <Sidebar
        seccionActiva={seccionActiva}
        onCambiarSeccion={manejarCambiarSeccion}
        onCerrarSesion={manejarCerrarSesion}
      />

      <Header seccion={seccion} turno={turno}>
        {esPantallaEnVivo ? (
          <SimuladorLector
            personal={estado.personal}
            seleccionado={seleccionado}
            onSeleccionar={setSeleccionado}
            onMarcar={manejarMarcacion}
            onSimularFalla={manejarFallaBiometrica}
            leyendo={leyendo}
            error={errorMarcacion}
          />
        ) : null}
      </Header>

      <main className={`app__main${esPantallaEnVivo ? ' app__main--sin-scroll' : ''}`}>
        {/*
          En Control Biométrico el estado informativo (padrón cargado, fuera de
          horario) ya se lee en el escenario y en el simulador del header; acá
          repetirlo solo le resta a un layout sin scroll. Los errores sí se
          quedan: son los únicos que necesitan atención y acción (reintentar).
        */}
        {!esPantallaEnVivo || errorApi || errorEstado ? (
          <div className="app__estado-api">
            {!esPantallaEnVivo ? (
              <p id="estado-api" role="status">
                {cargandoPersonal ? 'Cargando padrón…' : `${estado.personal.length} ${estado.personal.length === 1 ? 'comensal cargado' : 'comensales cargados'}.`}
              </p>
            ) : null}
            {errorApi ? <p role="alert">{errorApi}</p> : null}
            {!esPantallaEnVivo && cargandoEstado ? <p role="status">Consultando estado del comedor…</p> : null}
            {errorEstado ? <p role="alert">{errorEstado} <Boton variante="fantasma" onClick={recargarEstado}>Reintentar estado</Boton></p> : null}
            {!esPantallaEnVivo && pantalla?.fuera_de_horario ? <p role="status">Fuera de horario: no hay comida vigente y no se pueden registrar asistencias.</p> : null}
          </div>
        ) : null}
        {/* La `key` reinicia la animación de entrada en cada cambio de sección. */}
        <div className="transicion" key={seccionActiva}>
          {esPantallaEnVivo ? (
            <PantallaEnVivo
              evento={estado.ultimoEvento}
              leyendo={leyendo}
              pantalla={pantalla}
              turno={turno}
              personaSeleccionada={estado.personal.find(({ id }) => id === Number(seleccionado)) ?? null}
              onMarcarManual={manejarMarcacionManual}
            />
          ) : null}

          {seccionActiva === 'dashboard' ? (
            <Dashboard
              pantalla={pantalla}
            />
          ) : null}

          {seccionActiva === 'historial' ? <Historial personal={estado.personal} /> : null}

          {seccionActiva === 'reportes' ? <Reportes /> : null}
        </div>
      </main>
    </div>
  );
}
