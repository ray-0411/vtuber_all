@echo off
cd /d "%~dp0"
python src\youtube_websub_dashboard.py
if errorlevel 1 pause
