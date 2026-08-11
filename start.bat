@echo off
setlocal
cd /d "%~dp0"
set "GIT_ASSESSMENT_EXIT_CODE="

if not exist ".venv\Scripts\python.exe" (
  if defined GIT_ASSESSMENT_PROGRESS >"runtime\setup-status.txt" echo create-venv
  echo Preparing Git Assessment for first use...
  python -m venv .venv || goto :error
  if defined GIT_ASSESSMENT_PROGRESS >"runtime\setup-status.txt" echo install-packages
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
)

if not exist ".venv\Lib\site-packages\flask\__init__.py" (
  if defined GIT_ASSESSMENT_PROGRESS >"runtime\setup-status.txt" echo install-packages
  echo Repairing Python packages...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
)

if defined GIT_ASSESSMENT_PROGRESS >"runtime\setup-status.txt" echo start-server
".venv\Scripts\python.exe" run.py
set "GIT_ASSESSMENT_EXIT_CODE=%errorlevel%"
if "%GIT_ASSESSMENT_EXIT_CODE%"=="0" exit /b 0
goto :error

:error
if not defined GIT_ASSESSMENT_EXIT_CODE set "GIT_ASSESSMENT_EXIT_CODE=%errorlevel%"
if "%GIT_ASSESSMENT_EXIT_CODE%"=="0" set "GIT_ASSESSMENT_EXIT_CODE=1"
echo.
echo Unable to start Git Assessment. Please confirm Python 3.11+ and Git are installed.
echo Log: %~dp0runtime\logs\git-assessment.log
if defined GIT_ASSESSMENT_PROGRESS (
  exit /b %GIT_ASSESSMENT_EXIT_CODE%
) else if defined GIT_ASSESSMENT_HIDDEN (
  powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0Show Git Assessment Error.ps1" -ExitCode %GIT_ASSESSMENT_EXIT_CODE% >nul 2>&1
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Show Git Assessment Error.ps1" -ExitCode %GIT_ASSESSMENT_EXIT_CODE%
)
exit /b %GIT_ASSESSMENT_EXIT_CODE%
