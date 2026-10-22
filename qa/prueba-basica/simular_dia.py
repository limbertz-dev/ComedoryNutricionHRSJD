"""Un día completo ya registrado en la base QA, para que la jefa solo lo revise.

Crea un padrón sintético (usuario_id 960001 en adelante) con turno de cuatro
comidas en `bd_turnos_escenario_demo` y registra el día con la lógica real de
la app: `registrar_marcacion` para cada lectura e `identificar_lectura` para
las huellas no reconocidas que resuelve una cocinera. El reloj de la app se
fija a la hora de cada evento; no hace falta mover el reloj del laboratorio.

Además de las entregas normales genera duplicados, huellas no reconocidas
identificadas por cocina, lecturas fuera de horario y comensales sin turno.

Sin `--aplicar` solo muestra el plan. Lo insertado queda anotado en
`simulacion_dia.json`; `--limpiar --aplicar` borra exactamente esas filas.

    python -B qa/prueba-basica/simular_dia.py
    python -B qa/prueba-basica/simular_dia.py --aplicar
    python -B qa/prueba-basica/simular_dia.py --limpiar --aplicar
"""
import argparse
import json
import random
import uuid
from collections import Counter
from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

import comun as c

MANIFIESTO = c.CARPETA / 'simulacion_dia.json'
MARCA = 'comedor-simulacion-dia'
PRIMER_USUARIO = 960001
ULTIMO_POSIBLE = 960999
TURNO = 960001
ASIGNACION_BASE = 960000000
DISPOSITIVO = 'lector-simulacion-dia'
SIN_TURNO = 2

# Categoría del padrón demo -> servicio, y peso en el padrón.
PERFILES = [
    {'categoria_id': 9003, 'servicio_id': 9003, 'peso': 35},  # Medicos / MEDICINA INTERNA
    {'categoria_id': 9004, 'servicio_id': 9004, 'peso': 35},  # Tecnicos / LABORATORIO
    {'categoria_id': 9005, 'servicio_id': 9005, 'peso': 30},  # Internos / IMAGENOLOGIA
]

# Franja en la que llega la gente (dentro del horario de cada comida) y
# probabilidad de que un comensal con turno coma ese tiempo.
COMIDAS = {
    1: {'nombre': 'Desayuno', 'desde': '06:15', 'hasta': '09:30', 'asistencia': .60},
    2: {'nombre': 'Almuerzo', 'desde': '11:30', 'hasta': '14:30', 'asistencia': .85},
    3: {'nombre': 'Té', 'desde': '15:15', 'hasta': '16:45', 'asistencia': .40},
    4: {'nombre': 'Cena', 'desde': '18:30', 'hasta': '21:30', 'asistencia': .45},
}
# Por comida: huellas no reconocidas (las resuelve la cocinera de turno) y duplicados.
NO_RECONOCIDAS = {1: 1, 2: 3, 3: 1, 4: 1}
DUPLICADOS = {1: 1, 2: 3, 3: 0, 4: 1}
COCINERA_DE = {1: 'cocinera1', 2: 'cocinera2', 3: 'cocinera3', 4: 'cocinera1'}
FUERA_DE_HORARIO = ['10:25', '10:40']

NOMBRES = ['ANA', 'CARLOS', 'MARIA', 'JUAN', 'LUCIA', 'JORGE', 'ROSA', 'LUIS', 'CARMEN', 'PEDRO',
           'SILVIA', 'MARCO', 'PATRICIA', 'RENE', 'GLADYS', 'FERNANDO', 'ELENA', 'VICTOR', 'NORA',
           'RAUL', 'SANDRA', 'HUGO', 'MONICA', 'DANIEL', 'TERESA', 'OSCAR', 'BEATRIZ', 'EDWIN']
APELLIDOS = ['QUISPE', 'MAMANI', 'FLORES', 'CHOQUE', 'VARGAS', 'ROJAS', 'GUTIERREZ', 'LOPEZ',
             'CONDORI', 'APAZA', 'MENDOZA', 'TORREZ', 'CRUZ', 'RAMIREZ', 'SOSA', 'VILLCA',
             'ARANCIBIA', 'CALLE', 'ORTIZ', 'PAREDES', 'SALAZAR', 'COPA', 'LIMACHI', 'TICONA']


def fecha_argumento(valor):
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise argparse.ArgumentTypeError('La fecha va como AAAA-MM-DD.') from None


def fecha_del_laboratorio():
    if not c.CORRIDA.exists():
        raise c.Abortado('No hay corrida.json: indica la fecha con --fecha.')
    datos = json.loads(c.CORRIDA.read_text(encoding='utf-8'))
    return date.fromisoformat(datos.get('fecha_destino') or datos['fecha_original'])


def hora(valor):
    return time.fromisoformat(valor)


def padron(cantidad, azar):
    pesos = [p['peso'] for p in PERFILES]
    usados = set()
    personas = []
    for i in range(cantidad + SIN_TURNO):
        while True:
            nombre = f'{azar.choice(NOMBRES)} {azar.choice(APELLIDOS)} {azar.choice(APELLIDOS)}'
            if nombre not in usados:
                usados.add(nombre)
                break
        perfil = azar.choices(PERFILES, weights=pesos)[0]
        uid = PRIMER_USUARIO + i
        personas.append({'usuario_id': uid, 'nombre': nombre, 'con_turno': i < cantidad,
                         'login': f'simdia_{i + 1:03d}', 'legajo': f'SIM-D{i + 1:03d}',
                         'carnet': f'SIMD{i + 1:05d}', **perfil})
    return personas


def momento_en(fecha, desde, hasta, azar):
    inicio = datetime.combine(fecha, hora(desde))
    segundos = (datetime.combine(fecha, hora(hasta)) - inicio).total_seconds()
    # Más gente al principio de la franja, como en una fila real.
    return inicio + timedelta(seconds=int(azar.triangular(0, segundos, segundos * .3)))


def plan_del_dia(fecha, personas, azar):
    con_turno = [p for p in personas if p['con_turno']]
    sin_turno = [p for p in personas if not p['con_turno']]
    eventos = []
    for comida_id, spec in COMIDAS.items():
        comen = [p for p in con_turno if azar.random() < spec['asistencia']]
        azar.shuffle(comen)
        no_rec = comen[:NO_RECONOCIDAS[comida_id]]
        normales = comen[NO_RECONOCIDAS[comida_id]:]
        for p in normales:
            eventos.append({'momento': momento_en(fecha, spec['desde'], spec['hasta'], azar),
                            'tipo': 'normal', 'usuario_id': p['usuario_id'], 'comida_id': comida_id})
        for p in azar.sample(normales, DUPLICADOS[comida_id]):
            base = next(e['momento'] for e in eventos if e['tipo'] == 'normal'
                        and e['usuario_id'] == p['usuario_id'] and e['comida_id'] == comida_id)
            eventos.append({'momento': base + timedelta(minutes=azar.randint(2, 6)),
                            'tipo': 'duplicado', 'usuario_id': p['usuario_id'], 'comida_id': comida_id})
        for p in no_rec:
            eventos.append({'momento': momento_en(fecha, spec['desde'], spec['hasta'], azar),
                            'tipo': 'no_reconocida', 'usuario_id': p['usuario_id'], 'comida_id': comida_id,
                            'cuenta': COCINERA_DE[comida_id], 'demora_min': azar.randint(1, 3)})
        if comida_id == 2:
            for p in sin_turno:
                eventos.append({'momento': momento_en(fecha, spec['desde'], spec['hasta'], azar),
                                'tipo': 'sin_turno', 'usuario_id': p['usuario_id'], 'comida_id': comida_id})
    for valor in FUERA_DE_HORARIO:
        p = azar.choice(con_turno)
        eventos.append({'momento': datetime.combine(fecha, hora(valor)), 'tipo': 'fuera_horario',
                        'usuario_id': p['usuario_id'], 'comida_id': None})
    eventos.sort(key=lambda e: e['momento'])
    return eventos


def resumen_plan(eventos):
    tipos = Counter((e['comida_id'], e['tipo']) for e in eventos)
    for comida_id, spec in COMIDAS.items():
        partes = ', '.join(f'{t} {tipos[(comida_id, t)]}' for t in
                           ('normal', 'duplicado', 'no_reconocida', 'sin_turno') if tipos[(comida_id, t)])
        print(f'  {spec["nombre"]:9} {partes}')
    print(f'  fuera de horario {tipos[(None, "fuera_horario")]}')
    raciones = sum(1 for e in eventos if e['tipo'] in ('normal', 'no_reconocida'))
    print(f'  total: {len(eventos)} lecturas, {raciones} raciones previstas')


def comprobar_libre(conn, cantidad, fecha):
    ultimo = PRIMER_USUARIO + cantidad + SIN_TURNO - 1
    rango = {'a': PRIMER_USUARIO, 'b': ultimo}
    for tabla, columna in (('users', 'id'), ('personas', 'id'), ('personas', 'user_id'),
                           ('usuario_servicios', 'usuario_id'), ('turnos_asignados', 'usuario_id')):
        if conn.execute(text(f'SELECT COUNT(*) FROM `{c.DEMO}`.`{tabla}` WHERE {columna} BETWEEN :a AND :b'),
                        rango).scalar_one():
            raise c.Abortado(f'El rango ficticio choca con {c.DEMO}.{tabla}; no se simula.')
    if conn.execute(text(f'SELECT COUNT(*) FROM `{c.DEMO}`.turnos WHERE id=:t'), {'t': TURNO}).scalar_one():
        raise c.Abortado('El turno de la simulación ya existe sin manifiesto; revisar antes de simular.')
    if conn.execute(text('SELECT COUNT(*) FROM lecturas_biometricas WHERE dispositivo=:d'),
                    {'d': DISPOSITIVO}).scalar_one():
        raise c.Abortado('Hay lecturas del simulador sin manifiesto; revisar antes de simular.')
    if conn.execute(text('SELECT COUNT(*) FROM asistencias WHERE usuario_id BETWEEN :a AND :b'),
                    rango).scalar_one():
        raise c.Abortado('Hay raciones en el rango ficticio sin manifiesto; revisar antes de simular.')
    servidas = conn.execute(text(f'SELECT COUNT(*) FROM `{c.DEMO}`.comidas WHERE id IN (1,2,3,4) AND estado=1')).scalar_one()
    if servidas != 4:
        raise c.Abortado('El catálogo de comidas QA es incompatible; no se simula.')
    if fecha >= date.today() + timedelta(days=365):
        raise c.Abortado('Fecha fuera de rango.')


def insertar_padron(conn, fecha, personas):
    conn.execute(text(
        f'INSERT INTO `{c.DEMO}`.turnos (id,nombre_turno,hora_inicio,hora_fin,duracion_horas,categoria_id) '
        "VALUES (:id,'Simulación día completo 24 h','00:00:00','23:59:59',24,9001)"), {'id': TURNO})
    conn.execute(text(
        f'INSERT INTO `{c.DEMO}`.turno_comida (id,turno_id,comida_id,dia_relativo) VALUES (:id,:turno,:comida,0)'),
        [{'id': TURNO * 100 + cid, 'turno': TURNO, 'comida': cid} for cid in COMIDAS])
    conn.execute(text(f'INSERT INTO `{c.DEMO}`.users (id,name,categoria_id) VALUES (:usuario_id,:login,:categoria_id)'),
                 personas)
    conn.execute(text(
        f'INSERT INTO `{c.DEMO}`.personas (id,user_id,nombre_completo,carnet_identidad,tipo_trabajador,'
        "numero_tipo_salario) VALUES (:usuario_id,:usuario_id,:nombre,:carnet,'Simulado',:legajo)"), personas)
    conn.execute(text(
        f'INSERT INTO `{c.DEMO}`.usuario_servicios (id,usuario_id,servicio_id,estado,fecha_ingreso) '
        'VALUES (:usuario_id,:usuario_id,:servicio_id,1,:fecha)'),
        [{**p, 'fecha': fecha - timedelta(days=30)} for p in personas])
    conn.execute(text(
        f'INSERT INTO `{c.DEMO}`.turnos_asignados (id,usuario_id,servicio_id,area_id,fecha,estado,'
        "es_intercambio,turno_id) VALUES (:id,:usuario_id,:servicio_id,NULL,:fecha,'ACTIVO',0,:turno)"),
        [{**p, 'id': ASIGNACION_BASE + p['usuario_id'] - PRIMER_USUARIO + 1, 'fecha': fecha, 'turno': TURNO}
         for p in personas if p['con_turno']])


def guardar(manifiesto):
    MANIFIESTO.write_text(json.dumps(manifiesto, indent=1, ensure_ascii=False, default=str), encoding='utf-8')


def registrar_dia(motor, eventos, cuentas, manifiesto):
    from app.core import reloj
    from app.logica.intervencion import ErrorIntervencion, identificar_lectura
    from app.logica.marcacion import registrar_marcacion

    esperado = {'normal': (True, None), 'duplicado': (False, 'duplicado'),
                'fuera_horario': (False, 'fuera_horario'), 'no_reconocida': (False, 'no_identificado')}
    resultados = manifiesto['resultados']
    for numero, evento in enumerate(eventos, 1):
        momento = evento['momento']
        with patch.object(reloj, 'ahora', lambda: momento), Session(motor, expire_on_commit=False) as sesion:
            leido = None if evento['tipo'] == 'no_reconocida' else evento['usuario_id']
            r = registrar_marcacion(sesion, usuario_id=leido, momento=momento,
                                    dispositivo=DISPOSITIVO, metodo='biometrico')
        fila = {'n': numero, 'momento': momento.isoformat(), 'tipo': evento['tipo'],
                'usuario_id': evento['usuario_id'], 'comida_id': evento['comida_id'],
                'lectura_id': r.lectura_id, 'asistencia_id': r.asistencia_id,
                'valido': r.valido, 'motivo': r.motivo}
        if r.lectura_id:
            manifiesto['lecturas'].append(r.lectura_id)
        if r.asistencia_id:
            manifiesto['asistencias'].append(r.asistencia_id)
        if evento['tipo'] in esperado:
            fila['coincide'] = (r.valido, r.motivo) == esperado[evento['tipo']]
        else:  # sin turno: cualquier rechazo con motivo de derecho
            fila['coincide'] = not r.valido and r.motivo not in (None, 'duplicado', 'no_identificado')

        if evento['tipo'] == 'no_reconocida' and r.lectura_id:
            despues = momento + timedelta(minutes=evento['demora_min'])
            try:
                with patch.object(reloj, 'ahora', lambda: despues), Session(motor, expire_on_commit=False) as sesion:
                    respuesta = identificar_lectura(sesion, cuenta_id=cuentas[evento['cuenta']],
                                                    lectura_id=r.lectura_id, usuario_id=evento['usuario_id'],
                                                    clave=str(uuid.uuid4()))
                datos = respuesta if isinstance(respuesta, dict) else vars(respuesta)
                fila['identificacion'] = {'cuenta': evento['cuenta'], 'momento': despues.isoformat(),
                                          'valido': datos.get('valido'), 'asistencia_id': datos.get('asistencia_id')}
                if datos.get('asistencia_id'):
                    manifiesto['asistencias'].append(datos['asistencia_id'])
                fila['coincide'] = fila['coincide'] and datos.get('valido') is True
            except ErrorIntervencion as error:
                fila['identificacion'] = {'cuenta': evento['cuenta'], 'error': str(error)}
                fila['coincide'] = False
        resultados.append(fila)
        if numero % 20 == 0:
            guardar(manifiesto)
    guardar(manifiesto)


def simular(motor, fecha, cantidad, semilla, aplicar):
    if MANIFIESTO.exists():
        raise c.Abortado('Ya hay un día simulado (simulacion_dia.json); limpiarlo antes de otro.')
    azar = random.Random(f'{semilla}-{fecha}')
    personas = padron(cantidad, azar)
    eventos = plan_del_dia(fecha, personas, azar)
    with motor.connect() as conn:
        comprobar_libre(conn, cantidad, fecha)
        cuentas = dict(conn.execute(text(
            "SELECT username,id FROM usuarios_sistema WHERE username IN ('cocinera1','cocinera2','cocinera3') "
            "AND rol='cocinera' AND activo=1 AND eliminada_en IS NULL")).all())
    if len(cuentas) != 3:
        raise c.Abortado('Faltan las cuentas cocinera1, cocinera2 y cocinera3 activas.')
    print(f'{"Simulando" if aplicar else "Simularía"} el {fecha:%d/%m/%Y}: {cantidad} comensales con turno '
          f'de cuatro comidas y {SIN_TURNO} sin turno (usuario_id {PRIMER_USUARIO}–{PRIMER_USUARIO + len(personas) - 1}).')
    resumen_plan(eventos)
    if not aplicar:
        print('Simulacro: no se escribió nada. Repetir con --aplicar.')
        return

    manifiesto = {'marca': MARCA, 'base': c.SIM, 'demo': c.DEMO, 'fecha': fecha.isoformat(),
                  'usuarios': [PRIMER_USUARIO, PRIMER_USUARIO + len(personas) - 1], 'turno': TURNO,
                  'semilla': semilla, 'creado': datetime.now().isoformat(timespec='seconds'),
                  'lecturas': [], 'asistencias': [], 'resultados': []}
    # El manifiesto va antes del commit: si el commit fallara, la limpieza no encuentra filas.
    guardar(manifiesto)
    with motor.begin() as conn:
        insertar_padron(conn, fecha, personas)
    registrar_dia(motor, eventos, cuentas, manifiesto)

    resultados = manifiesto['resultados']
    fallos = [r for r in resultados if not r['coincide']]
    print(f'Registradas {len(manifiesto["lecturas"])} lecturas y {len(manifiesto["asistencias"])} raciones.')
    if fallos:
        print(f'ATENCIÓN: {len(fallos)} eventos no dieron el resultado esperado:')
        for r in fallos[:20]:
            print('  ', json.dumps(r, ensure_ascii=False))
    else:
        print('Todos los eventos dieron el resultado esperado por las reglas.')


def limpiar(motor, aplicar):
    if not MANIFIESTO.exists():
        raise c.Abortado('No hay simulacion_dia.json: no hay día simulado que limpiar.')
    datos = json.loads(MANIFIESTO.read_text(encoding='utf-8'))
    if datos.get('marca') != MARCA or datos.get('base') != c.SIM or datos.get('demo') != c.DEMO:
        raise c.Abortado('Manifiesto ajeno a esta herramienta; no se borra nada.')
    primero, ultimo = datos['usuarios']
    if not PRIMER_USUARIO <= primero <= ultimo <= ULTIMO_POSIBLE or datos['turno'] != TURNO:
        raise c.Abortado('Manifiesto fuera del rango ficticio; no se borra nada.')
    rango = {'a': primero, 'b': ultimo, 'd': DISPOSITIVO, 't': TURNO}
    pasos = [
        ('intervenciones_lectura', 'lectura_id IN :ids'),
        ('asistencias', 'usuario_id BETWEEN :a AND :b'),
        ('lecturas_biometricas', 'dispositivo=:d'),
        (f'{c.DEMO}`.`turnos_asignados', 'usuario_id BETWEEN :a AND :b AND turno_id=:t'),
        (f'{c.DEMO}`.`usuario_servicios', 'usuario_id BETWEEN :a AND :b'),
        (f'{c.DEMO}`.`personas', 'id BETWEEN :a AND :b'),
        (f'{c.DEMO}`.`users', 'id BETWEEN :a AND :b'),
        (f'{c.DEMO}`.`turno_comida', 'turno_id=:t'),
        (f'{c.DEMO}`.`turnos', 'id=:t'),
    ]
    with motor.begin() as conn:
        lecturas = set(conn.execute(text('SELECT id FROM lecturas_biometricas WHERE dispositivo=:d FOR UPDATE'),
                                    rango).scalars())
        asistencias = set(conn.execute(text('SELECT id FROM asistencias WHERE usuario_id BETWEEN :a AND :b FOR UPDATE'),
                                       rango).scalars())
        if lecturas - set(datos['lecturas']) or asistencias - set(datos['asistencias']):
            raise c.Abortado('Hay filas en el rango que no figuran en el manifiesto; revisar antes de borrar.')
        rango['ids'] = sorted(lecturas) or [0]

        def sentencia(sql):
            return text(sql).bindparams(bindparam('ids', expanding=True)) if ':ids' in sql else text(sql)
        conteos = {t.split('`.`')[-1]: conn.execute(sentencia(f'SELECT COUNT(*) FROM `{t}` WHERE {f}'), rango).scalar_one()
                   for t, f in pasos}
        print(f'{"Borrando" if aplicar else "Borraría"} el día simulado del {datos["fecha"]}: '
              + ', '.join(f'{t} {n}' for t, n in conteos.items()))
        if not aplicar:
            print('Simulacro: no se borró nada. Repetir con --aplicar.')
            return
        for tabla, filtro in pasos:
            borradas = conn.execute(sentencia(f'DELETE FROM `{tabla}` WHERE {filtro}'), rango).rowcount
            if borradas != conteos[tabla.split('`.`')[-1]]:
                raise c.Abortado('El borrado no coincide con lo contado; rollback.')


def permisos(limpieza):
    verbo = 'DELETE' if limpieza else 'INSERT'
    return c.permisos(
        *((c.DEMO, t, verbo) for t in ('turnos', 'turno_comida', 'users', 'personas',
                                        'usuario_servicios', 'turnos_asignados')),
        *((c.SIM, t, verbo) for t in ('lecturas_biometricas', 'asistencias', 'intervenciones_lectura')),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--fecha', type=fecha_argumento, help='AAAA-MM-DD; por defecto, la del laboratorio')
    parser.add_argument('--comensales', type=int, default=80, help='padrón con turno (10 a 900)')
    parser.add_argument('--semilla', default='qa', help='la misma semilla repite el mismo día')
    parser.add_argument('--limpiar', action='store_true', help='borrar el día simulado')
    parser.add_argument('--aplicar', action='store_true', help='escribir de verdad')
    args = parser.parse_args()
    if not 10 <= args.comensales <= 900:
        parser.error('--comensales va de 10 a 900.')

    permitidas = permisos(args.limpiar) if args.aplicar else ()
    with c.bloqueo_corrida(), c.entorno_seguro(permitidas) as (motor, _huella, _servidor), c.app_sin_dotenv():
        if args.limpiar:
            limpiar(motor, args.aplicar)
            if args.aplicar:
                MANIFIESTO.unlink()
        else:
            simular(motor, args.fecha or fecha_del_laboratorio(), args.comensales, args.semilla, args.aplicar)
        if args.aplicar:
            print('Hecho. No hace falta reiniciar la API.')


if __name__ == '__main__':
    c.ejecutar(main)
