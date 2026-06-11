#!/bin/bash
set -e

PGDATA=/var/lib/pgsql/data

# Start postgres temporarily to set up the user/password
pg_ctl -D "$PGDATA" -o "-c listen_addresses=''" -w start

psql -v ON_ERROR_STOP=1 -d postgres <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${POSTGRES_USER}') THEN
            CREATE ROLE "${POSTGRES_USER}" LOGIN SUPERUSER PASSWORD '${POSTGRES_PASSWORD}';
        ELSE
            ALTER ROLE "${POSTGRES_USER}" WITH PASSWORD '${POSTGRES_PASSWORD}';
        END IF;
    END
    \$\$;
EOSQL

pg_ctl -D "$PGDATA" -m fast -w stop

# Allow password-based connections from any host
echo "host all all 0.0.0.0/0 md5" >> "$PGDATA/pg_hba.conf"
echo "listen_addresses='*'" >> "$PGDATA/postgresql.conf"

exec postgres -D "$PGDATA"
