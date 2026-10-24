@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"

if not exist "..\..\database\published\merged_live_data.db" (
  echo [ERROR] Missing ..\..\database\published\merged_live_data.db
  echo Run update_and_upload.bat first.
  pause
  exit /b 1
)
if not exist "..\..\database\published\merged_analytics_cache.db" (
  echo [ERROR] Missing ..\..\database\published\merged_analytics_cache.db
  echo Run update_and_upload.bat first.
  pause
  exit /b 1
)

python scripts\sync_merged_to_postgres.py --confirm-replace
if errorlevel 1 (
  echo [ERROR] Supabase upload failed.
  pause
  exit /b 1
)

echo Supabase upload completed successfully.
pause
