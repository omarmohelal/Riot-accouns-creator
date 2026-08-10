@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo   Riot Creator Control v2.4 - Setup
echo ========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python was not found in PATH.
  pause
  exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Node.js / npm was not found in PATH.
  pause
  exit /b 1
)

if not exist "backend\.venv\Scripts\python.exe" (
  echo [1/6] Creating Python virtual environment...
  python -m venv backend\.venv
  if errorlevel 1 goto :fail
) else (
  echo [1/6] Virtual environment already exists.
)

echo [2/6] Updating pip...
backend\.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto :fail

echo [3/6] Installing backend dependencies...
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if errorlevel 1 goto :fail

echo [4/6] Installing Playwright Chromium...
backend\.venv\Scripts\python.exe -m playwright install chromium
if errorlevel 1 goto :fail

echo [5/6] Installing frontend dependencies...
pushd frontend
call npm install
if errorlevel 1 (
  popd
  goto :fail
)

echo [6/6] Building frontend...
call npm run build
if errorlevel 1 (
  popd
  goto :fail
)
popd

echo.
echo Setup completed successfully.
echo.
echo First run only:
echo   set RC_OWNER_EMAIL=you@example.com
echo   set RC_OWNER_PASSWORD=your-password
echo   START.bat
echo.
echo After the owner is stored in backend\data\app.db,
echo the environment variables are no longer required.
pause
exit /b 0

:fail
echo.
echo [ERROR] Setup failed. Check the message above.
pause
exit /b 1
