
@echo off
setlocal enabledelayedexpansion
set "SCRIPT_DIR=%~dp0"
set "RUN_BAT=%SCRIPT_DIR%run_scam_analyzer.bat"
schtasks /create /f /tn "ScamAnalyzer_Every5Min" /sc minute /mo 5 /tr "\"%RUN_BAT%\""
pause
