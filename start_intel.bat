@echo off
setlocal
title Reddit Opportunity Intel
cd /d "%~dp0"

set "PYEXE=.venv\Scripts\python.exe"

if not exist "%PYEXE%" (
    echo [intel] First run: creating .venv and installing deps...
    where py >nul 2>&1
    if errorlevel 1 (
        echo [intel] ERROR: Python launcher ^(^py^) not found. Install Python 3.10+ from python.org and retry.
        pause
        exit /b 1
    )
    py -3 -m venv .venv
    if errorlevel 1 (
        echo [intel] ERROR: Could not create virtual environment.
        pause
        exit /b 1
    )
    "%PYEXE%" -m pip install -q --upgrade pip
    "%PYEXE%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [intel] ERROR: pip install failed.
        pause
        exit /b 1
    )
    echo [intel] Ready. Ensure .env exists ^(copy from .env.example^).
    echo.
)

if not exist ".env" (
    echo [intel] WARNING: No .env file. Copy .env.example to .env and add Reddit credentials.
    echo.
)

echo [intel] Starting daemon ^(Ctrl+C to stop^)...
echo.
"%PYEXE%" run.py --daemon
if errorlevel 1 (
    echo.
    echo [intel] Exited with an error. Fix .env / RUNBOOK.md then try again.
    pause
)

endlocal
