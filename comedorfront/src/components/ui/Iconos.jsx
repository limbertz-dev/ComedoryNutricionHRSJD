/*
 * Iconos SVG inline: sin librería externa y sin dependencia de red, de modo
 * que la interfaz se vea igual en cualquier máquina. Todos heredan el color del
 * texto (`currentColor`) y el trazo es uniforme para que la app se vea de una
 * sola pieza.
 *
 * Estilo del set: lienzo de 24, trazo de 1.8 con puntas redondas y dos o tres
 * elementos por glifo — sin relleno y sin detalle fino. Cualquier icono nuevo
 * debe mantener ese nivel de detalle o el conjunto deja de leerse igual.
 */

function Svg({ children, tamano = 24, relleno = 'none', ...resto }) {
  return (
    <svg
      width={tamano}
      height={tamano}
      viewBox="0 0 24 24"
      fill={relleno}
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...resto}
    >
      {children}
    </svg>
  );
}

export function IconoEnVivo(props) {
  return (
    <Svg {...props}>
      <rect x="3" y="4" width="18" height="13" rx="2" />
      <path d="M8 21h8M12 17v4" />
    </Svg>
  );
}

export function IconoDashboard(props) {
  return (
    <Svg {...props}>
      <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
      <path d="m3 8 6-5 6 7 6-5" />
    </Svg>
  );
}

export function IconoReportes(props) {
  return (
    <Svg {...props}>
      <path d="M14.4 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7.6L14.4 3Z" />
      <path d="M14.2 3.2v4.6h4.6" />
      <path d="M9 17.2v-2.6M12 17.2v-5.2M15 17.2v-3.6" />
    </Svg>
  );
}

export function IconoHistorial(props) {
  return (
    <Svg {...props}>
      <path d="M3.6 12.4a8.4 8.4 0 1 0 2.6-6.2" />
      <path d="M3 3.4v4.4h4.4" />
      <path d="M12 7.9v4.5l3.2 1.9" />
    </Svg>
  );
}

export function IconoCalendario(props) {
  return (
    <Svg {...props}>
      <rect x="3" y="5" width="18" height="16" rx="2" />
      <path d="M16 3v4M8 3v4M3 10h18" />
    </Svg>
  );
}

export function IconoEditar(props) {
  return (
    <Svg {...props}>
      <path d="m15 4 5 5M4 20l5-1L20 8a2.1 2.1 0 0 0-5-3L4 16v4Z" />
    </Svg>
  );
}

export function IconoPapelera(props) {
  return (
    <Svg {...props}>
      <path d="M3 6h18M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
      <path d="m5 6 1 14a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1l1-14M10 10v7M14 10v7" />
    </Svg>
  );
}

export function IconoBuscar(props) {
  return (
    <Svg {...props}>
      <circle cx="10.8" cy="10.8" r="6.6" />
      <path d="m16 16 4.2 4.2" />
    </Svg>
  );
}

export function IconoHuella(props) {
  return (
    <Svg {...props} strokeWidth="1.6">
      <path d="M2.6 17.4v-4.3a9.4 9.4 0 0 1 18.8 0v3.1" />
      <path d="M6.1 20v-6.9a5.9 5.9 0 0 1 11.8 0v5.6" />
      <path d="M9.6 21.6v-8.5a2.4 2.4 0 0 1 4.8 0v7" />
      <path d="M12 13.1v3.4" />
    </Svg>
  );
}

export function IconoCheck(props) {
  return (
    <Svg {...props} strokeWidth="2.6">
      <path d="m4.8 12.6 4.7 4.7L19.2 7.6" />
    </Svg>
  );
}

export function IconoLista(props) {
  return (
    <Svg {...props}>
      <path d="m4 7 1.6 1.6L8.5 5.7M4 15.5l1.6 1.6 2.9-2.9" />
      <path d="M12 7.5h8M12 16h8" />
    </Svg>
  );
}

export function IconoEquis(props) {
  return (
    <Svg {...props} strokeWidth="2.6">
      <path d="M6.4 6.4 17.6 17.6M17.6 6.4 6.4 17.6" />
    </Svg>
  );
}

export function IconoReloj(props) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="8.6" />
      <path d="M12 7.4V12l3 1.8" />
    </Svg>
  );
}

export function IconoSubir(props) {
  return (
    <Svg {...props}>
      <path d="M20 15.6v3a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-3" />
      <path d="m8 8.6 4-4.4 4 4.4M12 4.2v11.6" />
    </Svg>
  );
}

export function IconoBandeja(props) {
  return (
    <Svg {...props}>
      <path d="M3.4 14.2h17.2a8.6 8.6 0 0 1-17.2 0Z" />
      <path d="M2.6 20.4h18.8" />
      <path d="M12 3.2v2.6M9 5.4c-.9.8-1.4 1.9-1.4 3.1M15 5.4c.9.8 1.4 1.9 1.4 3.1" />
    </Svg>
  );
}

export function IconoRecargar(props) {
  return (
    <Svg {...props}>
      <path d="M20.4 11.4a8.4 8.4 0 1 0-.8 4.6" />
      <path d="M20.4 5.6v5.8h-5.8" />
    </Svg>
  );
}

export function IconoCerrarSesion(props) {
  return (
    <Svg {...props}>
      <path d="M10 4H5.5A1.5 1.5 0 0 0 4 5.5v13A1.5 1.5 0 0 0 5.5 20H10" />
      <path d="m15 8 4 4-4 4M19 12H9" />
    </Svg>
  );
}

export function IconoAlerta(props) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="8.8" />
      <path d="M12 7.6v5M12 15.9h.01" />
    </Svg>
  );
}

export function IconoUsuario(props) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="8" r="3.4" />
      <path d="M5.5 20v-1.6a6.5 6.5 0 0 1 13 0V20" />
    </Svg>
  );
}

/** Escudo: raciones de policía (vía libre, sin persona del padrón). */
export function IconoEscudo(props) {
  return (
    <Svg {...props}>
      <path d="M12 3l7 3v5c0 4.6-3 8.4-7 10-4-1.6-7-5.4-7-10V6l7-3z" />
      <path d="M9.2 12.2l1.9 1.9 3.8-3.9" />
    </Svg>
  );
}

export function IconoCandado(props) {
  return (
    <Svg {...props}>
      <rect x="5" y="10" width="14" height="11" rx="2" />
      <path d="M8.3 10V7.3a3.7 3.7 0 0 1 7.4 0V10M12 14.6v2.8" />
    </Svg>
  );
}

export function IconoOjo(props) {
  return (
    <Svg {...props}>
      <path d="M2.8 12s3.2-5 9.2-5 9.2 5 9.2 5-3.2 5-9.2 5-9.2-5-9.2-5Z" />
      <circle cx="12" cy="12" r="2.2" />
    </Svg>
  );
}

export function IconoOjoOculto(props) {
  return (
    <Svg {...props}>
      <path d="m4 4 16 16M9.7 7.3A9.8 9.8 0 0 1 12 7c6 0 9.2 5 9.2 5a15.4 15.4 0 0 1-2.4 2.8M6.1 8.6A15.2 15.2 0 0 0 2.8 12s3.2 5 9.2 5c.8 0 1.6-.1 2.3-.3" />
    </Svg>
  );
}

export function IconoHospital(props) {
  return (
    <Svg {...props}>
      <path d="M5 21V6h14v15M3 21h18M9 21v-4h6v4" />
      <path d="M12 3v6M9 6h6M8.5 12h.01M12 12h.01M15.5 12h.01" />
    </Svg>
  );
}

export function IconoLogo(props) {
  return (
    <Svg {...props}>
      <path d="M3.5 14h17a8.5 8.5 0 0 1-17 0Z" />
      <path d="M2.5 20.5h19" />
      <path d="M12 3v3M9 6.5V4M15 6.5V4" />
    </Svg>
  );
}

export function IconoHojaCalculo(props) {
  return (
    <Svg {...props}>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M3 9.5h18M9.5 9.5V20" />
    </Svg>
  );
}

export function IconoDocumentoPdf(props) {
  return (
    <Svg {...props}>
      <path d="M6.5 3h7l4 4v14h-11Z" />
      <path d="M13.5 3v4h4M9.5 16h5" />
    </Svg>
  );
}
