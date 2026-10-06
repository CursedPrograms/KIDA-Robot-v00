@echo off
REM Make KIDA's voice lines as Ogg files for scripts/voice.py (same as NORA's).
REM   make_voice.bat [-Voice "Microsoft Hazel Desktop"]
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\make_voice.ps1" %*
if errorlevel 1 pause
