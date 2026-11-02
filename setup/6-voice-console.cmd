@echo off
setlocal
title 72 Ghante - voice test
cd /d "%~dp0.."
call "%~dp0local-runtime.cmd"
set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if not exist ".venv-voice\Scripts\python.exe" (
  echo The voice environment is missing. Ask Claude to run the voice install task again.
  pause
  exit /b 1
)
echo.
echo  Voice test. The assistant will greet Ramlal ji in English through this computer's speakers.
echo  Answer in English into the microphone. The answers to say are in context\Testing.md, section 9.2:
echo.
echo    1. Yes, speaking.
echo    2. Yes, there is a lot of damage.
echo    3. Yes, that is the field.
echo    4. There was hail and the wheat was flattened.
echo    5. Around three thirty in the afternoon.
echo    6. More than half, about seventy percent.
echo    7. The crop was standing.
echo    (it asks for a photo and waits 15 seconds, because there is no phone in this test.
echo     Say nothing. It then reads all details back and asks "Shall I file the report?" - only THEN say line 8)
echo    8. Yes, please file it.
echo.
echo  Use headphones if you can, so the microphone does not hear the speakers.
echo  To stop early: press Ctrl+C in this window, then close the small "backend" window.
echo.
start "72 Ghante backend" /min ".venv\Scripts\python.exe" scripts\dev.py --only orchestrator,mcp-registry,mcp-weather,s1
echo  Starting the backend and loading the English model (about 30 seconds)...
timeout /t 30 >nul
".venv\Scripts\python.exe" scripts\reset.py >nul 2>&1
set PHOTO_TIMEOUT_S=15
".venv-voice\Scripts\python.exe" -m apps.voice.agent console
echo.
echo The voice test has ended. You can close this window and the "backend" window.
pause

