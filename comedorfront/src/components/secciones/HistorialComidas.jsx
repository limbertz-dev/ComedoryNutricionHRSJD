import { useCallback, useMemo, useState } from 'react';
import {
  obtenerHistorialDiarioPersonal,
  obtenerHistorialMensualPersonal,
} from '../../api.js';
import useConsultaApi from '../../hooks/useConsultaApi.js';
import Boton from '../ui/Boton.jsx';
import AppSelect from '../ui/AppSelect.jsx';
import SelectorCalendario from './SelectorCalendario.jsx';
import { IconoBuscar, IconoCheck, IconoEquis } from '../ui/Iconos.jsx';
import './HistorialComidas.css';

const ABREVIATURAS = {
  Médico: 'MED',
  Médicos: 'MED',
  Residente: 'RES',
  Residentes: 'RES',
  Interno: 'INT',
  Internos: 'INT',
  Policías: 'POL',
  Policía: 'POL',
  Técnicos: 'TEC',
  Técnico: 'TEC',
  Servicio: 'SER',
  Administrativo: 'ADM',
};

const ESTADOS_FILTRO = [
  { valor: 'todos', etiqueta: 'Todos los estados' },
  { valor: 'recibio', etiqueta: 'Recibió' },
  { valor: 'no-recibio', etiqueta: 'No recibió' },
  { valor: 'pendiente', etiqueta: 'Pendiente' },
  { valor: 'no-aplica', etiqueta: 'No aplica' },
];

const FORMATO_FECHA = new Intl.DateTimeFormat('es-BO', {
  weekday: 'long',
  day: '2-digit',
  month: 'long',
  year: 'numeric',
});

const FORMATO_MES = new Intl.DateTimeFormat('es-BO', {
  month: 'long',
  year: 'numeric',
});

function valorFecha(fecha) {
  const dos = (numero) => String(numero).padStart(2, '0');
  return `${fecha.getFullYear()}-${dos(fecha.getMonth() + 1)}-${dos(fecha.getDate())}`;
}

function fechaDesdeValor(valor) {
  const [gestion, mes, dia] = valor.split('-').map(Number);
  return new Date(gestion, mes - 1, dia, 12);
}

function valorMes(fecha) {
  return valorFecha(fecha).slice(0, 7);
}

function periodoDesdeValor(valor) {
  const [gestion, mes] = valor.split('-').map(Number);
  return { gestion, mesIndice: mes - 1 };
}

function abreviatura(categoria) {
  return ABREVIATURAS[categoria] ?? categoria.slice(0, 3).toUpperCase();
}

function normalizarTexto(texto) {
  return texto
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .trim();
}

function siglasServicio(servicio) {
  if (!servicio || typeof servicio !== 'string') return '—';
  const limpio = servicio.trim().replace(/\s+/g, ' ');
  if (!limpio || limpio === '—' || limpio === '-') return '—';
  if (normalizarTexto(limpio) === 'sin servicio') return '—';

  const sinTildes = limpio.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  const palabras = sinTildes.split(' ').filter(Boolean);

  if (palabras.length === 0) return '—';
  if (palabras.length === 1) {
    return palabras[0].slice(0, 3).toUpperCase();
  }
  const iniciales = palabras.map((palabra) => palabra[0].toUpperCase()).join('').slice(0, 4);
  return iniciales || palabras[0].slice(0, 3).toUpperCase();
}

function coincideEstado(registro, alcance, estado) {
  if (estado === 'todos') return true;

  if (alcance === 'diario') {
    if (estado === 'no-aplica') return registro.comidas.some((comida) => !comida.aplica);
    if (estado === 'recibio') return registro.comidas.some((comida) => comida.aplica && comida.estado === true);
    if (estado === 'no-recibio') return registro.comidas.some((comida) => comida.aplica && comida.estado === false);
    return registro.comidas.some((comida) => comida.aplica && comida.estado === null);
  }

  if (estado === 'no-aplica') return registro.totales.some((comida) => comida.asignadas === 0);
  if (estado === 'recibio') return registro.totalRecibidas > 0;
  if (estado === 'no-recibio') return registro.totalNoRecibidas > 0;
  return registro.totalPendientes > 0;
}

function filtrarRegistros(registros, alcance, filtros) {
  const nombreBuscado = normalizarTexto(filtros.nombre);

  return registros.filter((registro) => {
    const coincideNombre = !nombreBuscado || normalizarTexto(registro.nombre).includes(nombreBuscado);
    const coincideCategoria = filtros.categoria === 'todas' || registro.categoria === filtros.categoria;
    const coincideServicio = filtros.servicio === 'todas' || registro.servicio === filtros.servicio;
    return coincideNombre && coincideCategoria && coincideServicio && coincideEstado(registro, alcance, filtros.estado);
  });
}

/**
 * Reúne todas las páginas del historial en un solo arreglo: el filtrado y la
 * paginación de esta vista son locales, sobre el día o el mes completos —
 * pedirle al servidor una sola página ya no alcanza, porque el tamaño de
 * página ahora lo decide quien mira la tabla, no la consulta.
 */
async function reunirHistorialCompleto(consultarPagina, parametros, signal) {
  const limite = 200;
  let desplazamiento = 0;
  let datos = [];
  let comidas = [];
  let total = 0;
  do {
    const pagina = await consultarPagina({ ...parametros, limite, desplazamiento, signal });
    comidas = pagina.comidas;
    total = pagina.total;
    datos = [...datos, ...pagina.datos];
    desplazamiento += pagina.datos.length;
  } while (desplazamiento < total);
  return { datos, comidas, total };
}

function FiltrosHistorial({ filtros, categorias, servicios, onCambiar }) {
  return (
    <div className="historial__filtros" role="search" aria-label="Filtrar historial de comidas">
      <label className="historial__filtro historial__filtro--nombre">
        <span>Buscar por nombre</span>
        <span className="historial__campo historial__campo--buscar">
          <IconoBuscar tamano={18} />
          <input
            type="search"
            value={filtros.nombre}
            placeholder="Buscar nombre"
            onChange={(evento) => onCambiar('nombre', evento.target.value)}
          />
        </span>
      </label>

      <label className="historial__filtro">
        <span>Categoría</span>
        <AppSelect
          id="filtro-categoria"
          value={filtros.categoria}
          onChange={(valor) => onCambiar('categoria', valor)}
          options={[
            { value: 'todas', label: 'Todas las categorías' },
            ...categorias.map((cat) => ({ value: cat, label: cat })),
          ]}
        />
      </label>

      <label className="historial__filtro">
        <span>Servicio</span>
        <AppSelect
          id="filtro-servicio"
          value={filtros.servicio}
          onChange={(valor) => onCambiar('servicio', valor)}
          options={[
            { value: 'todas', label: 'Todos los servicios' },
            ...servicios.map((serv) => ({ value: serv, label: serv })),
          ]}
        />
      </label>

      <label className="historial__filtro">
        <span>Estado de comida</span>
        <AppSelect
          id="filtro-estado"
          value={filtros.estado}
          onChange={(valor) => onCambiar('estado', valor)}
          options={ESTADOS_FILTRO.map((est) => ({ value: est.valor, label: est.etiqueta }))}
        />
      </label>
    </div>
  );
}

function EstadoComida({ comida }) {
  if (!comida.aplica) {
    return (
      <span className="historial__estado historial__estado--no-aplica" data-tooltip="Esta comida no corresponde al turno">
        <span aria-hidden="true">—</span>
        <span>No aplica</span>
      </span>
    );
  }

  if (comida.estado === null) {
    return (
      <span className="historial__estado historial__estado--pendiente" data-tooltip="Horario pendiente">
        <span className="historial__estado-punto" aria-hidden="true" />
        <span>Pendiente</span>
      </span>
    );
  }

  return (
    <span
      className={`historial__estado historial__estado--${comida.estado ? 'recibida' : 'no-recibida'}`}
      data-tooltip={comida.estado ? 'Recibió esta comida' : 'No recibió esta comida'}
    >
      {comida.estado ? <IconoCheck tamano={17} /> : <IconoEquis tamano={17} />}
      <span>{comida.estado ? 'Recibió' : 'No recibió'}</span>
    </span>
  );
}

function Categoria({ categoria }) {
  return (
    <abbr className="historial__categoria" data-tooltip={categoria} aria-label={categoria}>
      {abreviatura(categoria)}
    </abbr>
  );
}

function Servicio({ servicio }) {
  const siglas = siglasServicio(servicio);
  const esVacio = siglas === '—';

  return (
    <abbr
      className="historial__servicio"
      data-tooltip={esVacio ? undefined : servicio}
      aria-label={esVacio ? undefined : servicio}
    >
      {siglas}
    </abbr>
  );
}

function Leyenda() {
  return (
    <div className="historial__leyenda" aria-label="Significado de los estados">
      <span><i className="historial__leyenda-marca historial__leyenda-marca--recibida" /> Recibió</span>
      <span><i className="historial__leyenda-marca historial__leyenda-marca--no-recibida" /> No recibió</span>
      <span><i className="historial__leyenda-marca historial__leyenda-marca--pendiente" /> Pendiente</span>
      <span><i className="historial__leyenda-marca historial__leyenda-marca--no-aplica">—</i> No aplica</span>
    </div>
  );
}

function NombrePersona({ persona }) {
  return (
    <span className="historial__persona">
      <strong>{persona.nombre}</strong>
      <small>{persona.legajo}{persona.turno ? ` · Turno ${persona.turno}` : ''}</small>
    </span>
  );
}

function TotalTurno({ comidas }) {
  const asignadas = comidas.filter((comida) => comida.aplica);
  const recibidas = asignadas.filter((comida) => comida.estado === true).length;

  return (
    <span className="historial__total" data-tooltip={`${asignadas.length} comidas asignadas al turno`}>
      <strong>{recibidas}/{asignadas.length}</strong>
      <small>del turno</small>
    </span>
  );
}

function FilaSinResultados({ columnas }) {
  return (
    <tr className="historial__sin-resultados">
      <td colSpan={columnas}>No hay usuarios que coincidan con estos filtros.</td>
    </tr>
  );
}

function TablaDiaria({ registros, comidas }) {
  return (
    <div className="historial__tabla-caja">
      <table className="historial__tabla historial__tabla--diaria">
        <caption className="solo-lectores">Historial diario de comidas por usuario</caption>
        <thead>
          <tr>
            <th scope="col">Nombre</th>
            <th scope="col">Categoría</th>
            <th scope="col">Servicio</th>
            {comidas.map((comida) => <th key={comida.id} scope="col">{comida.etiqueta}</th>)}
            <th scope="col">Total turno</th>
          </tr>
        </thead>
        <tbody>
          {registros.length === 0 ? <FilaSinResultados columnas={comidas.length + 4} /> : registros.map((registro) => (
            <tr key={registro.id}>
              <th scope="row"><NombrePersona persona={registro} /></th>
              <td><Categoria categoria={registro.categoria} /></td>
              <td><Servicio servicio={registro.servicio} /></td>
              {registro.comidas.map((comida) => (
                <td key={comida.id}><EstadoComida comida={comida} /></td>
              ))}
              <td><TotalTurno comidas={registro.comidas} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TablaResumenMensual({ registros, comidas }) {
  return (
    <div className="historial__tabla-caja">
      <table className="historial__tabla historial__tabla--mensual">
        <caption className="solo-lectores">Resumen mensual de comidas por usuario</caption>
        <thead>
          <tr>
            <th scope="col">Nombre</th>
            <th scope="col">Categoría</th>
            <th scope="col">Servicio</th>
            {comidas.map((comida) => <th key={comida.id} scope="col">{comida.etiqueta}</th>)}
            <th scope="col">Total turno</th>
          </tr>
        </thead>
        <tbody>
          {registros.length === 0 ? <FilaSinResultados columnas={comidas.length + 4} /> : registros.map((registro) => (
            <tr key={registro.id}>
              <th scope="row"><NombrePersona persona={registro} /></th>
              <td><Categoria categoria={registro.categoria} /></td>
              <td><Servicio servicio={registro.servicio} /></td>
              {registro.totales.map((comida) => (
                <td key={comida.id}>
                  {comida.asignadas > 0 ? (
                    <span className="historial__conteo">
                      <strong>{comida.recibidas}</strong>
                      <small>/{comida.asignadas}</small>
                    </span>
                  ) : (
                    <span className="historial__conteo historial__conteo--no-aplica" data-tooltip="No corresponde al turno">—</span>
                  )}
                </td>
              ))}
              <td>
                <span className="historial__total" data-tooltip="Total de comidas asignadas en el mes">
                  <strong>{registro.totalRecibidas}/{registro.totalAsignadas}</strong>
                  <small>del turno</small>
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function HistorialComidas({ hoy }) {
  const [alcance, setAlcance] = useState('diario');
  const [fecha, setFecha] = useState(() => valorFecha(hoy));
  const [mes, setMes] = useState(() => valorMes(hoy));
  const [filtros, setFiltros] = useState({
    nombre: '',
    categoria: 'todas',
    servicio: 'todas',
    estado: 'todos',
  });
  /* Paginación local, sobre los registros ya filtrados del período completo. */
  const [tamanoPagina, setTamanoPagina] = useState(10);
  const [paginaActual, setPaginaActual] = useState(1);

  const fechaSeleccionada = useMemo(() => fechaDesdeValor(fecha), [fecha]);
  const periodo = useMemo(() => periodoDesdeValor(mes), [mes]);
  const fechaDelPeriodo = useMemo(
    () => new Date(periodo.gestion, periodo.mesIndice, 1, 12),
    [periodo],
  );

  const consultar = useCallback((signal) => alcance === 'diario'
    ? reunirHistorialCompleto(obtenerHistorialDiarioPersonal, { fecha }, signal)
    : reunirHistorialCompleto(obtenerHistorialMensualPersonal, periodo, signal),
  [alcance, fecha, periodo]);
  const { datos: pagina, cargando, error, recargar } = useConsultaApi(consultar);
  const registros = pagina?.datos ?? [];
  const categorias = [...new Set(registros.map((persona) => persona.categoria))].sort();
  const servicios = [...new Set(registros.map((persona) => persona.servicio))].sort();
  const diario = alcance === 'diario' ? registros : [];
  const mensual = alcance === 'mensual' ? registros : [];
  const diarioFiltrado = filtrarRegistros(diario, 'diario', filtros);
  const mensualFiltrado = filtrarRegistros(mensual, 'mensual', filtros);
  const registrosFiltrados = alcance === 'diario' ? diarioFiltrado : mensualFiltrado;

  const comidasDiarias = diarioFiltrado.flatMap((registro) => registro.comidas).filter((comida) => comida.aplica);
  const recibidasDiarias = comidasDiarias.filter((comida) => comida.estado === true).length;
  const noRecibidasDiarias = comidasDiarias.filter((comida) => comida.estado === false).length;
  const pendientesDiarias = comidasDiarias.filter((comida) => comida.estado === null).length;

  const totalRegistros = registrosFiltrados.length;
  const totalPaginas = Math.max(1, Math.ceil(totalRegistros / tamanoPagina));
  const paginaSegura = Math.min(paginaActual, totalPaginas);
  const filasVisibles = registrosFiltrados.slice(
    (paginaSegura - 1) * tamanoPagina,
    paginaSegura * tamanoPagina,
  );
  const inicioRango = totalRegistros === 0 ? 0 : (paginaSegura - 1) * tamanoPagina + 1;
  const finRango = Math.min(paginaSegura * tamanoPagina, totalRegistros);

  function cambiarFiltro(campo, valor) {
    setFiltros((actuales) => ({ ...actuales, [campo]: valor }));
    setPaginaActual(1);
  }

  function cambiarPeriodo(cambiar, valor) {
    setPaginaActual(1);
    setFiltros({ nombre: '', categoria: 'todas', servicio: 'todas', estado: 'todos' });
    cambiar(valor);
  }

  return (
    <section className="historial-comidas">
      <header className="historial__barra">
        <div className="historial__alcances" role="group" aria-label="Período del historial">
          <button
            type="button"
            className={alcance === 'diario' ? 'historial__alcance historial__alcance--activo' : 'historial__alcance'}
            aria-pressed={alcance === 'diario'}
            onClick={() => cambiarPeriodo(setAlcance, 'diario')}
          >
            Diario
          </button>
          <button
            type="button"
            className={alcance === 'mensual' ? 'historial__alcance historial__alcance--activo' : 'historial__alcance'}
            aria-pressed={alcance === 'mensual'}
            onClick={() => cambiarPeriodo(setAlcance, 'mensual')}
          >
            Mensual
          </button>
        </div>

        <SelectorCalendario
          key={alcance}
          alcance={alcance}
          fecha={fecha}
          mes={mes}
          hoy={hoy}
          onFecha={(valor) => cambiarPeriodo(setFecha, valor)}
          onMes={(valor) => cambiarPeriodo(setMes, valor)}
        />
      </header>

      <FiltrosHistorial
        filtros={filtros}
        categorias={categorias}
        servicios={servicios}
        onCambiar={cambiarFiltro}
      />
      {cargando ? <p role="status">Cargando historial…</p> : null}
      {error ? <p role="alert">{error} <Boton variante="secundario" onClick={recargar}>Reintentar historial</Boton></p> : null}

      {pagina ? <><div className="historial__resumen">
        <div>
          <strong>{alcance === 'diario' ? FORMATO_FECHA.format(fechaSeleccionada) : FORMATO_MES.format(fechaDelPeriodo)}</strong>
          <span>
            {alcance === 'diario'
              ? `${diarioFiltrado.length} usuarios · ${recibidasDiarias} recibidas · ${noRecibidasDiarias} no recibidas · ${pendientesDiarias} pendientes`
              : `${mensualFiltrado.length} de ${mensual.length} usuarios · Acumulado según las comidas asignadas al turno`}
          </span>
        </div>
        <Leyenda />
      </div>

      {pagina.total === 0 ? <p role="status">No hay registros de comidas para este período.</p> : (
        <div className="historial__tabla-envoltura">
          {alcance === 'diario'
            ? <TablaDiaria registros={filasVisibles} comidas={pagina.comidas} />
            : <TablaResumenMensual registros={filasVisibles} comidas={pagina.comidas} />}

          {totalRegistros > 0 ? (
            <div className="table-pagination">
              <label className="table-pagination-size">
                <span>Mostrar</span>
                <select
                  value={tamanoPagina}
                  onChange={(evento) => {
                    setTamanoPagina(Number(evento.target.value));
                    setPaginaActual(1);
                  }}
                >
                  <option value={10}>10 filas</option>
                  <option value={25}>25 filas</option>
                  <option value={50}>50 filas</option>
                </select>
              </label>

              <span className="table-pagination-range">
                Mostrando {inicioRango}–{finRango} de {totalRegistros} comensales
              </span>

              <div className="table-pagination-nav">
                <button
                  type="button"
                  className="boton-paginacion"
                  disabled={paginaSegura <= 1}
                  onClick={() => setPaginaActual((p) => Math.max(1, p - 1))}
                >
                  Anterior
                </button>
                <span className="table-pagination-pagina">
                  Página {paginaSegura} de {totalPaginas}
                </span>
                <button
                  type="button"
                  className="boton-paginacion"
                  disabled={paginaSegura >= totalPaginas}
                  onClick={() => setPaginaActual((p) => Math.min(totalPaginas, p + 1))}
                >
                  Siguiente
                </button>
              </div>
            </div>
          ) : null}
        </div>
      )}</> : null}
    </section>
  );
}
