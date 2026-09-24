@echo off
setlocal

cd /d "%~dp0"
chcp 65001 >nul

if not defined TWITCH_CLIENT_ID (
  echo TWITCH_CLIENT_ID is not set.
  echo Please set it before running this file.
  pause
  exit /b 1
)

if not defined TWITCH_CLIENT_SECRET (
  echo TWITCH_CLIENT_SECRET is not set.
  echo Please set it before running this file.
  pause
  exit /b 1
)

echo Starting local live-status scheduler...
echo Project: %CD%
echo Timezone: Asia/Taipei
echo Schedule: every hour at minute 00, 05, 10, 15, ...
echo.

fnm exec --using 20.20.1 python src\run_local_scheduler.py --interval-seconds 300 --timezone Asia/Taipei --collection-timeout-seconds 240

echo.
echo Scheduler stopped.
pause
