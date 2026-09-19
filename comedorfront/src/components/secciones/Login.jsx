import { useState } from 'react';
import {
  IconoHospital,
  IconoLogo,
  IconoOjo,
  IconoOjoOculto,
  IconoCandado,
  IconoUsuario,
} from '../ui/Iconos.jsx';
import './Login.css';

export default function Login({ onIngresar }) {
  const [mostrarContrasena, setMostrarContrasena] = useState(false);

  function manejarEnvio(evento) {
    evento.preventDefault();
    onIngresar();
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
          <header className="login__cabecera">
            <h1 id="login-titulo">Iniciar sesión</h1>
            <p>Sistema de Comedor y Nutrición Hospitalaria</p>
          </header>

          <form className="login__formulario" onSubmit={manejarEnvio} noValidate>
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
                />
              </span>
            </div>

            <div className="login__grupo">
              <label htmlFor="login-contrasena">Contraseña</label>
              <span className="login__campo">
                <IconoCandado tamano={22} />
                <input
                  id="login-contrasena"
                  name="contrasena"
                  type={mostrarContrasena ? 'text' : 'password'}
                  placeholder="Ingrese su contraseña"
                  autoComplete="current-password"
                />
                <button
                  className="login__mostrar-contrasena"
                  type="button"
                  aria-label={mostrarContrasena ? 'Ocultar contraseña' : 'Mostrar contraseña'}
                  aria-pressed={mostrarContrasena}
                  onClick={() => setMostrarContrasena((visible) => !visible)}
                >
                  {mostrarContrasena ? <IconoOjoOculto tamano={22} /> : <IconoOjo tamano={22} />}
                </button>
              </span>
            </div>

            <button className="login__ingresar" type="submit">
              Ingresar
            </button>
          </form>

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
