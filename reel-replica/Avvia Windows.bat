@echo off
rem Doppio clic per aprire Reel Replica (Windows)
cd /d "%~dp0"
where ffmpeg >nul 2>nul || (echo Installo ffmpeg... & winget install -e --id Gyan.FFmpeg)
if not exist .venv (
  echo Prima installazione...
  python -m venv .venv || (echo Manca Python: installalo da https://www.python.org spuntando "Add to PATH" & pause & exit /b 1)
)
.venv\Scripts\pip install -q --upgrade -r requirements.txt
.venv\Scripts\python app.py
pause
