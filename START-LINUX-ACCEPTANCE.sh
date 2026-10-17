#!/bin/sh
# Run only inside an approved isolated Linux test environment; opens no ports.
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "NOT VERIFIED: create the documented Python 3.12 validation venv first." >&2
  exit 1
fi
exec .venv/bin/python -m deployment.c3c.acceptance "$@"
