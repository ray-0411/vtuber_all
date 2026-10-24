@echo off
setlocal

cd /d "%~dp0..\..\..\catcher"
python "%~dp0streamer_form.py"
