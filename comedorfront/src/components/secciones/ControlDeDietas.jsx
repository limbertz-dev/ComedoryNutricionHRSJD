import { useCallback, useMemo, useState } from 'react';
import { guardarRacionesDia, obtenerRacionesDia } from '../../api.js';
import useConsultaApi from '../../hooks/useConsultaApi.js';
import Boton from '../ui/Boton.jsx';
import Etiqueta from '../ui/Etiqueta.jsx';
import TablaPlanilla from '../ui/TablaPlanilla.jsx';
import SelectorCalendario, { valorFecha } from './SelectorCalendario.jsx';
import './ControlDeDietas.css';

/*
 * Control de Dietas — planilla del día de raciones por servicio y tipo de dieta.
 *
 * Misma cuadrícula y jerarquía visual que el reporte de distribución de pacientes.
 * Las celdas son editables con recálculo en vivo de los totales por fila y columna.
 * El botón Guardar envía únicamente las celdas cuyos valores hayan sido modificados.
 */

/** Hora legible de la última actualización (HH:MM). */
function formatearHoraActualizado(iso) {
  if (!iso || typeof iso !== 'string') return null;
  try {
    const fecha = new Date(iso);
    if (!isNaN(fecha.getTime())) {
      return fecha.toLocaleTimeString('es-BO', { hour: '2-digit', minute: '2-digit' });
    }
  } catch {
    // fallback a corte de texto
  }
  const parte = iso.includes('T') ? iso.split('T')[1] : iso;
  return parte.slice(0, 5);
}

export default function ControlDeDietas() {
  const [hoy] = useState(() => new Date());
  const [fecha, setFecha] = useState(() => valorFecha(hoy));
  const [guardando, setGuardando] = useState(false);
  const [errorGuardar, setErrorGuardar] = useState(null);
  const [guardadoExito, setGuardadoExito] = useState(false);

  const consultar = useCallback(
    (signal) => obtenerRacionesDia({ fecha, signal }),
    [fecha],
  );
  const { datos: matriz, cargando, error, recargar } = useConsultaApi(consultar);

  // Estados locales para la matriz editable
  const [valoresOriginales, setValoresOriginales] = useState(null);
  const [valoresLocales, setValoresLocales] = useState(null);
  const [actualizadoTimestamp, setActualizadoTimestamp] = useState(null);
  const [ultimoMatrizCargado, setUltimoMatrizCargado] = useState(null);

  // Al llegar nuevos datos del servidor, inicializar valores locales si es una respuesta nueva
  if (matriz && matriz !== ultimoMatrizCargado) {
    const orig = {};
    const loc = {};
    for (const fila of matriz.filas) {
      orig[fila.codigo] = {};
      loc[fila.codigo] = {};
      matriz.columnas.forEach((col, idx) => {
        orig[fila.codigo][col.codigo] = fila.celdas[idx];
        loc[fila.codigo][col.codigo] = fila.celdas[idx];
      });
    }
    setValoresOriginales(orig);
    setValoresLocales(loc);
    setActualizadoTimestamp(matriz.actualizado);
    setUltimoMatrizCargado(matriz);
    setGuardadoExito(false);
    setErrorGuardar(null);
  }

  function manejarCambioCelda(filaCodigo, colCodigo, valorRaw) {
    setGuardadoExito(false);
    setErrorGuardar(null);
    let cantidad;
    if (valorRaw === '' || valorRaw === null || valorRaw === undefined) {
      cantidad = '';
    } else {
      const entero = parseInt(valorRaw, 10);
      cantidad = isNaN(entero) || entero < 0 ? 0 : entero;
    }
    setValoresLocales((prev) => ({
      ...prev,
      [filaCodigo]: {
        ...prev?.[filaCodigo],
        [colCodigo]: cantidad,
      },
    }));
  }

  // Lista de celdas modificadas que difieren del servidor
  const celdasModificadas = useMemo(() => {
    const lista = [];
    if (!valoresLocales || !valoresOriginales) return lista;
    for (const filaCod of Object.keys(valoresLocales)) {
      for (const colCod of Object.keys(valoresLocales[filaCod] || {})) {
        const actualRaw = valoresLocales[filaCod][colCod];
        const actualNum = actualRaw === '' ? 0 : (parseInt(actualRaw, 10) || 0);
        const origNum = valoresOriginales[filaCod]?.[colCod] ?? 0;
        if (actualNum !== origNum) {
          lista.push({ fila: filaCod, columna: colCod, cantidad: actualNum });
        }
      }
    }
    return lista;
  }, [valoresLocales, valoresOriginales]);

  const hayCambios = celdasModificadas.length > 0;

  const setModificadas = useMemo(
    () => new Set(celdasModificadas.map((c) => `${c.fila}:${c.columna}`)),
    [celdasModificadas],
  );

  const esCeldaModificada = useCallback(
    (fila, col) => setModificadas.has(`${fila}:${col}`),
    [setModificadas],
  );

  // Recálculo en vivo de filas y totales
  const reporteCalculado = useMemo(() => {
    if (!matriz || !valoresLocales) return null;

    const filas = matriz.filas.map((fila) => {
      const celdas = matriz.columnas.map((col) => {
        const val = valoresLocales[fila.codigo]?.[col.codigo];
        return val === '' ? '' : (parseInt(val, 10) || 0);
      });
      const total = celdas.reduce((s, v) => s + (v === '' ? 0 : Number(v)), 0);
      return {
        codigo: fila.codigo,
        etiqueta: fila.etiqueta,
        celdas,
        total,
      };
    });

    const celdasTotal = matriz.columnas.map((_, colIdx) =>
      filas.reduce((s, f) => s + (f.celdas[colIdx] === '' ? 0 : Number(f.celdas[colIdx])), 0),
    );
    const totalGeneral = celdasTotal.reduce((s, v) => s + v, 0);

    return {
      titulo: matriz.titulo,
      primeraColumna: matriz.primeraColumna,
      grupoColumnas: matriz.grupoColumnas,
      columnas: matriz.columnas,
      conTotal: true,
      filas,
      total: {
        etiqueta: 'TOTAL',
        celdas: celdasTotal,
        total: totalGeneral,
      },
      secciones: [],
    };
  }, [matriz, valoresLocales]);

  function cambiarFecha(nuevaFecha) {
    if (nuevaFecha === fecha) return;
    if (hayCambios) {
      const confirmar = window.confirm(
        'Tiene cambios sin guardar en la planilla. ¿Desea descartarlos y cambiar de fecha?',
      );
      if (!confirmar) return;
    }
    setFecha(nuevaFecha);
    setErrorGuardar(null);
    setGuardadoExito(false);
  }

  async function guardar() {
    if (!hayCambios || guardando) return;
    setGuardando(true);
    setErrorGuardar(null);
    setGuardadoExito(false);
    try {
      const actualizada = await guardarRacionesDia({ fecha, celdas: celdasModificadas });
      const orig = {};
      const loc = {};
      for (const f of actualizada.filas) {
        orig[f.codigo] = {};
        loc[f.codigo] = {};
        actualizada.columnas.forEach((col, idx) => {
          orig[f.codigo][col.codigo] = f.celdas[idx];
          loc[f.codigo][col.codigo] = f.celdas[idx];
        });
      }
      setValoresOriginales(orig);
      setValoresLocales(loc);
      setActualizadoTimestamp(actualizada.actualizado);
      setUltimoMatrizCargado(actualizada);
      setGuardadoExito(true);
    } catch (fallo) {
      setErrorGuardar(fallo.message);
    } finally {
      setGuardando(false);
    }
  }

  const horaFormateada = formatearHoraActualizado(actualizadoTimestamp);

  return (
    <article className="control-dietas">
      <header className="control-dietas__cabecera">
        <div className="control-dietas__filtro">
          <span className="control-dietas__filtro-rotulo">Fecha</span>
          <SelectorCalendario
            alcance="diario"
            fecha={fecha}
            mes={fecha.slice(0, 7)}
            hoy={hoy}
            onFecha={cambiarFecha}
            onMes={() => {}}
          />
        </div>

        <div className="control-dietas__acciones">
          {horaFormateada ? (
            <Etiqueta tono="neutro">
              Última actualización: {horaFormateada}
            </Etiqueta>
          ) : (
            <Etiqueta tono="neutro">Sin registros hoy</Etiqueta>
          )}

          {guardadoExito && !hayCambios ? (
            <Etiqueta tono="exito">Guardado</Etiqueta>
          ) : null}

          {hayCambios ? (
            <Etiqueta tono="aviso">
              {celdasModificadas.length} {celdasModificadas.length === 1 ? 'cambio sin guardar' : 'cambios sin guardar'}
            </Etiqueta>
          ) : null}

          <Boton
            variante="primario"
            disabled={!hayCambios || guardando}
            onClick={guardar}
          >
            {guardando ? 'Guardando…' : 'Guardar'}
          </Boton>
        </div>
      </header>

      {cargando ? <p className="control-dietas__estado" role="status">Cargando raciones del día…</p> : null}

      {error ? (
        <div className="control-dietas__error-carga" role="alert">
          <p className="control-dietas__error">{error}</p>
          <Boton variante="secundario" onClick={() => recargar()}>Reintentar</Boton>
        </div>
      ) : null}

      {errorGuardar ? (
        <div className="control-dietas__error-carga" role="alert">
          <p className="control-dietas__error">{errorGuardar}</p>
        </div>
      ) : null}

      {reporteCalculado && !cargando ? (
        <TablaPlanilla
          reporte={reporteCalculado}
          editable={true}
          onCambioCelda={manejarCambioCelda}
          esCeldaModificada={esCeldaModificada}
        />
      ) : null}
    </article>
  );
}
