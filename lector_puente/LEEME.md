# Puente del lector biométrico

Programa que corre en la PC de cocina. Lee el lector, manda cada huella a la API
(`POST /lector/lecturas`) y muestra el resultado a la cocinera. Solo necesita
Python 3.10+ (sin paquetes extra).

```
Lector ──► puente.py (PC de cocina) ──► API /lector/lecturas ──► misma marcación de siempre
              │                                                (derecho, horario, duplicado)
              └─ sin conexión 2 min ──► pendientes.csv (la jefa registra a mano)
```

## Cómo funciona

- **El lector entrega un número** por huella: el número de usuario de una terminal
  o el id de plantilla de un programa USB. La API lo traduce a la persona con
  `vinculos_lector`. Un número sin vínculo se registra como *huella no
  reconocida* y la cocinera la identifica en su pantalla, como hoy.
- **La hora la pone el servidor**, nunca la PC (regla anti-antedatado).
- **Reintentos seguros**: cada huella lleva una `Idempotency-Key`; si la red
  falla, el puente reintenta la misma y la API no la registra dos veces.
- **Nada se pierde en silencio**: si la API no responde en 2 minutos, el puente
  avisa «SIN CONEXIÓN» y anota la lectura en `pendientes.csv` con su hora real.

## Prueba en el hospital (viernes)

### 0. Antes de salir
- [ ] En la API (`comedorback`): `alembic upgrade head` (crea `vinculos_lector` y `solicitudes_lector`).
- [ ] Generar la clave del lector: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
- [ ] En el `.env` de la API: `LECTORES=cocina-01=<esa clave>` y reiniciar la API.

### 1. Identificar el aparato (anotar)
- Marca y modelo: ____________ · Conexión: USB / red · ¿Trae SDK o CD? ____
- Abrir el **Bloc de notas**, apoyar un dedo enrolado: **¿aparece un número y salta de línea?**
  - **Sí** → modo teclado: el puente funciona tal cual (`adaptador = teclado`).
  - **No** → hace falta un adaptador para ese modelo (`adaptadores.py`). Traer el
    manual o el SDK; el resto (API, vínculos, puente) ya está listo y probado.

### 2. Configurar el puente en la PC de cocina
```powershell
cd lector_puente
copy puente.ini.ejemplo puente.ini   # completar url y clave
python puente.py                     # debe decir: Conectado como cocina-01 · ...
```
Si dice «Clave del lector rechazada», la clave de `puente.ini` no es la de `LECTORES`.

### 3. Vincular 3 personas de prueba
1. Enrolar la huella en el lector y anotar el número que muestra.
2. `python vincular.py --api http://<servidor>:8000 --usuario jefa` → opción 1,
   escribir el número, buscar a la persona por nombre y elegirla.

### 4. Las tres huellas (dentro de un horario de comida)
| Prueba | Esperado en el puente | Esperado en Supervisión |
|---|---|---|
| Persona vinculada con derecho | `OK Almuerzo: NOMBRE` | Aceptada |
| La misma persona otra vez | `NO … Ya recibió esta comida` | Rechazada · duplicado |
| Dedo sin enrolar / número sin vincular | `NO … Huella no reconocida` | Rechazada · la cocinera la identifica |

### 5. Si algo falla
- Sin el aparato funcionando, `adaptador = prueba` permite escribir los números a
  mano y verificar toda la cadena («-» = huella no reconocida).
- `puente.log` guarda los errores de conexión. `pendientes.csv`, las lecturas que no
  llegaron.

## Archivos

| Archivo | Qué es |
|---|---|
| `puente.py` | El puente: lectura, envío con reintentos, pendientes |
| `adaptadores.py` | Cómo se lee cada tipo de lector (`teclado`, `prueba`) |
| `vincular.py` | Vincular huellas con personas desde la consola (jefa/sistemas) |
| `puente.ini.ejemplo` | Configuración; copiar a `puente.ini` (no se sube a git) |
| `test_puente.py` | Pruebas: `python -m pytest test_puente.py` |
