#!/bin/sh
# Carga la base de turnos: el volcado real si se montó en /turnos-real (del
# hospital, NUNCA va al repositorio), o si no el escenario SINTÉTICO de demo.
set -eu
if ls /turnos-real/*.sql >/dev/null 2>&1; then
  origen=/turnos-real
else
  origen=/turnos-demo
fi
echo "Base de turnos desde $origen"
for archivo in "$origen"/*.sql; do
  mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$TURNOS_DB" < "$archivo"
done
