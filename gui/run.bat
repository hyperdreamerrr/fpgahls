@echo off
setlocal
cd /d "%~dp0"

set "PY=C:\Program Files\Python311\python.exe"
if not exist "%PY%" set "PY=python"

echo Starting HLS Agent GUI ...
"%PY%" server.py --open
if errorlevel 1 pause
