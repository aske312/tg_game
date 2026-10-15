@echo off
setlocal
cd /d "%~dp0.."
".venv\Scripts\python.exe" "scripts\run_telegram.py"
pause
