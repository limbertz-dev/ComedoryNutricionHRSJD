import test from 'node:test';
import assert from 'node:assert/strict';
import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import PantallaEnVivo from '../src/components/secciones/PantallaEnVivo.jsx';
import GaugeRaciones from '../src/components/ui/GaugeRaciones.jsx';

for (const comida of ['Desayuno', 'Almuerzo', 'Té', 'Cena']) {
  for (const cerrado of [false, true]) {
    test(`al abrir muestra ${comida}, ${cerrado ? 'último servicio cerrado' : 'servicio vigente'}`, () => {
      const html = renderToStaticMarkup(h(PantallaEnVivo, {
        pantalla: { comida, fecha_comida: '2026-10-19', fuera_de_horario: cerrado,
          totales_del_dia: { raciones_servidas: 0 } },
        turno: comida, marcacionesIniciales: [],
      }));
      const seleccionado = html.match(/role="tab" aria-selected="true"[^>]*>([^<]+)<\/button>/g);
      assert.equal(seleccionado?.length, 1);
      assert.ok(seleccionado[0].includes(`>${comida}</button>`));
      if (cerrado) {
        assert.match(html, /Fuera de horario/);
        assert.ok(html.includes(`Se muestra ${comida}, el último servicio.`));
        assert.match(html, /registro de asistencias está deshabilitado/);
      }
    });
  }
}

test('el cupo cerrado sigue visible como consulta, sin anunciar entregas disponibles', () => {
  const html = renderToStaticMarkup(h(GaugeRaciones, {
    cupo: { previstas: 5, servidas: 2, restantes: 3, porcentaje: 40 },
    fueraDeHorario: true, turno: 'Cena',
  }));
  assert.match(html, /Último servicio · Cerrado/);
  assert.match(html, /Cena · 2 servidas/);
  assert.match(html, /No se permiten entregas/);
});
