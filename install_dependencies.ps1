#!/usr/bin/env powershell
# StudyMate Manual Setup Script for PowerShell
# Right-click this file and select "Run with PowerShell"
# If you get an error, run PowerShell as Administrator first

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "====================================" -ForegroundColor Cyan
Write-Host "  StudyMate - Manual Setup" -ForegroundColor Cyan
Write-Host "====================================" -ForegroundColor Cyan
Write-Host ""

# Check if Python is installed
try {
    $pythonVersion = python --version 2>&1
    Write-Host "Python found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Python not found!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Fix:"
    Write-Host "  1. Install Python 3.10+ from https://www.python.org"
    Write-Host "  2. Check 'Add Python to PATH' during installation"
    Write-Host "  3. Restart your computer"
    Write-Host "  4. Run this script again"
    Write-Host ""
    pause
    exit 1
}

Write-Host ""
Write-Host "Step 1: Upgrading pip, setuptools, and wheel..." -ForegroundColor Yellow
python -m pip install --upgrade pip setuptools wheel

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERROR: Failed to upgrade pip" -ForegroundColor Red
    Write-Host "Try running PowerShell as Administrator and try again"
    Write-Host ""
    pause
    exit 1
}

Write-Host ""
Write-Host "Step 2: Installing dependencies..." -ForegroundColor Yellow
python -m pip install -r requirements.txt

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERROR: Failed to install dependencies" -ForegroundColor Red
    Write-Host ""
    Write-Host "Troubleshooting:"
    Write-Host "  1. Run PowerShell as Administrator"
    Write-Host "  2. Try: python -m pip install --upgrade setuptools"
    Write-Host "  3. Then: python -m pip install -r requirements.txt"
    Write-Host ""
    pause
    exit 1
}

Write-Host ""
Write-Host "====================================" -ForegroundColor Green
Write-Host "SUCCESS! Dependencies installed." -ForegroundColor Green
Write-Host "====================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next step: Double-click StudyMate.bat to start the app"
Write-Host ""
pause
