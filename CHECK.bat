@echo off
setlocal
cd /d "%~dp0backend"
if exist ".venv\Scripts\python.exe" (
  .venv\Scripts\python.exe -m api.smoke_check
) else (
  python -m api.smoke_check
)
pause
