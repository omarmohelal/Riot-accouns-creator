@echo off
setlocal
cd /d "%~dp0"
echo ========================================
echo   Riot Creator Control v2.4 Data Migration
echo ========================================
echo.
echo Close all Riot Creator START windows first.
echo Paste the OLD project folder path below.
echo Example: C:\Users\You\Downloads\riot-creator-v2.3
echo.
set /p OLD_PATH=Old folder: 
if "%OLD_PATH%"=="" (
  echo [ERROR] No folder was entered.
  pause
  exit /b 1
)
if exist "backend\.venv\Scripts\python.exe" (
  "backend\.venv\Scripts\python.exe" "backend\migrate_from_previous.py" "%OLD_PATH%"
) else (
  python "backend\migrate_from_previous.py" "%OLD_PATH%"
)
echo.
pause
