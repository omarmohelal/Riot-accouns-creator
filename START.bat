@echo off
setlocal
cd /d "%~dp0backend"

echo ========================================
echo   Riot Creator Control v2.4
echo ========================================
echo.
echo The launcher automatically avoids stale servers on port 8000.
echo Runtime data: backend\data\app.db
echo.

if exist ".venv\Scripts\python.exe" (
  .venv\Scripts\python.exe launcher.py
) else (
  echo [INFO] .venv not found. Using system Python.
  echo        Run SETUP.bat once if dependencies are missing.
  python launcher.py
)

if errorlevel 1 (
  echo.
  echo [ERROR] Server exited with an error.
  echo Run SETUP.bat if this is the first launch.
)
pause
