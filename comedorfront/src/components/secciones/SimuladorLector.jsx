import Boton from '../ui/Boton.jsx';
import { IconoAlerta, IconoHuella } from '../ui/Iconos.jsx';
import './SimuladorLector.css';

/**
 * Simulador del lector biométrico.
 *
 * Vive en la barra principal del header, entre el título y las pastillas de
 * turno/fecha: así "Apoyar huella" queda siempre visible sin importar el
 * scroll, el mismo requisito que ya cumplía el botón "Simular marcación" del
 * mockup original, y sin agregarle una fila propia al header. App.jsx solo lo
 * monta cuando la sección activa es Control Biométrico.
 *
 * Elige a quién "apoya la huella" y dispara exactamente la misma marcación
 * que enviará el lector real (POST /asistencias con metodo 'biometrico').
 */
export default function SimuladorLector({
  personal,
  seleccionado,
  onSeleccionar,
  onMarcar,
  onSimularFalla,
  leyendo,
  error,
}) {
  const sinPadron = personal.length === 0;
  const personaId = Number(seleccionado);
  const listo = Number.isInteger(personaId) && personaId > 0;

  function elegirAlAzar() {
    if (sinPadron) return;
    const persona = personal[Math.floor(Math.random() * personal.length)];
    onSeleccionar(String(persona.id));
  }

  return (
    <div className="simulador-header" aria-label="Simulador de lector biométrico">
      <span className="simulador-header__insignia">Modo pruebas</span>

      <label className="simulador-header__campo">
        <span className="solo-lectores">Comensal</span>
        <select
          value={seleccionado}
          disabled={sinPadron || leyendo}
          onChange={(cambio) => onSeleccionar(cambio.target.value)}
        >
          <option value="">
            {sinPadron ? 'Padrón no disponible' : 'Seleccione un comensal…'}
          </option>
          {personal.map((persona) => (
            <option key={persona.id} value={persona.id}>
              {`${persona.nombre} — ${persona.categoria} (${persona.legajo})`}
            </option>
          ))}
        </select>
      </label>

      <Boton variante="secundario" onClick={elegirAlAzar} disabled={sinPadron || leyendo}>
        Al azar
      </Boton>

      <Boton
        icono={<IconoHuella tamano={16} />}
        onClick={() => onMarcar(personaId)}
        disabled={!listo || leyendo}
      >
        {leyendo ? 'Leyendo…' : 'Apoyar huella'}
      </Boton>

      {/* Imita una huella que el lector no llega a resolver contra nadie del
          padrón, sin depender del comensal elegido arriba. */}
      <Boton
        variante="secundario"
        className="simulador-header__boton-falla"
        icono={<IconoAlerta tamano={16} />}
        onClick={onSimularFalla}
        disabled={leyendo}
      >
        Falla biométrica
      </Boton>

      {/* Solo el error de verdad se asoma acá: los rechazos de negocio (sin
          cupo, ya marcó, fuera de horario) ya se leen en el escenario, con su
          check o equis. Truncado con título completo para no ensanchar el
          header con una franja de texto larga. */}
      {error ? (
        <span className="simulador-header__aviso" role="alert" data-tooltip={error}>
          {error}
        </span>
      ) : null}
    </div>
  );
}
