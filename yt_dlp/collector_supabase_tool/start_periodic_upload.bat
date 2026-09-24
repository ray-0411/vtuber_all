@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
chcp 65001 >nul
title VTuber Supabase Periodic Upload

if not exist ".env.supabase.local" (
  echo [ERROR] Missing .env.supabase.local
  pause
  exit /b 1
)

python scripts\run_periodic_upload.py --interval-seconds 1800 --minute-offset 3 --retry-interval-minutes 5

echo.
echo ============================================================
echo Periodic upload stopped.
echo ============================================================
pause
