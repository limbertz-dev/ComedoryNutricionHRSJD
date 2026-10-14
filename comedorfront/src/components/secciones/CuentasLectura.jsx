import { useCallback, useEffect, useMemo, useState } from 'react';
import Boton from '../ui/Boton.jsx';
import Etiqueta from '../ui/Etiqueta.jsx';
import { IconoBuscar } from '../ui/Iconos.jsx';
import { obtenerCuentasLectura } from '../../api.js';
import {
  ETIQUETAS_ROL,
  estadoDeCuenta,
  filtrarCuentas,
  contarCuentasPorEstado,
  formatoUltimoIngreso,
  ordenarCuentas,
} from '../../cuentas.js';
import './CuentasLectura.css';

/**
 * Cuentas (solo jefa, solo lectura).
 *
 * Tabla de cuentas con búsqueda local y Actualizar. Sin acciones y sin
 * "Nueva cuenta": la gestión vive en Administración (sistemas). Orden,
 * filtro, estado y último ingreso salen del módulo compartido cuentas.js,
 * así ambas tablas muestran filas idénticas.
 */
export default function CuentasLectura({
  cargandoInicial = true,
  errorInicial = null,
  cuentasIniciales = null,
  busquedaInicial = '',
  avisoInicial = null,
}) {
  const [cargando, setCargando] = useState(cargandoInicial);
  const [actualizando, setActualizando] = useState(false);
  const [error, setError] = useState(errorInicial);
  const [cuentas, setCuentas] = useState(cuentasIniciales);
  const [busqueda, setBusqueda] = useState(busquedaInicial);
  const [aviso, setAviso] = useState(avisoInicial);

  const cargarCuentas = useCallback(async ({ signal, esRefresco = false } = {}) => {
    if (!esRefresco) {
      setCargando(true);
      setError(null);
    } else {
      setActualizando(true);
    }
    try {
      const lista = await obtenerCuentasLectura({ signal });
      if (signal?.aborted) return;
      setCuentas(lista);
    } catch (fallo) {
      if (!signal?.aborted) {
        if (!esRefresco) {
          setError(fallo.message);
        } else {
          setAviso({ titulo: 'No se pudo actualizar', detalle: fallo.message });
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

  if (cargando) {
    return (
      <div className="cuentas">
        <p className="cuentas__estado" role="status">Cargando cuentas…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="cuentas">
        <div className="cuentas__error" role="alert">
          <p>{error}</p>
          <Boton onClick={() => cargarCuentas()}>Reintentar cuentas</Boton>
        </div>
      </div>
    );
  }

  const total = (cuentas ?? []).length;
  const sinCuentas = total === 0;
  const conteo = contarCuentasPorEstado(cuentas ?? []);

  return (
    <div className="cuentas">
      {aviso ? (
        <div className="cuentas__aviso" role="alert">
          <div className="cuentas__aviso-contenido">
            <strong className="cuentas__aviso-titulo">{aviso.titulo}</strong>
            {aviso.detalle ? (
              <p className="cuentas__aviso-detalle">{aviso.detalle}</p>
            ) : null}
          </div>
          <button
            type="button"
            className="cuentas__aviso-cerrar"
            onClick={() => setAviso(null)}
            aria-label="Cerrar aviso"
          >
            ×
          </button>
        </div>
      ) : null}

      <div className="cuentas__barra">
        <div className="cuentas__buscador">
          <span className="cuentas__buscador-icono" aria-hidden="true">
            <IconoBuscar tamano={16} />
          </span>
          <input
            type="text"
            className="cuentas__buscador-input"
            value={busqueda}
            onChange={(evento) => setBusqueda(evento.target.value)}
            placeholder="Buscar por usuario o nombre…"
            aria-label="Buscar por usuario o nombre"
          />
          {busqueda ? (
            <button
              type="button"
              className="cuentas__buscador-limpiar"
              onClick={() => setBusqueda('')}
              aria-label="Limpiar búsqueda"
            >
              ×
            </button>
          ) : null}
        </div>

        <Etiqueta tono="neutro">Solo lectura</Etiqueta>

        <Boton
          variante="secundario"
          tamano="sm"
          onClick={() => cargarCuentas({ esRefresco: true })}
          disabled={actualizando}
        >
          {actualizando ? 'Actualizando…' : 'Actualizar'}
        </Boton>
      </div>

      {sinCuentas ? (
        <p className="cuentas__vacio" role="status">
          No hay cuentas registradas.
        </p>
      ) : (
        <section className="cuentas__panel" aria-label="Cuentas del comedor">
          <header className="cuentas__panel-cabecera">
            <p className="cuentas__conteo" role="status">
              {`${cuentasVisibles.length} de ${total} ${total === 1 ? 'cuenta' : 'cuentas'}`}
            </p>
            <ul className="cuentas__estados" aria-label="Cuentas por estado">
              <li><Etiqueta tono="exito">{`Activas ${conteo.activas}`}</Etiqueta></li>
              {conteo.claveTemporal > 0 ? (
                <li><Etiqueta tono="aviso">{`Clave temporal ${conteo.claveTemporal}`}</Etiqueta></li>
              ) : null}
              <li><Etiqueta tono="neutro">{`Inactivas ${conteo.inactivas}`}</Etiqueta></li>
            </ul>
          </header>

          {cuentasVisibles.length === 0 ? (
            <div className="cuentas__vacio cuentas__vacio--tabla" role="status">
              <p>Ninguna cuenta coincide con la búsqueda.</p>
              <Boton variante="secundario" tamano="sm" onClick={() => setBusqueda('')}>
                Limpiar búsqueda
              </Boton>
            </div>
          ) : (
            <div className="cuentas__tabla-caja">
              <table className="cuentas__tabla" aria-label="Cuentas del comedor">
                <thead>
                  <tr>
                    <th scope="col">Usuario</th>
                    <th scope="col">Nombre</th>
                    <th scope="col">Rol</th>
                    <th scope="col">Estado</th>
                    <th scope="col">Último ingreso</th>
                  </tr>
                </thead>
                <tbody>
                  {cuentasVisibles.map((cuenta) => (
                    <FilaCuentaLectura key={cuenta.id} cuenta={cuenta} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
}

/** Fila de solo lectura: datos legibles, sin acciones. */
function FilaCuentaLectura({ cuenta }) {
  const estado = estadoDeCuenta(cuenta);
  const nunca = cuenta.ultimoIngreso === null || cuenta.ultimoIngreso === undefined || cuenta.ultimoIngreso === '';
  return (
    <tr className={cuenta.activo ? undefined : 'cuentas__fila--inactiva'}>
      <td className="cuentas__usuario" data-label="Usuario">{cuenta.username}</td>
      <td data-label="Nombre">{cuenta.nombre || '—'}</td>
      <td data-label="Rol">{ETIQUETAS_ROL[cuenta.rol] ?? cuenta.rol}</td>
      <td data-label="Estado">
        <Etiqueta tono={estado.tono}>{estado.texto}</Etiqueta>
      </td>
      <td data-label="Último ingreso" className={nunca ? 'cuentas__nunca' : undefined}>
        {formatoUltimoIngreso(cuenta.ultimoIngreso)}
      </td>
    </tr>
  );
}
