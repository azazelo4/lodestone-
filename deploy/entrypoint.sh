#!/bin/sh
set -e
case "$1" in
  migrate) exec alembic upgrade head ;;
  seed)    exec python -m app.seed ;;
  worker)  exec python -m app.delivery ;;  # dedicated notification sender (set LODESTONE_NOTIFY_WORKER=false on web pods)
  serve)
    if [ "${LODESTONE_AUTO_MIGRATE:-true}" = "true" ]; then alembic upgrade head; fi
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips '*' \
      --workers "${LODESTONE_WORKERS:-2}" ;;
  *) exec "$@" ;;
esac
