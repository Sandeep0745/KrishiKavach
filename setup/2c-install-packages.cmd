@echo off
setlocal
title 72 Ghante - install the Python packages
cd /d "%~dp0.."
call "%~dp0local-runtime.cmd"
set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=3.12"
if exist "%CD%\.venv\Scripts\python.exe" set "PY=%CD%\.venv\Scripts\python.exe"
echo.
echo  This creates the three Python environments the project uses and installs the package versions that
echo  were tested on the team laptop (the lists are in setup\locks). It needs the internet and about 3 GB of
echo  disk; the first time takes 10 to 20 minutes. Running it again only checks that everything is there.
echo.
where uv >nul 2>&1
if errorlevel 1 (
  echo  uv is missing. Run 1-install-tools.cmd or 1c-install-uv.cmd first.
  pause
  exit /b 1
)
call :env .venv venv.txt
if errorlevel 1 goto failed
call :env .venv-voice venv-voice.txt
if errorlevel 1 goto failed
call :env .venv-browser venv-browser.txt
if errorlevel 1 goto failed
echo.
echo --- the local English voice (Piper; used when the online voice is not available) ---
if exist "var\piper\en_US-lessac-medium.onnx" (
  echo  already there
) else (
  if not exist "var\piper" mkdir "var\piper"
  ".venv-voice\Scripts\python.exe" -m piper.download_voices en_US-lessac-medium --data-dir var\piper
  if errorlevel 1 goto failed
)
echo.
echo ============================================================
echo  Finished. Next: Part B of setup\SETUP-TONIGHT.md (the free accounts and the .env file).
echo ============================================================
pause
exit /b 0

:env
echo.
echo --- %~1 ---
if not exist "%~1\Scripts\python.exe" (
  uv venv "%~1" --python "%PY%"
  if errorlevel 1 exit /b 1
)
uv pip install --python "%~1\Scripts\python.exe" -r "setup\locks\%~2"
exit /b %errorlevel%

:failed
echo.
echo  Something above failed. Send Claude the last 20 lines of this window (they contain no keys).
pause
exit /b 1


