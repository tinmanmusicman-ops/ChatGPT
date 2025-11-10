@echo off
REM Simple launcher for the Gmail→Sheets poller
cd /d "%~dp0"
echo Checking dependencies...
pip install --quiet -r requirements.txt
python poll_gmail_to_sheet.py
pause
