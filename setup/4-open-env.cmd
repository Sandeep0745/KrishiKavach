@echo off
setlocal
title 72 Ghante - create .env
cd /d "%~dp0.."
call "%~dp0local-runtime.cmd"
if not exist ".env" copy ".env.example" ".env" >nul
echo Opening .env in Notepad.
echo Paste each key right after the = sign on its line, save (Ctrl+S), and close Notepad.
start "" notepad ".env"

