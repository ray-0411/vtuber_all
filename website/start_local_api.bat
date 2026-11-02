@echo off
setlocal
cd /d "%~dp0\.."
set "PYTHONUTF8=1"
python website\app.py
pause
