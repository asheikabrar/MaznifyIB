@echo off
REM StudyMate Diagnostic Script
REM Run this to diagnose dependency installation issues

echo ====================================
echo   StudyMate - Diagnostic Check
echo ====================================
echo.

REM Get the directory
set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

echo Current directory:
echo %SCRIPT_DIR%
echo.

REM Check Python
echo === PYTHON CHECK ===
python --version
if errorlevel 1 (
    echo ERROR: Python not found in PATH
    echo Fix: Reinstall Python with "Add Python to PATH" checked
    echo.
)

REM Check pip
echo.
echo === PIP CHECK ===
python -m pip --version
if errorlevel 1 (
    echo ERROR: Pip not working
    echo.
)

REM Check requirements.txt
echo.
echo === REQUIREMENTS.TXT CHECK ===
if exist requirements.txt (
    echo Found: requirements.txt
    echo Contents:
    type requirements.txt
) else (
    echo ERROR: requirements.txt not found
)

REM Try to install one package
echo.
echo === TRYING SAMPLE INSTALL ===
echo Attempting to install just "fastapi"...
python -m pip install fastapi
if errorlevel 1 (
    echo ERROR: Failed to install fastapi
    echo This means pip installation is not working on your system
    echo Try Solution 5 or 6 in WINDOWS_DEPENDENCY_FIX.md
) else (
    echo SUCCESS: fastapi installed
    echo If this worked, dependencies should install too
)

echo.
echo === DIAGNOSTIC COMPLETE ===
echo.
echo Next: Check WINDOWS_DEPENDENCY_FIX.md for solutions
echo.
pause
