@echo off
rem 72 Ghante keep-alive: runs hidden. Every 20 s it checks the app and the phone link and restarts whichever has stopped.
rem Stop it (and everything) with setup\9-stop-everything.cmd.
setlocal EnableDelayedExpansion
cd /d "%~dp0.."
call "setup\local-runtime.cmd"
set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"
set "LOG=logs\keepalive.log"
set LINKFAILS=0
echo !date! !time! keep-alive started>> "%LOG%"
:loop
if exist "run\stop-keepalive" (
  echo !date! !time! keep-alive stopped>> "%LOG%"
  del "run\stop-keepalive"
  exit /b 0
)
curl -s -f -o NUL -m 8 http://127.0.0.1:8000/health
if errorlevel 1 (
  timeout /t 5 /nobreak >nul
  curl -s -f -o NUL -m 8 http://127.0.0.1:8000/health
  if errorlevel 1 call :restart_app
)
call :check_link
timeout /t 20 /nobreak >nul
goto loop

:restart_app
echo !date! !time! the app was not answering: starting it again>> "%LOG%"
if exist "logs\app-output.log" powershell -NoProfile -Command "Add-Content -Path '%LOG%' -Value '--- last lines of the app before it stopped ---'; Get-Content -Tail 40 'logs\app-output.log' | Add-Content -Path '%LOG%'"
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'dev.py|apps\.|mcp_servers\.' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 3 /nobreak >nul
powershell -NoProfile -Command "Start-Process cmd -ArgumentList '/c setup\7-start-everything.cmd > logs\app-output.log 2>&1' -WorkingDirectory (Get-Location) -WindowStyle Hidden"
set /a W=0
:wait_app
timeout /t 5 /nobreak >nul
set /a W+=5
curl -s -f -o NUL -m 5 http://127.0.0.1:8000/health
if not errorlevel 1 (
  echo !date! !time! the app answers again after !W! s>> "%LOG%"
  exit /b 0
)
if !W! GEQ 180 (
  echo !date! !time! the app did not answer within 180 s>> "%LOG%"
  exit /b 1
)
goto wait_app

:check_link
set "U="
if exist "run\reports\phone-link-out.txt" for /f "tokens=2 delims=," %%a in ('findstr /c:"tunneled with tls termination" run\reports\phone-link-out.txt') do set "U=%%a"
if defined U set "U=!U: =!"
if not defined U goto new_link
curl -s -f -o NUL -m 15 !U!/health
if not errorlevel 1 (
  set LINKFAILS=0
  exit /b 0
)
set /a LINKFAILS+=1
if !LINKFAILS! LSS 2 exit /b 0
:new_link
set LINKFAILS=0
echo !date! !time! the phone link was not working: opening a new one>> "%LOG%"
taskkill /im ssh.exe /f >nul 2>&1
if exist "run\reports\phone-link-out.txt" del "run\reports\phone-link-out.txt"
powershell -NoProfile -Command "Start-Process cmd -ArgumentList '/c ssh -T -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -R 80:127.0.0.1:8000 nokey@localhost.run > run\reports\phone-link-out.txt 2>&1' -WorkingDirectory (Get-Location) -WindowStyle Hidden"
timeout /t 25 /nobreak >nul
set "U="
for /f "tokens=2 delims=," %%a in ('findstr /c:"tunneled with tls termination" run\reports\phone-link-out.txt') do set "U=%%a"
if not defined U (
  echo !date! !time! no phone link address yet>> "%LOG%"
  exit /b 1
)
set "U=!U: =!"
echo !date! !time! new phone link: !U!/farmer>> "%LOG%"
(
echo.
echo   THE PHONE LINK CHANGED. OPEN THIS ON THE PHONE ^(type it in Chrome^):
echo.
echo       !U!/farmer
echo.
echo   Then tap the big button again.
) > run\reports\PHONE-LINK.txt
start "" notepad run\reports\PHONE-LINK.txt
exit /b 0

