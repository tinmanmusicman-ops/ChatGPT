@echo off
setlocal EnableExtensions EnableDelayedExpansion
REM === Advanced launcher with timestamped logs & restart-on-failure ===
REM Place this .bat in the same folder as poll_gmail_to_sheet.py

cd /d "%~dp0"

REM ---------- Configurable settings ----------
set "SCRIPT=poll_gmail_to_sheet.py"
set "LOGDIR=logs"
set "RESTART_ON_FAIL=1"         REM 1=yes, 0=no
set "RESTART_DELAY=5"           REM seconds between restarts
set "USE_VENV=1"                REM 1=activate .venv if found, 0=skip
set "VENV_DIR=.venv"            REM relative path to virtual env
REM ------------------------------------------

if not exist "%LOGDIR%" mkdir "%LOGDIR%"

REM Check Python availability
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found on PATH. Install Python or add it to PATH.
  pause
  exit /b 1
)

REM Optional: activate virtual environment if present
if "%USE_VENV%"=="1" (
  if exist "%VENV_DIR%\Scripts\activate.bat" (
    call "%VENV_DIR%\Scripts\activate.bat"
  )
)

:runloop
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "TS=%%i"
set "LOGFILE=%LOGDIR%\poller_!TS!.log"

echo ==== LAUNCH !DATE! !TIME! ==== | powershell -NoProfile -Command "Tee-Object -FilePath '%LOGFILE%' -Append" >nul

REM Run the Python script and tee output to both console and file
powershell -NoProfile -Command ^
  "$p = Start-Process -FilePath 'python' -ArgumentList @('%SCRIPT%', '%*') -NoNewWindow -RedirectStandardOutput '%LOGFILE%' -RedirectStandardError '%LOGFILE%' -PassThru; "^
  "Wait-Process -Id $p.Id; exit $p.ExitCode"

set "EXITCODE=%ERRORLEVEL%"
echo ==== EXIT CODE: !EXITCODE! at !DATE! !TIME! ==== | powershell -NoProfile -Command "Tee-Object -FilePath '%LOGFILE%' -Append" >nul

if "%RESTART_ON_FAIL%"=="1" (
  if not "!EXITCODE!"=="0" (
    echo [WARN] Script exited with code !EXITCODE!. Restarting in %RESTART_DELAY%s...
    timeout /t %RESTART_DELAY% /nobreak >nul
    goto :runloop
  )
)

REM If we got here and not restarting, just hold window open for review
echo Done. Press any key to close.
pause >nul
