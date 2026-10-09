import { useEffect, useRef, useState } from 'react';
import Boton from '../ui/Boton.jsx';
import Etiqueta from '../ui/Etiqueta.jsx';
import Tarjeta from '../ui/Tarjeta.jsx';
import { IconoRecargar } from '../ui/Iconos.jsx';
import { obtenerEstadoMonitoreo } from '../../api.js';
import {
  MS_REEVALUAR_VIGENCIA,
  estadoDeVista,
  medirAhora,
  programarRefrescoMonitoreo,
  textoFechaHoraServidor,
  textoFechaServidor,
  textoHoraLocal,
} from '../../monitoreo.js';
import './SaludSistema.css';

const ENTORNOS = { produccion: 'Producción', desarrollo: 'Desarrollo', simulacion: 'Simulación' };
const MOTIVOS = {
  duplicado: 'duplicado',
  sin_derecho: 'sin derecho',
  fuera_horario: 'fuera de horario',
  no_identificado: 'no identificado',
};

/*
 * Lo que anuncia la región viva: solo cambia cuando cambia el estado, nunca
 * con la hora, para que el lector de pantalla no repita cada refresco.
 */
const RESUMENES = {
  cargando: { tono: 'neutro', etiqueta: 'Consultando', texto: 'Consultando el diagnóstico del sistema…' },
  vigente: {
    tono: 'exito',
    etiqueta: 'Diagnóstico actualizado',
    texto: 'Revise cada componente: este diagnóstico no garantiza que todo funcione.',
  },
  antiguo: {
    tono: 'aviso',
    etiqueta: 'Datos antiguos',
    texto: 'No hay un diagnóstico reciente: lo que se ve puede no reflejar el estado actual.',
  },
  revalidando: {
    tono: 'aviso',
    etiqueta: 'Revalidando',
    texto: 'Volvió a esta pestaña: se pide un diagnóstico nuevo. Lo que se ve es anterior.',
  },
  'fallo-con-datos': {
    tono: 'error',
    etiqueta: 'No se pudo actualizar',
    texto: 'Se muestran los datos anteriores; pueden no reflejar el estado actual.',
  },
  'sin-diagnostico': {
    tono: 'error',
    etiqueta: 'Diagnóstico no disponible',
    texto: 'No se pudo obtener el diagnóstico del sistema.',
  },
};

/**
 * Sección «Salud del sistema» (solo sistemas): GET /monitoreo/estado cada
 * 30 s después de terminar la consulta anterior, en pausa con la pestaña
 * oculta. La vigencia se recalcula con los relojes del equipo.
 */
export default function SaludSistema({ consultar = obtenerEstadoMonitoreo }) {
  const [diagnostico, setDiagnostico] = useState(null);
  const [recepcion, setRecepcion] = useState(null);
  const [error, setError] = useState('');
  const [consultando, setConsultando] = useState(true);
  const [pendiente, setPendiente] = useState(false);
  const [, setPulso] = useState(0);
  const refresco = useRef(null);

  useEffect(() => {
    const control = programarRefrescoMonitoreo({
      consultar: async ({ signal }) => {
        setConsultando(true);
        try {
          const datos = await consultar({ signal });
          if (signal.aborted) return;
          setDiagnostico(datos);
          setRecepcion(medirAhora());
          setError('');
          setPendiente(false);
        } catch (fallo) {
          if (!signal.aborted) setError(fallo.message);
        } finally {
          if (!signal.aborted) setConsultando(false);
        }
      },
      alVolver: () => setPendiente(true),
    });
    refresco.current = control;
    /* Solo dispara un nuevo cálculo de la vigencia; la vigencia sale de los relojes. */
    const pulso = setInterval(() => setPulso((vuelta) => vuelta + 1), MS_REEVALUAR_VIGENCIA);
    return () => {
      control.cancelar();
      clearInterval(pulso);
      refresco.current = null;
    };
  }, [consultar]);

  return (
    <VistaSaludSistema
      diagnostico={diagnostico}
      recepcion={recepcion}
      error={error}
      consultando={consultando}
      estado={estadoDeVista({ diagnostico, recepcion, error, pendiente })}
      onActualizar={() => refresco.current?.actualizar()}
    />
  );
}

/** Presentación pura de la sección, para renderizarla con datos sintéticos. */
export function VistaSaludSistema({ diagnostico, recepcion, error, consultando, estado, onActualizar }) {
  const resumen = RESUMENES[estado] ?? RESUMENES.cargando;
  const vigente = estado === 'vigente';

  return (
    <div className="salud" aria-busy={consultando ? 'true' : 'false'}>
      <div className="salud__barra">
        <div className="salud__resumen">
          <p className="salud__resumen-estado" role="status">
            <Etiqueta tono={resumen.tono}>{resumen.etiqueta}</Etiqueta>
            <span>{resumen.texto}</span>
          </p>
          {recepcion ? (
            <p className="salud__resumen-hora">
              Último diagnóstico recibido en este equipo a las {textoHoraLocal(recepcion.pared)}.
              Se actualiza cada 30 s mientras esta pestaña está visible.
            </p>
          ) : null}
        </div>
        {/* aria-disabled y no disabled: el refresco automático no debe quitarle
            el foco a quien está sobre el botón. Pulsarlo durante una consulta
            se une a ella, sin lanzar otra. */}
        <Boton
          variante="secundario"
          icono={<IconoRecargar />}
          onClick={onActualizar}
          aria-disabled={consultando ? 'true' : 'false'}
        >
          {consultando ? 'Actualizando diagnóstico…' : 'Actualizar diagnóstico'}
        </Boton>
      </div>

      {error ? (
        <div className={`salud__alerta salud__alerta--${diagnostico ? 'aviso' : 'error'}`} role="alert">
          <p className="salud__alerta-titulo">
            {diagnostico
              ? 'No se pudo actualizar el diagnóstico.'
              : 'No se pudo obtener el diagnóstico.'}
          </p>
          <p>Con este error no es posible saber qué componente falló.</p>
          <p className="salud__alerta-detalle">{error}</p>
        </div>
      ) : null}

      {diagnostico?.entorno === 'simulacion' ? (
        <aside className="salud__simulacion" role="note">
          <Etiqueta tono="aviso">Entorno de simulación</Etiqueta>
          <span>
            La API corre en el entorno de simulación. Esto no indica si hay o no un lector
            físico; el estado del reloj de negocio se describe aparte.
          </span>
        </aside>
      ) : null}

      <div className="salud__rejilla">
        {diagnostico ? (
          <>
            <TarjetaApi diagnostico={diagnostico} recepcion={recepcion} vigente={vigente} />
            <TarjetaReloj reloj={diagnostico.relojNegocio} />
            <TarjetaBase base={diagnostico.base} vigente={vigente} />
            <TarjetaActividad actividad={diagnostico.actividad} fecha={diagnostico.relojNegocio.fecha} />
            <TarjetaLector />
          </>
        ) : null}
        <Tarjeta titulo="Grafana" accesorio={<Etiqueta tono="neutro">Integración pendiente</Etiqueta>}>
          <p className="salud__texto">
            La conexión con Grafana se definirá cuando se conozca la infraestructura.
          </p>
        </Tarjeta>
      </div>
    </div>
  );
}

function Dato({ termino, children }) {
  return (
    <div className="salud__dato">
      <dt>{termino}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function TarjetaApi({ diagnostico, recepcion, vigente }) {
  return (
    <Tarjeta
      titulo="API"
      accesorio={vigente
        ? <Etiqueta tono="exito">Respondió</Etiqueta>
        : <Etiqueta tono="neutro">Respuesta anterior</Etiqueta>}
    >
      <dl className="salud__datos">
        <Dato termino="Entorno">{ENTORNOS[diagnostico.entorno]}</Dato>
        <Dato termino="Hora del servidor al generar el diagnóstico">
          {textoFechaHoraServidor(diagnostico.momentoReal)} (sin zona horaria informada)
        </Dato>
        <Dato termino="Recibido en este equipo">
          {recepcion ? textoHoraLocal(recepcion.pared) : '—'} (reloj de este equipo)
        </Dato>
      </dl>
    </Tarjeta>
  );
}

function TarjetaReloj({ reloj }) {
  return (
    <Tarjeta
      titulo="Reloj de negocio"
      accesorio={reloj.simulado
        ? <Etiqueta tono="aviso">Reloj simulado</Etiqueta>
        : <Etiqueta tono="neutro">Reloj real</Etiqueta>}
    >
      <dl className="salud__datos">
        <Dato termino="Hora de negocio">{textoFechaHoraServidor(reloj.ahora)}</Dato>
        <Dato termino="Fecha de negocio">{textoFechaServidor(reloj.fecha)}</Dato>
        <Dato termino="Reloj">
          {reloj.simulado ? 'Simulado' : 'Real'}, {reloj.congelado ? 'congelado' : 'en marcha'}
        </Dato>
      </dl>
      <p className="salud__nota">
        La hora de negocio no se usa para medir la antigüedad de este diagnóstico.
      </p>
    </Tarjeta>
  );
}

function TarjetaBase({ base, vigente }) {
  const completa = base.estado === 'ok';
  let etiqueta = <Etiqueta tono="aviso">Esquema incompleto</Etiqueta>;
  if (completa) {
    etiqueta = vigente
      ? <Etiqueta tono="exito">Presentes en el catálogo</Etiqueta>
      : <Etiqueta tono="neutro">Presentes en el catálogo (dato anterior)</Etiqueta>;
  }
  return (
    <Tarjeta titulo="Catálogo de la base" accesorio={etiqueta}>
      {completa ? null : (
        <div className="salud__faltan">
          <p className="salud__texto">
            {base.faltan.length > 0
              ? 'Faltan en el catálogo:'
              : 'El servidor indica que el esquema está incompleto, sin detallar qué falta.'}
          </p>
          {base.faltan.length > 0 ? (
            <ul>
              {base.faltan.map((nombre) => <li key={nombre}><code>{nombre}</code></li>)}
            </ul>
          ) : null}
          <p className="salud__texto">
            Los datos que dependen de lo que falta no están disponibles; no son cero.
          </p>
        </div>
      )}
      <dl className="salud__datos">
        <Dato termino="Tablas propias">{base.tablasPropias}</Dato>
        <Dato termino="Vistas de contrato">{base.vistasContrato}</Dato>
        <Dato termino="Revisión de migración registrada">
          {base.revisionAlembic === null ? 'Sin revisión registrada' : <code>{base.revisionAlembic}</code>}
        </Dato>
      </dl>
      <p className="salud__nota">
        Solo se comprueba su presencia en el catálogo: no se validan columnas, contenido,
        funcionamiento ni que la migración esté al día.
      </p>
    </Tarjeta>
  );
}

function TarjetaActividad({ actividad, fecha }) {
  const fechaTexto = textoFechaServidor(fecha);
  if (!actividad.disponible) {
    return (
      <Tarjeta titulo="Actividad del día" accesorio={<Etiqueta tono="aviso">No disponible</Etiqueta>}>
        <p className="salud__texto">
          {actividad.razon === 'tabla_ausente'
            ? 'La tabla de lecturas no existe en la base, así que la actividad no se puede consultar.'
            : 'La consulta de actividad falló.'}
          {' '}Los contadores no están disponibles (no son cero).
        </p>
        <dl className="salud__datos">
          <Dato termino="Fecha de negocio">{fechaTexto}</Dato>
          <Dato termino="Lecturas aceptadas">No disponible</Dato>
          <Dato termino="Lecturas rechazadas">No disponible</Dato>
        </dl>
      </Tarjeta>
    );
  }

  const registro = actividad.registroMayorId;
  const sinLecturasHoy = actividad.aceptadasDia === 0 && actividad.rechazadasDia === 0;
  return (
    <Tarjeta titulo="Actividad del día" accesorio={<Etiqueta tono="neutro">Consultada</Etiqueta>}>
      {sinLecturasHoy ? (
        <p className="salud__texto">
          {registro === null
            ? 'La tabla de lecturas está vacía.'
            : `No hay lecturas en la fecha de negocio ${fechaTexto}.`}
        </p>
      ) : null}
      <dl className="salud__datos">
        <Dato termino="Fecha de negocio">{fechaTexto}</Dato>
        <Dato termino="Lecturas aceptadas">{actividad.aceptadasDia}</Dato>
        <Dato termino="Lecturas rechazadas">{actividad.rechazadasDia}</Dato>
        {registro ? (
          <Dato termino="Registro con el id más alto">
            N.º {registro.id}: {registro.resultado === 'aceptada' ? 'aceptada' : 'rechazada'}
            {registro.motivo ? ` (${MOTIVOS[registro.motivo]})` : ''}; hora de negocio{' '}
            {textoFechaHoraServidor(registro.fechaHora)}; guardado en la base{' '}
            {textoFechaHoraServidor(registro.createdAt)}
          </Dato>
        ) : null}
      </dl>
      <p className="salud__nota">
        El registro con el id más alto no es necesariamente la última huella apoyada en el
        lector. Tener lecturas no prueba que el lector esté conectado.
      </p>
    </Tarjeta>
  );
}

function TarjetaLector() {
  return (
    <Tarjeta titulo="Lector biométrico" accesorio={<Etiqueta tono="neutro">Sin telemetría de conexión</Etiqueta>}>
      <dl className="salud__datos">
        <Dato termino="Estado">Desconocido</Dato>
      </dl>
      <p className="salud__texto">
        El sistema todavía no recibe señales del lector, así que no puede saber si está conectado.
      </p>
    </Tarjeta>
  );
}
