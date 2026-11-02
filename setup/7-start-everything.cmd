@echo off
setlocal
title 72 Ghante - everything
cd /d "%~dp0.."
call "%~dp0local-runtime.cmd"
set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if not exist ".venv\Scripts\python.exe" (
  echo Missing Python environment. Run setup\2c-install-packages.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" scripts\check_startup.py
if errorlevel 2 (
  start "" http://127.0.0.1:8000/
  start "" http://127.0.0.1:8000/farmer
  exit /b 0
)
if errorlevel 1 (
  pause
  exit /b 1
)
echo.
rem Demo setting for filing: the browser agent fills the form, and the scripted fill takes over if it fails.
rem To skip the agent (no AI, no limits), run:  setup\7-start-everything.cmd scripted
set FILING_MODE=auto
if /i "%~1"=="scripted" set FILING_MODE=scripted
rem District run, as tuned in Phase 4: 8 calls at a time, repeated identical decisions served from cache.
set MAX_PARALLEL_CALLS=8
set S1_SIM_CACHE=1
rem Test T3-09 (slow filing):  setup\7-start-everything.cmd slow
if /i "%~1"=="slow" set FILER_TEST_DELAY_S=100
if /i "%~1"=="slow" set FILING_MODE=scripted
echo  Starting the backend, the decision models, the Filer and the voice worker.
echo  A browser window showing the "FasalClaim Sandbox" portal opens on the right of the screen:
echo  that is where the report gets filed at the end of the call. Leave it open.
echo  In about 40 seconds two more pages open:
echo    the dashboard            http://localhost:8000/
echo    the farmer's phone app   http://localhost:8000/farmer
echo.
echo  The whole demo on this laptop (use a headset):
echo    1. On the farmer page press the big button once, and allow the microphone and camera.
echo    2. On the dashboard press "Start storm" (S key): 340 farmers are ranked and calls go out.
echo       Then press "Call hero" (H key): the simulated farmers pause and the farmer page rings.
echo    3. Answer, and speak the lines of context\Testing.md section 9.2.
echo    4. Take the photo when asked, say yes at the end, and watch the form being filled.
echo       The assistant then reads out the reference number, and a message card appears on the farmer page.
echo    5. Press P on the dashboard: the simulated farmers carry on until the closing banner.
echo       Reset (R twice) and wait a minute before another run.
echo.
echo  To use a real phone instead, also run setup\8-phone-link.cmd and open the link it prints on the phone.
echo  Every start begins a fresh demo: the last run is cleared (the same as Reset on the dashboard).
echo  To stop everything: press Ctrl+C in this window. Closing this window also stops everything.
echo.
start "" /b cmd /c "timeout /t 35 >nul & curl -s -o NUL -X POST http://127.0.0.1:8000/api/scenario/reset & timeout /t 5 >nul & start "" http://localhost:8000/ & timeout /t 2 >nul & start "" http://localhost:8000/farmer"
".venv\Scripts\python.exe" scripts\dev.py --voice
echo.
echo Everything has stopped. You can close this window.
pause

