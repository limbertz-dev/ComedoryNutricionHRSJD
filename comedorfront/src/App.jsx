import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import Boton from './components/ui/Boton.jsx';
import Header from './components/layout/Header.jsx';
import PanelSesionCocinera from './components/layout/PanelSesionCocinera.jsx';
import Sidebar from './components/layout/Sidebar.jsx';
import PantallaEnVivo from './components/secciones/PantallaEnVivo.jsx';
import Supervision from './components/secciones/Supervision.jsx';
import Administracion from './components/secciones/Administracion.jsx';
import CuentasLectura from './components/secciones/CuentasLectura.jsx';
import ReglasSistema from './components/secciones/ReglasSistema.jsx';
import LectorBiometrico from './components/secciones/LectorBiometrico.jsx';
import Dashboard from './components/secciones/Dashboard.jsx';
import Reportes from './components/secciones/Reportes.jsx';
import Historial from './components/secciones/Historial.jsx';
import Login from './components/secciones/Login.jsx';
import SinPermiso from './components/secciones/SinPermiso.jsx';
import {
  SECCION_SIN_PERMISO,
  buscarSeccion,
  guardarSeccionActiva,
  leerSeccionGuardada,
  seccionesDeRol,
} from './navegacion.js';
import {
  puedeConsultarIntervenciones,
  puedeIdentificarLecturas,
  puedeVerSeccion,
  seccionInicialDeRol,
  usaDatosDelComedor,
} from './permisos.js';
import { escucharSesion } from './sesion.js';
import { obtenerEstadoPantalla, obtenerPersonal } from './api.js';
import { ENROLAMIENTO_QA_ACTIVO } from './config.js';

import useConsultaApi from './hooks/useConsultaApi.js';
import useSesion, { ProveedorSesion } from './hooks/useSesion.js';

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
  return (
    <ProveedorSesion>
      <PuertaDeSesion />
    </ProveedorSesion>
  );
}

/*
 * Sin sesión activa no se monta el panel: ni una consulta de datos sale antes
 * de que GET /auth/yo confirme el rol, y al cerrar o expirar la sesión el
 * panel se desmonta entero, con todo lo que tenía cargado.
 */
function PuertaDeSesion() {
  const { fase, rol, usuario, logout } = useSesion();

  if (fase === 'verificando') {
    return <p className="app__verificando" role="status">Verificando sesión…</p>;
  }
  if (fase !== 'activa') return <Login />;
  if (seccionesDeRol(rol).length === 0) {
    return (
      <main className="sin-permiso-pantalla">
        <SinPermiso onSalir={logout} />
      </main>
    );
  }
  return <Panel rol={rol} usuario={usuario} />;
}

export function Panel({ rol, usuario = null }) {
  /* Persistida en localStorage: un F5 en Historial o Reportes no debe
     devolver forzadamente a Control Biométrico. Si lo guardado no le
     corresponde al rol, arranca en su primera sección. */
  const [seccionActiva, setSeccionActiva] = useState(() => leerSeccionGuardada(rol));
  /* Sección cuya consulta respondió 403: se reemplaza por «Sin permiso» hasta
     que se elija otra, para que nunca quede a la vista con datos a medias. */
  const [seccionVedada, setSeccionVedada] = useState(null);
  const seccionActual = useRef(seccionActiva);
  seccionActual.current = seccionActiva;
  useEffect(() => escucharSesion((aviso) => {
    if (aviso.tipo === 'prohibido') setSeccionVedada(seccionActual.current);
  }), []);
  const [estado, despachar] = useReducer(reductorComedor, undefined, estadoInicial);

  /* Sistemas ya no opera el comedor: no se le pide el padrón ni el cupo del
     turno, y el encabezado no le muestra un turno que no usa. */
  const usaComedor = usaDatosDelComedor(rol);
  const [cargandoPersonal, setCargandoPersonal] = useState(usaComedor);
  const [errorApi, setErrorApi] = useState('');
  const consultaEstado = useCallback((signal) => {
    if (!usaComedor) return Promise.resolve(null);
    // Cada entrada a una sección vuelve a consultar el reloj y los cupos del servidor.
    return obtenerEstadoPantalla({ signal });
  }, [seccionActiva, usaComedor]);
  const { datos: pantalla, cargando: cargandoEstado, error: errorEstado, recargar: recargarEstado } = useConsultaApi(consultaEstado);

  const turno = pantalla?.comida ?? (pantalla?.fuera_de_horario ? 'Sin servicio' : 'Consultando…');

  useEffect(() => {
    if (!usaComedor) return undefined;
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
  }, [usaComedor]);

  /* Guardia única: ninguna sección se monta si el rol no la tiene o si el
     backend ya la negó con 403. */
  const permitida = puedeVerSeccion(rol, seccionActiva) && seccionVedada !== seccionActiva;
  const esPantallaEnVivo = permitida && seccionActiva === 'vivo';
  const seccion = permitida ? buscarSeccion(seccionActiva) : SECCION_SIN_PERMISO;

  function manejarCambiarSeccion(id) {
    setSeccionVedada(null);
    setSeccionActiva(id);
    guardarSeccionActiva(id);
  }

  const esCocinera = rol === 'cocinera';

  return (
    <div className={`app${esCocinera ? ' app--pantalla-completa' : ''}`}>
      {esCocinera ? (
        <PanelSesionCocinera />
      ) : (
        <Sidebar
          seccionActiva={seccionActiva}
          onCambiarSeccion={manejarCambiarSeccion}
        />
      )}

      {esCocinera ? null : (
        <Header seccion={seccion} turno={usaComedor ? turno : null} />
      )}

      <main className={`app__main${esPantallaEnVivo ? ' app__main--sin-scroll' : ''}`}>
        {permitida && usaComedor && (!esPantallaEnVivo || errorApi || errorEstado) ? (
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
        <div className="transicion" key={permitida ? seccionActiva : SECCION_SIN_PERMISO.id}>
          {!permitida ? (
            <SinPermiso
              onVolver={seccionActiva === seccionInicialDeRol(rol) ? null
                : () => manejarCambiarSeccion(seccionInicialDeRol(rol))}
            />
          ) : null}

          {esPantallaEnVivo ? (
            <PantallaEnVivo
              evento={estado.ultimoEvento}
              pantalla={pantalla}
              turno={turno}
              recargarEstado={recargarEstado}
              puedeIdentificar={puedeIdentificarLecturas(rol)}
              personal={estado.personal}
              cargandoPadron={cargandoPersonal}
              errorPadron={errorApi}
            />
          ) : null}

          {permitida && seccionActiva === 'supervision' ? (
            <Supervision
              puedeConsultarIntervenciones={puedeConsultarIntervenciones(rol)}
              puedeConsultarHuellas={rol === 'jefa' && ENROLAMIENTO_QA_ACTIVO}
            />
          ) : null}

          {permitida && seccionActiva === 'dashboard' ? (
            <Dashboard
              pantalla={pantalla}
            />
          ) : null}

          {permitida && seccionActiva === 'historial'
            ? <Historial personal={estado.personal} /> : null}

          {permitida && seccionActiva === 'reportes'
            ? <Reportes /> : null}
          {permitida && seccionActiva === 'admin'
            ? <Administracion usuarioActual={usuario} /> : null}
          {permitida && seccionActiva === 'reglas'
            ? <ReglasSistema /> : null}
          {permitida && seccionActiva === 'monitoreo'
            ? <LectorBiometrico /> : null}
          {permitida && seccionActiva === 'cuentas'
            ? <CuentasLectura /> : null}
        </div>
      </main>
    </div>
  );
}
