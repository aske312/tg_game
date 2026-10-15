@echo off
setlocal
cd /d "%~dp0.."
".venv\Scripts\python.exe" "scripts\run_builder.py"
pause
