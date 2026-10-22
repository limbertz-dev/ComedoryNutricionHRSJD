#!/bin/sh
# Migra, siembra lo idempotente y arranca la API. Sin .env: todo llega por
# variables de entorno desde docker-compose.yml.
set -eu
python - <<'PY'
import time, pymysql, os
for intento in range(60):
    try:
        pymysql.connect(host=os.environ["DB_HOST"], port=int(os.environ.get("DB_PORT", 3306)),
                        user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"],
                        database=os.environ["DB_NAME"]).close()
        break
    except pymysql.err.OperationalError:
        time.sleep(2)
else:
    raise SystemExit("MySQL no respondió en 2 minutos.")
PY
alembic upgrade head
python -m app.semillas
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers
