@echo off
REM Manual Dependency Installer for StudyMate
REM Run this if StudyMate.bat fails to install dependencies

echo ====================================
echo   StudyMate - Manual Setup
echo ====================================
echo.

REM Get the directory where this script is located
set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in PATH
    echo.
    echo Fix:
    echo   1. Install Python 3.10+ from https://www.python.org
    echo   2. Make sure to check "Add Python to PATH" during installation
    echo   3. Restart your computer
    echo   4. Run this script again
    echo.
    pause
    exit /b 1
)

echo Python found: 
python --version
echo.

REM Upgrade pip, setuptools, wheel
echo Step 1: Upgrading pip, setuptools, and wheel...
python -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
    echo.
    echo ERROR: Failed to upgrade pip
    echo Try this in PowerShell as Administrator:
    echo   python -m pip install --upgrade pip setuptools wheel
    echo.
    pause
    exit /b 1
)

echo.
echo Step 2: Installing dependencies from requirements.txt...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: Failed to install dependencies
    echo.
    echo Try these steps in PowerShell as Administrator:
    echo   cd "%SCRIPT_DIR%"
    echo   python -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo.
echo ====================================
echo SUCCESS! Dependencies installed.
echo ====================================
echo.
echo Next step: Double-click StudyMate.bat to start the app
echo.
pause
