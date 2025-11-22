@echo off
cd /d C:\ChatGPT\Indeed
"C:\Users\SCRC\AppData\Local\Programs\Python\Python314\python.exe" Indeed.py >> Indeedlog.txt 2>&1
timeout /t 30 /nobreak > nul
"C:\Users\SCRC\AppData\Local\Programs\Python\Python314\python.exe" seam_thermostat_temp.py >> Thermostat.txt 2>&1
