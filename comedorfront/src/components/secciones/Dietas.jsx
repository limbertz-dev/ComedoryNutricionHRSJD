import { useCallback, useMemo, useState } from 'react';
import { crearDieta, editarDieta, eliminarDieta, obtenerDietas } from '../../api.js';
import useConsultaApi from '../../hooks/useConsultaApi.js';
import AppSelect from '../ui/AppSelect.jsx';
import Boton from '../ui/Boton.jsx';
import Etiqueta from '../ui/Etiqueta.jsx';
import './Dietas.css';

/*
 * Dietas — el catálogo oficial de nutrición, en una tabla de dos columnas.
 *
 * Todo se edita en la propia fila: dar de alta, renombrar, activar y
 * eliminar. Activa = "no disponible pero listada"; Eliminar = borrado lógico:
 * la dieta desaparece de la pantalla y la fila queda en la base. La
 * columna del libro no se muestra; solo se elige al crear, porque el backend
 * la exige. Los errores del backend (409 incluidos) se ven en la fila donde
 * se hizo la acción.
 */

/** Columna que se propone al crear, si el catálogo ya la usa. */
const COLUMNA_POR_DEFECTO = 'OTROS';

/** Interruptor de "activa": un botón con rol switch, sin checkbox nativo. */
function Interruptor({ activa, disabled, onClick, etiqueta }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={activa}
      aria-label={etiqueta}
      disabled={disabled}
      className={`dietas__switch${activa ? ' dietas__switch--activo' : ''}`}
      onClick={onClick}
    >
      <span className="dietas__switch-puntero" />
    </button>
  );
}

function ErrorDeFila({ mensaje }) {
  return mensaje ? <p className="dietas__error" role="alert">{mensaje}</p> : null;
}

/** Fila de alta: la columna del libro se elige acá porque el backend la exige. */
function FilaAlta({ columnas, enviando, error, onCrear, onCancelar }) {
  const [nombre, setNombre] = useState('');
  const [columna, setColumna] = useState(() => (columnas.includes(COLUMNA_POR_DEFECTO) ? COLUMNA_POR_DEFECTO : ''));
  const [activa, setActiva] = useState(true);

  function enviar(evento) {
    evento.preventDefault();
    if (!enviando) onCrear({ nombre, columnaInforme: columna, activa });
  }

  return (
    <tr className="dietas__fila dietas__fila--edicion">
      <td>
        <form className="dietas__form" onSubmit={enviar}>
          <input
            className="dietas__campo"
            type="text"
            value={nombre}
            placeholder="Nombre de la dieta"
            aria-label="Nombre de la nueva dieta"
            autoFocus
            onChange={(e) => setNombre(e.target.value)}
          />
          <AppSelect
            value={columna}
            onChange={setColumna}
            placeholder="Columna del libro"
            options={columnas.map((c) => ({ value: c, label: c }))}
            className="dietas__select"
          />
          <Boton type="submit" disabled={enviando}>{enviando ? 'Creando…' : 'Crear'}</Boton>
          <Boton variante="fantasma" onClick={onCancelar} disabled={enviando}>Cancelar</Boton>
        </form>
        <ErrorDeFila mensaje={error} />
      </td>
      <td className="dietas__col-activa">
        <Interruptor
          activa={activa}
          disabled={enviando}
          onClick={() => setActiva((valor) => !valor)}
          etiqueta="Nueva dieta activa"
        />
      </td>
    </tr>
  );
}

function FilaDieta({
  dieta, editando, confirmando, enviando, error,
  onEditar, onGuardar, onCancelar, onAlternar, onPedirEliminar, onEliminar,
}) {
  const [nombre, setNombre] = useState(dieta.nombre);
  const esNpo = dieta.esAyuno || !dieta.sumaAlLibro;

  function enviar(evento) {
    evento.preventDefault();
    if (!enviando) onGuardar(nombre);
  }

  return (
    <tr className={`dietas__fila${dieta.activa ? '' : ' dietas__fila--inactiva'}`}>
      <td>
        {editando ? (
          <form className="dietas__form" onSubmit={enviar}>
            <input
              className="dietas__campo"
              type="text"
              value={nombre}
              aria-label={`Nuevo nombre de ${dieta.nombre}`}
              autoFocus
              onChange={(e) => setNombre(e.target.value)}
            />
            <Boton type="submit" disabled={enviando}>{enviando ? 'Guardando…' : 'Guardar'}</Boton>
            <Boton variante="fantasma" onClick={onCancelar} disabled={enviando}>Cancelar</Boton>
          </form>
        ) : confirmando ? (
          <div className="dietas__dieta">
            <span className="dietas__confirmar">
              ¿Eliminar {dieta.nombre}? Ya no aparecerá en el catálogo.
            </span>
            <div className="dietas__acciones">
              <Boton onClick={onEliminar} disabled={enviando}>{enviando ? 'Eliminando…' : 'Sí, eliminar'}</Boton>
              <Boton variante="fantasma" onClick={onCancelar} disabled={enviando}>No</Boton>
            </div>
          </div>
        ) : (
          <div className="dietas__dieta">
            <span className="dietas__dieta-nombre">{dieta.nombre}</span>
            {esNpo ? <Etiqueta tono="aviso">no suma · es ayuno</Etiqueta> : null}
            <div className="dietas__acciones">
              <Boton variante="fantasma" onClick={onEditar} disabled={enviando}>Editar</Boton>
              {/* NPO no se elimina: el backend igual respondería 422. */}
              {dieta.esAyuno ? null : (
                <Boton variante="fantasma" onClick={onPedirEliminar} disabled={enviando}>Eliminar</Boton>
              )}
            </div>
          </div>
        )}
        <ErrorDeFila mensaje={error} />
      </td>
      <td className="dietas__col-activa">
        <Interruptor
          activa={dieta.activa}
          disabled={enviando}
          onClick={onAlternar}
          etiqueta={`${dieta.nombre} activa`}
        />
      </td>
    </tr>
  );
}

export default function Dietas() {
  /* Una sola acción en curso a la vez: `fila` identifica qué se abrió
     ('alta', 'dieta-3' al editar, 'eliminar-3' al confirmar). Los errores de
     una dieta se muestran siempre en su fila, con la clave 'dieta-3'. */
  const [fila, setFila] = useState(null);
  const [errorFila, setErrorFila] = useState({ clave: null, mensaje: '' });
  const [enviando, setEnviando] = useState(false);

  const { datos: dietas, cargando, error, recargar } = useConsultaApi(
    useCallback((signal) => obtenerDietas({ signal }), []),
  );
  const listaDietas = dietas ?? [];

  /* Las columnas que ya usa el catálogo: no hay endpoint de columnas y una
     lista escrita acá sería inventarla. */
  const columnas = useMemo(
    () => Array.from(new Set(listaDietas.map((d) => d.columnaLibro).filter(Boolean)))
      .sort((uno, otro) => uno.localeCompare(otro, 'es')),
    [listaDietas],
  );

  function abrir(clave) {
    setFila(clave);
    setErrorFila({ clave: null, mensaje: '' });
  }

  /* Corre la escritura, cierra la fila si salió bien y recarga el catálogo;
     si falla, el mensaje del backend queda en la fila de la acción. */
  async function ejecutar(clave, escritura) {
    if (enviando) return;
    setEnviando(true);
    setErrorFila({ clave: null, mensaje: '' });
    try {
      await escritura();
      setFila(null);
      await recargar({ conservar: true });
    } catch (fallo) {
      setErrorFila({ clave, mensaje: fallo.message });
    } finally {
      setEnviando(false);
    }
  }

  const errorDe = (clave) => (errorFila.clave === clave ? errorFila.mensaje : '');

  return (
    <article className="dietas">
      <header className="dietas__cabecera">
        <h2 className="dietas__titulo">Catálogo de dietas</h2>
        <Boton onClick={() => abrir('alta')} disabled={!dietas || enviando || fila === 'alta'}>
          + Nueva dieta
        </Boton>
      </header>

      {cargando ? <p className="dietas__estado" role="status">Cargando el catálogo de dietas…</p> : null}
      {error ? (
        <p className="dietas__error" role="alert">
          {error} <Boton variante="secundario" onClick={() => recargar()}>Reintentar</Boton>
        </p>
      ) : null}

      {dietas && (listaDietas.length > 0 || fila === 'alta') ? (
        <div className="dietas__tabla-caja">
          <table className="dietas__tabla">
            <caption className="solo-lectores">Catálogo de dietas y si están activas.</caption>
            <thead>
              <tr>
                <th scope="col">Dieta</th>
                <th scope="col" className="dietas__col-activa">Activa</th>
              </tr>
            </thead>
            <tbody>
              {fila === 'alta' ? (
                <FilaAlta
                  columnas={columnas}
                  enviando={enviando}
                  error={errorDe('alta')}
                  onCancelar={() => abrir(null)}
                  onCrear={(datos) => ejecutar('alta', () => crearDieta(datos))}
                />
              ) : null}
              {listaDietas.map((dieta) => {
                const clave = `dieta-${dieta.id}`;
                return (
                  <FilaDieta
                    key={`${dieta.id}-${fila === clave}`}
                    dieta={dieta}
                    editando={fila === clave}
                    confirmando={fila === `eliminar-${dieta.id}`}
                    enviando={enviando}
                    error={errorDe(clave)}
                    onEditar={() => abrir(clave)}
                    onCancelar={() => abrir(null)}
                    onGuardar={(nombre) => ejecutar(clave, () => {
                      if (!nombre.trim()) throw new Error('Escriba el nombre de la dieta.');
                      return editarDieta(dieta.id, { nombre });
                    })}
                    onAlternar={() => ejecutar(clave, () => editarDieta(dieta.id, { activa: !dieta.activa }))}
                    onPedirEliminar={() => abrir(`eliminar-${dieta.id}`)}
                    onEliminar={() => ejecutar(clave, () => eliminarDieta(dieta.id))}
                  />
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}

      {dietas && listaDietas.length === 0 && fila !== 'alta' ? (
        <p className="dietas__estado">El catálogo todavía no tiene dietas.</p>
      ) : null}
    </article>
  );
}
