@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
set "setup_result=%errorlevel%"
if /i not "%~1"=="--no-pause" pause
exit /b %setup_result%
