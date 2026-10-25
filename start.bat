@echo off
rem Double-click to start the Click2CAD web UI. Your browser opens automatically.
cd /d "%~dp0"
if not exist ".venv311\Scripts\python.exe" (
  echo .venv311 was not found. See README.md for one-time setup.
  pause
  exit /b 1
)
".venv311\Scripts\python.exe" serve.py %*
pause
