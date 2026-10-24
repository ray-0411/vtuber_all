@echo off
setlocal

cd /d "%~dp0..\..\catcher"
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

echo Running one live-status collection...
echo Project: %CD%
echo Timezone: Asia/Taipei
echo.

fnm exec --using 20.20.1 python src\run_local_scheduler.py --once --timezone Asia/Taipei --collection-timeout-seconds 240

echo.
echo One-time collection finished.
pause
