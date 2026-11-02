@echo off
setlocal
call "%~dp0local-runtime.cmd"
title 72 Ghante - check tools
set REPORT=%~dp0check-report.txt
rem Tools installed moments ago may not be on this window's PATH yet; add the usual install folders.
set "PATH=%PATH%;%LOCALAPPDATA%\Microsoft\WinGet\Links;%ProgramFiles%\WinGet\Links;%ProgramFiles(x86)%\cloudflared;%ProgramFiles%\cloudflared;%USERPROFILE%\.local\bin;%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%APPDATA%\Python\Python312\Scripts;%ProgramFiles%\nodejs;%ProgramFiles%\Git\cmd"
echo 72 Ghante tool check - %date% %time% > "%REPORT%"
echo.
echo Installing Python 3.12 through uv (free, a few minutes the first time)...
uv python find 3.12 >nul 2>nul || uv python install 3.12
echo.

call :check "Git"          git --version
call :check "uv"           uv --version
call :check "Python 3.12"  uv run --python 3.12 --no-project python --version
call :check "Node.js"      node --version
call :check "npm"          npm --version
call :check "cloudflared"  cloudflared --version
call :check "LiveKit CLI"  lk --version

echo.
echo ============================================================
type "%REPORT%"
echo ============================================================
echo. >> "%REPORT%"
where uv cloudflared lk >> "%REPORT%" 2>&1
echo The same report is saved as check-report.txt in the setup folder.
echo Every line should say OK. Node must be version 20 or higher.
pause
exit /b 0

:check
set NAME=%~1
shift
set OUT=
for /f "delims=" %%i in ('%1 %2 %3 %4 %5 %6 2^>nul') do if not defined OUT set OUT=%%i
if defined OUT (
  echo OK       %NAME% : %OUT% >> "%REPORT%"
) else (
  echo MISSING  %NAME% >> "%REPORT%"
)
goto :eof

