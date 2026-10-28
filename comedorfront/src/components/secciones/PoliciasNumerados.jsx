import { useCallback, useEffect, useState } from 'react';
import { ErrorApi, cambiarEstadoPolicia, crearPolicia, obtenerPolicias } from '../../api.js';
import Boton from '../ui/Boton.jsx';
import Etiqueta from '../ui/Etiqueta.jsx';
import { IconoEscudo } from '../ui/Iconos.jsx';

/**
 * Policías por número (Policía 1, 2, ...) para la jefatura: alta del
 * siguiente número y baja o reactivación. La cocinera los marca en el
 * checklist; una baja no borra sus raciones.
 */
export default function PoliciasNumerados({ inicial = null }) {
  const [policias, setPolicias] = useState(inicial);
  const [error, setError] = useState('');
  const [ocupado, setOcupado] = useState(false);

  const cargar = useCallback(async () => {
    try {
      setPolicias(await obtenerPolicias());
      setError('');
    } catch (causa) {
      setError(causa.message);
    }
  }, []);

  useEffect(() => {
    if (inicial === null) cargar();
  }, [cargar, inicial]);

  async function ejecutar(accion) {
    if (ocupado) return;
    setOcupado(true);
    try {
      await accion();
      await cargar();
    } catch (causa) {
      setError(causa instanceof ErrorApi ? (causa.datos?.detail ?? causa.message) : causa.message);
    } finally {
      setOcupado(false);
    }
  }

  const lista = policias ?? [];
  const activos = lista.filter((p) => p.activo).length;

  return (
    <section className="supervision__panel supervision__policias" aria-label="Policías del comedor">
      <header className="supervision__panel-cabecera">
        <div>
          <h3 className="supervision__subtitulo">Policías del comedor</h3>
          <p className="supervision__conteo" role="status">
            {`${activos} ${activos === 1 ? 'activo' : 'activos'} · la cocinera los marca en el checklist, sin nombre`}
          </p>
        </div>
        <Boton tamano="sm" icono={<IconoEscudo tamano={16} />} disabled={ocupado}
          onClick={() => ejecutar(crearPolicia)}>
          Agregar policía
        </Boton>
      </header>
      {error ? <p className="supervision__error" role="alert">{error}</p> : null}
      {policias === null && !error ? (
        <p className="supervision__vacio supervision__vacio--tabla" role="status">Cargando…</p>
      ) : lista.length === 0 ? (
        <p className="supervision__vacio supervision__vacio--tabla" role="status">
          Todavía no hay policías. «Agregar policía» crea el Policía 1.
        </p>
      ) : (
        <div className="supervision__tabla-caja">
          <table className="supervision__tabla" aria-label="Policías del comedor">
            <thead>
              <tr>
                <th scope="col">Policía</th>
                <th scope="col">Estado</th>
                <th scope="col">Acción</th>
              </tr>
            </thead>
            <tbody>
              {lista.map((p) => (
                <tr key={p.id}>
                  <td>{p.nombre}</td>
                  <td><Etiqueta tono={p.activo ? 'exito' : 'neutro'}>{p.activo ? 'Activo' : 'De baja'}</Etiqueta></td>
                  <td>
                    <Boton variante="secundario" tamano="sm" disabled={ocupado}
                      onClick={() => ejecutar(() => cambiarEstadoPolicia(p.id, !p.activo))}>
                      {p.activo ? 'Dar de baja' : 'Reactivar'}
                    </Boton>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
