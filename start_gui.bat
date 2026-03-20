@echo off
setlocal

cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERROR] Virtual environment Python not found: "%PY%"
  echo Please create/install venv first, then try again.
  pause
  exit /b 1
)

echo Starting DVK GUI...
"%PY%" -m streamlit run "%~dp0dvk_gui.py"

endlocal
