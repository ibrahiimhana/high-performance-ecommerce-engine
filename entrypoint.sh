#!/bin/sh
# Container entrypoint. Waits for Postgres (if configured), then execs
# whatever command was passed (gunicorn, celery, migrate, ...).
set -e

if [ -n "$POSTGRES_HOST" ]; then
    echo "[entrypoint] waiting for Postgres at $POSTGRES_HOST:$POSTGRES_PORT ..."
    until python -c "
import socket, sys
try:
    s = socket.socket(); s.settimeout(1)
    sys.exit(0 if s.connect_ex(('$POSTGRES_HOST', int('$POSTGRES_PORT')))==0 else 1)
except Exception:
    sys.exit(1)
"; do
        sleep 1
    done
    echo "[entrypoint] Postgres reachable."
fi

exec "$@"
