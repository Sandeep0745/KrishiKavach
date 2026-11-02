@echo off
setlocal
title 72 Ghante - watch the form being filed
cd /d "%~dp0.."
call "%~dp0local-runtime.cmd"
set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set ANONYMIZED_TELEMETRY=false
echo.
echo  This opens a browser window and files the test farmer's crop-loss report in our own sandbox portal:
echo    1. once through the whole pipeline (the browser agent reads each page and fills it),
echo    2. once more by the browser agent alone,
echo    3. once by the scripted fill, and once with the agent cut off after 5 seconds so the scripted fill takes over.
echo  Just watch the window. It takes about four minutes. Nothing real is filed anywhere.
echo.
".venv\Scripts\python.exe" scripts\filing_check.py --visible --agent-runs 1
echo.
pause

