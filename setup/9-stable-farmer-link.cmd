@echo off
setlocal
title 72 Ghante - reusable farmer link
cd /d "%~dp0.."
call "%~dp0local-runtime.cmd"
".venv\Scripts\python.exe" scripts\farmer_link.py
echo.
pause
