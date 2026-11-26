@echo off
cd /d "%~dp0"
taskkill /F /IM pythonw.exe >nul 2>&1
start "" pythonw.exe "%~dp0deck_server.py"
exit