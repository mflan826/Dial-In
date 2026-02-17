@echo off
title Sniper Drag Tuner - Holley EFI Tuning Assistant
echo ================================================
echo   Sniper Drag Tuner - Holley EFI Tuning Assistant
echo ================================================
echo.
echo Checking Python...

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed or not in PATH.
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

echo Checking dependencies...
pip install llama-cpp-python >nul 2>&1

echo Starting Sniper Drag Tuner...
echo.
python "%~dp0sniper_drag_tuner.py"

if %errorlevel% neq 0 (
    echo.
    echo Application exited with an error.
    pause
)
