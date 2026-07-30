@echo off
REM StudyMate Debug Launcher - Keeps window open to see errors

setlocal enabledelayedexpansion

echo ====================================
echo   StudyMate - Debug Mode
echo ====================================
echo.

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

REM Show Python version
echo Python version:
python --version
echo.

REM Check if launcher.py exists
if not exist launcher.py (
    echo ERROR: launcher.py not found!
    echo Make sure you're in the StudyMate directory
    pause
    exit /b 1
)

REM Check if .env exists
if not exist .env (
    echo Warning: .env file not found, creating from template...
    if exist .env.example (
        copy .env.example .env
        echo Created .env file
    )
)

echo.
echo Running launcher...
echo.

REM Run launcher with full output
python launcher.py

REM This will stay open even if there's an error
echo.
echo ====================================
echo Process ended (check output above for errors)
echo ====================================
pause
