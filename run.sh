#!/bin/bash
# Start Local Project Hub. Uses ./.hubenv when present, otherwise system python3.
set -e
cd "$(dirname "$0")"

PY=python3
if [ -x .hubenv/bin/python ]; then PY=.hubenv/bin/python; fi

# Keep run artifacts out of the way but inspectable.
export LOCAL_PROJECT_HUB_HOME="${LOCAL_PROJECT_HUB_HOME:-$PWD/.hubstate}"
mkdir -p "$LOCAL_PROJECT_HUB_HOME"
exec "$PY" main.py "$@"
