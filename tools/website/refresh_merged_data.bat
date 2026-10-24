@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"

echo [1/3] Merging legacy_live_data.db with the latest live_data.db...
python scripts\merge_live_databases.py --current ..\..\database\website\live_data.db --legacy ..\..\database\website\legacy_live_data.db --audience ..\..\database\website\streamer_audience.db --output ..\..\database\website\merged_live_data.db --report ..\..\other\log-data\merge_report-website.json --overwrite
if errorlevel 1 goto :failed

echo.
echo [2/3] Synchronizing Group settings...
python scripts\create_group_settings.py --database ..\..\database\website\merged_live_data.db
if errorlevel 1 goto :failed

echo.
echo [3/3] Rebuilding analytics cache...
python scripts\build_analytics_cache.py --source ..\..\database\website\merged_live_data.db --output ..\..\database\website\merged_analytics_cache.db
if errorlevel 1 goto :failed

echo.
echo Refresh completed successfully.
echo The dashboard will use the updated merged database on its next start.
pause
exit /b 0

:failed
set "RESULT=%errorlevel%"
echo.
echo Refresh failed. Existing completed database files were kept whenever possible.
pause
exit /b %RESULT%
