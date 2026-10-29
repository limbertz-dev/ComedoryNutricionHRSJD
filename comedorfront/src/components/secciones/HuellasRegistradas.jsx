import { useEffect, useState } from 'react';
import { obtenerRegistrosHuellas } from '../../api.js';
import Boton from '../ui/Boton.jsx';
import Etiqueta from '../ui/Etiqueta.jsx';
import SelectorCalendario, { valorFecha } from './SelectorCalendario.jsx';
import './HuellasRegistradas.css';

const FECHA = new Intl.DateTimeFormat('es-BO', {
  dateStyle: 'short', timeStyle: 'medium', timeZone: 'America/La_Paz',
});

/** La jefa consulta el vínculo y la cuenta que realizó el alta, sin modificarlo. */
export default function HuellasRegistradas({ version = 0, consultar = obtenerRegistrosHuellas, inicial, hoy = new Date() }) {
  const [pagina, setPagina] = useState(inicial?.pagina ?? null);
  const [error, setError] = useState(inicial?.error ?? '');
  const [cargando, setCargando] = useState(!inicial);
  const [busqueda, setBusqueda] = useState('');
  const [termino, setTermino] = useState('');
  const [desplazamiento, setDesplazamiento] = useState(0);
  const [refresco, setRefresco] = useState(0);
  /* Filtro por un solo día (hoy al abrir); null = todas las fechas. */
  const [fecha, setFecha] = useState(() => valorFecha(hoy));

  useEffect(() => {
    if (inicial) return undefined;
    const controlador = new AbortController();
    setCargando(true);
    consultar({ busqueda: termino, limite: 50, desplazamiento, fecha, signal: controlador.signal })
      .then(datos => { if (!controlador.signal.aborted) { setPagina(datos); setError(''); } })
      .catch(fallo => { if (!controlador.signal.aborted) setError(fallo.message); })
      .finally(() => { if (!controlador.signal.aborted) setCargando(false); });
    return () => controlador.abort();
  }, [inicial, consultar, termino, desplazamiento, fecha, version, refresco]);

  function elegirFecha(valor) {
    setFecha(valor);
    setDesplazamiento(0);
  }

  function buscar(evento) {
    evento.preventDefault();
    setTermino(busqueda.trim());
    setDesplazamiento(0);
    setRefresco(valor => valor + 1);
  }

  const filas = pagina?.datos ?? [];
  return (
    <section className="huellas-registro" aria-labelledby="huellas-registro-titulo" aria-busy={cargando}>
      <header className="huellas-registro__cabecera">
        <div>
          <h2 id="huellas-registro-titulo">Huellas registradas</h2>
          <p>Comensal vinculado y cuenta que realizó cada alta. Hora de Bolivia.</p>
        </div>
        <div className="huellas-registro__acciones">
          <div className="huellas-registro__fecha-filtro" role="group" aria-label="Filtrar por día del alta">
            <SelectorCalendario alcance="diario" fecha={fecha ?? valorFecha(hoy)} mes={(fecha ?? valorFecha(hoy)).slice(0, 7)}
              hoy={hoy} onFecha={elegirFecha} onMes={() => {}} />
            <Boton variante={fecha === null ? 'primario' : 'fantasma'} tamano="sm" disabled={cargando || fecha === null}
              onClick={() => elegirFecha(null)}>Todas las fechas</Boton>
          </div>
          <Boton variante="secundario" tamano="sm" disabled={cargando}
            onClick={() => setRefresco(valor => valor + 1)}>
            {cargando ? 'Actualizando huellas…' : 'Actualizar huellas'}
          </Boton>
        </div>
      </header>
      <form className="huellas-registro__busqueda" role="search" aria-label="Buscar huellas registradas" onSubmit={buscar}>
        <label htmlFor="huellas-registro-busqueda">Buscar comensal o cuenta</label>
        <div>
          <input id="huellas-registro-busqueda" type="search" value={busqueda} maxLength={100}
            placeholder="Nombre, legajo, ID o usuario" onChange={e => setBusqueda(e.target.value)} />
          <Boton type="submit" variante="secundario" tamano="sm" disabled={cargando}>Buscar</Boton>
        </div>
      </form>
      {error ? <p className="huellas-registro__estado huellas-registro__estado--error" role="alert">
        {pagina ? 'Se conserva la última consulta. ' : ''}{error} Usa «Actualizar huellas» para reintentar.
      </p> : null}
      {cargando ? <p className="huellas-registro__estado" role="status">
        {pagina ? 'Actualizando el registro de huellas…' : 'Cargando huellas registradas…'}
      </p> : null}
      {pagina && !cargando && filas.length === 0 ? <p className="huellas-registro__estado" role="status">
        {termino ? 'No hay huellas que coincidan con la búsqueda.'
          : fecha ? 'No hubo altas de huella ese día. Elige otro día o «Todas las fechas».'
            : 'Todavía no hay huellas registradas. Las nuevas altas aparecerán aquí con su comensal y responsable.'}
      </p> : null}
      {filas.length > 0 ? <>
        <div className="huellas-registro__tabla-caja" role="region" aria-label="Tabla de huellas registradas" tabIndex={0}>
          <table className="huellas-registro__tabla" aria-label="Huellas registradas">
            <thead><tr><th scope="col">Fecha del alta</th><th scope="col">Comensal vinculado</th>
              <th scope="col">Categoría y servicio</th><th scope="col">Registró</th><th scope="col">Estado</th></tr></thead>
            <tbody>{filas.map(fila => {
              const policia = fila.tipo === 'policia';
              return <tr key={`${fila.tipo ?? 'personal'}:${fila.comensal.usuario_id ?? fila.registrada_en}:${fila.comensal.nombre}`}>
                <td className="huellas-registro__fecha"><time dateTime={fila.registrada_en}>{FECHA.format(new Date(fila.registrada_en))}</time></td>
                <td><strong>{fila.comensal.nombre || `Comensal ${fila.comensal.usuario_id}`}</strong>
                  <span>{policia
                    ? (fila.comensal.legajo ? `CI o placa ${fila.comensal.legajo}` : 'Sin CI ni placa')
                    : `${fila.comensal.legajo || 'Sin legajo'} · ID ${fila.comensal.usuario_id}`}</span>
                  {!policia && !fila.comensal.disponible ? <span>Ficha no disponible en el padrón actual</span> : null}</td>
                <td><strong>{fila.comensal.categoria || 'Sin categoría'}</strong>
                  <span>{policia ? 'Fuera del padrón · vía libre' : fila.comensal.servicio || 'Sin servicio'}</span></td>
                <td><strong>{fila.cuenta.nombre || fila.cuenta.usuario || (fila.cuenta.id ? `Cuenta ${fila.cuenta.id}` : 'Sin cuenta')}</strong>
                  <span>{fila.cuenta.usuario || (fila.cuenta.id ? 'Cuenta no disponible' : 'Registro sin cuenta')}</span></td>
                <td>{policia
                  ? <Etiqueta tono={fila.activo === false ? 'neutro' : 'acento'}>{fila.activo === false ? 'Policía · baja' : 'Policía'}</Etiqueta>
                  : <Etiqueta tono="acento">Vinculada</Etiqueta>}</td>
              </tr>;
            })}</tbody>
          </table>
        </div>
        <nav className="huellas-registro__paginas" aria-label="Páginas del registro de huellas">
          <p>{pagina.desplazamiento + 1}–{pagina.desplazamiento + filas.length} de {pagina.total} {pagina.total === 1 ? 'huella' : 'huellas'}</p>
          {pagina.total > pagina.limite ? <>
            <Boton variante="fantasma" tamano="sm" disabled={cargando || pagina.desplazamiento === 0}
              onClick={() => setDesplazamiento(Math.max(0, pagina.desplazamiento - pagina.limite))}>Anterior</Boton>
            <Boton variante="fantasma" tamano="sm" disabled={cargando || pagina.desplazamiento + filas.length >= pagina.total}
              onClick={() => setDesplazamiento(pagina.desplazamiento + pagina.limite)}>Siguiente</Boton>
          </> : null}
        </nav>
      </> : null}
    </section>
  );
}
