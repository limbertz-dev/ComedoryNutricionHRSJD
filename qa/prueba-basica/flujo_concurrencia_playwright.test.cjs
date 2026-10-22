'use strict';
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { comprobarLectura } = require('./flujo_concurrencia_playwright.cjs');

test('HTTP 200 no aprueba una entrega rechazada ni una identidad diferente', () => {
  const res = { status: 200, datos: { usuario_id: 900101, valido: true, motivo: null, lectura_id: 1, asistencia_id: 2 } };
  assert.doesNotThrow(() => comprobarLectura(res, 900101));
  for (const cambio of [
    { valido: false, motivo: 'duplicado', asistencia_id: null },
    { usuario_id: 900102 }, { asistencia_id: null }, { lectura_id: null },
  ]) assert.throws(() => comprobarLectura({ ...res, datos: { ...res.datos, ...cambio } }, 900101));
  assert.throws(() => comprobarLectura({ ...res, status: 500 }, 900101));
});

test('un duplicado solo pasa con motivo exacto y sin nueva asistencia', () => {
  const res = { status: 200, datos: { usuario_id: 900101, valido: false, motivo: 'duplicado', lectura_id: 1, asistencia_id: null } };
  assert.doesNotThrow(() => comprobarLectura(res, 900101, 'duplicado'));
  assert.throws(() => comprobarLectura({ ...res, datos: { ...res.datos, asistencia_id: 3 } }, 900101, 'duplicado'));
  assert.throws(() => comprobarLectura({ ...res, datos: { ...res.datos, motivo: 'sin_derecho' } }, 900101, 'duplicado'));
});
