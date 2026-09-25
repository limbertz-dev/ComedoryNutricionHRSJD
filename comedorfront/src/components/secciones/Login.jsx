import { useEffect, useState } from 'react';
import useSesion from '../../hooks/useSesion.js';
import { textoDeReintento } from '../../sesion.js';
import {
  IconoAlerta,
  IconoHospital,
  IconoLogo,
  IconoOjo,
  IconoOjoOculto,
  IconoCandado,
  IconoReloj,
  IconoUsuario,
} from '../ui/Iconos.jsx';
import './Login.css';

/*
 * Avisos que llegan desde fuera del formulario: la sesión se cerró sola
 * (401 en cualquier sección) o no se pudo confirmar al abrir la app.
 */
const AVISOS_DE_SESION = {
  expirada: { variante: 'info', texto: 'Su sesión expiró. Vuelva a ingresar para continuar.' },
  sin_conexion: { variante: 'error', texto: 'No se pudo verificar la sesión con el servidor. Ingrese de nuevo.' },
};

/**
 * Pantalla de ingreso. Además del formulario, muestra los cuatro estados del
 * contrato: credencial incorrecta (401), cuenta bloqueada (423, con la hora
 * de reintento), cambio obligatorio de contraseña temporal (428 o
 * `debe_cambiar`) y sesión expirada (401 fuera del Login).
 */
export default function Login() {
  const { fase, aviso, usuario: usuarioDeSesion, login, cambiarPassword, logout } = useSesion();
  const [usuario, setUsuario] = useState('');
  const [contrasena, setContrasena] = useState('');
  const [mostrarContrasena, setMostrarContrasena] = useState(false);
  const [enviando, setEnviando] = useState(false);
  /* `{ variante, texto }` del último intento fallido. */
  const [mensaje, setMensaje] = useState(null);
  /* Resultado 423 vigente: `{ detalle, reintentoEn }`. */
  const [bloqueo, setBloqueo] = useState(null);
  const [ahora, setAhora] = useState(() => new Date());

  const textoBloqueo = bloqueo ? textoDeReintento(bloqueo.reintentoEn, ahora) : '';
  /* Solo se deshabilita el botón si se sabe hasta cuándo: sin hora de
     reintento no hay cuenta regresiva que lo vuelva a habilitar. */
  const enEspera = Boolean(bloqueo?.reintentoEn) && textoBloqueo !== '';

  /* Cuenta regresiva del bloqueo: al cumplirse, el botón se habilita solo. */
  useEffect(() => {
    if (!bloqueo?.reintentoEn) return undefined;
    const intervalo = setInterval(() => setAhora(new Date()), 1000);
    return () => clearInterval(intervalo);
  }, [bloqueo]);

  async function manejarIngreso(evento) {
    evento.preventDefault();
    if (enviando || enEspera) return;
    if (!usuario.trim() || !contrasena) {
      setMensaje({ variante: 'error', texto: 'Ingrese su usuario y su contraseña.' });
      return;
    }
    setEnviando(true);
    setMensaje(null);
    setBloqueo(null);
    try {
      const resultado = await login(usuario.trim(), contrasena);
      if (resultado.tipo === 'credencial') {
        setMensaje({ variante: 'error', texto: resultado.detalle });
        setContrasena('');
      } else if (resultado.tipo === 'bloqueada') {
        setAhora(new Date());
        setBloqueo(resultado);
        setContrasena('');
      }
    } catch (error) {
      setMensaje({ variante: 'error', texto: error.message });
    } finally {
      setEnviando(false);
    }
  }

  let avisoVisible = mensaje ?? AVISOS_DE_SESION[aviso] ?? null;
  if (bloqueo) {
    avisoVisible = bloqueo.reintentoEn && !enEspera
      ? { variante: 'info', texto: 'Ya puede intentar ingresar de nuevo.' }
      : { variante: 'aviso', titulo: bloqueo.detalle, texto: textoBloqueo };
  }

  return (
    <main className="login">
      <span className="login__puntos login__puntos--superior" aria-hidden="true" />
      <span className="login__puntos login__puntos--inferior" aria-hidden="true" />

      <div className="login__contenido">
        <div className="login__marca" aria-label="Comedor y Nutrición Hospitalaria">
          <span className="login__marca-icono">
            <IconoLogo tamano={44} />
          </span>
          <div className="login__marca-texto">
            <strong>Comedor y Nutrición</strong>
            <span>Hospitalaria</span>
          </div>
        </div>

        <section className="login__tarjeta" aria-labelledby="login-titulo">
          {fase === 'cambio' ? (
            <CambioObligatorio
              usuario={usuarioDeSesion || usuario.trim()}
              onCambiar={cambiarPassword}
              onVolver={() => {
                setContrasena('');
                logout();
              }}
            />
          ) : (
            <>
              <header className="login__cabecera">
                <h1 id="login-titulo">Iniciar sesión</h1>
                <p>Sistema de Comedor y Nutrición Hospitalaria</p>
              </header>

              <form className="login__formulario" onSubmit={manejarIngreso} noValidate>
                {avisoVisible ? <AvisoLogin {...avisoVisible} /> : null}

                <div className="login__grupo">
                  <label htmlFor="login-usuario">Usuario</label>
                  <span className="login__campo">
                    <IconoUsuario tamano={23} />
                    <input
                      id="login-usuario"
                      name="usuario"
                      type="text"
                      placeholder="Ingrese su usuario"
                      autoComplete="username"
                      autoFocus
                      value={usuario}
                      onChange={(evento) => setUsuario(evento.target.value)}
                    />
                  </span>
                </div>

                <div className="login__grupo">
                  <label htmlFor="login-contrasena">Contraseña</label>
                  <CampoContrasena
                    id="login-contrasena"
                    placeholder="Ingrese su contraseña"
                    autoComplete="current-password"
                    valor={contrasena}
                    onCambiar={setContrasena}
                    visible={mostrarContrasena}
                    onAlternar={() => setMostrarContrasena((visible) => !visible)}
                  />
                </div>

                <button className="login__ingresar" type="submit" disabled={enviando || enEspera}>
                  {enviando ? 'Ingresando…' : 'Ingresar'}
                </button>
              </form>
            </>
          )}

          <footer className="login__hospital">
            <div className="login__separador" aria-hidden="true">
              <span />
              <IconoHospital tamano={30} />
              <span />
            </div>
            <strong>Hospital San Juan de Dios</strong>
            <small>Acceso exclusivo para personal autorizado</small>
          </footer>
        </section>
      </div>
    </main>
  );
}

/**
 * Contraseña temporal: no se entra al sistema sin cambiarla. La identidad ya
 * viaja en el header con el temporal del 428, así que nunca se pide la actual.
 */
function CambioObligatorio({ usuario, onCambiar, onVolver }) {
  const [nueva, setNueva] = useState('');
  const [confirmacion, setConfirmacion] = useState('');
  const [visible, setVisible] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState('');

  async function manejarEnvio(evento) {
    evento.preventDefault();
    if (enviando) return;
    if (!nueva) {
      setError('Ingrese la contraseña nueva.');
      return;
    }
    if (nueva !== confirmacion) {
      setError('La confirmación no coincide con la contraseña nueva.');
      return;
    }
    setEnviando(true);
    setError('');
    try {
      const resultado = await onCambiar({ usuario, nueva });
      if (resultado.tipo === 'credencial' || resultado.tipo === 'bloqueada') setError(resultado.detalle);
      else if (resultado.tipo === 'cambio') setError('El servidor sigue pidiendo el cambio de contraseña.');
    } catch (fallo) {
      setError(fallo.message);
    } finally {
      setEnviando(false);
    }
  }

  return (
    <>
      <header className="login__cabecera">
        <h1 id="login-titulo">Cambie su contraseña</h1>
        <p>Por seguridad, reemplace la contraseña temporal antes de continuar.</p>
      </header>

      <form className="login__formulario" onSubmit={manejarEnvio} noValidate>
        <AvisoLogin
          variante={error ? 'error' : 'aviso'}
          texto={error || `La contraseña de ${usuario || 'este usuario'} es temporal.`}
        />

        <div className="login__grupo">
          <label htmlFor="cambio-nueva">Contraseña nueva</label>
          <CampoContrasena
            id="cambio-nueva"
            placeholder="Escriba su nueva contraseña"
            autoComplete="new-password"
            valor={nueva}
            onCambiar={setNueva}
            visible={visible}
            onAlternar={() => setVisible((v) => !v)}
            autoFocus
          />
        </div>

        <div className="login__grupo">
          <label htmlFor="cambio-confirmacion">Repita la contraseña nueva</label>
          <CampoContrasena
            id="cambio-confirmacion"
            placeholder="Otra vez, para confirmar"
            autoComplete="new-password"
            valor={confirmacion}
            onCambiar={setConfirmacion}
            visible={visible}
            onAlternar={() => setVisible((v) => !v)}
          />
        </div>

        <button className="login__ingresar" type="submit" disabled={enviando}>
          {enviando ? 'Guardando…' : 'Guardar y entrar'}
        </button>
        <button className="login__volver" type="button" onClick={onVolver} disabled={enviando}>
          Volver al inicio de sesión
        </button>
      </form>
    </>
  );
}

function CampoContrasena({ id, placeholder, autoComplete, valor, onCambiar, visible, onAlternar, autoFocus }) {
  return (
    <span className="login__campo">
      <IconoCandado tamano={22} />
      <input
        id={id}
        type={visible ? 'text' : 'password'}
        placeholder={placeholder}
        autoComplete={autoComplete}
        autoFocus={autoFocus}
        value={valor}
        onChange={(evento) => onCambiar(evento.target.value)}
      />
      <button
        className="login__mostrar-contrasena"
        type="button"
        aria-label={visible ? 'Ocultar contraseña' : 'Mostrar contraseña'}
        aria-pressed={visible}
        onClick={onAlternar}
      >
        {visible ? <IconoOjoOculto tamano={22} /> : <IconoOjo tamano={22} />}
      </button>
    </span>
  );
}

/** Franja de estado sobre el formulario: error, aviso (bloqueo) o información. */
function AvisoLogin({ variante, titulo, texto }) {
  const Icono = variante === 'aviso' ? IconoReloj : IconoAlerta;
  return (
    <div className={`login__aviso login__aviso--${variante}`} role={variante === 'error' ? 'alert' : 'status'}>
      <Icono tamano={22} />
      <p>
        {titulo ? <strong>{titulo} </strong> : null}
        {texto}
      </p>
    </div>
  );
}
