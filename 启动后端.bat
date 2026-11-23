@echo off
chcp 65001 >nul
title YingBian Backend

echo.
echo   Checking environment and starting backend...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\start-backend.ps1"

echo.
echo   Server stopped. Press any key to close.
pause >nul