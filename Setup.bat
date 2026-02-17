@echo off
title Sniper Drag Tuner - Setup
echo ================================================
echo   Sniper Drag Tuner - Dependency Setup
echo ================================================
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found. Install Python 3.10+ first.
    echo https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Installing required Python packages...
echo.

pip install llama-cpp-python
if %errorlevel% neq 0 (
    echo.
    echo Warning: llama-cpp-python failed to install.
    echo The app will still work with the expert system.
    echo For LLM support, you may need Visual C++ Build Tools.
    echo.
)

echo.
echo ================================================
echo   Setup complete!
echo   Run Start_Sniper_Drag_Tuner.bat to launch.
echo ================================================
echo.

echo Optional: To add local LLM support, download a GGUF model:
echo   Recommended: TinyLlama 1.1B (700MB)
echo   https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF
echo   Place the .gguf file in the 'models' folder.
echo.

pause
