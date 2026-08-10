@echo off
setlocal
cd /d "%~dp0"
if not exist "CURRENT_URL.txt" (
  echo No current URL was found. Starting the app first...
  call START.bat
  exit /b
)
set /p APP_URL=<CURRENT_URL.txt
if "%APP_URL%"=="" (
  echo CURRENT_URL.txt is empty. Run START.bat first.
  pause
  exit /b 1
)
start "" "%APP_URL%"
