#!/bin/sh
# Corre UNA vez, la primera vez que se crea el volumen de MySQL.
# - NUTRICION_DB: base propia del comedor (la administra alembic desde la API).
# - TURNOS_DB:    base del módulo de turnos. SOLO LECTURA para la API y para Grafana.
# - APP_USER:     la API. Todo en NUTRICION_DB, solo SELECT en TURNOS_DB.
# - GRAFANA_USER: tableros. Solo SELECT y solo en las tablas que muestra; de
#                 usuarios_sistema, solo id/usuario/nombre/rol (nunca el hash).
set -eu
mysql -uroot -p"$MYSQL_ROOT_PASSWORD" <<SQL
CREATE DATABASE IF NOT EXISTS \`$NUTRICION_DB\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS \`$TURNOS_DB\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS '$APP_USER'@'%' IDENTIFIED BY '$APP_PASSWORD';
GRANT ALL PRIVILEGES ON \`$NUTRICION_DB\`.* TO '$APP_USER'@'%';
GRANT SELECT ON \`$TURNOS_DB\`.* TO '$APP_USER'@'%';
-- pytest usa bases *_test: no se otorgan en producción.

CREATE USER IF NOT EXISTS '$GRAFANA_USER'@'%' IDENTIFIED BY '$GRAFANA_PASSWORD';
SQL
