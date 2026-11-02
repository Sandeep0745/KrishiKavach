@echo off
rem Project-local tools and model cache for this laptop.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0repair-python-paths.ps1"
set "PATH=%~dp0..\.setup-tools\bin;%~dp0..\.venv\Scripts;%PATH%"
set "UV_CACHE_DIR=%~dp0..\.runtime\uv-cache"
set "UV_PYTHON_INSTALL_DIR=%~dp0..\.runtime\python"
set "HF_HOME=%~dp0..\.runtime\huggingface"
set "FILER_PROFILE_DIR=%~dp0..\.runtime\filer-profile"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
