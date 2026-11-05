#!/bin/bash
# Doppio clic per aprire Reel Replica (Mac)
cd "$(dirname "$0")"
if ! command -v ffmpeg >/dev/null; then
  if command -v brew >/dev/null; then echo "Installo ffmpeg…"; brew install ffmpeg
  else echo "Manca ffmpeg. Installa Homebrew (https://brew.sh) e poi: brew install ffmpeg"; read -r; exit 1; fi
fi
if [ ! -d .venv ]; then
  echo "Prima installazione…"
  python3 -m venv .venv || { echo "Manca Python 3: scaricalo da https://www.python.org"; read -r; exit 1; }
fi
.venv/bin/pip install -q --upgrade -r requirements.txt
.venv/bin/python app.py
