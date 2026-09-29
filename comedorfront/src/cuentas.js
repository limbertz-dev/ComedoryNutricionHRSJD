/*
 * cuentas.js — presentación compartida de las tablas de cuentas.
 *
 * Sin JSX, para probarlo con `node --test`. Lo usan Administración
 * (sistemas, con acciones) y Cuentas (jefa, solo lectura) para ordenar,
 * filtrar y mostrar filas idénticas sin duplicar lógica.
 */

/** Etiqueta legible de cada rol. */
export const ETIQUETAS_ROL = { sistemas: 'Sistemas', jefa: 'Jefa', cocinera: 'Cocinera' };

/** Peso para ordenar: sistemas, jefa y cocinera, en ese orden. */
const PESO_ROL = { sistemas: 0, jefa: 1, cocinera: 2 };

/**
 * Orden de la tabla: primero las activas; dentro, por rol (sistemas, jefa,
 * cocinera) y por usuario.
 */
export function ordenarCuentas(cuentas = []) {
  return [...cuentas].sort((a, b) => {
    if (a.activo !== b.activo) return a.activo ? -1 : 1;
    const pesoA = PESO_ROL[a.rol] ?? 99;
    const pesoB = PESO_ROL[b.rol] ?? 99;
    if (pesoA !== pesoB) return pesoA - pesoB;
    return String(a.username).localeCompare(String(b.username), 'es');
  });
}

/** Filtro local de la tabla por usuario o nombre. */
export function filtrarCuentas(cuentas, busqueda = '') {
  const termino = busqueda.trim().toLowerCase();
  if (!termino) return [...cuentas];
  return cuentas.filter((cuenta) => (
    cuenta.username.toLowerCase().includes(termino)
    || (cuenta.nombre ?? '').toLowerCase().includes(termino)
  ));
}

/** Estado legible: Inactiva, Clave temporal (activa con clave por cambiar) o Activa. */
export function estadoDeCuenta(cuenta) {
  if (!cuenta.activo) return { texto: 'Inactiva', tono: 'neutro' };
  if (cuenta.debeCambiar) return { texto: 'Clave temporal', tono: 'aviso' };
  return { texto: 'Activa', tono: 'exito' };
}

/** Último ingreso: «Nunca» si no ingresó; si no, fecha y hora cortas. */
export function formatoUltimoIngreso(texto) {
  if (texto === null || texto === undefined || texto === '') return 'Nunca';
  const momento = new Date(texto);
  if (Number.isNaN(momento.getTime())) return String(texto);
  return momento.toLocaleString('es-BO', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}
