@echo off
setlocal

cd /d "%~dp0..\..\..\catcher"
python "%~dp0working_calendar.py" %*
