@echo off
title WiFi Monitor - Update

cd /d "%~dp0"

echo ========================================
echo   WiFi Monitor - One Click Update
echo ========================================
echo.

if not exist "win10_wifi_auto_reconnect.zip" (
    echo [ERROR] win10_wifi_auto_reconnect.zip not found!
    echo Please put the zip file in this folder first.
    echo.
    pause
    exit /b 1
)

echo [1/3] Extracting update files...
powershell -Command "Expand-Archive -Path 'win10_wifi_auto_reconnect.zip' -DestinationPath '.' -Force"

if %errorlevel% neq 0 (
    echo [ERROR] Extraction failed!
    pause
    exit /b 1
)

echo [2/3] Cleaning up temp files...
if exist "wifi_monitor_config.json" (
    echo   Config file preserved
)

echo [3/3] Update complete!
echo.
echo ========================================
echo   Update successful!
echo   Main program: wifi_monitor.py
echo   Run: double-click launch batch file
echo ========================================
echo.
pause
