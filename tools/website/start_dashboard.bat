@echo off
cd /d "%~dp0"
python scripts\build_analytics_cache.py --source ..\..\database\website\merged_live_data.db --output ..\..\database\website\merged_analytics_cache.db
if errorlevel 1 exit /b %errorlevel%
python "..\..\website\app.py" --database ..\..\database\website\merged_live_data.db --analytics-cache ..\..\database\website\merged_analytics_cache.db
pause
