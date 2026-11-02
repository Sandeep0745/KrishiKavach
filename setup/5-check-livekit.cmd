@echo off
setlocal
title 72 Ghante - check LiveKit
cd /d "%~dp0.."
call "%~dp0local-runtime.cmd"
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
"%PY%" scripts\check_livekit.py > "%~dp0livekit-report.txt" 2>&1
type "%~dp0livekit-report.txt"
echo.
echo Saved as setup\livekit-report.txt (contains no secrets). You can close this window.
pause

