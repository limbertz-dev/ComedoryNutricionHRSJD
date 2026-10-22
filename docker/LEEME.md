# Despliegue con Docker Compose

Cinco servicios: **MySQL**, **API** (FastAPI), **frontend** (nginx), **Grafana** y
un paso único de **permisos**. El lector biométrico NO va en Docker: el puente
(`lector_puente/`) corre en la PC de cocina, donde está el USB del ZK9500.

```
Navegadores ──► front :8080 ──► api :8000 ──► db (MySQL :3307)
                                   ▲              ▲
PC de cocina: puente ──────────────┘              │
Grafana :3000 ── usuario de solo lectura ─────────┘
```

## Levantar

```powershell
copy docker\compose.env.example .env      # completar las claves (ver el archivo)
docker compose up -d --build
docker compose exec api python -m app.semillas.admin --username jefa --rol jefa
```

| Servicio | Dirección |
|---|---|
| App | http://localhost:8080 |
| API (documentación) | http://localhost:8000/docs |
| Grafana | http://localhost:3000 (usuario `admin`, clave `GRAFANA_ADMIN_PASSWORD`) |
| MySQL | `localhost:3307` |

La primera cuenta recibe una clave temporal (se muestra una vez) y se cambia en el
primer ingreso.

## Qué hace cada paso al arrancar

1. **db** (solo la primera vez que se crea el volumen): crea `bd_nutricion` y la base
   de turnos, el usuario de la API (todo en `bd_nutricion`, solo `SELECT` en turnos)
   y el de Grafana. Carga la base de turnos desde `docker/mysql/turnos-real/` si hay
   un volcado ahí (el real del hospital, **nunca** va a git) o, si no, el escenario
   **sintético** de demo.
2. **api**: espera a MySQL, `alembic upgrade head`, siembra horarios, coeficientes y
   mapeo de categorías, y arranca.
3. **permisos**: da a Grafana `SELECT` tabla por tabla. De `usuarios_sistema` solo
   ve id, usuario, nombre y rol (nunca el hash). No ve la base de turnos ni escribe.
4. **grafana**: tablero «Comedor · Raciones y lector» ya cargado.

## Tablero de Grafana

Raciones de hoy, policías de hoy, lecturas rechazadas, minutos desde la última
lectura (si sube en horario de comida: revisar el lector y el puente), raciones por
día (personal y policías), por comida, por columna del informe, rechazos por
motivo, intervenciones por cocinera y lecturas por lector. Personal y policías se
suman igual que en los informes de la app.

## En el hospital

- `API_URL_PUBLICA` y `ORIGENES_PERMITIDOS` van con la IP o el nombre del servidor
  (por ejemplo `http://192.168.1.20:8000` y `http://192.168.1.20:8080`). El front
  se reconstruye al cambiar `API_URL_PUBLICA`: `docker compose up -d --build front`.
- `LECTORES=cocina-01=<clave>` y la misma clave en `lector_puente/puente.ini`, con
  `url = http://<servidor>:8000`.
- Respaldo de la base: `docker compose exec db sh -c 'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --databases bd_nutricion' > respaldo.sql`.

## Comandos útiles

```powershell
docker compose ps                 # estado
docker compose logs -f api        # registros de la API
docker compose down               # detener (los datos quedan en los volúmenes)
docker compose down -v            # BORRAR también los datos (base y Grafana)
```
