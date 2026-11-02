@echo off
setlocal
cd /d "%~dp0.."
call "%~dp0local-runtime.cmd"
rem Run after setup/7-start-everything.cmd. This resets only the synthetic sandbox.
".venv\Scripts\python.exe" scripts\weather_demo.py --run
pause
