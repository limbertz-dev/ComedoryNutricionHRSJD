import { useState } from 'react';
import { ErrorApi, registrarPoliciaEnChecklist } from '../../api.js';
import Boton from '../ui/Boton.jsx';
import { IconoEscudo } from '../ui/Iconos.jsx';
import { Dialogo } from './Administracion.jsx';
import './Administracion.css';

/**
 * «Registrar policía» de la cocinera, en el checklist y en Control
 * Biométrico. Los policías no tienen identidad: cada confirmación suma una
 * ración a la columna Policías de la comida en curso. Pide confirmar para
 * evitar un toque por error. `onRegistrado` recibe la respuesta del servidor.
 */
export default function RegistrarPolicia({ onRegistrado, abiertoInicial = false, registrar = registrarPoliciaEnChecklist }) {
  const [abierto, setAbierto] = useState(abiertoInicial);
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState('');

  function cerrar() {
    if (enviando) return;
    setAbierto(false);
    setError('');
  }

  async function confirmar() {
    if (enviando) return;
    setEnviando(true);
    setError('');
    try {
      const respuesta = await registrar();
      if (respuesta.valido) {
        setAbierto(false);
      } else {
        setError(respuesta.detalle || 'No se registró la ración del policía.');
      }
      onRegistrado?.(respuesta);
    } catch (causa) {
      setError(causa instanceof ErrorApi ? (causa.datos?.detail ?? causa.message) : causa.message);
    } finally {
      setEnviando(false);
    }
  }

  return (
    <>
      <Boton tamano="sm" icono={<IconoEscudo tamano={16} />} onClick={() => setAbierto(true)}>
        Registrar policía
      </Boton>
      {abierto ? (
        <Dialogo etiqueta="Registrar policía" onCerrar={cerrar}>
          <div className="administracion__dialogo-cabecera">
            <span className="administracion__dialogo-icono administracion__dialogo-icono--acento" aria-hidden="true">
              <IconoEscudo tamano={22} />
            </span>
            <h2 className="administracion__dialogo-titulo">¿Desea registrar un policía?</h2>
          </div>
          <p className="administracion__dialogo-mensaje">
            Se suma una ración a la columna Policías de la comida en curso. No hace falta nombre.
          </p>
          {error ? <p className="administracion__error-campo" role="alert">{error}</p> : null}
          <div className="administracion__dialogo-acciones">
            <Boton variante="secundario" onClick={cerrar} disabled={enviando}>Cancelar</Boton>
            <Boton onClick={confirmar} disabled={enviando}>
              {enviando ? 'Registrando…' : 'Sí, registrar policía'}
            </Boton>
          </div>
        </Dialogo>
      ) : null}
    </>
  );
}
