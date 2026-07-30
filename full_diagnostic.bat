@echo off
REM StudyMate Complete Diagnostic Report
REM Run this and copy all the output

setlocal enabledelayedexpansion

echo ====================================
echo   StudyMate - Complete Diagnostic
echo ====================================
echo.
echo Time: %date% %time%
echo.

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

REM === SECTION 1: Python & System ===
echo === SECTION 1: PYTHON & SYSTEM ===
python --version
python -c "import sys; print('Python location: ' + sys.executable)"
echo.

REM === SECTION 2: Directory Structure ===
echo === SECTION 2: DIRECTORY STRUCTURE ===
echo Current dir: %SCRIPT_DIR%
if exist app\main.py (
    echo OK - app/main.py exists
) else (
    echo ERROR - app/main.py missing!
)

if exist requirements.txt (
    echo OK - requirements.txt exists
) else (
    echo ERROR - requirements.txt missing!
)

if exist .env (
    echo OK - .env exists
) else (
    echo WARNING - .env missing (will be created)
)

if exist studymate.db (
    echo OK - studymate.db exists
) else (
    echo INFO - studymate.db will be created on first run
)
echo.

REM === SECTION 3: Package Imports ===
echo === SECTION 3: PACKAGE IMPORTS ===
python -c "import fastapi; print('OK - fastapi')" 2>&1
python -c "import uvicorn; print('OK - uvicorn')" 2>&1
python -c "import sqlalchemy; print('OK - sqlalchemy')" 2>&1
python -c "import pydantic; print('OK - pydantic')" 2>&1
python -c "import jinja2; print('OK - jinja2')" 2>&1
python -c "from anthropic import Anthropic; print('OK - anthropic')" 2>&1
echo.

REM === SECTION 4: App Import ===
echo === SECTION 4: APP IMPORT ===
python -c "from app.main import app; print('OK - app.main imports')" 2>&1
if errorlevel 1 (
    echo ERROR: Cannot import app.main
    echo.
    echo Trying to get detailed error:
    python -c "import traceback; from app import main" 2>&1
)
echo.

REM === SECTION 5: Database ===
echo === SECTION 5: DATABASE ===
if exist studymate.db (
    python -c "from app.db import engine; engine.connect(); print('OK - database connection works')" 2>&1
) else (
    echo INFO - Database doesn't exist yet, will create on start
)
echo.

REM === SECTION 6: Launcher Test ===
echo === SECTION 6: LAUNCHER IMPORT ===
python -c "import launcher; print('OK - launcher imports')" 2>&1
if errorlevel 1 (
    echo ERROR: Cannot import launcher
    echo Trying detailed error:
    python launcher.py 2>&1
)
echo.

echo === END DIAGNOSTIC ===
echo.
echo Copy this entire output and share with support
echo.
pause
