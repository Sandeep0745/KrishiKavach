@echo off
setlocal
title 72 Ghante - install tools
echo ============================================================
echo  72 Ghante - installing free developer tools with winget
echo  Git, uv, Node.js LTS, cloudflared, LiveKit CLI
echo  Nothing here costs money. Say Yes if Windows asks permission.
echo ============================================================
echo.

where winget >nul 2>nul
if errorlevel 1 (
  echo winget was not found on this computer.
  echo Open Microsoft Store, install or update "App Installer", then run this file again.
  pause
  exit /b 1
)

call :install Git.Git "Git"
call :install astral-sh.uv "uv (Python manager)"
call :install OpenJS.NodeJS.LTS "Node.js LTS"
call :install Cloudflare.cloudflared "cloudflared"
call :install LiveKit.LiveKitCLI "LiveKit CLI"

echo.
echo ============================================================
echo  Finished. CLOSE this window now.
echo  Then double-click  2-check-tools.cmd  (it must run in a NEW window).
echo ============================================================
pause
exit /b 0

:install
echo.
echo --- %~2 ---
winget list --id %1 -e --accept-source-agreements 2>nul | findstr /i /c:"%1" >nul
if not errorlevel 1 (
  echo Already installed. Skipping.
  goto :eof
)
winget install --id %1 -e --accept-source-agreements --accept-package-agreements
goto :eof
