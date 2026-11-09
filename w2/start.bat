@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Starting Yingbian API server...
python -m src.api
pause
