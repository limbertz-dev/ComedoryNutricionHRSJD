const test = require('node:test');
const assert = require('node:assert/strict');
const { comprobarIntervencion } = require('./soporte_playwright.cjs');

test('una tabla vacía o una lectura distinta nunca aprueba la intervención', () => {
  assert.throws(() => comprobarIntervencion([], 67), /no ve la intervención/);
  assert.throws(() => comprobarIntervencion([{ decision_original: { lectura_id: 66 } }], 67), /no ve la intervención/);
});

test('la fila debe corresponder a la persona, resultado y cocinera esperados', () => {
  const fila = { decision_original: { lectura_id: 67 }, cuenta: { usuario: 'cocinera2' },
    resultado: 'registrada', comensal: { usuario_id: 900102 } };
  assert.equal(comprobarIntervencion([fila], 67), fila);
  for (const cambios of [{ cuenta: { usuario: 'cocinera1' } }, { resultado: 'rechazada' },
    { comensal: { usuario_id: 900101 } }]) {
    assert.throws(() => comprobarIntervencion([{ ...fila, ...cambios }], 67));
  }
});
