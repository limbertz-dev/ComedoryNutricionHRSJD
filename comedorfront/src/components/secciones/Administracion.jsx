import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Boton from '../ui/Boton.jsx';
import Etiqueta from '../ui/Etiqueta.jsx';
import { IconoAlerta, IconoBuscar, IconoCheck } from '../ui/Iconos.jsx';
import {
  buscarCandidatos,
  crearCuenta,
  desactivarCuenta,
  obtenerCuentas,
  reactivarCuenta,
  reiniciarClaveCuenta,
} from '../../api.js';
import {
  ETIQUETAS_ROL,
  estadoDeCuenta,
  filtrarCuentas,
  formatoUltimoIngreso,
  ordenarCuentas,
} from '../../cuentas.js';
import './Administracion.css';

/* Re-exportados: la vista de lectura y los tests los toman del módulo. */
export {
  ETIQUETAS_ROL,
  estadoDeCuenta,
  filtrarCuentas,
  formatoUltimoIngreso,
  ordenarCuentas,
};

const ROLES_NUEVA_CUENTA = [
  { valor: 'cocinera', etiqueta: 'Cocinera' },
  { valor: 'jefa', etiqueta: 'Jefa' },
];

/**
 * Cómo va a quedar el usuario: minúsculas, sin espacios en los extremos. Es
 * la misma normalización del backend; acá solo se anticipa para no sorprender.
 */
export function normalizarNombreUsuario(texto) {
  return typeof texto === 'string' ? texto.trim().toLowerCase() : '';
}

/** True si la fila es la cuenta con la que se ingresó (nunca se desactiva). */
export function esCuentaPropia(cuenta, usuarioActual) {
  if (!cuenta || typeof usuarioActual !== 'string' || !usuarioActual.trim()) return false;
  return cuenta.username.toLowerCase() === usuarioActual.trim().toLowerCase();
}

/**
 * Búsqueda de candidatos con debounce (~300 ms) que cancela lo anterior: cada
 * programar() anula el temporizador pendiente y aborta con AbortController la
 * petición en vuelo; por número de secuencia, una respuesta vieja nunca pisa
 * a una nueva.
 */
export function crearBuscadorCandidatos({ buscar, retardo = 300 } = {}) {
  let temporizador = null;
  let controlador = null;
  let secuencia = 0;

  function abortarVuelo() {
    if (controlador) {
      controlador.abort();
      controlador = null;
    }
  }

  function cancelar() {
    if (temporizador !== null) {
      clearTimeout(temporizador);
      temporizador = null;
    }
    secuencia += 1;
    abortarVuelo();
  }

  function programar(texto, { onResultado, onError, onEstado } = {}) {
    if (temporizador !== null) {
      clearTimeout(temporizador);
      temporizador = null;
    }
    abortarVuelo();
    const termino = typeof texto === 'string' ? texto.trim() : '';
    if (termino.length < 2) {
      secuencia += 1;
      onEstado?.(false);
      onResultado?.([]);
      return;
    }
    const actual = ++secuencia;
    onEstado?.(true);
    temporizador = setTimeout(() => {
      temporizador = null;
      if (actual !== secuencia) return;
      const propio = new AbortController();
      controlador = propio;
      Promise.resolve()
        .then(() => buscar(termino, { signal: propio.signal }))
        .then((resultados) => {
          if (actual !== secuencia || propio.signal.aborted) return;
          controlador = null;
          onResultado?.(resultados);
        })
        .catch((error) => {
          if (actual !== secuencia || propio.signal.aborted) return;
          controlador = null;
          onError?.(error);
        })
        .finally(() => {
          if (actual === secuencia) onEstado?.(false);
        });
    }, retardo);
  }

  return { programar, cancelar };
}

/**
 * Ejecuta desactivar / reactivar / reiniciar: aviso del resultado y la tabla
 * se relee del servidor. Devuelve lo que devolvió la operación.
 */
export async function ejecutarAccionCuenta({
  ejecutar,
  tituloExito,
  tituloError,
  recargar,
  setAviso,
  setProcesando,
}) {
  setProcesando?.(true);
  setAviso?.(null);
  try {
    const resultado = await ejecutar();
    setAviso?.({ tipo: 'exito', titulo: tituloExito, detalle: '' });
    await recargar?.();
    return resultado;
  } catch (error) {
    setAviso?.({ tipo: 'error', titulo: tituloError, detalle: error.message });
    return undefined;
  } finally {
    setProcesando?.(false);
  }
}

/**
 * Cierre de una creación exitosa: aviso, clave temporal al diálogo de un solo
 * uso y la tabla se relee del servidor.
 */
export async function finalizarCreacionCuenta({ resultado, setAviso, setClave, recargar }) {
  setAviso?.({ tipo: 'exito', titulo: `Cuenta ${resultado.cuenta.username} creada`, detalle: '' });
  setClave?.({ usuario: resultado.cuenta.username, valor: resultado.claveTemporal });
  await recargar?.();
}

/** Copia al portapapeles; false si el navegador no lo permite. */
export function copiarTexto(texto) {
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      return navigator.clipboard.writeText(texto).then(() => true, () => false);
    }
  } catch {
    return Promise.resolve(false);
  }
  return Promise.resolve(false);
}

/**
 * Administración de cuentas (solo sistemas).
 *
 * Tabla de cuentas con búsqueda local y acciones con confirmación
 * (reiniciar clave, desactivar o reactivar), diálogo de nueva cuenta con
 * pestañas «Desde el padrón» y «Sin vínculo», y diálogo de clave temporal
 * de un solo uso: la clave vive solo en memoria mientras está abierto.
 */
export default function Administracion({
  usuarioActual = null,
  cargandoInicial = true,
  errorInicial = null,
  cuentasIniciales = null,
  busquedaInicial = '',
  dialogoNuevoInicial = false,
  avisoInicial = null,
  claveInicial = null,
  confirmacionInicial = null,
}) {
  const [cargando, setCargando] = useState(cargandoInicial);
  const [actualizando, setActualizando] = useState(false);
  const [error, setError] = useState(errorInicial);
  const [cuentas, setCuentas] = useState(cuentasIniciales);
  const [busqueda, setBusqueda] = useState(busquedaInicial);
  const [aviso, setAviso] = useState(avisoInicial);
  const [dialogoNuevo, setDialogoNuevo] = useState(dialogoNuevoInicial);
  const [confirmacion, setConfirmacion] = useState(confirmacionInicial);
  /* La clave temporal: solo en este estado, solo mientras el diálogo abierto. */
  const [clave, setClave] = useState(claveInicial);
  const [procesandoId, setProcesandoId] = useState(null);

  const cargarCuentas = useCallback(async ({ signal, esRefresco = false } = {}) => {
    if (!esRefresco) {
      setCargando(true);
      setError(null);
    } else {
      setActualizando(true);
    }
    try {
      const lista = await obtenerCuentas({ signal });
      if (signal?.aborted) return;
      setCuentas(lista);
    } catch (fallo) {
      if (!signal?.aborted) {
        if (!esRefresco) {
          setError(fallo.message);
        } else {
          setAviso({ tipo: 'error', titulo: 'No se pudo actualizar', detalle: fallo.message });
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
  }, []);

  useEffect(() => {
    const controlador = new AbortController();
    cargarCuentas({ signal: controlador.signal });
    return () => controlador.abort();
  }, [cargarCuentas]);

  const cuentasVisibles = useMemo(
    () => filtrarCuentas(ordenarCuentas(cuentas ?? []), busqueda),
    [cuentas, busqueda],
  );

  async function manejarConfirmado() {
    if (!confirmacion) return;
    const { tipo, cuenta } = confirmacion;
    setConfirmacion(null);
    if (tipo === 'desactivar') {
      await ejecutarAccionCuenta({
        ejecutar: () => desactivarCuenta(cuenta.id),
        tituloExito: `Cuenta ${cuenta.username} desactivada`,
        tituloError: 'No se pudo desactivar',
        recargar: () => cargarCuentas({ esRefresco: true }),
        setAviso,
        setProcesando: (valor) => setProcesandoId(valor ? cuenta.id : null),
      });
    } else if (tipo === 'reactivar') {
      await ejecutarAccionCuenta({
        ejecutar: () => reactivarCuenta(cuenta.id),
        tituloExito: `Cuenta ${cuenta.username} reactivada`,
        tituloError: 'No se pudo reactivar',
        recargar: () => cargarCuentas({ esRefresco: true }),
        setAviso,
        setProcesando: (valor) => setProcesandoId(valor ? cuenta.id : null),
      });
    } else if (tipo === 'reiniciar') {
      const resultado = await ejecutarAccionCuenta({
        ejecutar: () => reiniciarClaveCuenta(cuenta.id),
        tituloExito: `Clave de ${cuenta.username} reiniciada`,
        tituloError: 'No se pudo reiniciar la clave',
        recargar: () => cargarCuentas({ esRefresco: true }),
        setAviso,
        setProcesando: (valor) => setProcesandoId(valor ? cuenta.id : null),
      });
      if (resultado) {
        setClave({ usuario: resultado.cuenta.username, valor: resultado.claveTemporal });
      }
    }
  }

  async function manejarCreada(resultado) {
    setDialogoNuevo(false);
    await finalizarCreacionCuenta({
      resultado,
      setAviso,
      setClave,
      recargar: () => cargarCuentas({ esRefresco: true }),
    });
  }

  if (cargando) {
    return (
      <div className="administracion">
        <p className="administracion__estado" role="status">Cargando cuentas…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="administracion">
        <div className="administracion__error" role="alert">
          <p>{error}</p>
          <Boton onClick={() => cargarCuentas()}>Reintentar cuentas</Boton>
        </div>
      </div>
    );
  }

  const sinCuentas = (cuentas ?? []).length === 0;

  return (
    <div className="administracion">
      {aviso ? <AvisoAccion aviso={aviso} onCerrar={() => setAviso(null)} /> : null}

      <div className="administracion__barra">
        <div className="administracion__buscador">
          <span className="administracion__buscador-icono" aria-hidden="true">
            <IconoBuscar tamano={15} />
          </span>
          <input
            type="text"
            className="administracion__buscador-input"
            value={busqueda}
            onChange={(evento) => setBusqueda(evento.target.value)}
            placeholder="Buscar por usuario o nombre…"
            aria-label="Buscar por usuario o nombre"
          />
          {busqueda ? (
            <button
              type="button"
              className="administracion__buscador-limpiar"
              onClick={() => setBusqueda('')}
              aria-label="Limpiar búsqueda"
            >
              ×
            </button>
          ) : null}
        </div>

        <Boton
          variante="secundario"
          onClick={() => cargarCuentas({ esRefresco: true })}
          disabled={actualizando}
        >
          {actualizando ? 'Actualizando…' : 'Actualizar'}
        </Boton>
        <Boton onClick={() => setDialogoNuevo(true)}>
          Nueva cuenta
        </Boton>
      </div>

      {sinCuentas ? (
        <p className="administracion__vacio" role="status">
          No hay cuentas registradas.
        </p>
      ) : cuentasVisibles.length === 0 ? (
        <p className="administracion__vacio" role="status">
          Ninguna cuenta coincide con la búsqueda.
        </p>
      ) : (
        <div className="administracion__tabla-caja">
          <table className="administracion__tabla" aria-label="Cuentas del comedor">
            <thead>
              <tr>
                <th scope="col">Usuario</th>
                <th scope="col">Nombre</th>
                <th scope="col">Rol</th>
                <th scope="col">Vínculo</th>
                <th scope="col">Estado</th>
                <th scope="col">Último ingreso</th>
                <th scope="col">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {cuentasVisibles.map((cuenta) => (
                <FilaCuenta
                  key={cuenta.id}
                  cuenta={cuenta}
                  esPropia={esCuentaPropia(cuenta, usuarioActual)}
                  procesando={procesandoId === cuenta.id}
                  onReiniciar={() => setConfirmacion({ tipo: 'reiniciar', cuenta })}
                  onDesactivar={() => setConfirmacion({ tipo: 'desactivar', cuenta })}
                  onReactivar={() => setConfirmacion({ tipo: 'reactivar', cuenta })}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {dialogoNuevo ? (
        <DialogoNuevaCuenta
          onCrear={manejarCreada}
          onCerrar={() => setDialogoNuevo(false)}
        />
      ) : null}

      {confirmacion ? (
        <DialogoConfirmacion
          confirmacion={confirmacion}
          onConfirmar={manejarConfirmado}
          onCancelar={() => setConfirmacion(null)}
        />
      ) : null}

      {clave ? (
        <DialogoClave
          usuario={clave.usuario}
          valor={clave.valor}
          onCerrar={() => setClave(null)}
        />
      ) : null}
    </div>
  );
}

/** Fila de la tabla: datos legibles y acciones con confirmación. */
function FilaCuenta({ cuenta, esPropia, procesando, onReiniciar, onDesactivar, onReactivar }) {
  const estado = estadoDeCuenta(cuenta);
  return (
    <tr className={cuenta.activo ? undefined : 'administracion__fila--inactiva'}>
      <td className="administracion__usuario">{cuenta.username}</td>
      <td>{cuenta.nombre || '—'}</td>
      <td>{ETIQUETAS_ROL[cuenta.rol] ?? cuenta.rol}</td>
      <td>{cuenta.vinculada ? 'Padrón' : 'Sin vínculo'}</td>
      <td>
        <Etiqueta tono={estado.tono}>{estado.texto}</Etiqueta>
      </td>
      <td>{formatoUltimoIngreso(cuenta.ultimoIngreso)}</td>
      <td>
        <div className="administracion__acciones">
          <Boton variante="secundario" onClick={onReiniciar} disabled={procesando}>
            Reiniciar clave
          </Boton>
          {cuenta.activo ? (
            esPropia ? (
              <span className="administracion__propia">Su cuenta</span>
            ) : (
              <Boton variante="secundario" onClick={onDesactivar} disabled={procesando}>
                Desactivar
              </Boton>
            )
          ) : (
            <Boton variante="secundario" onClick={onReactivar} disabled={procesando}>
              Reactivar
            </Boton>
          )}
        </div>
      </td>
    </tr>
  );
}

/** Aviso de éxito o error tras una acción, con cierre manual. */
function AvisoAccion({ aviso, onCerrar }) {
  return (
    <div
      className={`administracion__aviso administracion__aviso--${aviso.tipo}`}
      role={aviso.tipo === 'exito' ? 'status' : 'alert'}
    >
      {aviso.tipo === 'exito' ? (
        <span className="administracion__aviso-icono" aria-hidden="true">
          <IconoCheck tamano={18} />
        </span>
      ) : (
        <span className="administracion__aviso-icono" aria-hidden="true">
          <IconoAlerta tamano={18} />
        </span>
      )}
      <div className="administracion__aviso-contenido">
        <strong className="administracion__aviso-titulo">{aviso.titulo}</strong>
        {aviso.detalle ? (
          <p className="administracion__aviso-detalle">{aviso.detalle}</p>
        ) : null}
      </div>
      <button
        type="button"
        className="administracion__aviso-cerrar"
        onClick={onCerrar}
        aria-label="Cerrar aviso"
      >
        ×
      </button>
    </div>
  );
}

/**
 * Fondo + caja de diálogo. Se cierra con Escape o con un clic en el fondo.
 * La clave temporal, al cerrarse su diálogo, se borra del estado del padre.
 */
function Dialogo({ etiqueta, onCerrar, children }) {
  useEffect(() => {
    function alTeclado(evento) {
      if (evento.key === 'Escape') onCerrar();
    }
    document.addEventListener('keydown', alTeclado);
    return () => document.removeEventListener('keydown', alTeclado);
  }, [onCerrar]);

  return (
    <div
      className="administracion__fondo"
      onMouseDown={(evento) => {
        if (evento.target === evento.currentTarget) onCerrar();
      }}
    >
      <div className="administracion__dialogo" role="dialog" aria-label={etiqueta}>
        {children}
      </div>
    </div>
  );
}

/**
 * Nueva cuenta, con dos pestañas: «Desde el padrón» (búsqueda con 2+ caracteres
 * y debounce, candidato elegido con usuario en solo lectura) y «Sin vínculo»
 * (usuario, nombre y rol, para quien aún no está en el padrón).
 */
export function DialogoNuevaCuenta({
  onCrear,
  onCerrar,
  pestanaInicial = 'padron',
  busquedaPadronInicial = '',
  candidatosIniciales = [],
  candidatoInicial = null,
  usuarioLibreInicial = '',
  nombreLibreInicial = '',
}) {
  const [pestana, setPestana] = useState(pestanaInicial);
  const [busquedaPadron, setBusquedaPadron] = useState(busquedaPadronInicial);
  const [candidatos, setCandidatos] = useState(candidatosIniciales);
  const [buscando, setBuscando] = useState(false);
  const [errorCandidatos, setErrorCandidatos] = useState('');
  const [candidatoElegido, setCandidatoElegido] = useState(candidatoInicial);
  const [rolPadron, setRolPadron] = useState('cocinera');
  const [usuarioLibre, setUsuarioLibre] = useState(usuarioLibreInicial);
  const [nombreLibre, setNombreLibre] = useState(nombreLibreInicial);
  const [rolLibre, setRolLibre] = useState('cocinera');
  const [creando, setCreando] = useState(false);
  const [errorCrear, setErrorCrear] = useState('');

  const buscador = useRef(null);
  if (!buscador.current) {
    buscador.current = crearBuscadorCandidatos({
      buscar: (termino, opciones) => buscarCandidatos(termino, opciones),
    });
  }

  useEffect(() => {
    if (pestana !== 'padron') return undefined;
    buscador.current.programar(busquedaPadron, {
      onResultado: (lista) => {
        setCandidatos(lista);
        setErrorCandidatos('');
      },
      onError: (fallo) => setErrorCandidatos(fallo.message),
      onEstado: setBuscando,
    });
    return () => buscador.current.cancelar();
  }, [busquedaPadron, pestana]);

  function cambiarPestana(nueva) {
    buscador.current.cancelar();
    setPestana(nueva);
    setErrorCrear('');
  }

  async function crearDesdePadron() {
    if (!candidatoElegido || creando) return;
    setCreando(true);
    setErrorCrear('');
    try {
      const resultado = await crearCuenta({
        rol: rolPadron,
        usuarioTurnosId: candidatoElegido.usuarioTurnosId,
      });
      onCrear(resultado);
    } catch (fallo) {
      setErrorCrear(fallo.message);
    } finally {
      setCreando(false);
    }
  }

  async function crearSinVinculo() {
    if (creando) return;
    setCreando(true);
    setErrorCrear('');
    try {
      const resultado = await crearCuenta({
        rol: rolLibre,
        username: usuarioLibre,
        nombre: nombreLibre,
      });
      onCrear(resultado);
    } catch (fallo) {
      setErrorCrear(fallo.message);
    } finally {
      setCreando(false);
    }
  }

  const vistaPreviaUsuario = normalizarNombreUsuario(usuarioLibre);

  return (
    <Dialogo etiqueta="Nueva cuenta" onCerrar={onCerrar}>
      <h2 className="administracion__dialogo-titulo">Nueva cuenta</h2>

      <div className="administracion__pestanas" role="tablist" aria-label="Origen de la cuenta">
        <button
          type="button"
          role="tab"
          aria-selected={pestana === 'padron'}
          className={`administracion__pestana${pestana === 'padron' ? ' administracion__pestana--activa' : ''}`}
          onClick={() => cambiarPestana('padron')}
        >
          Desde el padrón
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={pestana === 'libre'}
          className={`administracion__pestana${pestana === 'libre' ? ' administracion__pestana--activa' : ''}`}
          onClick={() => cambiarPestana('libre')}
        >
          Sin vínculo
        </button>
      </div>

      {pestana === 'padron' ? (
        <div className="administracion__panel-pestana">
          <label className="administracion__campo" htmlFor="nueva-busqueda-padron">
            <span className="administracion__campo-rotulo">Buscar en el padrón</span>
            <input
              id="nueva-busqueda-padron"
              type="text"
              className="administracion__input"
              value={busquedaPadron}
              onChange={(evento) => setBusquedaPadron(evento.target.value)}
              placeholder="Nombre o usuario, con 2 letras o más…"
              autoComplete="off"
            />
          </label>

          {buscando ? <p className="administracion__ayuda" role="status">Buscando…</p> : null}
          {errorCandidatos ? <p className="administracion__error-campo" role="alert">{errorCandidatos}</p> : null}

          {!buscando && !errorCandidatos && busquedaPadron.trim().length >= 2 && candidatos.length === 0 ? (
            <p className="administracion__ayuda" role="status">Nadie del padrón coincide con esa búsqueda.</p>
          ) : null}

          {candidatos.length > 0 ? (
            <ul className="administracion__candidatos" aria-label="Candidatos del padrón">
              {candidatos.map((candidato) => (
                <li
                  key={candidato.usuarioTurnosId}
                  className={`administracion__candidato${candidato.tieneCuenta ? ' administracion__candidato--usado' : ''}${
                    candidatoElegido?.usuarioTurnosId === candidato.usuarioTurnosId
                      ? ' administracion__candidato--elegido'
                      : ''
                  }`}
                >
                  <div className="administracion__candidato-datos">
                    <strong>{candidato.nombre}</strong>
                    <span>{candidato.login} · {candidato.categoria ?? 'Sin categoría'}</span>
                  </div>
                  {candidato.tieneCuenta ? (
                    <>
                      <Etiqueta tono="neutro">Ya tiene cuenta</Etiqueta>
                      <Boton variante="secundario" disabled title="Ya tiene cuenta">
                        Elegir
                      </Boton>
                    </>
                  ) : (
                    <Boton
                      variante="secundario"
                      onClick={() => setCandidatoElegido(candidato)}
                      disabled={candidatoElegido?.usuarioTurnosId === candidato.usuarioTurnosId}
                    >
                      {candidatoElegido?.usuarioTurnosId === candidato.usuarioTurnosId ? 'Elegido' : 'Elegir'}
                    </Boton>
                  )}
                </li>
              ))}
            </ul>
          ) : null}

          {candidatoElegido ? (
            <div className="administracion__elegido">
              <label className="administracion__campo" htmlFor="nueva-usuario-padron">
                <span className="administracion__campo-rotulo">Usuario de la cuenta</span>
                <input
                  id="nueva-usuario-padron"
                  type="text"
                  className="administracion__input"
                  value={candidatoElegido.login}
                  readOnly
                  aria-readonly="true"
                />
              </label>
              <Boton variante="fantasma" onClick={() => setCandidatoElegido(null)}>
                Cambiar
              </Boton>
            </div>
          ) : null}

          <label className="administracion__campo" htmlFor="nueva-rol-padron">
            <span className="administracion__campo-rotulo">Rol</span>
            <select
              id="nueva-rol-padron"
              className="administracion__select"
              value={rolPadron}
              onChange={(evento) => setRolPadron(evento.target.value)}
            >
              {ROLES_NUEVA_CUENTA.map(({ valor, etiqueta }) => (
                <option key={valor} value={valor}>{etiqueta}</option>
              ))}
            </select>
          </label>
        </div>
      ) : (
        <div className="administracion__panel-pestana">
          <p className="administracion__ayuda">
            Para personas que aún no están en el padrón del comedor. La cuenta queda sin vínculo.
          </p>

          <label className="administracion__campo" htmlFor="nueva-usuario-libre">
            <span className="administracion__campo-rotulo">Usuario</span>
            <input
              id="nueva-usuario-libre"
              type="text"
              className="administracion__input"
              value={usuarioLibre}
              onChange={(evento) => setUsuarioLibre(evento.target.value)}
              placeholder="Por ejemplo: maria.cocina"
              autoComplete="off"
            />
          </label>
          {usuarioLibre.trim() ? (
            <p className="administracion__ayuda">Va a quedar: {vistaPreviaUsuario}</p>
          ) : null}

          <label className="administracion__campo" htmlFor="nueva-nombre-libre">
            <span className="administracion__campo-rotulo">Nombre</span>
            <input
              id="nueva-nombre-libre"
              type="text"
              className="administracion__input"
              value={nombreLibre}
              onChange={(evento) => setNombreLibre(evento.target.value)}
              placeholder="Nombre de la persona"
              autoComplete="off"
            />
          </label>

          <label className="administracion__campo" htmlFor="nueva-rol-libre">
            <span className="administracion__campo-rotulo">Rol</span>
            <select
              id="nueva-rol-libre"
              className="administracion__select"
              value={rolLibre}
              onChange={(evento) => setRolLibre(evento.target.value)}
            >
              {ROLES_NUEVA_CUENTA.map(({ valor, etiqueta }) => (
                <option key={valor} value={valor}>{etiqueta}</option>
              ))}
            </select>
          </label>
        </div>
      )}

      {errorCrear ? <p className="administracion__error-campo" role="alert">{errorCrear}</p> : null}

      <div className="administracion__dialogo-acciones">
        <Boton variante="secundario" onClick={onCerrar} disabled={creando}>
          Cancelar
        </Boton>
        {pestana === 'padron' ? (
          <Boton onClick={crearDesdePadron} disabled={!candidatoElegido || creando}>
            {creando ? 'Creando…' : 'Crear'}
          </Boton>
        ) : (
          <Boton onClick={crearSinVinculo} disabled={creando}>
            {creando ? 'Creando…' : 'Crear'}
          </Boton>
        )}
      </div>
    </Dialogo>
  );
}

const TEXTOS_CONFIRMACION = {
  desactivar: {
    titulo: 'Desactivar cuenta',
    mensaje: (cuenta) => `¿Desactivar la cuenta de ${cuenta.username}? No podrá ingresar hasta que se reactive.`,
    confirmar: 'Desactivar',
  },
  reactivar: {
    titulo: 'Reactivar cuenta',
    mensaje: (cuenta) => `¿Reactivar la cuenta de ${cuenta.username}? Volverá a ingresar con su clave.`,
    confirmar: 'Reactivar',
  },
  reiniciar: {
    titulo: 'Reiniciar clave',
    mensaje: (cuenta) => `¿Reiniciar la clave de ${cuenta.username}? Se genera una clave temporal nueva, que se muestra una sola vez.`,
    confirmar: 'Reiniciar',
  },
};

/** Confirmación de desactivar, reactivar o reiniciar clave. */
export function DialogoConfirmacion({ confirmacion, onConfirmar, onCancelar }) {
  const textos = TEXTOS_CONFIRMACION[confirmacion.tipo];
  return (
    <Dialogo etiqueta={textos.titulo} onCerrar={onCancelar}>
      <h2 className="administracion__dialogo-titulo">{textos.titulo}</h2>
      <p className="administracion__dialogo-mensaje">{textos.mensaje(confirmacion.cuenta)}</p>
      <div className="administracion__dialogo-acciones">
        <Boton variante="secundario" onClick={onCancelar}>
          Cancelar
        </Boton>
        <Boton onClick={onConfirmar}>
          {textos.confirmar}
        </Boton>
      </div>
    </Dialogo>
  );
}

/**
 * Clave temporal de un solo uso: se muestra una sola vez, con Copiar y el
 * aviso de entrega en mano. Al cerrarse, el padre la borra de su estado.
 */
export function DialogoClave({ usuario, valor, onCerrar }) {
  const [copiado, setCopiado] = useState(false);

  async function manejarCopiar() {
    const ok = await copiarTexto(valor);
    setCopiado(ok);
  }

  return (
    <Dialogo etiqueta="Clave temporal" onCerrar={onCerrar}>
      <h2 className="administracion__dialogo-titulo">Clave temporal de {usuario}</h2>
      <p className="administracion__dialogo-mensaje">
        Anótela o cópiela ahora: no se volverá a mostrar.
      </p>
      <div className="administracion__clave-caja">
        <code className="administracion__clave">{valor}</code>
        <Boton variante="secundario" onClick={manejarCopiar}>
          {copiado ? '¡Copiada!' : 'Copiar'}
        </Boton>
      </div>
      <p className="administracion__clave-aviso" role="note">
        No se volverá a mostrar; entréguela en mano. Se cambia en el primer ingreso.
      </p>
      <div className="administracion__dialogo-acciones">
        <Boton onClick={onCerrar}>
          Cerrar
        </Boton>
      </div>
    </Dialogo>
  );
}
