@echo off
rem run.bat — launch the KIDA remote controller (creates its own venv on first run)
rem Usage: run.bat <robot-ip-or-url> [--port 5003] [--fullscreen]

cd /d "%~dp0"
if not exist venv (
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    call venv\Scripts\activate.bat
)
python main.py %*
