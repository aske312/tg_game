@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
if "%~1"=="" (
    echo Usage: server.cmd update^|start^|stop^|restart^|status^|logs^|health^|version [app^|builder^|all]
    exit /b 2
)
".venv\Scripts\python.exe" "scripts\server.py" %*
exit /b %errorlevel%
