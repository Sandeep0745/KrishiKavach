@echo off
setlocal
title 72 Ghante - install tools (route that avoids GitHub downloads)
echo ============================================================
echo  Installs Python 3.12 from python.org and uv from PyPI.
echo  Use this when 1-install-tools.cmd fails on GitHub downloads.
echo ============================================================
echo.
echo --- Python 3.12 (python.org) ---
winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
echo.
echo --- uv (PyPI) ---
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=py -3.12"
%PY% -m pip install --upgrade uv
echo.
echo ============================================================
echo  Finished. CLOSE this window, then run 2-check-tools.cmd.
echo  cloudflared and the LiveKit CLI are skipped here; the project
echo  can run without them (a tunnel through npx is the substitute).
echo ============================================================
pause
