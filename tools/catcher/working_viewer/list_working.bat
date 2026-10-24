@echo off
setlocal

cd /d "%~dp0..\..\..\catcher"
python "%~dp0list_working.py" --limit 30 %*
pause
