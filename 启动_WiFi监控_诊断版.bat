@echo off
title WiFi Monitor - Diagnostic

echo ========================================
echo    WiFi Monitor - Diagnostic
echo ========================================
echo.

cd /d "%~dp0"

echo [1/5] Checking Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   FAIL: Python not found
    echo   Install Python 3.x from https://www.python.org/downloads/
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PY_VER=%%i
echo   OK: %PY_VER%

echo.
echo [2/5] Checking program file...
if not exist "wifi_monitor.py" (
    echo   FAIL: wifi_monitor.py not found in %cd%
    echo.
    dir /b *.py
    echo.
    pause
    exit /b 1
)
echo   OK: wifi_monitor.py exists

echo.
echo [3/5] Checking tkinter...
python -c "import tkinter; print('OK')" >nul 2>&1
if %errorlevel% neq 0 (
    echo   FAIL: tkinter not available
    echo   Reinstall Python with "tcl/tk and IDLE" checked
    pause
    exit /b 1
)
echo   OK: tkinter works

echo.
echo [4/5] Checking syntax...
python -m py_compile wifi_monitor.py >nul 2>&1
if %errorlevel% neq 0 (
    echo   FAIL: Syntax error! Details:
    echo.
    python -m py_compile wifi_monitor.py 2>&1
    echo.
    pause
    exit /b 1
)
echo   OK: Syntax valid

echo.
echo [5/5] Starting program...
echo.
echo ========================================
echo   Starting WiFi Monitor...
echo   (If it crashes, error will show below)
echo ========================================
echo.

python -u wifi_monitor.py

set EXIT_CODE=%errorlevel%
if %EXIT_CODE% neq 0 (
    echo.
    echo ========================================
    echo   Program crashed! Exit code: %EXIT_CODE%
    echo ========================================
    echo.
    echo Send a screenshot of this window to the developer.
    echo.
    pause
)
