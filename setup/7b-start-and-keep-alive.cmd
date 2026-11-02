@echo off
title 72 Ghante - start
cd /d "%~dp0.."
call "%~dp0local-runtime.cmd"
echo.
echo  Starts the app and the phone link in the background and keeps them running:
echo  if either stops, it is started again within about 30 seconds.
echo  There are no black windows to keep open. To stop everything: setup\9-stop-everything.cmd
echo.
echo  In about a minute the dashboard opens, and Notepad shows the phone link (type it on the phone).
echo.
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | Where-Object { $_.CommandLine -match 'keepalive.cmd' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
del "run\stop-keepalive" 2>nul
powershell -NoProfile -Command "Start-Process cmd -ArgumentList '/c run\keepalive.cmd' -WorkingDirectory (Get-Location) -WindowStyle Hidden"
timeout /t 10 >nul

