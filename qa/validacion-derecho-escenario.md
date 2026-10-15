# Validación inmediata: el servidor concede el derecho (escenario sintético)

> **Documento histórico: consultar el resultado de ejecución al final y `INTEGRACION.md`.** Lo «esperado» sale de leer el código (develop 52afda2 y
> `feat/escenario-sintetico` 693ed5c). Se ejecuta después de que el preparador de A2 haya
> incorporado el comensal y las cuentas en las bases autorizadas.
> El circuito E2E y la QA por roles (`guion-e2e-intervenciones-52afda2.md`) quedan para la fase siguiente.

## Objetivo

Demostrar por HTTP que el servidor, con las reglas vigentes, concede a `usuariosimulado` (900001)
el almuerzo de la fecha F:
- sin consumir una ración (ni `POST /asistencias` ni `/identificar`),
- sin una autorización manual de jefatura (no se usa jefa ni sistemas),
- y sin tocar `reglas_derecho`.

La evidencia del preparador calcula el derecho en un subproceso con `app/consultas/derecho.py`.
Sirve como apoyo, pero **no es la prueba del servidor**: la prueba es la respuesta HTTP.

## Requisitos previos

- [ ] Las bases del escenario están autorizadas (A1 o Limbert) y el preparador terminó con salida 0.
- [ ] El servidor corre con `ENTORNO=simulacion` y `DB_NAME` / `DB_NAME_TURNOS` = las bases del escenario.
- [ ] Huella CHECKSUM ANTES de las bases protegidas (Limbert).

## Pasos

Solo se usan cuentas de cocinera, que tienen lectura de `/personal/*` (`ACCESO["personal"]`).
**No es una ejecución de solo lectura:** cada login escribe su auditoría de acceso (`intentos_login`).
Raciones, lecturas e intervenciones tienen que seguir en **cero**.

**Ejecutor:** `qa/validar_derecho_escenario.py`, corrido por la sesión de A1, que ya tiene la conexión.
El script:
- Exige exactamente `bd_nutricion_escenario_sim` y `bd_turnos_escenario_demo` en el manifiesto y en
  `GET /salud` de la API (entorno `simulacion` y revisión `e1a7c3b9d5f2`). El sufijo solo no basta.
- Toma la fecha y la ventana del manifiesto, nunca la hora real.
- Calcula el derecho de 900001 a 900007 con `app/consultas/derecho.py` sobre las bases del escenario (sin login).
- Coteja ese cálculo con el manifiesto.
- Presenta el contraste 900007 tal como es: tiene derecho sin novedad persistida, y el rechazo con
  `permiso` pertenece a la transacción revertida del preparador.
- Compara la regla vigente campo por campo. Si no puede, queda **PENDIENTE**, nunca VERDE.
- La comprobación por HTTP con cocinera2 y cocinera3 queda **PENDIENTE** mientras sus cuentas no estén
  habilitadas (sin clave o con 428). Es el único paso que queda pendiente por eso.

| # | Acción | Esperado (leído) | Obtenido |
|---|---|---|---|
| V0 | SQL de solo lectura en la `*_sim`: asistencias, lecturas e `intervenciones_lectura` de 900001..900007; y la versión vigente de `reglas_derecho` (id, `vigente_desde`, `duracion_minima_horas`, `excluir_enfermeria`) | 0 / 0 / 0; la versión es la que trae la migración | |
| V1 | Habilitación por el operador (`app.semillas.admin --username cocinera2 --resetear`, ídem cocinera3, solo con `DB_NAME` del escenario) y `POST /auth/login` | 428 por clave temporal; luego `POST /auth/cambio-password` → 200. Es un trámite de la cuenta: no es una autorización de jefatura y no crea cuentas de jefa ni de sistemas | |
| V2 | `GET /personal/900001/derecho?fecha=F` (cocinera2) | incluye `comida_id=2` (almuerzo), `fecha_comida=F`, `dia_relativo=0`, turno sintético de 12 h | |
| V3 | Lo mismo con cocinera3 | idéntico a V2 | |
| V4 | `GET /personal/{900002..900006}/derecho?fecha=F` | **no** incluye el almuerzo de F (900006 tampoco lo tiene en F; su derecho cae en F+1). Cada caso difiere del principal en un solo factor: duración, categoría, mapeo, novedad o fecha | |
| V5 | 900007 (contraste de novedad): sin novedad persistida, según `693ed5c` | incluye el almuerzo; el «con novedad» lo mide el preparador dentro de una transacción revertida | |
| V6 | `GET /pantalla/comidas-del-dia` (cocinera2) con el reloj dentro del día F, si hace falta; mover el reloj exige rol de jefatura, así que el paso se omite si no se puede sin jefa | `previstas` del almuerzo = cantidad de casos con derecho según el manifiesto | |
| V7 | Repetir V0 | **sin cambios**: 0 raciones, 0 lecturas, 0 intervenciones; `reglas_derecho` igual | |
| V7b | Cotejar V2 a V5 con «derecho esperado/obtenido» del manifiesto | coinciden caso por caso. El manifiesto es evidencia del preparador; V2 a V5 son la del servidor | |
| V8 | Huella CHECKSUM DESPUÉS (Limbert) | igual a ANTES | |

## Prohibido en esta fase

- `POST /asistencias`, en cualquier método.
- `POST /asistencias/lecturas/{id}/identificar`.
- Cuentas de jefa o de sistemas.
- Cualquier escritura en `reglas_derecho` o en `horarios_comida`.

Si algún paso necesitara una de estas cosas, se para y se reporta. No se busca un atajo.

---

## Resultado de la ejecución (15/10/2026)

**EJECUTADO** por A1 (sesión `4b`), con su conexión, tal como autorizó Limbert:
- Sin las claves de las cocineras y sin API levantada. Por eso no hubo login y nada se escribió en `intentos_login`.
- Validador: sha256 `1890e3ac4f58563b73fd4142250ee754c2ab3d8444e6a0ea7044501cfa1869d9`.
- Manifiesto: `qa/manifiesto_escenario_2026-10-15.json`, sha256 `db95821e…c5a61a`, commit `5cd80fa`.
- Salida textual sin editar: `qa/validador_salida_2026-10-15.txt`. **Código de salida 0**.
- Recuento: **25 VERDE, 3 PENDIENTE, 0 ROJO**.

Un intento anterior (sha `6bafda16…`) abortó antes de conectarse. El validador rechazaba una `DB_PASSWORD`
definida pero vacía. Se corrigió en una sola línea, igual que en el preparador. Ese intento no leyó ni escribió nada.

| Bloque | Estado |
|---|---|
| Manifiesto: bases exactas, fecha 2026-10-15 con una sola ventana de 11:00 a 15:00, commit sin cambios sin commit | VERDE |
| Raciones / lecturas / intervenciones, antes y después | VERDE (0 / 0 / 0) |
| Regla vigente (id 1, desde 2000-01-01, mínimo 12 h, excluye enfermería, anulan: baja médica, licencia, permiso, vacación), campo por campo; reglas sin cambios | VERDE |
| cocinera2 (id 1) y cocinera3 (id 2): rol cocinera, activas, sin vínculo, `debe_cambiar=True` | VERDE (estado en el manifiesto) |
| Derecho con `app/consultas/derecho.py` sobre las bases del escenario = manifiesto: 900001 con almuerzo; 900002–900006 sin almuerzo | VERDE |
| 900007: con almuerzo sin novedad persistida; sin almuerzo con `permiso` en la transacción revertida del preparador (persistida 0) | VERDE |
| `GET /salud`: la API apunta al escenario | **VERDE** (15/10, 12:42; GET sin login, por A3): la API del escenario en `http://127.0.0.1:8765` (no en el 8000) responde 200, entorno `simulacion`, `bd_nutricion_escenario_sim` / `bd_turnos_escenario_demo`, revisión `e1a7c3b9d5f2`, 12 tablas propias, 9 vistas, sin faltantes, reloj no simulado |
| Login y `GET /personal/{id}/derecho` con **cocinera2** | **PENDIENTE**: sin evidencia HTTP. Existe `qa/habilitar_cocineras_escenario.py` (API en 8765), pero no hay salida de su ejecución |
| Login y `GET /personal/{id}/derecho` con **cocinera3** | **PENDIENTE**: lo mismo que cocinera2 |

Huellas CHECKSUM tomadas por A1, antes y después, sin cambios:
- `bd_proyecto_backend` `f5eb97fceccdab88`
- `bd_turnos_demo` `6bb572af7f0447f2`

El preparador además registró `bd_nutricion` `0b148f96edaf929c` y `bd_nutricion_sim` `f0ffa17c110944b6`.
Alembic `e1a7c3b9d5f2`.

**Alcance de lo demostrado:** el derecho sale del **código del servidor** (la misma función que usa
`GET /personal/{id}/derecho`) ejecutado sobre las bases del escenario. La respuesta HTTP del servidor en
marcha **todavía no se comprobó**. Para hacerlo hacen falta las cuentas habilitadas y una API autorizada
con `ENTORNO=simulacion`.

La QA formal por roles y el circuito de entrega siguen aplazados.
