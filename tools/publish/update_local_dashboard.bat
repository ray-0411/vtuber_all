@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
call settings.bat

echo ========================================
echo   Prepare local website database
echo ========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python was not found in PATH.
  goto :failed
)
if not exist "%CURRENT_DB%" (
  echo [ERROR] Missing current database: %CURRENT_DB%
  goto :failed
)
if not exist "%AUDIENCE_DB%" (
  echo [ERROR] Missing audience database: %AUDIENCE_DB%
  goto :failed
)

python scripts\publish_local_snapshot.py --current "%CURRENT_DB%" --audience "%AUDIENCE_DB%"
if errorlevel 1 goto :failed

echo.
echo Local website database updated. Refresh the website to see the new data.
pause
exit /b 0

:failed
set "RESULT=%errorlevel%"
if "%RESULT%"=="0" set "RESULT=1"
echo.
echo [ERROR] Local website database update failed.
pause
exit /b %RESULT%
