import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Boton from '../ui/Boton.jsx';
import Etiqueta from '../ui/Etiqueta.jsx';
import { IconoAlerta, IconoBuscar, IconoCandado, IconoCheck, IconoEditar, IconoPapelera, IconoRecargar, IconoUsuario } from '../ui/Iconos.jsx';
import {
  cambiarClaveCuenta,
  crearCuenta,
  desactivarCuenta,
  editarCuenta,
  eliminarCuenta,
  obtenerCuentas,
  reactivarCuenta,
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

/** Largo mínimo de la contraseña; el servidor aplica la misma regla. */
export const LARGO_MINIMO_CLAVE = 8;

/**
 * Por qué no se puede usar todavía la contraseña escrita, o '' si sirve.
 * Anticipa las reglas del servidor para avisar antes de enviar.
 */
export function motivoClaveInvalida(clave, confirmacion, usuario = '') {
  if (!clave) return 'Escriba la contraseña.';
  if (clave.length < LARGO_MINIMO_CLAVE) return `La contraseña debe tener al menos ${LARGO_MINIMO_CLAVE} caracteres.`;
  if (usuario && clave.trim().toLowerCase() === normalizarNombreUsuario(usuario)) {
    return 'La contraseña no puede ser el nombre de usuario.';
  }
  if (clave !== confirmacion) return 'Las dos contraseñas no coinciden.';
  return '';
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
 * Ejecuta desactivar / reactivar: aviso del resultado y la tabla se relee
 * del servidor. Devuelve lo que devolvió la operación.
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

/** Cierre de una creación exitosa: aviso y la tabla se relee del servidor. */
export async function finalizarCreacionCuenta({ resultado, setAviso, recargar }) {
  setAviso?.({
    tipo: 'exito',
    titulo: `Cuenta ${resultado.cuenta.username} creada`,
    detalle: 'Ya puede ingresar con la contraseña que eligió.',
  });
  await recargar?.();
}

/**
 * Administración de cuentas (solo sistemas).
 *
 * Tabla de cuentas con búsqueda local y acciones (cambiar clave, desactivar
 * o reactivar) y diálogo de nueva cuenta con ingreso directo de sus datos.
 * Root escribe la contraseña definitiva: la cuenta entra con
 * ella sin cambio obligatorio. La contraseña solo vive en el estado del
 * diálogo mientras está abierto.
 */
export default function Administracion({
  usuarioActual = null,
  cargandoInicial = true,
  errorInicial = null,
  cuentasIniciales = null,
  busquedaInicial = '',
  dialogoNuevoInicial = false,
  avisoInicial = null,
  cambioClaveInicial = null,
  edicionInicial = null,
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
  /* La cuenta cuya contraseña se está cambiando, o null. */
  const [cambioClave, setCambioClave] = useState(cambioClaveInicial);
  const [edicion, setEdicion] = useState(edicionInicial);
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
    if (tipo === 'eliminar') {
      await ejecutarAccionCuenta({
        ejecutar: async () => {
          await eliminarCuenta(cuenta.id);
          // Ocultar solo tras la confirmación del servidor, incluso si falla
          // el refresco siguiente. No se borra la identidad ni su historial.
          setCuentas(previas => previas?.filter(fila => fila.id !== cuenta.id) ?? null);
        },
        tituloExito: `Cuenta ${cuenta.username} eliminada de la lista`,
        tituloError: 'No se pudo eliminar la cuenta',
        recargar: () => cargarCuentas({ esRefresco: true }),
        setAviso,
        setProcesando: (valor) => setProcesandoId(valor ? cuenta.id : null),
      });
    } else if (tipo === 'desactivar' || tipo === 'reactivar') {
      const desactivar = tipo === 'desactivar';
      await ejecutarAccionCuenta({
        ejecutar: () => desactivar ? desactivarCuenta(cuenta.id) : reactivarCuenta(cuenta.id),
        tituloExito: `Cuenta ${cuenta.username} ${desactivar ? 'desactivada' : 'reactivada'}`,
        tituloError: `No se pudo ${tipo}`,
        recargar: () => cargarCuentas({ esRefresco: true }),
        setAviso,
        setProcesando: (valor) => setProcesandoId(valor ? cuenta.id : null),
      });
    }
  }

  async function manejarEditada(cuenta) {
    setEdicion(null);
    setCuentas(previas => previas?.map(fila => fila.id === cuenta.id ? cuenta : fila) ?? null);
    setAviso({ tipo: 'exito', titulo: `Cuenta ${cuenta.username} actualizada` });
    await cargarCuentas({ esRefresco: true });
  }

  async function manejarClaveCambiada(cuenta) {
    setCambioClave(null);
    setAviso({
      tipo: 'exito',
      titulo: `Contraseña de ${cuenta.username} cambiada`,
      detalle: 'Sus sesiones abiertas se cerraron; ya ingresa con la nueva.',
    });
    await cargarCuentas({ esRefresco: true });
  }

  async function manejarCreada(resultado) {
    setDialogoNuevo(false);
    await finalizarCreacionCuenta({
      resultado,
      setAviso,
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

      <div className="administracion__barra" role="search">
        <div className="administracion__buscador">
          <span className="administracion__buscador-icono" aria-hidden="true">
            <IconoBuscar tamano={15} />
          </span>
          <input
            type="text"
            className="administracion__buscador-input"
            value={busqueda}
            onChange={(evento) => setBusqueda(evento.target.value)}
            placeholder="Buscar cuenta…"
            aria-label="Buscar cuenta"
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

        <p className="administracion__contador" role="status">
          {sinCuentas
            ? 'Sin cuentas'
            : `${cuentasVisibles.length} de ${cuentas.length} ${cuentas.length === 1 ? 'cuenta' : 'cuentas'}`}
        </p>

        <Boton
          variante="secundario"
          icono={<IconoRecargar tamano={17} />}
          onClick={() => cargarCuentas({ esRefresco: true })}
          disabled={actualizando || procesandoId !== null}
        >
          {actualizando ? 'Actualizando…' : 'Actualizar'}
        </Boton>
        <Boton onClick={() => setDialogoNuevo(true)} disabled={actualizando || procesandoId !== null}>
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
                  procesando={procesandoId !== null || actualizando}
                  onCambiarClave={() => setCambioClave(cuenta)}
                  onEditar={() => setEdicion(cuenta)}
                  onDesactivar={() => setConfirmacion({ tipo: 'desactivar', cuenta })}
                  onReactivar={() => setConfirmacion({ tipo: 'reactivar', cuenta })}
                  onEliminar={() => setConfirmacion({ tipo: 'eliminar', cuenta })}
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

      {edicion ? (
        <DialogoEditarCuenta cuenta={edicion} onGuardada={manejarEditada} onCerrar={() => setEdicion(null)} />
      ) : null}

      {cambioClave ? (
        <DialogoCambiarClave
          cuenta={cambioClave}
          onCambiada={manejarClaveCambiada}
          onCerrar={() => setCambioClave(null)}
        />
      ) : null}
    </div>
  );
}

/** Fila de la tabla: datos legibles y acciones con confirmación. */
function FilaCuenta({ cuenta, esPropia, procesando, onEditar, onCambiarClave, onDesactivar, onReactivar, onEliminar }) {
  const estado = estadoDeCuenta(cuenta);
  return (
    <tr className={cuenta.activo ? undefined : 'administracion__fila--inactiva'}>
      <td className="administracion__usuario">{cuenta.username}</td>
      <td>{cuenta.nombre || '—'}</td>
      <td>{ETIQUETAS_ROL[cuenta.rol] ?? cuenta.rol}</td>
      <td>
        <Etiqueta tono={estado.tono}>{estado.texto}</Etiqueta>
      </td>
      <td>{formatoUltimoIngreso(cuenta.ultimoIngreso)}</td>
      <td>
        <div className="administracion__acciones">
          <Boton variante="secundario" icono={<IconoEditar tamano={15} />} onClick={onEditar} disabled={procesando}>
            Editar
          </Boton>
          <Boton variante="secundario" onClick={onCambiarClave} disabled={procesando}>
            Cambiar clave
          </Boton>
          {esPropia ? (
            <span className="administracion__propia">Su cuenta</span>
          ) : (
            <>
              <Boton variante="secundario" onClick={cuenta.activo ? onDesactivar : onReactivar} disabled={procesando}>
                {cuenta.activo ? 'Desactivar' : 'Reactivar'}
              </Boton>
              <Boton variante="secundario" icono={<IconoPapelera tamano={15} />} onClick={onEliminar} disabled={procesando}>
                Eliminar
              </Boton>
            </>
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

/** Fondo + caja de diálogo. Se cierra con Escape o con un clic en el fondo. */
function Dialogo({ etiqueta, onCerrar, children }) {
  const caja = useRef(null);

  /* Al abrir, el foco pasa al diálogo; al cerrar, vuelve a donde estaba. */
  useEffect(() => {
    const previo = document.activeElement;
    caja.current?.focus();
    return () => {
      if (previo instanceof HTMLElement && previo.isConnected) previo.focus();
    };
  }, []);

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
      <div
        ref={caja}
        className="administracion__dialogo"
        role="dialog"
        aria-modal="true"
        aria-label={etiqueta}
        tabIndex={-1}
      >
        {children}
      </div>
    </div>
  );
}

/** Nueva cuenta con ingreso directo de sus datos. */
export function DialogoNuevaCuenta({
  onCrear,
  onCerrar,
  usuarioLibreInicial = '',
  nombreLibreInicial = '',
  claveInicial = '',
}) {
  const [usuarioLibre, setUsuarioLibre] = useState(usuarioLibreInicial);
  const [nombreLibre, setNombreLibre] = useState(nombreLibreInicial);
  const [rolLibre, setRolLibre] = useState('cocinera');
  const [clave, setClave] = useState(claveInicial);
  const [confirmacionClave, setConfirmacionClave] = useState(claveInicial);
  const [creando, setCreando] = useState(false);
  const [errorCrear, setErrorCrear] = useState('');

  async function crear(evento) {
    evento.preventDefault();
    if (creando) return;
    const motivo = motivoClaveInvalida(clave, confirmacionClave, usuarioLibre);
    if (motivo) {
      setErrorCrear(motivo);
      return;
    }
    setCreando(true);
    setErrorCrear('');
    try {
      const resultado = await crearCuenta({
        rol: rolLibre,
        username: usuarioLibre,
        nombre: nombreLibre,
        password: clave,
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
      <div className="administracion__dialogo-cabecera">
        <span className="administracion__dialogo-icono administracion__dialogo-icono--acento" aria-hidden="true">
          <IconoUsuario tamano={22} />
        </span>
        <h2 className="administracion__dialogo-titulo">Nueva cuenta</h2>
      </div>

      <form onSubmit={crear}>
        <div className="administracion__panel-pestana">
          <label className="administracion__campo" htmlFor="nueva-usuario-libre">
            <span className="administracion__campo-rotulo">Usuario</span>
            <input
              id="nueva-usuario-libre"
              type="text"
              className="administracion__input"
              value={usuarioLibre}
              onChange={(evento) => setUsuarioLibre(evento.target.value)}
              placeholder="Por ejemplo: maria.cocina"
              required
              maxLength={50}
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
              required
              maxLength={100}
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
        <CamposClave
          idBase="nueva"
          clave={clave}
          onClave={setClave}
          confirmacion={confirmacionClave}
          onConfirmacion={setConfirmacionClave}
        />

        {errorCrear ? <p className="administracion__error-campo" role="alert">{errorCrear}</p> : null}

        <div className="administracion__dialogo-acciones">
          <Boton variante="secundario" onClick={onCerrar} disabled={creando}>
            Cancelar
          </Boton>
          <Boton type="submit" disabled={creando}>
            {creando ? 'Creando\u2026' : 'Crear'}
          </Boton>
        </div>
      </form>
    </Dialogo>
  );
}

/** Edición de datos de la cuenta con los valores actuales y envío único. */
export function DialogoEditarCuenta({ cuenta, onGuardada, onCerrar, editar = editarCuenta }) {
  const [nombre, setNombre] = useState(cuenta.nombre ?? '');
  const [rol, setRol] = useState(cuenta.rol);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState('');
  const cambioNombre = !cuenta.vinculada && nombre.trim() !== (cuenta.nombre ?? '');
  const cambioRol = rol !== cuenta.rol;
  const puedeGuardar = (cuenta.vinculada || nombre.trim()) && (cambioNombre || cambioRol);

  async function guardar(evento) {
    evento.preventDefault();
    if (guardando || !puedeGuardar) return;
    setGuardando(true);
    setError('');
    try {
      const cambios = { ...(cambioNombre ? { nombre: nombre.trim() } : {}), ...(cambioRol ? { rol } : {}) };
      const actualizada = await editar(cuenta.id, cambios);
      onGuardada(actualizada);
    } catch (fallo) {
      setError(fallo.message);
    } finally {
      setGuardando(false);
    }
  }

  return (
    <Dialogo etiqueta="Editar cuenta" onCerrar={guardando ? () => {} : onCerrar}>
      <div className="administracion__dialogo-cabecera">
        <span className="administracion__dialogo-icono administracion__dialogo-icono--acento" aria-hidden="true">
          <IconoEditar tamano={22} />
        </span>
        <h2 className="administracion__dialogo-titulo">Editar cuenta</h2>
      </div>
      <form onSubmit={guardar}>
        <div className="administracion__panel-pestana">
          <label className="administracion__campo" htmlFor="editar-usuario">
            <span className="administracion__campo-rotulo">Usuario</span>
            <input id="editar-usuario" className="administracion__input" value={cuenta.username} readOnly />
          </label>
          <label className="administracion__campo" htmlFor="editar-nombre">
            <span className="administracion__campo-rotulo">Nombre</span>
            <input id="editar-nombre" className="administracion__input" value={nombre} maxLength={100}
              required={!cuenta.vinculada} readOnly={cuenta.vinculada} disabled={guardando}
              onChange={evento => setNombre(evento.target.value)} />
          </label>
          {cuenta.vinculada ? <p className="administracion__ayuda">El nombre de esta cuenta se administra desde el padrón.</p> : null}
          <label className="administracion__campo" htmlFor="editar-rol">
            <span id="editar-rol-rotulo" className="administracion__campo-rotulo">Rol</span>
            <select id="editar-rol" aria-labelledby="editar-rol-rotulo" className="administracion__select" value={rol}
              disabled={guardando || cuenta.rol === 'sistemas'} onChange={evento => setRol(evento.target.value)}>
              {cuenta.rol === 'sistemas' ? <option value="sistemas">Sistemas</option> :
                ROLES_NUEVA_CUENTA.map(({ valor, etiqueta }) => <option key={valor} value={valor}>{etiqueta}</option>)}
            </select>
          </label>
          {cambioRol ? <p className="administracion__ayuda">Al cambiar el rol se cerrarán las sesiones abiertas de esta cuenta.</p> : null}
        </div>
        {error ? <p className="administracion__error-campo" role="alert">{error}</p> : null}
        <div className="administracion__dialogo-acciones">
          <Boton variante="secundario" onClick={onCerrar} disabled={guardando}>Cancelar</Boton>
          <Boton type="submit" disabled={guardando || !puedeGuardar}>{guardando ? 'Guardando…' : 'Guardar cambios'}</Boton>
        </div>
      </form>
    </Dialogo>
  );
}

const TEXTOS_CONFIRMACION = {
  eliminar: {
    tono: 'aviso',
    titulo: 'Eliminar cuenta',
    mensaje: (cuenta) => `¿Eliminar la cuenta ${cuenta.username} de la lista? Quedará desactivada y no podrá ingresar. Sus datos y registros se conservarán.`,
    confirmar: 'Eliminar',
  },
  desactivar: {
    tono: 'aviso',
    titulo: 'Desactivar cuenta',
    mensaje: (cuenta) => `¿Desactivar la cuenta de ${cuenta.username}? No podrá ingresar hasta que se reactive.`,
    confirmar: 'Desactivar',
  },
  reactivar: {
    tono: 'acento',
    titulo: 'Reactivar cuenta',
    mensaje: (cuenta) => `¿Reactivar la cuenta de ${cuenta.username}? Volverá a ingresar con su clave.`,
    confirmar: 'Reactivar',
  },
};

/** Confirmación de desactivar o reactivar. */
export function DialogoConfirmacion({ confirmacion, onConfirmar, onCancelar }) {
  const textos = TEXTOS_CONFIRMACION[confirmacion.tipo];
  return (
    <Dialogo etiqueta={textos.titulo} onCerrar={onCancelar}>
      <div className="administracion__dialogo-cabecera">
        <span className={`administracion__dialogo-icono administracion__dialogo-icono--${textos.tono}`} aria-hidden="true">
          <IconoAlerta tamano={22} />
        </span>
        <h2 className="administracion__dialogo-titulo">{textos.titulo}</h2>
      </div>
      <p className="administracion__dialogo-mensaje">{textos.mensaje(confirmacion.cuenta)}</p>
      <div className="administracion__dialogo-acciones">
        <Boton variante="secundario" onClick={onCancelar}>
          Cancelar
        </Boton>
        <Boton onClick={onConfirmar} className={confirmacion.tipo === 'eliminar' ? 'administracion__eliminar' : undefined}>
          {textos.confirmar}
        </Boton>
      </div>
    </Dialogo>
  );
}

/**
 * Contraseña y su confirmación, con «Mostrar» para revisar lo escrito.
 * Se usa al crear la cuenta y al cambiar su clave.
 */
export function CamposClave({ idBase, clave, onClave, confirmacion, onConfirmacion }) {
  const [visible, setVisible] = useState(false);
  const tipo = visible ? 'text' : 'password';
  return (
    <div className="administracion__clave-campos">
      <div className="administracion__clave-fila">
        <label className="administracion__campo" htmlFor={`${idBase}-clave`}>
          <span className="administracion__campo-rotulo">Contraseña</span>
          <input
            id={`${idBase}-clave`}
            type={tipo}
            className="administracion__input"
            value={clave}
            onChange={(evento) => onClave(evento.target.value)}
            placeholder={`Al menos ${LARGO_MINIMO_CLAVE} caracteres`}
            autoComplete="new-password"
          />
        </label>
        <label className="administracion__campo" htmlFor={`${idBase}-confirmacion`}>
          <span className="administracion__campo-rotulo">Repetir contraseña</span>
          <input
            id={`${idBase}-confirmacion`}
            type={tipo}
            className="administracion__input"
            value={confirmacion}
            onChange={(evento) => onConfirmacion(evento.target.value)}
            autoComplete="new-password"
          />
        </label>
      </div>
      <div className="administracion__clave-pie">
        <p className="administracion__ayuda">
          Es la contraseña definitiva: la persona entra con ella sin tener que cambiarla.
        </p>
        <Boton variante="fantasma" onClick={() => setVisible((valor) => !valor)} aria-pressed={visible}>
          {visible ? 'Ocultar' : 'Mostrar'}
        </Boton>
      </div>
    </div>
  );
}

/**
 * Cambiar la contraseña de una cuenta: root escribe la nueva. Al guardarla se
 * cierran las sesiones abiertas de esa cuenta.
 */
export function DialogoCambiarClave({ cuenta, onCambiada, onCerrar, cambiar = cambiarClaveCuenta, claveInicial = '' }) {
  const [clave, setClave] = useState(claveInicial);
  const [confirmacion, setConfirmacion] = useState(claveInicial);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState('');

  async function guardar() {
    if (guardando) return;
    const motivo = motivoClaveInvalida(clave, confirmacion, cuenta.username);
    if (motivo) {
      setError(motivo);
      return;
    }
    setGuardando(true);
    setError('');
    try {
      await cambiar(cuenta.id, clave);
      onCambiada(cuenta);
    } catch (fallo) {
      setError(fallo.message);
    } finally {
      setGuardando(false);
    }
  }

  return (
    <Dialogo etiqueta="Cambiar clave" onCerrar={onCerrar}>
      <div className="administracion__dialogo-cabecera">
        <span className="administracion__dialogo-icono administracion__dialogo-icono--acento" aria-hidden="true">
          <IconoCandado tamano={22} />
        </span>
        <h2 className="administracion__dialogo-titulo">Cambiar clave de {cuenta.username}</h2>
      </div>
      <p className="administracion__dialogo-mensaje">
        Si tiene una sesión abierta, se cerrará y tendrá que ingresar con la nueva contraseña.
      </p>

      <CamposClave
        idBase="cambio"
        clave={clave}
        onClave={setClave}
        confirmacion={confirmacion}
        onConfirmacion={setConfirmacion}
      />

      {error ? <p className="administracion__error-campo" role="alert">{error}</p> : null}

      <div className="administracion__dialogo-acciones">
        <Boton variante="secundario" onClick={onCerrar} disabled={guardando}>
          Cancelar
        </Boton>
        <Boton onClick={guardar} disabled={guardando}>
          {guardando ? 'Guardando…' : 'Guardar contraseña'}
        </Boton>
      </div>
    </Dialogo>
  );
}
