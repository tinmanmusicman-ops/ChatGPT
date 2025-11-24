@echo off
REM Simple launcher for the Gmail→Sheets poller
cd /d "%~dp0"
echo Checking dependencies...
python t.py
pause
