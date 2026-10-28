# Despliegue con Docker Compose y nginx

El contenedor `front` sirve React y actúa como proxy reverso. El navegador y el
puente del lector entran por nginx; la API no publica un puerto en el servidor.
MySQL y Grafana solo publican en `127.0.0.1` para mantenimiento local.

```text
Navegador / puente del lector
             |
             v
        nginx (front)
        /       -> React
        /api/*  -> api:8000 -> db:3306
                                  ^
Grafana (acceso local) ------------|
```

## Prueba local por HTTP

En la raíz del worktree, con Docker Desktop iniciado:

```powershell
Copy-Item docker\compose.env.example .env  # solo si todavía no existe
# Completar las claves en .env; API_URL_PUBLICA=/api.
docker compose up -d --build
docker compose ps
docker compose exec front nginx -t
docker compose exec api python -m app.semillas.admin --username jefa --rol jefa
```

La primera cuenta recibe una clave temporal, que se muestra una vez y se cambia
en el primer ingreso. Nunca copiar el archivo de ejemplo encima de un `.env`
que ya tenga configuración.

| Servicio | Dirección |
|---|---|
| App | http://localhost:8080 |
| Salud de la API por nginx | http://localhost:8080/api/salud |
| Documentación de la API | http://localhost:8080/api/docs |
| Grafana (solo en el servidor) | http://127.0.0.1:3000 |
| MySQL (solo en el servidor) | 127.0.0.1:3307 |

Si ya usabas Docker, cambiar en el `.env` existente
`API_URL_PUBLICA=http://localhost:8000` por `API_URL_PUBLICA=/api` y reconstruir
el frontend. La URL queda incorporada al compilar; reiniciar no basta.
Los puertos 8000 y 3307 ya no son puntos de entrada desde otras PCs.

## Hospital: HTTPS con certificado propio

Requiere Docker Compose **2.24.4 o posterior** por `!override`. Esta opción
reemplaza el puerto HTTP de prueba por **80 y 443**, sin conservar el 8080.

1. Definir un nombre DNS que las PCs resuelvan a la IP fija del servidor.
2. Obtener un certificado para ese nombre (autoridad del hospital o pública).
   Si es una autoridad interna, instalar su certificado raíz de confianza en las
   PCs y en el entorno de Python del puente. No desactivar la verificación TLS.
3. Guardar la cadena completa en PEM y la clave privada PEM sin contraseña en
   una carpeta del servidor con acceso restringido. Por ejemplo,
   `docker/front/certs/fullchain.pem` y `docker/front/certs/privkey.pem`.
   Esa carpeta está excluida de Git y del contexto de build.
4. Ajustar en el `.env` existente:

```dotenv
API_URL_PUBLICA=/api
ORIGENES_PERMITIDOS=https://comedor.hospital.example
TLS_CERTIFICADO=./docker/front/certs/fullchain.pem
TLS_CLAVE_PRIVADA=./docker/front/certs/privkey.pem
```

El nombre `comedor.hospital.example` es ilustrativo: reemplazarlo por el real,
tanto en DNS como en el certificado y los orígenes.

```powershell
docker compose -f docker-compose.yml -f docker-compose.https.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.https.yml exec front nginx -t
```

Entrar a `https://<nombre-real-del-servidor>/`; HTTP redirige a HTTPS.
La salud está en `/api/salud` y la documentación en `/api/docs`.
Usar ambos `-f` también en futuras actualizaciones y comandos del despliegue HTTPS.

nginx no solicita ni renueva certificados automáticamente. Después de renovar,
volver a validar y recrear `front` para que remonte y cargue los archivos nuevos:

```powershell
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --force-recreate --no-deps front
docker compose -f docker-compose.yml -f docker-compose.https.yml exec front nginx -t
```

## Lector biométrico

El puente (`lector_puente/`) corre en la PC de cocina, junto al USB y su SDK,
fuera de Docker. En `puente.ini`:

```ini
[api]
url = https://<nombre-real-del-servidor>/api
clave = <la-misma-clave-configurada-en-LECTORES>
```

En la API, configurar `LECTORES=cocina-01=<clave>` en el `.env` del despliegue.
Para pruebas HTTP, la URL del puente es `http://<servidor>:8080/api`.
Las plantillas biométricas y credenciales también viajan por esta conexión.

## Cómo se enruta

nginx elimina el prefijo `/api` al reenviar y conserva la consulta:
`/api/pantalla/estado?fecha=2026-10-23` llega como
`/pantalla/estado?fecha=2026-10-23`.
Las rutas de API nunca reciben el `index.html` de React.

La API recibe `API_ROOT_PATH=/api` para generar documentación y redirecciones
con el prefijo correcto. nginx sobrescribe las cabeceras de IP y protocolo;
Uvicorn las acepta dentro de la red de Docker. No publicar directamente el puerto
de la API sin revisar esa confianza.
nginx vuelve a resolver el nombre `api` mediante el DNS de Docker, de modo que
tolera que la API cambie de IP al recrearse.

## Bases y arranque

1. **db**, solo al crear el volumen: crea las dos bases y los usuarios. La API
   tiene permisos sobre nutrición y solo `SELECT` sobre turnos. Importa los
   `.sql` de `docker/mysql/turnos-real/` si existen; en caso contrario importa
   la demostración sintética. Una importación inicial no sincroniza turnos.
   Confirmar la fuente vigente antes de operar en el hospital.
2. **api**: espera a MySQL, ejecuta `alembic upgrade head`, semillas y Uvicorn.
3. **permisos**: habilita a Grafana lectura sobre las tablas autorizadas.
4. **grafana**: carga el tablero de comedor.

El proxy no cambia los horarios, reglas, migraciones ni el comportamiento de las
cuentas. Confirmar los valores iniciales y la conexión con los turnos reales
antes de comenzar la atención.

## Develop y QA

Ambos worktrees tienen los mismos archivos de despliegue. Cada instalación
necesita su propio `.env`, claves y datos. No usar los datos hospitalarios para QA.

Para ejecutar dos instalaciones HTTP en un mismo equipo, usar nombres de
proyecto distintos (`docker compose -p comedor-qa ...`) y asignar puertos
distintos en cada `.env`: `FRONT_PUERTO`, `MYSQL_PUERTO` y `GRAFANA_PUERTO`.
El override HTTPS ocupa 80/443: no levantar dos copias simultáneamente en esos
puertos del mismo equipo. Los nombres de proyecto distintos también separan
redes y volúmenes.

## Mantenimiento y verificación

- Revisar `docker compose ps`, `docker compose logs --tail=100 api front` y
  `docker compose exec front nginx -t`.
- Verificar desde otra PC login, permisos, rutas de React, salud e informes,
  y realizar una lectura con el dispositivo real.
- Programar respaldos y probar su restauración; guardar también la configuración
  del despliegue en un lugar protegido.
- `docker compose down` conserva los volúmenes. **No usar `down -v`** sobre
  una instalación con datos que se deban conservar.
- Grafana queda disponible solo desde el servidor; para acceso remoto,
  usar un túnel o preparar un acceso HTTPS restringido por separado.

Referencias: [proxy nginx](https://nginx.org/en/docs/http/ngx_http_proxy_module.html)
y [override de Compose](https://docs.docker.com/reference/compose-file/merge/).
