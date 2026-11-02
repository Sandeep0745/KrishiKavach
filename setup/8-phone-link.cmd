@echo off
setlocal
title 72 Ghante - phone link
cd /d "%~dp0.."
call "%~dp0local-runtime.cmd"
echo.
echo  This is a TEMPORARY link. For one reusable judge-demo bookmark,
echo  follow setup\SINGLE-FARMER-LINK.md and use setup\9-stable-farmer-link.cmd.
echo.
echo  This gives the phone a secure (https) link to the app on this laptop. A phone browser only allows
echo  the microphone and camera on an https page, so the plain http://192.168... address will not work.
echo.
echo  Start setup\7-start-everything.cmd first, then leave this window open.
echo  Look below for a line with an https address. On the phone, open that address followed by /farmer
echo  for example:  https://something.lhr.life/farmer
echo.
echo  While this window is open, anyone who has the link can reach the demo. Close it after the demo.
echo.
where cloudflared >nul 2>&1
if %errorlevel%==0 (
  echo  Using cloudflared.
  cloudflared tunnel --url http://127.0.0.1:8000
) else (
  echo  cloudflared is not installed, so this uses the free localhost.run service through Windows' built-in ssh.
  echo  If it asks "Are you sure you want to continue connecting", type yes and press Enter.
  echo.
  ssh -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -R 80:127.0.0.1:8000 nokey@localhost.run
)
echo.
echo The link is closed.
pause

