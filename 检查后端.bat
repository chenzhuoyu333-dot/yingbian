@echo off
chcp 65001 >nul
title YingBian - Check Backend

echo.
echo   Checking backend...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\check-backend.ps1"

echo.
echo   Press any key to close.
pause >nul