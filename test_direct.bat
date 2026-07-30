@echo off
REM Direct test - bypass everything and just run the server

setlocal enabledelayedexpansion

echo ====================================
echo   StudyMate - Direct Test
echo ====================================
echo.

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

echo Current directory: %SCRIPT_DIR%
echo.

REM Show Python
echo Step 1: Check Python
python --version
if errorlevel 1 (
    echo ERROR: Python not working
    pause
    exit /b 1
)

echo.
echo Step 2: Test import fastapi
python -c "import fastapi; print('OK - fastapi works')"
if errorlevel 1 (
    echo ERROR: fastapi not working
    pause
    exit /b 1
)

echo.
echo Step 3: Test import uvicorn
python -c "import uvicorn; print('OK - uvicorn works')"
if errorlevel 1 (
    echo ERROR: uvicorn not working
    pause
    exit /b 1
)

echo.
echo Step 4: Test import app modules
python -c "from app import main; print('OK - app modules work')"
if errorlevel 1 (
    echo ERROR: app modules not working
    echo.
    echo This might mean:
    echo   1. Database is corrupted
    echo   2. app/main.py has syntax error
    echo   3. Missing environment variable
    pause
    exit /b 1
)

echo.
echo Step 5: Starting server on http://127.0.0.1:8000
echo Press Ctrl+C to stop
echo.
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

echo.
echo Server stopped
pause
