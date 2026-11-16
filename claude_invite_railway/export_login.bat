@echo off
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python -m pip install -r requirements.txt
if errorlevel 1 goto fail
.venv\Scripts\python -m playwright install chromium
if errorlevel 1 goto fail
.venv\Scripts\python export_login.py
pause
exit /b
:fail
echo Installation failed. Check Python 3.11+ and Internet.
pause
