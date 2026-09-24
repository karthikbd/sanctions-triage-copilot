@echo off
REM Sanctions Triage Copilot - one-click launcher for Windows
cd /d "%~dp0"
if not exist ".env" copy ".env.example" ".env" >nul
if not exist ".venv\Scripts\python.exe" (
  echo First run: creating virtual environment...
  python -m venv .venv || (echo Python 3.10+ not found. Install it from python.org or run this from an Anaconda Prompt. & pause & exit /b 1)
)
if not exist ".venv\installed-v0.2" (
  echo Installing dependencies ^(first run of v0.2 includes SDV, a few minutes^)...
  ".venv\Scripts\python" -m pip install --upgrade pip
  ".venv\Scripts\pip" install -e ".[mcp,dev,synth]" || (echo Install failed. & pause & exit /b 1)
  echo ok> ".venv\installed-v0.2"
)
echo Starting on http://127.0.0.1:8000  (close this window or the terminal to stop)
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8000"
".venv\Scripts\stc" serve
pause
