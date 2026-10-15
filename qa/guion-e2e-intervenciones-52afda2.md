# Guion E2E y QA por roles: intervenciones de cocina (develop 52afda2)

> **Estado: PREPARADO, NO EJECUTADO.**
> Todo lo que dice «esperado» sale de LEER el código de 52afda2. No es un resultado de ejecución.
> La columna «Obtenido» se llena solo al ejecutar, con evidencia (status, cuerpo, conteo SQL o captura).
> Mientras esté vacía, el paso no está verificado.

> **Fase siguiente, en espera.** Antes va `validacion-derecho-escenario.md`.
> **Discrepancia de los controles negativos: resuelta contra el commit, pendiente del manifiesto.**
> La versión anterior de este guion se basó en un preparador sin casos negativos. El commit `693ed5c`
> de `feat/escenario-sintetico` (que sigue a `ce54644`) **sí los contempla**: 900002 (turno de 8 h),
> 900003 (Enfermería, 12 h), 900004 (12 h sin `turno_comida`), 900005 (novedad `permiso`),
> 900006 (asignación al día siguiente) y el contraste 900007.
> El manifiesto real (`docs\escenario-sintetico\manifiesto-<F>.json`) **todavía no existe**: el preparador no se ha corrido.
> Lo que sigue sale del código del commit. Ninguno de estos controles está ejecutado.

Código leído: `comedorback/app/logica/intervencion.py`, `app/api/asistencias.py`,
`app/api/intervenciones.py`, `app/consultas/servicio.py`, `app/consultas/derecho.py`,
`app/core/permisos.py`, `comedorfront/src/permisos.js`, `src/navegacion.js`,
y `scripts/preparar_escenario_sintetico.py` (rama `feat/escenario-sintetico`).
Alembic head del código: `e1a7c3b9d5f2`.

---

## 0. Compuertas

No se ejecuta nada hasta que se cumplan las dos. Las confirma Limbert en el chat; no se suponen.

### G1: A1, migración verificada y aislamiento
- [ ] Bases del escenario dedicadas: por defecto `bd_turnos_escenario_demo` y `bd_nutricion_escenario_sim`.
      Nunca `bd_nutricion`, `bd_proyecto_backend`, `bd_turnos_demo` ni `bd_nutricion_sim`
      (las dos últimas son copias de datos reales).
- [ ] `alembic current` sobre la `*_sim` del escenario = `e1a7c3b9d5f2` (head), con evidencia.
- [ ] El servidor corre con `ENTORNO=simulacion`, `DB_NAME` = la `*_sim` y `DB_NAME_TURNOS` = la `*_demo` del escenario.
      `GET /simulacion/reloj` responde 200.
- [ ] Huella CHECKSUM ANTES de las bases protegidas que existan (`bd_proyecto_backend` como mínimo). La toma Limbert.

### G2: A2, escenario validado (manifiesto de `693ed5c`)
Según el código del commit (se confirma con el manifiesto real), para la `--fecha` F:
- `usuariosimulado` = users.id **900001**, categoría «Administrativo», sin cuenta de acceso.
  Turno de **12 h** que da derecho al **almuerzo** (comida_id 2) del mismo día, sin novedades.
- Las cuentas `cocinera2` y `cocinera3`, de rol cocinera, independientes, con clave temporal (`debe_cambiar=1`).
  Con `--claves-sin-revelar`, el operador las habilita en su consola con `app.semillas.admin --resetear`,
  solo sobre la base del escenario. El primer login responde 428 y hay que cambiar la clave.
- Casos negativos 900002 a 900006 y contraste 900007 (ver §4).
- **No se crean jefa ni sistemas en esta etapa.** P8 y la QA de jefa y root (§5) necesitan esas cuentas
  más adelante; hasta entonces quedan **NO EJECUTABLES**.

Hay que confirmar con el manifiesto real:
- [ ] Revisión del código, ids, rol y estado de las cuentas, regla vigente y ventana del almuerzo
      (una sola), derecho esperado = obtenido en cada caso, aislamiento y huellas.
- [ ] La entrega de cocinera3 (P7): **otra ocurrencia válida de 900001** (otra `--fecha`) o un
      segundo comensal sintético, lo que el manifiesto permita. No es un requisito aparte.

---

## 1. Distinciones que el reporte tiene que respetar

1. **409 `lectura_ya_resuelta` no cambia la responsable.** La asistencia y la fila `registrada`
   siguen a nombre de la cocinera que entregó primero. El intento de la otra cocinera **sí puede
   quedar auditado** como fila `rechazada` a su nombre, con `resuelta_por_mi=false`. Esa fila es
   auditoría del intento: no es una entrega ni un cambio de responsable.
2. **200 con `valido=false` es un rechazo de negocio**, no un error de la API: `sin_derecho` y `duplicado`
   responden 200 con `resultado="rechazada"`. Los conflictos sobre la lectura o el servicio responden 409.
   Las dos cosas se reportan por separado.
3. **Supervisión es de solo lectura, pero el permiso manual antiguo sigue vigente.** En la interfaz,
   Supervisión no tiene «Autorizar» ni «Registrar ración manual» (cd21f8c). En la API, la jefa
   **sigue pudiendo** `POST /asistencias` con `metodo="manual"` (`MARCACION_MANUAL = JEFATURA`,
   no cambió a propósito). Ninguna de las dos cosas se reporta como la otra.
4. **Cada rechazo temporal se verifica por separado**, con su propia lectura, su propio
   movimiento de reloj y su propio motivo esperado:
   `servicio_distinto`, `lectura_no_resoluble` (lectura `fuera_horario`) y `reloj_inconsistente`.
   Ninguno se infiere de otro.

---

## 2. Preparación (después de G1 y G2)

| # | Acción | Esperado (leído) | Obtenido |
|---|---|---|---|
| 2.1 | Login de cocinera2 y cocinera3 con clave temporal | 428; cambio de clave → 200 con token | |
| 2.2 | Login de la jefa (y de sistemas) | 200 | |
| 2.3 | `PUT /simulacion/reloj {momento: inicio de la ventana del almuerzo en F + 5 min, congelar: true}` (jefa) | 200, `simulado=true`, `congelado=true` | |
| 2.4 | `GET /personal/900001/derecho?fecha=F` (jefa) | incluye almuerzo (2) | |
| 2.5 | Raciones de 900001 en (2, F) en la `*_sim` | 0 | |

Cada intento lleva una clave UUID v4 nueva: `python -c "import uuid;print(uuid.uuid4())"`.

---

## 3. Caso principal

| # | Acción | Esperado (leído) | Obtenido |
|---|---|---|---|
| P1 | `POST /asistencias {"metodo":"biometrico"}` sin `usuario_id` (cocinera2) | 200, `valido=false`, `motivo="no_identificado"`, `lectura_id=L1`, sin `asistencia_id`. «Huella mojada» es solo narrativa: no se guarda ningún diagnóstico | |
| P1b | Foto de `lecturas_biometricas` id=L1 | `usuario_id NULL`, `resultado='rechazada'`, `motivo='no_identificado'` | |
| P1c | `GET /pantalla/lecturas-por-identificar` (cocinera2) | incluye L1 | |
| P2 | `POST /asistencias/lecturas/L1/identificar`, `Idempotency-Key: K1`, body **solo** `{"usuario_id":900001}` (cocinera2) | 200, `valido=true`, `resultado="registrada"`, `reintento=false`, `asistencia_id=A1`, `intervencion_id=I1`, comida 2, fecha F | |
| P2x | **Control de campos extra:** el mismo body más `"motivo"` o `"descripcion"`, con la clave K1x (cocinera2) | **422** (`extra="forbid"`); 0 filas nuevas en `intervenciones_lectura` y en `asistencias` | |
| P3 | SQL: raciones de 900001 en (2, F) | 1 | |
| P3b | SQL: asistencia A1 | `metodo='manual'`, `lectura_id=L1`, `registrado_por_cuenta=cocinera2` | |
| P3c | SQL: lectura L1 | idéntica a la foto de P1b | |
| P3d | SQL: `intervenciones_lectura` con `lectura_id=L1` | 1 fila: cocinera2, `registrada`, `asistencia_id=A1` | |
| P4 | Repetir P2 tal cual: misma K1 y mismo body | 200, `reintento=true`, mismos I1 y A1; los conteos de P3 no cambian | |
| P4b | K1 con otro `usuario_id` | 409 `clave_reutilizada_con_otro_contenido`; sin filas nuevas | |
| P5 | `.../L1/identificar`, clave K2, `{"usuario_id":900001}` (**cocinera3**) | **409 `lectura_ya_resuelta`**, `resuelta_por_mi=false` | |
| P5b | SQL después de P5 | raciones = 1; A1 sigue con `registrado_por_cuenta=cocinera2`; la fila `registrada` de L1 sigue siendo de cocinera2; **puede haber 1 fila `rechazada` (`lectura_ya_resuelta`) de cocinera3**. Ver distinción 1 | |
| P6 | `POST /asistencias {"metodo":"biometrico"}` → L2; `.../L2/identificar`, clave K3, `{"usuario_id":900001}` | **200, `valido=false`**, `resultado="rechazada"`, `motivo="duplicado"`, sin `asistencia_id`. Ver distinción 2 | |
| P6b | SQL después de P6 | raciones = 1; L2 sin cambios y sin asistencia; L2 sigue pendiente | |
| P7 | Entrega de cocinera3 con lo que fije el manifiesto (otra ocurrencia de 900001 u otro comensal sintético): lectura nueva L3 dentro de su ventana; `.../L3/identificar`, clave K4 (**cocinera3**) | 200 `registrada`, asistencia A2 con `registrado_por_cuenta=cocinera3`, `lectura_id=L3`; A1 sigue con cocinera2 | |
| P8 | `GET /intervenciones-cocina?desde=F&hasta=F'` (jefa) | I1 con `decision_original` = {L1, `rechazada`, `no_identificado`}, `cuenta`=cocinera2, `resultado_final.entrega_registrada=true`, `asistencia_id=A1`, `estado_actual_lectura="resuelta"`. También aparecen P5 (cocinera3, rechazada), P6 (duplicado) y P7 (cocinera3, registrada). Los `totales` cuadran | |
| P8b | Mismo GET con `cuenta_id=cocinera2` y con `cuenta_id=cocinera3` | cada filtro trae solo las filas de esa cuenta | |
| P8c | `POST .../L2/identificar` con el token de la **jefa**, y con el de **sistemas** | 403 `rol_no_autorizado` | |
| P8d | `GET /pantalla/lecturas-por-identificar` (jefa) | 403 | |
| P8e | `GET /intervenciones-cocina` con cocinera2 y con sistemas | 403 | |

---

## 4. Controles negativos

Cada control usa una lectura nueva `no_identificado`, una clave nueva y cocinera2.
Lo que se exige en todos:
- Sin asistencia nueva.
- La lectura queda idéntica.
- Exactamente una fila `rechazada` con el motivo esperado y `cuenta_id` = cocinera2.

### 4.1 Derecho: respuesta 200 con `valido=false` (rechazo de negocio)

Casos de `693ed5c`. Cada uno difiere del principal (900001) en **un solo factor**. Los cuatro
primeros tienen turno de **12 h**: con ellos se prueba que un turno de 12 h no evita la
comprobación. El de duración es el control aparte. Todos devuelven el mismo motivo,
`sin_derecho`: la respuesta no dice la causa. La causa sale del factor único y del derecho
esperado = obtenido del manifiesto.

| # | Comensal | Factor distinto | Esperado (leído) | Obtenido |
|---|---|---|---|---|
| N1 | 900003 | categoría Enfermería (12 h, `excluir_enfermeria` vigente) | 200, `valido=false`, `sin_derecho` | |
| N2 | 900005 | novedad `permiso` guardada sobre su asignación de 12 h | 200, `valido=false`, `sin_derecho` | |
| N3 | 900004 | turno de 12 h sin `turno_comida` (no mapea al almuerzo) | 200, `valido=false`, `sin_derecho` | |
| N3b | 900006 | asignación de 12 h en F+1 (otra fecha) | 200, `valido=false`, `sin_derecho` | |
| N0 | 900002 | turno de 8 h (control de duración, adicional) | 200, `valido=false`, `sin_derecho` | |
| N2c | 900007 | contraste: sin novedad persistida, **tiene** derecho | solo lectura: `/personal/900007/derecho` incluye el almuerzo. NO se identifica (consumiría una ración). El «con novedad» lo midió el preparador en una transacción revertida | |

### 4.2 Rechazos temporales: 409, cada uno por separado

Usan 900001: tiene derecho válido, y la comprobación del servicio va ANTES del derecho y del duplicado.
Se corren al final, porque mueven el reloj.

| # | Montaje | Esperado (leído) | Obtenido |
|---|---|---|---|
| T1 fuera de ventana efectiva | lectura dentro de la ventana; `PUT /simulacion/reloj` a `fin + 1 min`; identificar | **409 `servicio_distinto`**; `servicio_usado` = almuerzo F | |
| T2 lectura fuera de horario | reloj fuera de toda ventana; `POST /asistencias` biométrico | la marcación responde `motivo="fuera_horario"` (no `no_identificado`); al identificarla: **409 `lectura_no_resoluble`** | |
| T3 reloj retrocedido | lectura dentro de la ventana; reloj puesto ANTES de su `fecha_hora`; identificar | **409 `reloj_inconsistente`** | |

---

## 5. QA formal por roles (navegador obligatorio)

Las pruebas de API **no sustituyen** esta parte. Cada fila necesita una captura o una
observación directa en el navegador. Si no hay navegador disponible, la fila queda
**NO VERIFICADA** y no se da por buena con la API.

### Cocinera (cocinera2 / cocinera3): sección Control Biométrico
| Verificación | Esperado (leído) | Obtenido |
|---|---|---|
| Menú | solo «Control Biométrico» | |
| Lectura no reconocida | aparece para identificar; se busca a la persona y se confirma sin campo de nota ni de motivo | |
| Duplicado y sin derecho | se muestran como rechazo, no como error del sistema | |
| Sin modo manual | no se ofrece «Modo manual» | |

### Jefa: sección **Supervisión**
| Verificación | Esperado (leído) | Obtenido |
|---|---|---|
| Contenido | comidas del día, últimas marcaciones e intervenciones de cocina, con pestañas, filtros, búsqueda, actualización y paginación | |
| Solo lectura | ningún botón «Autorizar» ni «Registrar ración manual» | |
| Intervenciones | se ve el rechazo original de L1, la entrega A1 y la responsable cocinera2; el intento de cocinera3 aparece como rechazado, sin cambiar la responsable | |
| Otras secciones | Resumen, Historial, Reportes y Cuentas abren sin error | |

### Sistemas (root): las tres secciones aprobadas
| Sección | Esperado (leído) | Obtenido |
|---|---|---|
| **Reglas del sistema** (`reglas`) | abre; horarios versionados por fecha, sin edición hacia atrás | |
| **Administración** (`admin`) | abre; cuentas del comedor | |
| **Lector biométrico** (`monitoreo`) | abre; estado del lector | |
| Menú | solo esas tres; sin Supervisión ni intervenciones (en la API, 403) | |

---

## 6. Cierre

| # | Acción | Esperado | Obtenido |
|---|---|---|---|
| C1 | `DELETE /simulacion/reloj` | reloj real | |
| C2 | SQL: asistencias nuevas en la `*_sim` | solo A1 y A2 | |
| C3 | SQL: fotos de L1..Ln | ninguna lectura modificada | |
| C4 | Huella CHECKSUM DESPUÉS de las bases protegidas (Limbert) | igual a la de ANTES; si cambia, se para todo y se reporta | |

## 7. Reglas del reporte

- Cada paso tiene «Esperado» (leído) y «Obtenido» (ejecutado, con evidencia).
  Un paso sin «Obtenido» se reporta **sin ejecutar**, nunca como VERDE.
- Un ROJO se reporta tal cual. En esta pasada no se corrige código y el paso no se repite «hasta que pase».
- Al final se listan las desviaciones del manifiesto y lo que quedó NO EJECUTADO o NO VERIFICADO, con su causa.
