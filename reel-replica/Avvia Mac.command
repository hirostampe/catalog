#!/bin/bash
# Doppio clic per aprire Reel Replica (Mac)
cd "$(dirname "$0")"

# Rende visibile Homebrew (Mac con chip Apple o Intel)
for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && eval "$("$b" shellenv)"; done
if ! command -v brew >/dev/null; then
  echo "Manca Homebrew. Installalo con il comando indicato nel README, poi riapri questo file."
  read -r; exit 1
fi

# Python recente + ffmpeg (solo la prima volta)
command -v ffmpeg >/dev/null || { echo "Installo ffmpeg…"; brew install ffmpeg; }
[ -x "$(brew --prefix)/bin/python3.12" ] || { echo "Installo Python…"; brew install python@3.12; }
PY="$(brew --prefix)/bin/python3.12"

if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
  echo "Prima installazione…"
  rm -rf .venv && "$PY" -m venv .venv
fi
.venv/bin/pip install -q --upgrade -r requirements.txt
.venv/bin/python app.py
