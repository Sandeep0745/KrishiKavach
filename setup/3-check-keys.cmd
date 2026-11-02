@echo off
setlocal
title 72 Ghante - check keys
cd /d "%~dp0.."
call "%~dp0local-runtime.cmd"
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
"%PY%" scripts\check_keys.py > "%~dp0keys-report.txt" 2>&1
type "%~dp0keys-report.txt"
echo.
echo Saved as setup\keys-report.txt (contains no keys). You can close this window.
pause

