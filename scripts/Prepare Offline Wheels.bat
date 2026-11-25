@echo off
setlocal
cd /d "%~dp0.."
if not exist "wheels" mkdir "wheels"
echo Downloading offline Python wheels into wheels\ ...
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m pip download -r requirements\requirements.txt -d wheels
) else (
  python -m pip download -r requirements\requirements.txt -d wheels
)
if errorlevel 1 (
  echo Failed to download offline wheels.
  pause
  exit /b 1
)
echo Offline wheels are ready in %CD%\wheels
pause
