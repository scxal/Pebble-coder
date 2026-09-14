#!/usr/bin/env bash
# Suite de sanity de Pebble-Coder. Uso: ./run_tests.sh [-v] [patron]
cd "$(dirname "$0")"
exec python3 -m unittest discover -s tests -t . "$@"
