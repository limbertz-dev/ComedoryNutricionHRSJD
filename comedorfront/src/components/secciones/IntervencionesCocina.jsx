import { useEffect, useState } from 'react';
import Boton from '../ui/Boton.jsx';
import Etiqueta from '../ui/Etiqueta.jsx';
import { obtenerIntervencionesCocina } from '../../api.js';
import { diaLegible } from '../../dias.js';
import './IntervencionesCocina.css';

/** Filas por página: el máximo que el servidor admite es 100. */
export const LIMITE_INTERVENCIONES = 50;

const FILTROS = [
  ['todas', 'Todas'],
  ['registrada', 'Entregas registradas'],
  ['rechazada', 'Intentos rechazados'],
];

/** Por qué un intento no terminó en entrega, en palabras de la jefa. */
export const MOTIVOS_RECHAZO_INTERVENCION = {
  sin_derecho: 'Sin derecho en este turno',
  duplicado: 'Ya había recibido su comida',
  lectura_ya_resuelta: 'La huella ya tenía una entrega',
  lectura_no_resoluble: 'La lectura no era identificable',
  servicio_distinto: 'La huella era de otro servicio',
  servicio_no_determinable: 'No se pudo determinar el servicio',
  reloj_inconsistente: 'Reloj del servidor inconsistente',
};

const DECISIONES_LECTOR = {
  no_identificado: 'Huella no reconocida',
};

/** "HH:MM:SS" de una fecha y hora del servidor; '—' si no la trae. */
function horaLarga(texto) {
  const coincidencia = typeof texto === 'string' ? /T(\d{2}:\d{2}(?::\d{2})?)/.exec(texto) : null;
  return coincidencia ? coincidencia[1] : '—';
}

/** "27/09" de "2026-09-27". */
function diaCorto(valor) {
  const coincidencia = typeof valor === 'string' ? /^\d{4}-(\d{2})-(\d{2})/.exec(valor) : null;
  return coincidencia ? `${coincidencia[2]}/${coincidencia[1]}` : '';
}

/** Texto de la decisión original del lector, que ninguna intervención cambia. */
export function textoDecisionOriginal(decision) {
  const resultado = decision?.resultado === 'aceptada' ? 'Aceptada' : 'Rechazada';
  const motivo = DECISIONES_LECTOR[decision?.motivo] ?? decision?.motivo ?? null;
  return [resultado, motivo].filter(Boolean).join(' · ');
}

/**
 * Intervenciones de cocina (solo jefa, solo consulta).
 *
 * Por cada intento de la cocinera sobre una huella no reconocida: persona,
 * comida, momento, cocinera responsable, decisión original del lector y
 * resultado final. Sin botones de aprobación ni acciones: la entrega la
 * decide la cocinera frente al lector y el servidor la valida. Los registros
 * manuales independientes de jefatura no aparecen aquí.
 *
 * `comidaId` acota a la pestaña activa de Supervisión (null: todo el día) y
 * `version` cambia con cada refresco de la sección. `inicial` reemplaza la
 * consulta (para las pruebas): `{ pagina }` o `{ error }`.
 */
export default function IntervencionesCocina({
  fecha,
  comidaId = null,
  comida = null,
  version = 0,
  inicial = undefined,
  consultar = obtenerIntervencionesCocina,
}) {
  const conInicial = inicial !== undefined;
  const [filtro, setFiltro] = useState('todas');
  const [desplazamiento, setDesplazamiento] = useState(0);
  const [pagina, setPagina] = useState(conInicial ? inicial.pagina ?? null : null);
  const [error, setError] = useState(conInicial ? inicial.error ?? '' : '');
  const [cargando, setCargando] = useState(!conInicial);

  /* Otro filtro vuelve a la primera página. Otra comida remonta el
     componente (Supervisión le pone `key`), así que también. */
  function elegirFiltro(valor) {
    setFiltro(valor);
    setDesplazamiento(0);
  }

  useEffect(() => {
    if (conInicial) return undefined;
    const controlador = new AbortController();
    setCargando(true);
    consultar({
      desde: fecha ?? null,
      hasta: fecha ?? null,
      comidaId,
      resultado: filtro === 'todas' ? null : filtro,
      limite: LIMITE_INTERVENCIONES,
      desplazamiento,
      signal: controlador.signal,
    })
      .then((respuesta) => {
        if (controlador.signal.aborted) return;
        setPagina(respuesta);
        setError('');
      })
      .catch((fallo) => {
        if (!controlador.signal.aborted) setError(fallo.message);
      })
      .finally(() => {
        if (!controlador.signal.aborted) setCargando(false);
      });
    return () => controlador.abort();
  }, [conInicial, consultar, fecha, comidaId, filtro, desplazamiento, version]);

  const datos = pagina?.datos ?? [];
  const dia = diaLegible(pagina?.desde ?? (typeof fecha === 'string' ? fecha : null));
  const periodo = [comida ?? 'Todas las comidas', dia].filter(Boolean).join(' · ');
  const desdeFila = pagina && pagina.total > 0 ? pagina.desplazamiento + 1 : 0;
  const hastaFila = pagina ? pagina.desplazamiento + datos.length : 0;

  return (
    <section className="intervenciones" aria-label="Intervenciones de cocina">
      <header className="intervenciones__cabecera">
        <div className="intervenciones__titulos">
          <h2 className="intervenciones__titulo">Intervenciones de cocina</h2>
          <p className="intervenciones__periodo">{periodo}</p>
        </div>
        {pagina ? (
          <ul className="intervenciones__totales" aria-label="Totales del período">
            <li><Etiqueta tono="exito">{`Entregas registradas ${pagina.totales.registradas}`}</Etiqueta></li>
            <li><Etiqueta tono="error">{`Intentos rechazados ${pagina.totales.rechazadas}`}</Etiqueta></li>
          </ul>
        ) : null}
      </header>

      <p className="intervenciones__nota">
        Huellas que el lector no reconoció y que cocina identificó frente al lector. Es una
        consulta: la entrega la confirma la cocinera y la valida el servidor.
      </p>

      <div className="intervenciones__filtros" role="tablist" aria-label="Filtrar intervenciones por resultado">
        {FILTROS.map(([valor, etiqueta]) => (
          <button
            key={valor}
            type="button"
            role="tab"
            aria-selected={filtro === valor}
            className={`intervenciones__chip${filtro === valor ? ' intervenciones__chip--activo' : ''}`}
            onClick={() => elegirFiltro(valor)}
          >
            {etiqueta}
          </button>
        ))}
      </div>

      {error ? (
        <p className="intervenciones__estado intervenciones__estado--error" role="alert">
          {pagina ? 'Sin actualizar: se muestran los datos anteriores. ' : ''}{error}
        </p>
      ) : null}

      {!pagina && !error && cargando ? (
        <p className="intervenciones__estado" role="status">Cargando intervenciones de cocina…</p>
      ) : null}

      {pagina && datos.length === 0 ? (
        <p className="intervenciones__estado" role="status">
          {filtro === 'todas'
            ? 'No hubo intervenciones de cocina en este período.'
            : 'No hay intervenciones con ese resultado en este período.'}
        </p>
      ) : null}

      {datos.length > 0 ? (
        <div className="intervenciones__tabla-caja">
          <table className="intervenciones__tabla" aria-label="Intervenciones de cocina">
            <thead>
              <tr>
                <th scope="col">Momento</th>
                <th scope="col">Persona</th>
                <th scope="col">Comida</th>
                <th scope="col">Cocinera</th>
                <th scope="col">Decisión original</th>
                <th scope="col">Resultado final</th>
              </tr>
            </thead>
            <tbody>
              {datos.map((intervencion) => (
                <FilaIntervencion key={intervencion.clave} intervencion={intervencion} diaPagina={pagina.desde} />
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {pagina && pagina.total > datos.length ? (
        <nav className="intervenciones__paginas" aria-label="Páginas de intervenciones">
          <span className="intervenciones__rango">{`${desdeFila}–${hastaFila} de ${pagina.total}`}</span>
          <Boton
            variante="secundario"
            tamano="sm"
            disabled={cargando || pagina.desplazamiento === 0}
            onClick={() => setDesplazamiento(Math.max(0, pagina.desplazamiento - LIMITE_INTERVENCIONES))}
          >
            Anterior
          </Boton>
          <Boton
            variante="secundario"
            tamano="sm"
            disabled={cargando || hastaFila >= pagina.total}
            onClick={() => setDesplazamiento(pagina.desplazamiento + LIMITE_INTERVENCIONES)}
          >
            Siguiente
          </Boton>
        </nav>
      ) : null}
    </section>
  );
}

/** Una intervención, solo lectura: ningún control de aprobación. */
function FilaIntervencion({ intervencion, diaPagina }) {
  const { comensal, cuenta, servicio, decisionOriginal } = intervencion;
  const otroDia = servicio.fechaComida && servicio.fechaComida !== diaPagina;
  const registrada = intervencion.entregaRegistrada;
  return (
    <tr className={registrada ? undefined : 'intervenciones__fila--rechazada'}>
      <td className="intervenciones__hora">{horaLarga(intervencion.momento)}</td>
      <td>
        <span className="intervenciones__principal">{comensal.nombre ?? `Comensal ${comensal.usuarioId}`}</span>
        {comensal.categoria ? <span className="intervenciones__sub">{comensal.categoria}</span> : null}
      </td>
      <td>
        <span className="intervenciones__principal">{servicio.comida ?? '—'}</span>
        {otroDia ? <span className="intervenciones__sub">{`Servicio del ${diaCorto(servicio.fechaComida)}`}</span> : null}
      </td>
      <td>
        <span className="intervenciones__principal">{cuenta.nombre ?? cuenta.usuario}</span>
        {cuenta.nombre ? <span className="intervenciones__sub">{cuenta.usuario}</span> : null}
      </td>
      <td>
        <span className="intervenciones__principal">{textoDecisionOriginal(decisionOriginal)}</span>
        <span className="intervenciones__sub">
          {[`Lector ${horaLarga(decisionOriginal.fechaHora)}`, decisionOriginal.dispositivo].filter(Boolean).join(' · ')}
        </span>
      </td>
      <td>
        <Etiqueta tono={registrada ? 'exito' : 'error'}>
          {registrada ? 'Entrega registrada' : 'Intento rechazado'}
        </Etiqueta>
        <span className="intervenciones__sub">
          {registrada
            ? 'La huella quedó resuelta'
            : [
              MOTIVOS_RECHAZO_INTERVENCION[intervencion.motivoRechazo] ?? intervencion.motivoRechazo,
              intervencion.lecturaResuelta ? 'la huella se resolvió en otro intento' : 'la huella sigue sin entrega',
            ].filter(Boolean).join(' · ')}
        </span>
      </td>
    </tr>
  );
}
