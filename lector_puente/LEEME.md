# Puente del lector biométrico

Programa que corre en la PC de cocina. Lee el lector, manda cada huella a la API
(`POST /lector/lecturas`) y muestra el resultado a la cocinera.

Lector previsto: **ZKTeco ZK9500** (primera opción) o **ZK4500**, por USB. Estos
lectores solo *capturan* la huella: la comparación la hace el SDK ZKFinger en la PC,
contra las huellas enroladas que el puente carga de la API.

```
Arranque:   puente ── GET /lector/plantillas ──► API          (huellas enroladas)
            puente ── carga en el SDK ZKFinger (memoria de la PC)
Cada dedo:  ZK9500 ── captura ──► SDK compara 1:N ──► identificador ──► POST /lector/lecturas
                                                                         (derecho, horario, duplicado)
Sin red:    reintenta 2 min ──► pendientes.csv (la jefa registra a mano con su hora real)
```

## Cómo funciona

- **Cada huella enrolada es un vínculo**: `personal` (una persona del padrón) o
  `policia` (sin persona). Una huella que no coincide con ninguna se registra como
  *no reconocida* y la cocinera la identifica en su pantalla, como hoy.
- **Policías: vía libre.** Su huella da una ración en la columna Policías en cada
  lectura (sin turno, derecho ni duplicado; solo dentro de un horario de comida).
  No aparecen en historiales ni en el padrón.
- **La hora la pone el servidor**, nunca la PC (regla anti-antedatado).
- **Reintentos seguros**: cada huella lleva una `Idempotency-Key`; si la red falla,
  el puente reintenta la misma y la API no la registra dos veces.
- **Nada se pierde en silencio**: si la API no responde en 2 minutos, el puente
  avisa «SIN CONEXIÓN» y anota la lectura en `pendientes.csv`.
- **Huellas nuevas**: el puente vuelve a cargar las plantillas cada minuto.

## Instalación en la PC de cocina (una vez)

1. Instalar **Python 3.10+** (marcar «Add to PATH»).
2. Instalar el **ZKFinger SDK for Windows** de ZKTeco (trae el driver del ZK9500/ZK4500).
3. Conectar el lector por USB: debe encender su luz.
4. `pip install -r requirements-zkteco.txt`
5. `copy puente.ini.ejemplo puente.ini` y completar `url` y `clave`.

Si al abrir aparece «Falta libzkfp.dll», el SDK del punto 2 no está instalado.

## En la API (antes de ir)

- [ ] `alembic upgrade head` (crea `vinculos_lector`, `solicitudes_lector`, `raciones_policia`).
- [ ] Clave del lector: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
- [ ] `.env`: `LECTORES=cocina-01=<esa clave>`; reiniciar la API. La misma clave en `puente.ini`.
- [ ] La columna **Policías** activa en `categorias_reporte` (si no, la huella de un policía se rechaza).

## Prueba en el hospital

### 1. Enrolar 3 personas y 1 policía (con el puente CERRADO)
```powershell
python enrolar.py --usuario jefa
```
Opción 1 (personal): buscar a la persona por nombre, apoyar el **mismo dedo 3 veces**.
Opción 2 (policía): solo los 3 apoyos. Un dedo ya enrolado se rechaza.

### 2. Abrir el puente
```powershell
python puente.py      # «Conectado como cocina-01 · … · N huellas cargadas en el lector.»
```

### 3. Las pruebas (dentro de un horario de comida)
| Prueba | Esperado en el puente | Esperado en la app |
|---|---|---|
| Persona enrolada con derecho | `OK Almuerzo: NOMBRE` | Supervisión: aceptada |
| La misma persona otra vez | `NO … Ya recibió esta comida` | Rechazada · duplicado |
| Dedo sin enrolar | `NO … Huella no reconocida` | La cocinera la identifica |
| Policía | `OK Almuerzo: Policía` (cada vez) | Reportes: columna Policías |
| Desconectar la red 1 minuto | reintenta y registra | sin duplicados |

### 4. Si el aparato no funciona
- `adaptador = prueba` en `puente.ini` permite escribir identificadores a mano y
  verificar toda la cadena con la API («-» = huella no reconocida).
- `puente.log` guarda los errores de conexión; `pendientes.csv`, lo que no llegó.
- Lo único que habla con el aparato es `SdkZK` en `zkteco.py`.

## Archivos

| Archivo | Qué es |
|---|---|
| `puente.py` | El puente: lectura, envío con reintentos, pendientes |
| `zkteco.py` | Adaptador ZK9500/ZK4500 (SDK ZKFinger vía `pyzkfp`) |
| `enrolar.py` | Enrolar huellas con el ZKTeco: personal o policía |
| `adaptadores.py` | `zkteco`, `teclado` (lectores que escriben un número), `prueba` |
| `vincular.py` | Vincular números de lectores que reconocen solos (terminales) |
| `puente.ini.ejemplo` | Configuración; copiar a `puente.ini` (no se sube a git) |
| `test_puente.py`, `test_zkteco.py` | Pruebas: `python -m pytest` |
