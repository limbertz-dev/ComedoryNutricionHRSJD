import { useCallback, useEffect, useState } from 'react';
import Boton from '../ui/Boton.jsx';
import Etiqueta from '../ui/Etiqueta.jsx';
import {
  eliminarHorarioProgramado,
  eliminarReglasDerechoProgramadas,
  obtenerHistorialHorario,
  obtenerHorariosVigentes,
  obtenerNovedadesDisponibles,
  obtenerReglasDerecho,
  programarHorario,
  programarReglasDerecho,
} from '../../api.js';
import './ReglasSistema.css';

/** Fecha local "YYYY-MM-DD" sin mover el día por zona horaria. */
export function fechaLocal(momento = new Date()) {
  const dos = (numero) => String(numero).padStart(2, '0');
  return `${momento.getFullYear()}-${dos(momento.getMonth() + 1)}-${dos(momento.getDate())}`;
}

/**
 * Fecha mínima de "vigente desde". En simulación App pasa el día del
 * servidor (claveDelDia del reloj), siempre; fuera de ella, el hoy local,
 * igual que Historial.
 */
export function minimoVigencia(hoy) {
  return typeof hoy === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(hoy) ? hoy : fechaLocal();
}

/** "2026-09-30" → "30/09/2026", por texto para no mover el día. */
export function formatoFecha(texto) {
  const partes = typeof texto === 'string' ? texto.split('-') : [];
  if (partes.length !== 3 || partes.some((parte) => !/^\d+$/.test(parte))) return String(texto ?? '');
  const [gestion, mes, dia] = partes;
  return `${dia}/${mes}/${gestion}`;
}

/** "2026-09-30" → "30/09", para la vista previa del cambio. */
export function formatoDiaMes(texto) {
  const partes = typeof texto === 'string' ? texto.split('-') : [];
  if (partes.length !== 3 || partes.some((parte) => !/^\d+$/.test(parte))) return String(texto ?? '');
  return `${partes[2]}/${partes[1]}`;
}

/** "11:30:00" → "11:30"; "11:30" queda igual. */
export function formatoHora(texto) {
  if (typeof texto !== 'string') return '';
  const partes = texto.split(':');
  if (partes.length < 2) return texto;
  return `${partes[0].padStart(2, '0')}:${partes[1].padStart(2, '0')}`;
}

/**
 * Estado de un horario por sus fechas: futuro es programado; con fin nulo
 * o no pasado sigue vigente; con fin pasado es anterior. El servidor
 * igual valida al eliminar (version_ya_vigente).
 */
export function estadoHorario(horario, hoy) {
  if (horario.vigenteDesde > hoy) return 'programada';
  if (horario.vigenteHasta === null || horario.vigenteHasta >= hoy) return 'vigente';
  return 'anterior';
}

export const ETIQUETAS_ESTADO = { programada: 'Programada', vigente: 'Vigente', anterior: 'Anterior' };
const TONOS_ESTADO = { programada: 'aviso', vigente: 'exito', anterior: 'neutro' };

const PESO_ESTADO = { programada: 0, vigente: 1, anterior: 2 };

/** Versiones de derecho: programadas, vigente y anteriores. */
export function ordenarVersionesDerecho(versiones = []) {
  return [...versiones].sort((a, b) => {
    const peso = (PESO_ESTADO[a.estado] ?? 99) - (PESO_ESTADO[b.estado] ?? 99);
    if (peso !== 0) return peso;
    if (a.estado === 'anterior') return b.vigenteDesde.localeCompare(a.vigenteDesde);
    return a.vigenteDesde.localeCompare(b.vigenteDesde);
  });
}

/** Líneas del resumen de cambios contra la versión vigente. */
export function resumenDiferencias(vigente, { duracionMinimaHoras, novedadesQueAnulan = [], excluirEnfermeria = false } = {}) {
  const lineas = [];
  if (duracionMinimaHoras !== vigente.duracionMinimaHoras) {
    lineas.push(`Turno mínimo: de ${vigente.duracionMinimaHoras} h a ${duracionMinimaHoras} h.`);
  }
  const antes = new Set(vigente.novedadesQueAnulan);
  const ahora = new Set(novedadesQueAnulan);
  const agregadas = [...ahora].filter((novedad) => !antes.has(novedad));
  const quitadas = [...antes].filter((novedad) => !ahora.has(novedad));
  if (agregadas.length > 0) {
    lineas.push(`Novedades que anulan: se agrega ${agregadas.map((novedad) => `«${novedad}»`).join(', ')}.`);
  }
  if (quitadas.length > 0) {
    lineas.push(`Novedades que anulan: se quita ${quitadas.map((novedad) => `«${novedad}»`).join(', ')}.`);
  }
  if (excluirEnfermeria !== vigente.excluirEnfermeria) {
    lineas.push(excluirEnfermeria ? 'Enfermería: ahora queda excluida.' : 'Enfermería: deja de estar excluida.');
  }
  if (lineas.length === 0) lineas.push('Sin cambios respecto a la versión vigente.');
  return lineas;
}

/**
 * Reglas del sistema (solo sistemas).
 *
 * Dos pestañas: horarios de comida (tabla con programar e historial) y
 * derecho a comer (tarjeta vigente, programar versión y lista). `hoy` es
 * el día del servidor en simulación; fuera de ella, hoy local.
 */
export default function ReglasSistema({ hoy, pestanaInicial = 'horarios' }) {
  const [minimo] = useState(() => minimoVigencia(hoy));
  const [pestana, setPestana] = useState(pestanaInicial);

  return (
    <div className="reglas">
      <p className="reglas__nota" role="note">
        Los cambios se aplican desde la fecha elegida y nunca modifican días pasados.
      </p>

      <div className="reglas__pestanas" role="tablist" aria-label="Reglas del sistema">
        <button
          type="button"
          role="tab"
          aria-selected={pestana === 'horarios'}
          className={`reglas__pestana${pestana === 'horarios' ? ' reglas__pestana--activa' : ''}`}
          onClick={() => setPestana('horarios')}
        >
          Horarios de comida
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={pestana === 'derecho'}
          className={`reglas__pestana${pestana === 'derecho' ? ' reglas__pestana--activa' : ''}`}
          onClick={() => setPestana('derecho')}
        >
          Derecho a comer
        </button>
      </div>

      {pestana === 'horarios'
        ? <PestanaHorarios hoyMinimo={minimo} />
        : <PestanaDerecho hoyMinimo={minimo} />}
    </div>
  );
}

/** Aviso de éxito o error tras programar o eliminar, con cierre manual. */
function AvisoReglas({ aviso, onCerrar }) {
  return (
    <div
      className={`reglas__aviso reglas__aviso--${aviso.tipo}`}
      role={aviso.tipo === 'exito' ? 'status' : 'alert'}
    >
      <div className="reglas__aviso-contenido">
        <strong className="reglas__aviso-titulo">{aviso.titulo}</strong>
        {aviso.detalle ? (
          <p className="reglas__aviso-detalle">{aviso.detalle}</p>
        ) : null}
      </div>
      <button
        type="button"
        className="reglas__aviso-cerrar"
        onClick={onCerrar}
        aria-label="Cerrar aviso"
      >
        ×
      </button>
    </div>
  );
}

/** Fondo + caja de diálogo. Se cierra con Escape o con un clic en el fondo. */
function DialogoReglas({ etiqueta, onCerrar, children }) {
  useEffect(() => {
    function alTeclado(evento) {
      if (evento.key === 'Escape') onCerrar();
    }
    document.addEventListener('keydown', alTeclado);
    return () => document.removeEventListener('keydown', alTeclado);
  }, [onCerrar]);

  return (
    <div
      className="reglas__fondo"
      onMouseDown={(evento) => {
        if (evento.target === evento.currentTarget) onCerrar();
      }}
    >
      <div className="reglas__dialogo" role="dialog" aria-label={etiqueta}>
        {children}
      </div>
    </div>
  );
}

/** Confirmación genérica de Eliminar, con Cancelar y Eliminar. */
export function DialogoConfirmacion({ titulo, mensaje, textoConfirmar = 'Eliminar', procesando = false, onConfirmar, onCancelar }) {
  return (
    <DialogoReglas etiqueta={titulo} onCerrar={onCancelar}>
      <h2 className="reglas__dialogo-titulo">{titulo}</h2>
      <p className="reglas__dialogo-mensaje">{mensaje}</p>
      <div className="reglas__dialogo-acciones">
        <Boton variante="secundario" onClick={onCancelar} disabled={procesando}>
          Cancelar
        </Boton>
        <Boton onClick={onConfirmar} disabled={procesando}>
          {procesando ? 'Eliminando…' : textoConfirmar}
        </Boton>
      </div>
    </DialogoReglas>
  );
}

/**
 * Pestaña de horarios: tabla de los que rigen, con Programar cambio e
 * Historial por comida. Tras cada acción la tabla se relee del servidor.
 */
export function PestanaHorarios({
  hoyMinimo,
  horariosIniciales = null,
  cargandoInicial = true,
  errorInicial = null,
  avisoInicial = null,
  programarInicial = null,
  historialInicial = null,
}) {
  const [cargando, setCargando] = useState(cargandoInicial);
  const [error, setError] = useState(errorInicial);
  const [horarios, setHorarios] = useState(horariosIniciales);
  const [aviso, setAviso] = useState(avisoInicial);
  const [programar, setProgramar] = useState(programarInicial);
  const [historial, setHistorial] = useState(historialInicial);

  const cargar = useCallback(async ({ signal } = {}) => {
    setCargando(true);
    setError(null);
    try {
      const lista = await obtenerHorariosVigentes({ signal });
      if (signal?.aborted) return;
      setHorarios(lista);
    } catch (fallo) {
      if (!signal?.aborted) setError(fallo.message);
    } finally {
      if (!signal?.aborted) setCargando(false);
    }
  }, []);

  useEffect(() => {
    const controlador = new AbortController();
    cargar({ signal: controlador.signal });
    return () => controlador.abort();
  }, [cargar]);

  /* Relectura silenciosa tras programar o eliminar: la tabla sigue visible. */
  async function releer() {
    try {
      setHorarios(await obtenerHorariosVigentes());
    } catch (fallo) {
      setAviso({ tipo: 'error', titulo: 'No se pudo actualizar', detalle: fallo.message });
    }
  }

  async function manejarProgramado() {
    setProgramar(null);
    setAviso({ tipo: 'exito', titulo: 'Cambio programado', detalle: 'Regirá desde la fecha elegida.' });
    await releer();
  }

  async function manejarEliminado() {
    setAviso({ tipo: 'exito', titulo: 'Horario eliminado', detalle: 'Se quitó el cambio programado.' });
    await releer();
  }

  if (cargando) {
    return <p className="reglas__estado" role="status">Cargando horarios…</p>;
  }

  if (error) {
    return (
      <div className="reglas__error" role="alert">
        <p>{error}</p>
        <Boton onClick={() => cargar()}>Reintentar horarios</Boton>
      </div>
    );
  }

  const lista = horarios ?? [];

  return (
    <div className="reglas__panel">
      {aviso ? <AvisoReglas aviso={aviso} onCerrar={() => setAviso(null)} /> : null}

      {lista.length === 0 ? (
        <p className="reglas__vacio" role="status">No hay horarios cargados.</p>
      ) : (
        <div className="reglas__tabla-caja">
          <table className="reglas__tabla" aria-label="Horarios de comida">
            <thead>
              <tr>
                <th scope="col">Comida</th>
                <th scope="col">Horario</th>
                <th scope="col">Vigente desde</th>
                <th scope="col">Motivo</th>
                <th scope="col">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {lista.map((horario) => (
                <tr key={horario.horarioId}>
                  <td className="reglas__comida">{horario.comida}</td>
                  <td>
                    {formatoHora(horario.horaInicio)}–{formatoHora(horario.horaFin)}
                    {horario.cruzaMedianoche ? (
                      <span className="reglas__medianoche">cruza medianoche</span>
                    ) : null}
                  </td>
                  <td>{formatoFecha(horario.vigenteDesde)}</td>
                  <td>{horario.motivo || '—'}</td>
                  <td>
                    <div className="reglas__acciones">
                      <Boton variante="secundario" onClick={() => setProgramar(horario)}>
                        Programar cambio
                      </Boton>
                      <Boton variante="secundario" onClick={() => setHistorial(horario)}>
                        Historial
                      </Boton>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {programar ? (
        <DialogoProgramarHorario
          horario={programar}
          hoyMinimo={hoyMinimo}
          onProgramado={manejarProgramado}
          onCerrar={() => setProgramar(null)}
        />
      ) : null}

      {historial ? (
        <DialogoHistorialHorario
          horario={historial}
          hoy={hoyMinimo}
          onEliminado={manejarEliminado}
          onCerrar={() => setHistorial(null)}
        />
      ) : null}
    </div>
  );
}

/**
 * Programar cambio de horario: horas, vigente desde (mínimo hoy del
 * servidor) y motivo, con vista previa antes de confirmar.
 */
export function DialogoProgramarHorario({
  horario,
  hoyMinimo,
  onProgramado,
  onCerrar,
  valoresIniciales = {},
  errorInicial = '',
}) {
  const [horaInicio, setHoraInicio] = useState(valoresIniciales.horaInicio ?? formatoHora(horario.horaInicio));
  const [horaFin, setHoraFin] = useState(valoresIniciales.horaFin ?? formatoHora(horario.horaFin));
  const [vigenteDesde, setVigenteDesde] = useState(valoresIniciales.vigenteDesde ?? hoyMinimo);
  const [motivo, setMotivo] = useState(valoresIniciales.motivo ?? '');
  const [programando, setProgramando] = useState(false);
  const [error, setError] = useState(errorInicial);

  const vistaPrevia = horaInicio && horaFin && vigenteDesde
    ? `Desde el ${formatoDiaMes(vigenteDesde)}, ${horario.comida} pasará a ${horaInicio}–${horaFin}.`
    : null;

  async function programar() {
    if (programando) return;
    setProgramando(true);
    setError('');
    try {
      await programarHorario({
        comidaId: horario.comidaId,
        horaInicio,
        horaFin,
        vigenteDesde,
        motivo,
      });
      onProgramado();
    } catch (fallo) {
      setError(fallo.message);
    } finally {
      setProgramando(false);
    }
  }

  return (
    <DialogoReglas etiqueta={`Programar cambio de ${horario.comida}`} onCerrar={onCerrar}>
      <h2 className="reglas__dialogo-titulo">Programar cambio de {horario.comida}</h2>
      <p className="reglas__ayuda">
        Horario actual: {formatoHora(horario.horaInicio)}–{formatoHora(horario.horaFin)}.
      </p>

      <div className="reglas__fila-campos">
        <label className="reglas__campo" htmlFor="programar-hora-inicio">
          <span className="reglas__campo-rotulo">Hora de inicio</span>
          <input
            id="programar-hora-inicio"
            type="time"
            className="reglas__input"
            value={horaInicio}
            onChange={(evento) => setHoraInicio(evento.target.value)}
          />
        </label>
        <label className="reglas__campo" htmlFor="programar-hora-fin">
          <span className="reglas__campo-rotulo">Hora de fin</span>
          <input
            id="programar-hora-fin"
            type="time"
            className="reglas__input"
            value={horaFin}
            onChange={(evento) => setHoraFin(evento.target.value)}
          />
        </label>
      </div>

      <label className="reglas__campo" htmlFor="programar-vigente-desde">
        <span className="reglas__campo-rotulo">Vigente desde</span>
        <input
          id="programar-vigente-desde"
          type="date"
          className="reglas__input"
          value={vigenteDesde}
          min={hoyMinimo}
          onChange={(evento) => setVigenteDesde(evento.target.value)}
        />
      </label>

      <label className="reglas__campo" htmlFor="programar-motivo">
        <span className="reglas__campo-rotulo">Motivo</span>
        <input
          id="programar-motivo"
          type="text"
          className="reglas__input"
          value={motivo}
          onChange={(evento) => setMotivo(evento.target.value)}
          placeholder="Por qué cambia el horario"
          autoComplete="off"
        />
      </label>

      {vistaPrevia ? <p className="reglas__vista-previa" role="status">{vistaPrevia}</p> : null}
      {error ? <p className="reglas__error-campo" role="alert">{error}</p> : null}

      <div className="reglas__dialogo-acciones">
        <Boton variante="secundario" onClick={onCerrar} disabled={programando}>
          Cancelar
        </Boton>
        <Boton onClick={programar} disabled={programando}>
          {programando ? 'Programando…' : 'Programar'}
        </Boton>
      </div>
    </DialogoReglas>
  );
}

/**
 * Historial de una comida: sus versiones con estado; las programadas
 * traen Eliminar con confirmación.
 */
export function DialogoHistorialHorario({
  horario,
  hoy,
  onEliminado,
  onCerrar,
  versionesIniciales = null,
  cargandoInicial = true,
  errorInicial = null,
  confirmacionInicial = null,
}) {
  const [cargando, setCargando] = useState(cargandoInicial);
  const [error, setError] = useState(errorInicial);
  const [versiones, setVersiones] = useState(versionesIniciales);
  const [confirmacion, setConfirmacion] = useState(confirmacionInicial);
  const [eliminando, setEliminando] = useState(false);
  const [errorAccion, setErrorAccion] = useState('');

  const cargar = useCallback(async ({ signal } = {}) => {
    setCargando(true);
    setError(null);
    try {
      const lista = await obtenerHistorialHorario(horario.comidaId, { signal });
      if (signal?.aborted) return;
      setVersiones(lista);
    } catch (fallo) {
      if (!signal?.aborted) setError(fallo.message);
    } finally {
      if (!signal?.aborted) setCargando(false);
    }
  }, [horario.comidaId]);

  useEffect(() => {
    const controlador = new AbortController();
    cargar({ signal: controlador.signal });
    return () => controlador.abort();
  }, [cargar]);

  async function manejarEliminar() {
    if (!confirmacion || eliminando) return;
    setEliminando(true);
    setErrorAccion('');
    try {
      await eliminarHorarioProgramado(confirmacion.horarioId);
      setConfirmacion(null);
      onEliminado();
      const lista = await obtenerHistorialHorario(horario.comidaId);
      setVersiones(lista);
    } catch (fallo) {
      setErrorAccion(fallo.message);
    } finally {
      setEliminando(false);
    }
  }

  return (
    <DialogoReglas etiqueta={`Historial de ${horario.comida}`} onCerrar={onCerrar}>
      <h2 className="reglas__dialogo-titulo">Historial de {horario.comida}</h2>

      {cargando ? <p className="reglas__ayuda" role="status">Cargando historial…</p> : null}
      {error ? (
        <div className="reglas__error" role="alert">
          <p>{error}</p>
          <Boton onClick={() => cargar()}>Reintentar historial</Boton>
        </div>
      ) : null}

      {!cargando && !error ? (
        <ul className="reglas__versiones" aria-label={`Versiones de ${horario.comida}`}>
          {(versiones ?? []).map((version) => {
            const estado = estadoHorario(version, hoy);
            return (
              <li key={version.horarioId} className="reglas__version">
                <div className="reglas__version-datos">
                  <Etiqueta tono={TONOS_ESTADO[estado]}>{ETIQUETAS_ESTADO[estado]}</Etiqueta>
                  <strong>
                    {formatoHora(version.horaInicio)}–{formatoHora(version.horaFin)}
                  </strong>
                  <span>Desde el {formatoFecha(version.vigenteDesde)}</span>
                  {version.motivo ? <span className="reglas__version-motivo">{version.motivo}</span> : null}
                </div>
                {estado === 'programada' ? (
                  <Boton variante="secundario" onClick={() => setConfirmacion(version)}>
                    Eliminar
                  </Boton>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}

      {errorAccion ? <p className="reglas__error-campo" role="alert">{errorAccion}</p> : null}

      <div className="reglas__dialogo-acciones">
        <Boton variante="secundario" onClick={onCerrar}>
          Cerrar
        </Boton>
      </div>

      {confirmacion ? (
        <DialogoConfirmacion
          titulo="Eliminar horario programado"
          mensaje={`¿Eliminar el cambio de ${horario.comida} que regiría desde el ${formatoFecha(confirmacion.vigenteDesde)}?`}
          procesando={eliminando}
          onConfirmar={manejarEliminar}
          onCancelar={() => setConfirmacion(null)}
        />
      ) : null}
    </DialogoReglas>
  );
}

/**
 * Pestaña de derecho: tarjeta de la versión vigente, programar nueva
 * versión y lista de versiones. Tras cada acción todo se relee.
 */
export function PestanaDerecho({
  hoyMinimo,
  derechoInicial = null,
  novedadesIniciales = null,
  cargandoInicial = true,
  errorInicial = null,
  avisoInicial = null,
  formularioInicial = false,
  confirmacionInicial = null,
}) {
  const [cargando, setCargando] = useState(cargandoInicial);
  const [error, setError] = useState(errorInicial);
  const [dato, setDato] = useState(derechoInicial);
  const [novedades, setNovedades] = useState(novedadesIniciales);
  const [aviso, setAviso] = useState(avisoInicial);
  const [formulario, setFormulario] = useState(formularioInicial);
  const [confirmacion, setConfirmacion] = useState(confirmacionInicial);
  const [eliminando, setEliminando] = useState(false);

  const cargar = useCallback(async ({ signal } = {}) => {
    setCargando(true);
    setError(null);
    try {
      const [reglas, disponibles] = await Promise.all([
        obtenerReglasDerecho({ signal }),
        obtenerNovedadesDisponibles({ signal }),
      ]);
      if (signal?.aborted) return;
      setDato(reglas);
      setNovedades(disponibles);
    } catch (fallo) {
      if (!signal?.aborted) setError(fallo.message);
    } finally {
      if (!signal?.aborted) setCargando(false);
    }
  }, []);

  useEffect(() => {
    const controlador = new AbortController();
    cargar({ signal: controlador.signal });
    return () => controlador.abort();
  }, [cargar]);

  async function releer() {
    try {
      const [reglas, disponibles] = await Promise.all([
        obtenerReglasDerecho(),
        obtenerNovedadesDisponibles(),
      ]);
      setDato(reglas);
      setNovedades(disponibles);
    } catch (fallo) {
      setAviso({ tipo: 'error', titulo: 'No se pudo actualizar', detalle: fallo.message });
    }
  }

  async function manejarProgramada() {
    setFormulario(false);
    setAviso({ tipo: 'exito', titulo: 'Versión programada', detalle: 'Regirá desde la fecha elegida.' });
    await releer();
  }

  async function manejarEliminar() {
    if (!confirmacion || eliminando) return;
    setEliminando(true);
    try {
      await eliminarReglasDerechoProgramadas(confirmacion.id);
      setConfirmacion(null);
      setAviso({ tipo: 'exito', titulo: 'Versión eliminada', detalle: 'Se quitó la versión programada.' });
      await releer();
    } catch (fallo) {
      setConfirmacion(null);
      setAviso({ tipo: 'error', titulo: 'No se pudo eliminar', detalle: fallo.message });
    } finally {
      setEliminando(false);
    }
  }

  if (cargando) {
    return <p className="reglas__estado" role="status">Cargando derecho a comer…</p>;
  }

  if (error) {
    return (
      <div className="reglas__error" role="alert">
        <p>{error}</p>
        <Boton onClick={() => cargar()}>Reintentar derecho</Boton>
      </div>
    );
  }

  const vigente = dato.vigente;
  const versiones = ordenarVersionesDerecho(dato.versiones);

  return (
    <div className="reglas__panel">
      {aviso ? <AvisoReglas aviso={aviso} onCerrar={() => setAviso(null)} /> : null}

      <section className="reglas__tarjeta" aria-label="Versión vigente del derecho a comer">
        <div className="reglas__tarjeta-encabezado">
          <h3 className="reglas__tarjeta-titulo">Versión vigente</h3>
          <Etiqueta tono="exito">Vigente</Etiqueta>
        </div>
        <dl className="reglas__datos">
          <div className="reglas__dato">
            <dt>Turno mínimo</dt>
            <dd>{vigente.duracionMinimaHoras} h</dd>
          </div>
          <div className="reglas__dato">
            <dt>Novedades que anulan</dt>
            <dd>
              {vigente.novedadesQueAnulan.length === 0
                ? 'Ninguna: cualquier novedad mantiene el derecho.'
                : (
                  <span className="reglas__novedades">
                    {vigente.novedadesQueAnulan.map((novedad) => (
                      <Etiqueta key={novedad} tono="neutro">{novedad}</Etiqueta>
                    ))}
                  </span>
                )}
            </dd>
          </div>
          <div className="reglas__dato">
            <dt>Enfermería excluida</dt>
            <dd>{vigente.excluirEnfermeria ? 'Sí' : 'No'}</dd>
          </div>
          <div className="reglas__dato">
            <dt>Vigente desde</dt>
            <dd>{formatoFecha(vigente.vigenteDesde)}</dd>
          </div>
          <div className="reglas__dato">
            <dt>Programada por</dt>
            <dd>{vigente.creadaPor ?? '—'}</dd>
          </div>
          <div className="reglas__dato">
            <dt>Motivo</dt>
            <dd>{vigente.motivo}</dd>
          </div>
        </dl>
      </section>

      <div className="reglas__barra">
        <Boton onClick={() => setFormulario(true)}>
          Programar nueva versión
        </Boton>
      </div>

      <h3 className="reglas__subtitulo">Versiones</h3>
      <ul className="reglas__versiones" aria-label="Versiones del derecho a comer">
        {versiones.map((version) => (
          <li key={version.id} className="reglas__version">
            <div className="reglas__version-datos">
              <Etiqueta tono={TONOS_ESTADO[version.estado]}>{ETIQUETAS_ESTADO[version.estado]}</Etiqueta>
              <strong>Desde el {formatoFecha(version.vigenteDesde)}</strong>
              <span>Turno mínimo {version.duracionMinimaHoras} h</span>
              <span className="reglas__version-motivo">{version.motivo}</span>
            </div>
            {version.estado === 'programada' ? (
              <Boton variante="secundario" onClick={() => setConfirmacion(version)}>
                Eliminar
              </Boton>
            ) : null}
          </li>
        ))}
      </ul>

      {formulario ? (
        <DialogoNuevaVersion
          vigente={vigente}
          novedadesDisponibles={novedades ?? []}
          hoyMinimo={hoyMinimo}
          onProgramada={manejarProgramada}
          onCerrar={() => setFormulario(false)}
        />
      ) : null}

      {confirmacion ? (
        <DialogoConfirmacion
          titulo="Eliminar versión programada"
          mensaje={`¿Eliminar la versión que regiría desde el ${formatoFecha(confirmacion.vigenteDesde)}?`}
          procesando={eliminando}
          onConfirmar={manejarEliminar}
          onCancelar={() => setConfirmacion(null)}
        />
      ) : null}
    </div>
  );
}

/**
 * Nueva versión de derecho: turno mínimo, novedades, enfermería,
 * vigente desde y motivo, con el resumen de cambios antes de confirmar.
 */
export function DialogoNuevaVersion({
  vigente,
  novedadesDisponibles,
  hoyMinimo,
  onProgramada,
  onCerrar,
  valoresIniciales = {},
  errorInicial = '',
}) {
  const [duracion, setDuracion] = useState(valoresIniciales.duracionMinimaHoras ?? vigente.duracionMinimaHoras);
  const [elegidas, setElegidas] = useState(
    () => new Set(valoresIniciales.novedadesQueAnulan ?? vigente.novedadesQueAnulan),
  );
  const [excluir, setExcluir] = useState(valoresIniciales.excluirEnfermeria ?? vigente.excluirEnfermeria);
  const [vigenteDesde, setVigenteDesde] = useState(valoresIniciales.vigenteDesde ?? hoyMinimo);
  const [motivo, setMotivo] = useState(valoresIniciales.motivo ?? '');
  const [programando, setProgramando] = useState(false);
  const [error, setError] = useState(errorInicial);

  const forma = {
    duracionMinimaHoras: Number(duracion),
    novedadesQueAnulan: [...elegidas],
    excluirEnfermeria: excluir,
  };
  const diferencias = resumenDiferencias(vigente, forma);

  function alternarNovedad(novedad) {
    setElegidas((anterior) => {
      const siguiente = new Set(anterior);
      if (siguiente.has(novedad)) siguiente.delete(novedad);
      else siguiente.add(novedad);
      return siguiente;
    });
  }

  async function programar() {
    if (programando) return;
    setProgramando(true);
    setError('');
    try {
      await programarReglasDerecho({ ...forma, vigenteDesde, motivo });
      onProgramada();
    } catch (fallo) {
      setError(fallo.message);
    } finally {
      setProgramando(false);
    }
  }

  return (
    <DialogoReglas etiqueta="Programar nueva versión" onCerrar={onCerrar}>
      <h2 className="reglas__dialogo-titulo">Programar nueva versión</h2>

      <label className="reglas__campo" htmlFor="version-turno-minimo">
        <span className="reglas__campo-rotulo">Turno mínimo (horas)</span>
        <input
          id="version-turno-minimo"
          type="number"
          className="reglas__input reglas__input--corto"
          value={duracion}
          min={1}
          max={48}
          onChange={(evento) => setDuracion(evento.target.value)}
        />
      </label>

      <fieldset className="reglas__grupo">
        <legend className="reglas__campo-rotulo">Novedades que anulan el derecho</legend>
        {novedadesDisponibles.length === 0 ? (
          <p className="reglas__ayuda">No hay novedades para elegir.</p>
        ) : (
          <div className="reglas__casillas">
            {novedadesDisponibles.map((novedad) => (
              <label key={novedad} className="reglas__casilla">
                <input
                  type="checkbox"
                  className="reglas__casilla-caja"
                  checked={elegidas.has(novedad)}
                  onChange={() => alternarNovedad(novedad)}
                />
                <span>{novedad}</span>
              </label>
            ))}
          </div>
        )}
      </fieldset>

      <label className="reglas__interruptor" htmlFor="version-excluir-enfermeria">
        <input
          id="version-excluir-enfermeria"
          type="checkbox"
          className="reglas__interruptor-caja"
          checked={excluir}
          onChange={(evento) => setExcluir(evento.target.checked)}
        />
        <span className="reglas__interruptor-riel" aria-hidden="true" />
        <span className="reglas__interruptor-texto">Excluir a enfermería</span>
      </label>

      <label className="reglas__campo" htmlFor="version-vigente-desde">
        <span className="reglas__campo-rotulo">Vigente desde</span>
        <input
          id="version-vigente-desde"
          type="date"
          className="reglas__input"
          value={vigenteDesde}
          min={hoyMinimo}
          onChange={(evento) => setVigenteDesde(evento.target.value)}
        />
      </label>

      <label className="reglas__campo" htmlFor="version-motivo">
        <span className="reglas__campo-rotulo">Motivo (10 caracteres o más)</span>
        <textarea
          id="version-motivo"
          className="reglas__input reglas__area"
          value={motivo}
          onChange={(evento) => setMotivo(evento.target.value)}
          placeholder="Por qué cambia el derecho a comer"
          rows={3}
        />
      </label>

      <div className="reglas__diferencias">
        <h3 className="reglas__diferencias-titulo">Resumen de cambios</h3>
        <ul className="reglas__diferencias-lista">
          {diferencias.map((linea) => (
            <li key={linea}>{linea}</li>
          ))}
        </ul>
      </div>

      {error ? <p className="reglas__error-campo" role="alert">{error}</p> : null}

      <div className="reglas__dialogo-acciones">
        <Boton variante="secundario" onClick={onCerrar} disabled={programando}>
          Cancelar
        </Boton>
        <Boton onClick={programar} disabled={programando}>
          {programando ? 'Programando…' : 'Programar versión'}
        </Boton>
      </div>
    </DialogoReglas>
  );
}
