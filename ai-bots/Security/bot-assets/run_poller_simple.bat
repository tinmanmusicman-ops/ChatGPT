@echo off
REM Simple launcher for the Gmail→Sheets poller
cd /d "%~dp0"

python poll_gmail_to_sheet_advanced.py
pause
