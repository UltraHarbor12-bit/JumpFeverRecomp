#!/bin/sh
# Jump Fever Recomp - abre el launcher (GUI). Argumentos extra se pasan al launcher.
cd "$(dirname "$0")"
exec python3 tools/launcher/sjf_launcher.py "$@"
