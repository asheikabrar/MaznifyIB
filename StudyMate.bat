@echo off
REM StudyMate Single-Click Launcher for Windows
REM Double-click this file to start StudyMate

setlocal enabledelayedexpansion

echo ====================================
echo   StudyMate - Launching...
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
    echo   2. IMPORTANT: Check "Add Python to PATH" during installation
    echo   3. Restart your computer
    echo   4. Double-click StudyMate.bat again
    echo.
    pause
    exit /b 1
)

python --version

REM Check if dependencies are installed
python -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo.
    echo Installing dependencies (this may take 2-5 minutes)...
    echo.
    python -m pip install --upgrade pip setuptools wheel
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo ========================================
        echo ERROR: Failed to install dependencies
        echo ========================================
        echo.
        echo Option 1 - Use manual installer (Easy):
        echo   1. Double-click install_dependencies.bat
        echo.
        echo Option 2 - Run diagnostics (Helpful):
        echo   1. Double-click diagnose.bat
        echo   2. Share the output with support
        echo.
        echo Option 3 - PowerShell method (Recommended):
        echo   1. Right-click PowerShell - Run as Administrator
        echo   2. Run: cd "%SCRIPT_DIR%"
        echo   3. Run: python -m pip install --upgrade pip setuptools wheel
        echo   4. Run: python -m pip install -r requirements.txt
        echo   5. Try StudyMate.bat again
        echo.
        echo Option 4 - Check troubleshooting:
        echo   1. Open WINDOWS_DEPENDENCY_FIX.md
        echo.
        pause
        exit /b 1
    )
    echo.
    echo Dependencies installed successfully!
)

REM Run the launcher once in a separate window and exit immediately
echo.
echo Starting StudyMate...
echo.
start "StudyMate" python launcher.py
exit /b 0
