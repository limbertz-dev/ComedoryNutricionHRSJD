import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';
/* Nunito: la tipografía del sistema visual que reciclamos. Se sirve local
   (sin CDN) y solo en los pesos que la app usa: 400 normal, 600 rótulos,
   700 ítems y botones, 800 títulos y cifras. */
import '@fontsource/nunito/latin-400.css';
import '@fontsource/nunito/latin-ext-400.css';
import '@fontsource/nunito/latin-600.css';
import '@fontsource/nunito/latin-ext-600.css';
import '@fontsource/nunito/latin-700.css';
import '@fontsource/nunito/latin-ext-700.css';
import '@fontsource/nunito/latin-800.css';
import '@fontsource/nunito/latin-ext-800.css';
import './styles/global.css';

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
