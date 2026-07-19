@echo off
title WiFi Auto Reconnect

cd /d "%~dp0"

echo ========================================
echo   WiFi Auto Reconnect Tool Starting...
echo ========================================
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found!
    echo Please install Python 3.x first.
    echo Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [Check] tkinter module...
python -c "import tkinter; print('tkinter OK')" 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] tkinter module not available!
    echo Reinstall Python and check "tcl/tk and IDLE" during installation.
    pause
    exit /b 1
)

echo.
echo [Starting] Opening GUI window...
echo (If GUI doesn't appear, check error messages below)
echo.

python -u wifi_monitor.py 2>&1

echo.
echo ========================================
echo Program exited (code: %errorlevel%)
echo ========================================
pause
