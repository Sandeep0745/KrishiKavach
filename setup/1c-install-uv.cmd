@echo off
setlocal
title 72 Ghante - install uv from PyPI
echo --- Python 3.12 (python.org) ---
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
"%PY%" --version
echo.
echo --- uv (PyPI) ---
"%PY%" -m pip install --upgrade uv
echo.
echo ============================================================
echo  Finished. CLOSE this window, then run 2-check-tools.cmd.
echo ============================================================
pause
