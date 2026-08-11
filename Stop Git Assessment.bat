@echo off
setlocal
cd /d "%~dp0"
if not exist "runtime\git-assessment.pid" (
  echo Git Assessment is not running.
  pause
  exit /b 0
)
set /p GIT_ASSESSMENT_PID=<"runtime\git-assessment.pid"
powershell -NoProfile -Command "$p = Get-Process -Id %GIT_ASSESSMENT_PID% -ErrorAction SilentlyContinue; if ($p) { Stop-Process -Id $p.Id; exit 0 }; exit 1"
if errorlevel 1 (
  echo Git Assessment process was not found.
) else (
  echo Git Assessment stopped.
)
del /q "runtime\git-assessment.pid" >nul 2>&1
pause
