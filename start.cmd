@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONUTF8=1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" -CheckOnly
if errorlevel 1 (
    echo Preparing this computer's Python environment...
    call "%~dp0setup.cmd" --no-pause
    if errorlevel 1 goto failed
)
if /i "%~1"=="--inspect" goto cli
if /i "%~1"=="--help" goto cli
if /i "%~1"=="-h" goto cli
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py" %*
exit /b %errorlevel%
:cli
".venv\Scripts\python.exe" main.py %*
exit /b %errorlevel%
:failed
pause
exit /b 1
