@echo off
rem Starts Zendesk Warning Light from source with no console window.
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py"
