import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import Boton from '../ui/Boton.jsx';
import Etiqueta from '../ui/Etiqueta.jsx';
import { IconoAlerta, IconoCheck, IconoRecargar, IconoReloj } from '../ui/Iconos.jsx';
import { guardarHorario } from '../../api.js';
import {
  cargarComidas,
  cruzaMedianoche,
  estadoInicialReglas,
  formatoHora,
  guardarComida,
  horasConSegundos,
  motivoSinGuardar,
  nombreDeComida,
  recargarComidas,
  reductorReglas,
  textoMomento,
  valorDeHora,
} from '../../reglasHorarios.js';
import './ReglasSistema.css';

/*
 * Lo que se le dice a quien mira el botón cuando «Guardar cambios» no puede
 * enviar. El botón queda con aria-disabled (no disabled) para no perder el
 * foco en pleno guardado, y este texto lo describe.
 */
const TEXTO_SIN_GUARDAR = {
  guardando: 'Guardando…',
  'otro-envio': 'Espere: se está guardando otra comida.',
  actualizando: 'Actualizando los horarios…',
  incierto: 'Recargue los horarios y compruebe cómo quedaron antes de guardar.',
  recargar: 'Recargue los horarios para seguir editando esta comida.',
  'sin-base': 'No se pudo comprobar la versión abierta de esta comida: recargue los horarios.',
  multiple: 'Esta comida tiene más de una versión abierta: no se puede guardar.',
  incompleto: 'Complete la hora de inicio y la de fin.',
  iguales: 'La hora de inicio y la de fin no pueden ser iguales.',
  'sin-cambios': 'Sin cambios por guardar.',
};

/**
 * Reglas del sistema (solo sistemas): el horario de cada comida.
 *
 * Una tarjeta por comida con su inicio, su fin y «Guardar cambios». El
 * cambio rige desde que se guarda: no hay fecha de vigencia, programación ni
 * motivo. `cargar` y `guardar` se pueden reemplazar para probar la pantalla
 * con respuestas sintéticas.
 */
export default function ReglasSistema({ cargar = cargarComidas, guardar = guardarHorario }) {
  const [estado, despachar] = useReducer(reductorReglas, undefined, estadoInicialReglas);
  const candado = useRef({ ocupado: false });
  const controlador = useRef(null);

  const recargar = useCallback(() => {
    controlador.current?.abort();
    const propio = new AbortController();
    controlador.current = propio;
    return recargarComidas({ despachar, cargar, signal: propio.signal });
  }, [cargar]);

  useEffect(() => {
    recargar();
    return () => controlador.current?.abort();
  }, [recargar]);

  const manejarGuardar = useCallback((comida, borrador) => guardarComida({
    comida, borrador, despachar, recargar, candado: candado.current, guardar,
  }), [recargar, guardar]);

  return (
    <VistaReglas
      estado={estado}
      onRecargar={recargar}
      onGuardar={manejarGuardar}
      onCerrarAviso={(comidaId) => despachar({ tipo: 'AVISO_CERRADO', comidaId })}
    />
  );
}

/** Presentación pura de la pantalla, para renderizarla con estados sintéticos. */
export function VistaReglas({ estado, onRecargar, onGuardar, onCerrarAviso, borradores = {} }) {
  const ocupada = estado.guardando !== null || estado.actualizando;

  return (
    <section className="reglas" aria-busy={estado.actualizando ? 'true' : 'false'}>
      <div className="reglas__intro">
        <span className="reglas__intro-icono" aria-hidden="true"><IconoReloj tamano={26} /></span>
        <div className="reglas__intro-texto">
          <h2 className="reglas__titulo">Horario de cada comida</h2>
          <p className="reglas__nota">
            Cambie la hora de inicio o de fin y pulse «Guardar cambios». El horario nuevo se aplica
            en el momento de guardar: no hay fecha de vigencia ni se programa para más adelante.
          </p>
        </div>
        <Boton
          variante="secundario"
          icono={<IconoRecargar />}
          onClick={() => { if (!ocupada) onRecargar(); }}
          aria-disabled={ocupada ? 'true' : 'false'}
          className="reglas__recargar"
        >
          {estado.actualizando ? 'Actualizando…' : 'Recargar horarios'}
        </Boton>
      </div>

      {estado.incierto ? (
        <div className="reglas__banner reglas__banner--aviso" role="alert">
          <span className="reglas__banner-icono" aria-hidden="true"><IconoAlerta tamano={20} /></span>
          <div className="reglas__banner-texto">
            <strong>Hay un guardado sin comprobar.</strong>
            <p>
              No sabemos si el último cambio quedó guardado. Recargue los horarios y revise cómo
              quedaron antes de guardar otra vez.
            </p>
          </div>
          <Boton
            variante="secundario"
            onClick={() => { if (!ocupada) onRecargar(); }}
            aria-disabled={ocupada ? 'true' : 'false'}
          >
            Recargar y comprobar
          </Boton>
        </div>
      ) : null}

      {estado.fallaRefresco ? (
        <div className="reglas__banner reglas__banner--error" role="alert">
          <span className="reglas__banner-icono" aria-hidden="true"><IconoAlerta tamano={20} /></span>
          <div className="reglas__banner-texto">
            <strong>No se pudieron actualizar los horarios.</strong>
            <p>Lo que ve puede no ser lo último guardado. {estado.fallaRefresco}</p>
          </div>
        </div>
      ) : null}

      <ContenidoReglas
        estado={estado}
        onRecargar={onRecargar}
        onGuardar={onGuardar}
        onCerrarAviso={onCerrarAviso}
        borradores={borradores}
      />
    </section>
  );
}

function ContenidoReglas({ estado, onRecargar, onGuardar, onCerrarAviso, borradores }) {
  if (estado.fase === 'cargando') {
    return (
      <div className="reglas__cargando">
        <p className="reglas__estado" role="status">Cargando horarios…</p>
        <div className="reglas__esqueleto" aria-hidden="true" />
        <div className="reglas__esqueleto" aria-hidden="true" />
      </div>
    );
  }

  if (estado.fase === 'error') {
    return (
      <div className="reglas__error" role="alert">
        <p>{estado.error}</p>
        <Boton onClick={onRecargar}>Reintentar horarios</Boton>
      </div>
    );
  }

  if ((estado.comidas ?? []).length === 0) {
    return (
      <p className="reglas__vacio" role="status">
        El servidor no informó ningún horario de comida para este momento, así que no hay nada que
        editar. Si esperaba ver comidas, verifique que los horarios estén cargados y la hora del
        sistema.
      </p>
    );
  }

  return (
    <ul className="reglas__lista" aria-label="Horarios de comida">
      {estado.comidas.map((comida, indice) => (
        <li key={comida.comidaId} className="reglas__item" style={{ '--i': indice }}>
          <TarjetaComida
            key={`${comida.comidaId}:${comida.horario.horarioId}`}
            comida={comida}
            estado={estado}
            onGuardar={onGuardar}
            onCerrarAviso={onCerrarAviso}
            borradorInicial={borradores[comida.comidaId]}
          />
        </li>
      ))}
    </ul>
  );
}

/** Una comida: nombre, inicio, fin y Guardar cambios. */
export function TarjetaComida({ comida, estado, onGuardar, onCerrarAviso, borradorInicial }) {
  const { horario, base } = comida;
  const [borrador, setBorrador] = useState(
    () => borradorInicial ?? { inicio: valorDeHora(horario.horaInicio), fin: valorDeHora(horario.horaFin) },
  );
  const nombre = nombreDeComida(comida);
  const id = `comida-${comida.comidaId}`;
  const motivo = motivoSinGuardar(estado, comida, borrador);
  const guardando = motivo === 'guardando';
  const aviso = estado.avisos[comida.comidaId];
  const conSegundos = horasConSegundos(horario.horaInicio, horario.horaFin, borrador.inicio, borrador.fin);

  const sinEditar = formatoHora(borrador.inicio) === formatoHora(horario.horaInicio)
    && formatoHora(borrador.fin) === formatoHora(horario.horaFin);
  /* Sin tocar nada manda lo que dice el servidor; editado, lo que se vería. */
  const cruza = sinEditar ? horario.cruzaMedianoche : cruzaMedianoche(borrador.inicio, borrador.fin);
  const sinGuardar = !sinEditar && motivo !== 'guardando';
  const versionMasReciente = comida.listado.horarioId !== horario.horarioId;

  function manejarEnvio(evento) {
    evento.preventDefault();
    if (motivo === null) onGuardar(comida, borrador);
  }

  return (
    <form
      className={`reglas__tarjeta${aviso?.tipo === 'exito' ? ' reglas__tarjeta--guardada' : ''}`}
      onSubmit={manejarEnvio}
      aria-labelledby={`${id}-nombre`}
      noValidate
    >
      <div className="reglas__cabecera">
        <div className="reglas__nombre-caja">
          <h3 className="reglas__nombre" id={`${id}-nombre`}>{nombre}</h3>
          <p className="reglas__meta">
            Vigente desde el {textoMomento(horario.vigenteDesde)}
            {horario.creadaPor ? ` · guardado por ${horario.creadaPor}` : ''}
          </p>
        </div>
        {sinGuardar ? <Etiqueta tono="acento">Cambios sin guardar</Etiqueta> : null}
      </div>

      <div className="reglas__campos">
        <label className="reglas__campo" htmlFor={`${id}-inicio`}>
          <span className="reglas__rotulo">Inicio</span>
          <input
            id={`${id}-inicio`}
            type="time"
            step={conSegundos ? 1 : 60}
            className="reglas__input"
            value={borrador.inicio}
            onChange={(evento) => setBorrador({ ...borrador, inicio: evento.target.value })}
            aria-describedby={cruza ? `${id}-medianoche` : undefined}
          />
        </label>
        <label className="reglas__campo" htmlFor={`${id}-fin`}>
          <span className="reglas__rotulo">Fin</span>
          <input
            id={`${id}-fin`}
            type="time"
            step={conSegundos ? 1 : 60}
            className="reglas__input"
            value={borrador.fin}
            onChange={(evento) => setBorrador({ ...borrador, fin: evento.target.value })}
            aria-describedby={cruza ? `${id}-medianoche` : undefined}
          />
        </label>
        <Boton
          type="submit"
          className="reglas__guardar"
          aria-disabled={motivo === null ? 'false' : 'true'}
          aria-describedby={motivo === null ? undefined : `${id}-razon`}
        >
          {guardando ? <span className="reglas__giro" aria-hidden="true" /> : null}
          {guardando ? 'Guardando…' : 'Guardar cambios'}
        </Boton>
      </div>

      {cruza ? (
        <p className="reglas__medianoche" id={`${id}-medianoche`}>
          <IconoReloj tamano={16} />
          Cruza la medianoche: termina el día siguiente.
        </p>
      ) : null}

      {motivo !== null ? (
        <p className="reglas__razon" id={`${id}-razon`}>{TEXTO_SIN_GUARDAR[motivo]}</p>
      ) : null}

      {versionMasReciente ? (
        <p className="reglas__nota-tarjeta" role="note">
          La hora del sistema está en una fecha anterior a la última versión de esta comida. Se
          muestra y se edita la versión más reciente guardada.
        </p>
      ) : null}
      {base.tipo === 'ninguna' ? (
        <p className="reglas__nota-tarjeta" role="note">
          Esta comida no tiene un horario abierto: al guardar se crea uno nuevo.
        </p>
      ) : null}
      {base.tipo === 'error' ? (
        <p className="reglas__alerta-tarjeta" role="alert">
          No se pudo comprobar el historial de esta comida, así que no se puede guardar. {base.mensaje}
        </p>
      ) : null}
      {base.tipo === 'multiple' ? (
        <p className="reglas__alerta-tarjeta" role="alert">
          Esta comida tiene más de un horario abierto en la base de datos. Hay que corregirlo antes
          de poder guardar: avise a soporte.
        </p>
      ) : null}

      {aviso ? (
        <div
          className={`reglas__aviso reglas__aviso--${aviso.tipo}`}
          role={aviso.tipo === 'exito' || aviso.tipo === 'aviso' ? 'status' : 'alert'}
        >
          <span className="reglas__aviso-icono" aria-hidden="true">
            {aviso.tipo === 'exito' ? <IconoCheck tamano={18} /> : <IconoAlerta tamano={18} />}
          </span>
          <div className="reglas__aviso-contenido">
            <strong>{aviso.titulo}</strong>
            {aviso.detalle ? <p>{aviso.detalle}</p> : null}
          </div>
          <button
            type="button"
            className="reglas__aviso-cerrar"
            onClick={() => onCerrarAviso(comida.comidaId)}
            aria-label="Cerrar aviso"
          >
            ×
          </button>
        </div>
      ) : null}
    </form>
  );
}
