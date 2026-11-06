@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0yuanshen-rhythm-key-helper.exe" (
    "%~dp0yuanshen-rhythm-key-helper.exe" --calibration-demo
) else (
    if not exist "%~dp0.venv\Scripts\python.exe" (
        echo Please extract the complete portable ZIP, or run setup.cmd for the source version.
        pause
        exit /b 1
    )
    "%~dp0.venv\Scripts\python.exe" "%~dp0main.py" --calibration-demo
)
if errorlevel 1 pause
