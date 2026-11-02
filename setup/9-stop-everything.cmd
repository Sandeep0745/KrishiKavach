@echo off
title 72 Ghante - stop everything
cd /d "%~dp0.."
call "%~dp0local-runtime.cmd"
echo Stopping the keep-alive, the app and the phone link...
echo.> "run\stop-keepalive"
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | Where-Object { $_.CommandLine -match 'keepalive.cmd' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'dev.py|apps\.|mcp_servers\.' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
taskkill /im ssh.exe /f >nul 2>&1
del "run\stop-keepalive" 2>nul
echo Done.
timeout /t 5 >nul

