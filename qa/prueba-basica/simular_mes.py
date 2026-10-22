"""Un mes de raciones sintéticas en la base QA, para ver el informe mensual con cifras.

Solo escribe `asistencias` de `bd_nutricion_escenario_sim`, con comensales
ficticios (usuario_id 950001 en adelante) que no existen en el padrón de la
demo: no tocan derechos, lecturas, cuentas ni la corrida de la prueba básica.
El informe los cuenta porque cuenta raciones servidas, no personas.

Sin `--aplicar` solo muestra lo que insertaría. Lo insertado queda anotado
en `simulacion_mes.json`; `--limpiar --aplicar` borra exactamente esas filas
y nada más.

    python -B qa/prueba-basica/simular_mes.py --mes 2026-09
    python -B qa/prueba-basica/simular_mes.py --mes 2026-09 --aplicar
    python -B qa/prueba-basica/simular_mes.py --limpiar --aplicar
"""
import argparse
import calendar
import json
import random
from collections import Counter
from datetime import date, datetime, time, timedelta

from sqlalchemy import text

import comun as c

MANIFIESTO = c.CARPETA / 'simulacion_mes.json'
PRIMER_USUARIO = 950001
ULTIMO_POSIBLE = 950999
MARCA = 'comedor-simulacion-mensual'

# Peso de cada columna del informe en el padrón ficticio; una columna activa
# que no figure aquí recibe el peso por defecto.
PESOS = {'medico': 30, 'servicio': 25, 'administrativo': 15, 'tecnicos': 25,
         'policias': 8, 'internos': 15}
PESO_POR_DEFECTO = 10
COMENSALES_SIN_CLASIFICAR = 2

# Probabilidad de que un comensal coma ese tiempo un día hábil; el fin de
# semana va con menos gente, como en el comedor real.
ASISTENCIA = {'desayuno': .55, 'almuerzo': .80, 'te': .35, 'cena': .40}
FACTOR_FIN_DE_SEMANA = .6


def mes_argumento(valor):
    try:
        anio, mes = (int(p) for p in valor.split('-'))
        return date(anio, mes, 1)
    except ValueError:
        raise argparse.ArgumentTypeError('El mes va como AAAA-MM, por ejemplo 2026-09.') from None


def mes_anterior(hoy):
    primero = hoy.replace(day=1)
    return (primero - timedelta(days=1)).replace(day=1)


def catalogos(conn):
    columnas = conn.execute(text(
        'SELECT id,codigo FROM categorias_reporte WHERE activo=1 ORDER BY orden,id'
    )).mappings().all()
    if not any(f['codigo'] == 'sin_clasificar' for f in columnas):
        raise c.Abortado('Falta la columna Sin clasificar activa; no se simula.')
    comidas = conn.execute(text(
        f'SELECT id,codigo FROM `{c.DEMO}`.comidas WHERE estado=1'
    )).mappings().all()
    por_codigo = {f['codigo']: f['id'] for f in comidas}
    for spec in c.COMIDAS_LABORATORIO.values():
        if por_codigo.get(spec['codigo']) != spec['id']:
            raise c.Abortado('El catálogo de comidas QA es incompatible; no se simula.')
    return columnas


def padron(columnas, cantidad, azar):
    """Comensales ficticios, cada uno con su columna fija como el personal real."""
    clasificadas = [f for f in columnas if f['codigo'] != 'sin_clasificar']
    sin_clasificar = next(f['id'] for f in columnas if f['codigo'] == 'sin_clasificar')
    pesos = [PESOS.get(f['codigo'], PESO_POR_DEFECTO) for f in clasificadas]
    # Reparto proporcional por resto mayor: sorteado, un padrón chico deja
    # columnas infladas o vacías que no se parecen al comedor real.
    plazas = cantidad - COMENSALES_SIN_CLASIFICAR
    cuotas = [plazas * p / sum(pesos) for p in pesos]
    enteras = [int(q) for q in cuotas]
    for i in sorted(range(len(cuotas)), key=lambda i: enteras[i] - cuotas[i])[:plazas - sum(enteras)]:
        enteras[i] += 1
    asignadas = [f['id'] for f, n in zip(clasificadas, enteras) for _ in range(n)]
    asignadas += [sin_clasificar] * COMENSALES_SIN_CLASIFICAR
    azar.shuffle(asignadas)
    return {PRIMER_USUARIO + i: cid for i, cid in enumerate(asignadas)}


def filas_del_mes(primero, comensales, azar):
    ultimo = primero.replace(day=calendar.monthrange(primero.year, primero.month)[1])
    filas = []
    dia = primero
    while dia <= ultimo:
        factor = FACTOR_FIN_DE_SEMANA if dia.weekday() >= 5 else 1
        for spec in c.COMIDAS_LABORATORIO.values():
            hora = time.fromisoformat(spec['hora'])
            for uid, categoria in comensales.items():
                if azar.random() >= ASISTENCIA[spec['codigo']] * factor:
                    continue
                momento = datetime.combine(dia, hora) + timedelta(minutes=azar.randint(0, 50),
                                                                   seconds=azar.randint(0, 59))
                filas.append({'usuario': uid, 'fecha': dia, 'comida': spec['id'],
                              'categoria': categoria, 'momento': momento})
        dia += timedelta(days=1)
    return filas, ultimo


def resumen(filas, columnas):
    nombres = {f['id']: f['codigo'] for f in columnas}
    comidas = {s['id']: s['codigo'] for s in c.COMIDAS_LABORATORIO.values()}
    conteo = Counter((comidas[f['comida']], nombres[f['categoria']]) for f in filas)
    for comida in comidas.values():
        partes = ', '.join(f'{cat} {conteo[(comida, cat)]}' for cat in nombres.values()
                           if conteo[(comida, cat)])
        print(f'  {comida:9} {sum(v for (k, _), v in conteo.items() if k == comida):5}  ({partes})')
    print(f'  {"total":9} {len(filas):5}')


def simular(conn, primero, cantidad, semilla, aplicar):
    if MANIFIESTO.exists():
        raise c.Abortado('Ya hay un mes simulado (simulacion_mes.json); limpiarlo antes de otro.')
    ajenas = conn.execute(text(
        'SELECT COUNT(*) FROM asistencias WHERE usuario_id BETWEEN :a AND :b'
    ), {'a': PRIMER_USUARIO, 'b': ULTIMO_POSIBLE}).scalar_one()
    if ajenas:
        raise c.Abortado('Hay raciones en el rango ficticio sin manifiesto; revisar antes de simular.')
    if conn.execute(text(
        f'SELECT COUNT(*) FROM `{c.DEMO}`.users WHERE id BETWEEN :a AND :b'
    ), {'a': PRIMER_USUARIO, 'b': ULTIMO_POSIBLE}).scalar_one():
        raise c.Abortado('El rango ficticio choca con usuarios de la demo; no se simula.')

    columnas = catalogos(conn)
    azar = random.Random(f'{semilla}-{primero:%Y-%m}')
    filas, ultimo = filas_del_mes(primero, padron(columnas, cantidad, azar), azar)
    if ultimo >= date.today():
        raise c.Abortado('El mes simulado tiene que estar cerrado: elegir uno anterior a hoy.')

    print(f'{"Insertaría" if not aplicar else "Insertando"} {len(filas)} raciones de '
          f'{cantidad} comensales ficticios, del {primero:%d/%m} al {ultimo:%d/%m/%Y}:')
    resumen(filas, columnas)
    if not aplicar:
        print('Simulacro: no se escribió nada. Repetir con --aplicar.')
        return

    conn.execute(text(
        'INSERT INTO asistencias (usuario_id,fecha_comida,comida_id,categoria_reporte_id,'
        'servicio_id,turno_asignado_id,metodo,lectura_id,fecha_hora,registrado_por,'
        'registrado_por_cuenta) VALUES (:usuario,:fecha,:comida,:categoria,NULL,NULL,'
        "'biometrico',NULL,:momento,NULL,NULL)"
    ), filas)
    ids = conn.execute(text(
        'SELECT id FROM asistencias WHERE usuario_id BETWEEN :a AND :b ORDER BY id'
    ), {'a': PRIMER_USUARIO, 'b': ULTIMO_POSIBLE}).scalars().all()
    if len(ids) != len(filas):
        raise c.Abortado('Las filas insertadas no coinciden con las previstas; rollback.')
    # El manifiesto se escribe antes del commit: si el commit fallara, la
    # limpieza encuentra cero filas y solo descarta el manifiesto.
    MANIFIESTO.write_text(json.dumps({
        'marca': MARCA, 'base': c.SIM, 'mes': f'{primero:%Y-%m}',
        'desde': primero.isoformat(), 'hasta': ultimo.isoformat(),
        'usuarios': [PRIMER_USUARIO, PRIMER_USUARIO + cantidad - 1],
        'semilla': semilla, 'total': len(ids), 'ids': ids,
        'creado': datetime.now().isoformat(timespec='seconds'),
    }, indent=1), encoding='utf-8')


def limpiar(conn, aplicar):
    if not MANIFIESTO.exists():
        raise c.Abortado('No hay simulacion_mes.json: no hay mes simulado que limpiar.')
    datos = json.loads(MANIFIESTO.read_text(encoding='utf-8'))
    if datos.get('marca') != MARCA or datos.get('base') != c.SIM:
        raise c.Abortado('Manifiesto ajeno a esta herramienta; no se borra nada.')
    primero, ultimo = datos['usuarios']
    if not PRIMER_USUARIO <= primero <= ultimo <= ULTIMO_POSIBLE:
        raise c.Abortado('Manifiesto con usuarios fuera del rango ficticio; no se borra nada.')
    filtro = ('usuario_id BETWEEN :a AND :b AND fecha_comida BETWEEN :d AND :h '
              'AND lectura_id IS NULL AND turno_asignado_id IS NULL')
    valores = {'a': primero, 'b': ultimo, 'd': datos['desde'], 'h': datos['hasta']}
    actuales = set(conn.execute(text(
        f'SELECT id FROM asistencias WHERE {filtro} FOR UPDATE'
    ), valores).scalars().all())
    if not actuales:
        print('Ninguna fila del manifiesto llegó a la base: se descarta el manifiesto.')
        return
    if actuales != set(datos['ids']):
        raise c.Abortado('Las filas actuales no coinciden con el manifiesto; revisar antes de borrar.')
    print(f'{"Borraría" if not aplicar else "Borrando"} {len(actuales)} raciones simuladas de {datos["mes"]}.')
    if not aplicar:
        print('Simulacro: no se borró nada. Repetir con --aplicar.')
        return
    borradas = conn.execute(text(f'DELETE FROM asistencias WHERE {filtro}'), valores).rowcount
    if borradas != len(actuales):
        raise c.Abortado('El borrado no coincide con el manifiesto; rollback.')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--mes', type=mes_argumento, default=mes_anterior(date.today()),
                        help='AAAA-MM; por defecto, el mes anterior al de hoy')
    parser.add_argument('--comensales', type=int, default=120, help='padrón ficticio (10 a 999)')
    parser.add_argument('--semilla', default='qa', help='la misma semilla repite las mismas cifras')
    parser.add_argument('--limpiar', action='store_true', help='borrar el mes simulado')
    parser.add_argument('--aplicar', action='store_true', help='escribir de verdad')
    args = parser.parse_args()
    if not 10 <= args.comensales <= ULTIMO_POSIBLE - PRIMER_USUARIO + 1:
        parser.error('--comensales va de 10 a 999.')

    verbo = 'DELETE' if args.limpiar else 'INSERT'
    permitidas = c.permisos((c.SIM, 'asistencias', verbo)) if args.aplicar else ()
    with c.bloqueo_corrida(), c.entorno_seguro(permitidas) as (motor, _huella, _servidor):
        with motor.begin() as conn:
            if args.limpiar:
                limpiar(conn, args.aplicar)
            else:
                simular(conn, args.mes, args.comensales, args.semilla, args.aplicar)
        if args.limpiar and args.aplicar:
            MANIFIESTO.unlink()
        if args.aplicar:
            print('Hecho. El informe del mes ya lo muestra; no hace falta reiniciar la API.')


if __name__ == '__main__':
    c.ejecutar(main)
