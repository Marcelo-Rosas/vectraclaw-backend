#!/bin/sh
set -e
exec uvicorn wrapper:app --host 0.0.0.0 --port "${NOUS_HERMES_RUNTIME_PORT:-9120}"
